"""
Zwillingstag – Cloudflare Python Worker

The existing FastAPI backend runs directly on Cloudflare Workers using the
Python Workers runtime.  Workers KV replaces the disk-based protocol and
member caches – all entries are stored permanently (no TTL) because Bundestag
speech data never changes once published.

REST API
  GET /api/health          – health check
  GET /api/members         – CDU/CSU Bundestag members (KV-cached permanently)
  GET /api/sessions        – recent Bundestag sessions
  GET /api/speeches        – available speeches (KV-cached permanently)
  GET /api/speeches/{id}   – single speech (KV-cached permanently)
  GET /api/reactions/{id}  – LLM reactions for a speech (KV-cached permanently)
  GET /api/state           – full simulation state

WebSocket
  WS /ws                   – real-time state updates

Workers KV keys (no TTL – stored permanently, speeches don't change):
  members              CDU/CSU member list
  speeches             Available Bundestag speeches index
  proto:{session_id}   Speeches parsed from one protocol XML
  speech:{id}          Individual speech detail
  reactions:{id}       LLM-generated reactions
  current_speech_id    Currently selected speech ID

Secrets (set via `wrangler secret put` or the Cloudflare dashboard):
  BUNDESTAG_API_KEY    Bundestag DIP API key (mock data used when absent)
  OPENAI_API_KEY       OpenAI key for LLM reactions (mock reactions when absent)
"""

import asyncio
import json
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from workers import WorkerEntrypoint

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

DIP_API_BASE = "https://search.dip.bundestag.de/api/v1"
MDB_INDEX_URL = "https://www.bundestag.de/xml/v2/mdb/index.xml"
PROTOCOLS_TO_LOAD = 3
TOPIC_MIN_LEN = 10
TOPIC_MAX_LEN = 120
ENRICH_CONCURRENCY = 10
MOCK_REACTION_SEED = 42  # Seed used when no speech is provided for deterministic mock reactions

# ─── Models ───────────────────────────────────────────────────────────────────


class ReactionType(str, Enum):
    CLAP = "clap"
    REMARK = "remark"
    QUESTION = "question"
    SILENT = "silent"


class Member(BaseModel):
    id: str
    name: str
    party: str
    state: str
    role: Optional[str] = None
    focus_areas: List[str] = []
    political_style: str = ""
    seat_row: int = 0
    seat_col: int = 0
    mdb_id: Optional[str] = None
    photo_url: Optional[str] = None
    bio: Optional[str] = None


class Speech(BaseModel):
    id: str
    speaker_name: str
    speaker_party: Optional[str] = None
    text: str
    date: str
    session_id: Optional[str] = None
    session_title: Optional[str] = None
    topic: Optional[str] = None


class Reaction(BaseModel):
    member_id: str
    reaction_type: ReactionType
    intensity: int = 1
    text: Optional[str] = None


class SimulationState(BaseModel):
    current_speech: Optional[Speech] = None
    reactions: List[Reaction] = []
    available_speeches: List[Speech] = []
    is_live: bool = False


# ─── HTTP helpers (Workers fetch API) ────────────────────────────────────────


async def http_get_text(url: str, headers: Optional[dict] = None) -> str:
    """HTTP GET via the Workers fetch API, returns response body as text."""
    from js import fetch

    if headers:
        resp = await fetch(url, headers=headers)
    else:
        resp = await fetch(url)
    return await resp.text()


async def http_get_json(url: str, headers: Optional[dict] = None) -> Any:
    text = await http_get_text(url, headers)
    return json.loads(text)


async def http_post_json(url: str, data: dict, headers: dict) -> Any:
    """HTTP POST with JSON body via the Workers fetch API."""
    from js import fetch

    resp = await fetch(url, method="POST", headers=headers, body=json.dumps(data))
    text = await resp.text()
    return json.loads(text)


# ─── KV helpers (no TTL – permanent storage) ─────────────────────────────────


async def kv_get(kv, key: str) -> Optional[Any]:
    """Retrieve a JSON value from Workers KV. Returns None if not found."""
    val = await kv.get(key)
    if val is None:
        return None
    return json.loads(val)


async def kv_put(kv, key: str, value: Any) -> None:
    """Store a JSON value in Workers KV with no TTL (permanent)."""
    await kv.put(key, json.dumps(value, ensure_ascii=False))


# ─── Member (MdB) service ─────────────────────────────────────────────────────


def _name_to_id(name: str) -> str:
    import unicodedata
    normalized = unicodedata.normalize("NFKD", name)
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", ascii_name.lower()).strip("_")


def _strip_html(text: str) -> str:
    clean = re.sub(r"<[^>]+>", " ", text)
    clean = re.sub(r"&[a-z]+;", " ", clean)
    clean = re.sub(r"\s+", " ", clean)
    return clean.strip()


def _elem_text(el) -> Optional[str]:
    if el is None:
        return None
    return (el.text or "").strip() or None


def _parse_mdb_index(content: str) -> List[dict]:
    """Parse the Bundestag MdB index XML and return CDU/CSU member dicts."""
    root = ET.fromstring(content)
    members = []
    for mdb in root.findall(".//mdb"):
        fraktion = mdb.get("fraktion", "")
        if "CDU" not in fraktion and "CSU" not in fraktion:
            continue
        mdb_id_el = mdb.find("mdbID")
        if mdb_id_el is None or mdb_id_el.get("status") != "Aktiv":
            continue
        name_el = mdb.find("mdbName")
        raw_name = (name_el.text or "").strip() if name_el is not None else ""
        parts = raw_name.split(", ", 1)
        full_name = f"{parts[1]} {parts[0]}".strip() if len(parts) == 2 else raw_name
        foto_url = _elem_text(mdb.find("mdbFotoURL"))
        foto_gross_url = _elem_text(mdb.find("mdbFotoGrossURL"))
        members.append({
            "mdb_id": mdb_id_el.text or "",
            "name": full_name,
            "state": _elem_text(mdb.find("mdbLand")) or "",
            "photo_url": foto_gross_url or foto_url,
            "info_xml_url": _elem_text(mdb.find("mdbInfoXMLURL")),
            "party": "CDU",
        })
    return members


def _extract_role(info) -> Optional[str]:
    bio_raw = _elem_text(info.find("mdbBiografischeInformationen")) or ""
    bio = bio_raw.lower()
    role_keywords = [
        ("fraktionsvorsitzender", "Fraktionsvorsitzende/-r CDU/CSU"),
        ("parlamentarischer geschäftsführer", "Parlamentarische/-r Geschäftsführer/-in"),
        ("parlamentarische staatssekretärin", "Parlamentarische/-r Staatssekretär/-in"),
        ("parlamentarischer staatssekretär", "Parlamentarische/-r Staatssekretär/-in"),
    ]
    for keyword, label in role_keywords:
        if keyword in bio:
            return label
    return None


def _build_political_style(party: str, state: str, beruf: Optional[str], bio: str) -> str:
    lines = []
    if party == "CSU":
        lines.append("CSU-Mitglied, konservativ-bayerisch")
    else:
        lines.append("CDU-Mitglied, christdemokratisch-konservativ")
    if beruf:
        lines.append(f"von Beruf {beruf}")
    if state:
        lines.append(f"vertritt {state}")
    if bio:
        first = bio.split(".")[0].strip()
        if len(first) > 20:
            lines.append(first[:200])
    return "; ".join(lines)


def _parse_mdb_individual(base: dict, content: str) -> Member:
    """Parse an individual MdB XML to enrich with party/bio/role data."""
    try:
        root = ET.fromstring(content)
        info = root.find(".//mdbInfo")
        if info is None:
            return _dict_to_member(base)
        partei = _elem_text(info.find("mdbPartei"))
        beruf = _elem_text(info.find("mdbBeruf"))
        bio_raw = _elem_text(info.find("mdbBiografischeInformationen")) or ""
        bio_clean = _strip_html(bio_raw)[:500].strip()
        role = _extract_role(info)
        political_style = _build_political_style(
            party=partei or base["party"],
            state=base["state"],
            beruf=beruf,
            bio=bio_clean,
        )
        return Member(
            id=_name_to_id(base["name"]),
            mdb_id=base.get("mdb_id"),
            name=base["name"],
            party=partei or base["party"],
            state=base["state"],
            role=role,
            focus_areas=[],
            political_style=political_style,
            bio=bio_clean,
            photo_url=base.get("photo_url"),
        )
    except Exception:
        return _dict_to_member(base)


def _dict_to_member(d: dict) -> Member:
    return Member(
        id=_name_to_id(d["name"]),
        mdb_id=d.get("mdb_id"),
        name=d["name"],
        party=d.get("party", "CDU"),
        state=d.get("state", ""),
        role=d.get("role"),
        focus_areas=d.get("focus_areas", []),
        political_style=d.get("political_style", ""),
        bio=d.get("bio"),
        photo_url=d.get("photo_url"),
    )


def _assign_seats(members: List[Member]) -> List[Member]:
    """Arrange members in a semi-circular parliament layout."""
    n = len(members)
    row_sizes = []
    remaining = n
    cols_first = max(6, n // 6)
    row = 0
    while remaining > 0:
        size = min(cols_first + row * 2, remaining)
        row_sizes.append(size)
        remaining -= size
        row += 1
    idx = 0
    for row_idx, size in enumerate(row_sizes):
        for col_idx in range(size):
            if idx >= n:
                break
            members[idx].seat_row = row_idx
            members[idx].seat_col = col_idx
            idx += 1
    return members


async def fetch_members(kv) -> List[Member]:
    """Return CDU/CSU members, using KV cache if available."""
    cached = await kv_get(kv, "members")
    if cached is not None:
        return _assign_seats([Member(**m) for m in cached])

    try:
        content = await http_get_text(MDB_INDEX_URL)
        basic = _parse_mdb_index(content)
        sem = asyncio.Semaphore(ENRICH_CONCURRENCY)

        async def enrich(m: dict) -> Member:
            url = m.get("info_xml_url")
            if not url:
                return _dict_to_member(m)
            async with sem:
                try:
                    xml_text = await http_get_text(url)
                    return _parse_mdb_individual(m, xml_text)
                except Exception:
                    return _dict_to_member(m)

        enriched = await asyncio.gather(*[enrich(m) for m in basic])
        members = _assign_seats(list(enriched))
        await kv_put(kv, "members", [m.model_dump() for m in members])
        return members
    except Exception as e:
        logger.error(f"fetch_members error: {e}")
        return _assign_seats(_fallback_members())


def _fallback_members() -> List[Member]:
    """Minimal CDU/CSU fallback list used when the Bundestag API is unreachable."""
    data = [
        {"id": "merz_friedrich", "name": "Friedrich Merz", "party": "CDU",
         "state": "Nordrhein-Westfalen", "role": "Fraktionsvorsitzender CDU/CSU",
         "political_style": "Konservativ, wirtschaftsliberal"},
        {"id": "doebrindt_alexander", "name": "Alexander Dobrindt", "party": "CSU",
         "state": "Bayern", "role": "Vorsitzender der CSU-Landesgruppe",
         "political_style": "Bayerisch-konservativ, populistisch"},
        {"id": "roettgen_norbert", "name": "Norbert Röttgen", "party": "CDU",
         "state": "Nordrhein-Westfalen", "role": "Außenpolitischer Sprecher",
         "political_style": "Moderater CDU-Außenpolitiker, proeuropäisch"},
        {"id": "kloeckner_julia", "name": "Julia Klöckner", "party": "CDU",
         "state": "Rheinland-Pfalz", "political_style": "Wirtschaftspolitisch engagiert"},
        {"id": "linnemann_carsten", "name": "Carsten Linnemann", "party": "CDU",
         "state": "Nordrhein-Westfalen", "role": "CDU-Generalsekretär",
         "political_style": "Wirtschaftsliberal, reformorientiert"},
    ]
    return [_dict_to_member(d) for d in data]


# ─── Bundestag API ────────────────────────────────────────────────────────────


def _normalize_date(date_str: str) -> str:
    if not date_str:
        return datetime.now().strftime("%Y-%m-%d")
    if re.match(r"\d{2}\.\d{2}\.\d{4}", date_str):
        d, m, y = date_str[:10].split(".")
        return f"{y}-{m}-{d}"
    return date_str[:10]


def _extract_top_title(top: ET.Element) -> str:
    for klasse in ("T_fett", "T_NaS"):
        for p in top:
            if p.get("klasse") == klasse:
                text = re.sub(r"\s+", " ", (p.text or "").strip())
                if len(text) > TOPIC_MIN_LEN:
                    return text[:TOPIC_MAX_LEN]
    return top.get("top-id", "")


def _parse_rede(
    rede: ET.Element,
    session_id: str,
    session_title: str,
    date_str: str,
    topic: str,
) -> Optional[Speech]:
    rede_id = rede.get("id", "")
    if not rede_id:
        return None
    redner_el = rede.find(".//redner")
    vorname = nachname = fraktion = ""
    if redner_el is not None:
        name_el = redner_el.find("name")
        if name_el is not None:
            vn = name_el.find("vorname")
            nn = name_el.find("nachname")
            frak = name_el.find("fraktion")
            vorname = (vn.text or "").strip() if vn is not None else ""
            nachname = (nn.text or "").strip() if nn is not None else ""
            fraktion = (frak.text or "").strip() if frak is not None else ""
    speaker_name = f"{vorname} {nachname}".strip() or "Unbekannt"
    text_parts = []
    for p in rede:
        if p.tag == "p" and p.get("klasse") != "redner":
            t = (p.text or "").strip()
            if t:
                text_parts.append(t)
    full_text = " ".join(text_parts)
    if not full_text:
        return None
    return Speech(
        id=f"{session_id}:{rede_id}",
        speaker_name=speaker_name,
        speaker_party=fraktion or None,
        text=full_text,
        date=_normalize_date(date_str),
        session_id=session_id,
        session_title=session_title,
        topic=topic,
    )


def _parse_protocol_xml(
    content: str,
    session_id: str,
    session_title: str,
    date_str: str,
) -> List[Speech]:
    try:
        root = ET.fromstring(content)
    except ET.ParseError as e:
        logger.error(f"XML parse error: {e}")
        return []
    sitzungsverlauf = root.find("sitzungsverlauf")
    if sitzungsverlauf is None:
        return []
    rede_to_topic: Dict[str, str] = {}
    for top in sitzungsverlauf:
        topic = _extract_top_title(top)
        for rede in top.findall(".//rede"):
            rede_id = rede.get("id", "")
            if rede_id:
                rede_to_topic[rede_id] = topic
    speeches = []
    for rede in sitzungsverlauf.findall(".//rede"):
        speech = _parse_rede(
            rede,
            session_id=session_id,
            session_title=session_title,
            date_str=date_str,
            topic=rede_to_topic.get(rede.get("id", ""), ""),
        )
        if speech:
            speeches.append(speech)
    return speeches


async def fetch_recent_sessions(api_key: str, limit: int = 10) -> list:
    """Fetch recent Bundestag sessions from the DIP API."""
    if not api_key:
        return _mock_sessions()
    try:
        params = f"apikey={api_key}&format=json&f.herausgeber=BT&num={limit * 2}"
        data = await http_get_json(f"{DIP_API_BASE}/plenarprotokoll/?{params}")
        result = []
        for doc in data.get("documents", []):
            if doc.get("herausgeber") != "BT":
                continue
            if doc.get("fundstelle", {}).get("xml_url"):
                result.append({
                    "id": doc["id"],
                    "title": doc["titel"],
                    "date": doc["datum"],
                    "session_number": doc.get("dokumentnummer", ""),
                })
            if len(result) >= limit:
                break
        return result
    except Exception as e:
        logger.error(f"fetch_recent_sessions error: {e}")
        return _mock_sessions()


async def _load_recent_speeches(kv, api_key: str) -> List[Speech]:
    """Fetch the most recent Bundestag protocols and return their speeches."""
    params = f"apikey={api_key}&format=json&f.herausgeber=BT&num={PROTOCOLS_TO_LOAD * 2}"
    data = await http_get_json(f"{DIP_API_BASE}/plenarprotokoll/?{params}")
    protocols = []
    for doc in data.get("documents", []):
        if doc.get("herausgeber") != "BT":
            continue
        if doc.get("fundstelle", {}).get("xml_url"):
            protocols.append(doc)
        if len(protocols) >= PROTOCOLS_TO_LOAD:
            break

    all_speeches: List[Speech] = []
    for proto in protocols:
        xml_url = proto["fundstelle"]["xml_url"]
        session_id = str(proto["id"])
        session_title = proto["titel"]
        date_str = proto["datum"]

        proto_key = f"proto:{session_id}"
        cached_proto = await kv_get(kv, proto_key)
        if cached_proto is not None:
            speeches = [Speech(**s) for s in cached_proto]
        else:
            xml_content = await http_get_text(xml_url)
            speeches = _parse_protocol_xml(xml_content, session_id, session_title, date_str)
            if speeches:
                # Store protocol and individual speeches permanently (no TTL)
                await kv_put(kv, proto_key, [s.model_dump() for s in speeches])
                for s in speeches:
                    await kv_put(kv, f"speech:{s.id}", s.model_dump())
        all_speeches.extend(speeches)
    return all_speeches


async def fetch_speeches(kv, api_key: str) -> List[Speech]:
    """Return available speeches, using KV cache if available."""
    cached = await kv_get(kv, "speeches")
    if cached is not None:
        return [Speech(**s) for s in cached]

    if not api_key:
        speeches = _mock_speeches()
        await kv_put(kv, "speeches", [s.model_dump() for s in speeches])
        return speeches
    try:
        speeches = await _load_recent_speeches(kv, api_key)
        if speeches:
            await kv_put(kv, "speeches", [s.model_dump() for s in speeches])
        return speeches
    except Exception as e:
        logger.error(f"fetch_speeches error: {e}")
        return _mock_speeches()


async def get_speech_by_id(kv, api_key: str, speech_id: str) -> Optional[Speech]:
    """Get a specific speech by ID, using KV cache."""
    cached = await kv_get(kv, f"speech:{speech_id}")
    if cached is not None:
        return Speech(**cached)
    speeches = await fetch_speeches(kv, api_key)
    return next((s for s in speeches if s.id == speech_id), None)


# ─── LLM service ──────────────────────────────────────────────────────────────


def _build_reaction_prompt(speech: Speech, members: List[Member]) -> str:
    def member_line(m: Member) -> str:
        bio_snippet = ""
        if m.bio:
            first = m.bio.split(".")[0].strip()
            if len(first) > 20:
                bio_snippet = f" | Bio: {first[:160]}"
        role_snippet = f" | Funktion: {m.role}" if m.role else ""
        style_snippet = f" | Stil: {m.political_style[:100]}" if m.political_style else ""
        return f"- ID:{m.id} | {m.name} ({m.party}, {m.state}){role_snippet}{style_snippet}{bio_snippet}"

    members_summary = "\n".join(member_line(m) for m in members)
    return f"""Du simulierst CDU/CSU-Abgeordnete des deutschen Bundestags, die auf eine Rede reagieren.

REDE:
Redner: {speech.speaker_name} ({speech.speaker_party or 'unbekannte Partei'})
Thema: {speech.topic or 'allgemein'}
Text: {speech.text[:1500]}

CDU/CSU-ABGEORDNETE:
{members_summary}

Aufgabe: Generiere für JEDEN Abgeordneten eine realistische, charaktergerechte Reaktion.
Mögliche Reaktionstypen:
- "clap": Applaus (intensity 1-5, 5=stehend)
- "remark": Kurzer Zwischenruf / Bemerkung (max 80 Zeichen, auf Deutsch)
- "question": Zwischenfrage oder kritische Nachfrage (max 100 Zeichen, auf Deutsch)
- "silent": Keine sichtbare Reaktion

Berücksichtige: CDU/CSU ist Opposition – bei Regierungsreden eher kritisch/still/Zwischenrufe.

Gib NUR valides JSON zurück (kein Markdown), exakt dieses Format:
{{"reactions": [{{"member_id": "...", "reaction_type": "clap|remark|question|silent", "intensity": 1, "text": null}}]}}
"""


async def generate_reactions(
    kv,
    speech: Speech,
    members: List[Member],
    api_key: Optional[str],
    model: str = "gpt-4o-mini",
) -> List[Reaction]:
    """Generate reactions for all members, using KV cache if available."""
    kv_key = f"reactions:{speech.id}"
    cached = await kv_get(kv, kv_key)
    if cached is not None:
        return [Reaction(**r) for r in cached]

    if not api_key:
        reactions = _mock_reactions(members, speech)
    else:
        try:
            payload = {
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Du bist ein präziser politischer Simulator. "
                            "Antworte ausschließlich mit validem JSON, ohne Markdown-Formatierung."
                        ),
                    },
                    {"role": "user", "content": _build_reaction_prompt(speech, members)},
                ],
                "temperature": 0.8,
                "max_tokens": 4000,
                "response_format": {"type": "json_object"},
            }
            result = await http_post_json(
                "https://api.openai.com/v1/chat/completions",
                data=payload,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            )
            raw = result["choices"][0]["message"]["content"]
            data = json.loads(raw)
            member_ids = {m.id for m in members}
            reactions = []
            for item in data.get("reactions", []):
                mid = item.get("member_id")
                if mid not in member_ids:
                    continue
                try:
                    r_type = ReactionType(item.get("reaction_type", "silent"))
                except ValueError:
                    r_type = ReactionType.SILENT
                reactions.append(Reaction(
                    member_id=mid,
                    reaction_type=r_type,
                    intensity=max(1, min(5, int(item.get("intensity", 1)))),
                    text=item.get("text"),
                ))
            reacted_ids = {r.member_id for r in reactions}
            for m in members:
                if m.id not in reacted_ids:
                    reactions.append(Reaction(member_id=m.id, reaction_type=ReactionType.SILENT))
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            reactions = _mock_reactions(members, speech)

    await kv_put(kv, kv_key, [r.model_dump() for r in reactions])
    return reactions


def _mock_reactions(members: List[Member], speech: Optional[Speech] = None) -> List[Reaction]:
    """Deterministic mock reactions based on member profile."""
    import random

    own_faction = bool(
        speech and speech.speaker_party
        and speech.speaker_party.upper() in ("CDU", "CSU", "CDU/CSU")
    )
    rnd = random.Random(hash(speech.id) if speech else MOCK_REACTION_SEED)
    remarks_pool = [
        "Hören Sie doch auf!", "Das glauben Sie doch selbst nicht!",
        "Das ist doch absurd!", "Schämen Sie sich!", "Sehr fragwürdig!",
        "Das ist falsch!", "Wo sind die Ergebnisse?", "Eine Katastrophe!",
    ]
    questions_pool = [
        "Wann legen Sie endlich konkrete Zahlen vor?",
        "Welche Alternativen haben Sie geprüft?",
        "Was kostet das den Steuerzahler?",
        "Ist das mit Ihrem Koalitionspartner abgestimmt?",
    ]
    reactions = []
    for m in members:
        roll = rnd.random()
        if own_faction:
            if roll < 0.60:
                reactions.append(Reaction(
                    member_id=m.id, reaction_type=ReactionType.CLAP,
                    intensity=rnd.randint(3, 5),
                ))
            elif roll < 0.75:
                reactions.append(Reaction(
                    member_id=m.id, reaction_type=ReactionType.REMARK,
                    text=rnd.choice(["Sehr gut!", "Richtig so!", "Sehr wahr!", "Bravo!"]),
                ))
            else:
                reactions.append(Reaction(member_id=m.id, reaction_type=ReactionType.SILENT))
        else:
            if roll < 0.08:
                reactions.append(Reaction(
                    member_id=m.id, reaction_type=ReactionType.CLAP,
                    intensity=rnd.randint(1, 2),
                ))
            elif roll < 0.30:
                reactions.append(Reaction(
                    member_id=m.id, reaction_type=ReactionType.REMARK,
                    text=rnd.choice(remarks_pool),
                ))
            elif roll < 0.42:
                reactions.append(Reaction(
                    member_id=m.id, reaction_type=ReactionType.QUESTION,
                    text=rnd.choice(questions_pool),
                ))
            else:
                reactions.append(Reaction(member_id=m.id, reaction_type=ReactionType.SILENT))
    return reactions


# ─── Simulation state (KV-backed) ─────────────────────────────────────────────


async def get_simulation_state(
    kv,
    api_key_bundestag: str,
    api_key_openai: Optional[str],
    model: str,
) -> dict:
    speeches = await fetch_speeches(kv, api_key_bundestag)
    current_speech_id = await kv_get(kv, "current_speech_id")
    current_speech = None
    reactions: List[Reaction] = []

    if current_speech_id:
        current_speech = next((s for s in speeches if s.id == current_speech_id), None)
    if current_speech is None and speeches:
        current_speech = speeches[0]
        await kv_put(kv, "current_speech_id", current_speech.id)
    if current_speech:
        members = await fetch_members(kv)
        reactions = await generate_reactions(kv, current_speech, members, api_key_openai, model)

    return SimulationState(
        current_speech=current_speech,
        reactions=reactions,
        available_speeches=speeches,
        is_live=False,
    ).model_dump()


# ─── Mock data fallbacks ──────────────────────────────────────────────────────


def _mock_speeches() -> List[Speech]:
    return [
        Speech(
            id="mock_001",
            speaker_name="Karl Lauterbach",
            speaker_party="SPD",
            text=(
                "Sehr geehrte Frau Präsidentin, meine Damen und Herren! "
                "Die Gesundheitsversorgung in Deutschland steht vor enormen Herausforderungen. "
                "Die Krankenhausreform, die wir jetzt auf den Weg bringen, ist längst überfällig. "
                "Wir werden Qualitätszentren schaffen und die Versorgung verbessern. "
                "Die CDU/CSU hat jahrelang Reformen blockiert. Jetzt handeln wir."
            ),
            date="2024-03-15",
            session_id="session_001",
            session_title="Plenarsitzung 20. Wahlperiode",
            topic="Krankenhausreform",
        ),
        Speech(
            id="mock_002",
            speaker_name="Robert Habeck",
            speaker_party="GRÜNE",
            text=(
                "Sehr geehrter Herr Präsident, werte Kolleginnen und Kollegen! "
                "Die Energiewende ist kein Luxusprojekt, sondern eine wirtschaftliche Notwendigkeit. "
                "Deutschland kann und muss Vorreiter bei den erneuerbaren Energien werden. "
                "Der Ausbau der Windkraft schreitet voran, die Solarenergie boomt. "
                "Wir werden die Klimaziele erreichen – entgegen allen Unkenrufen."
            ),
            date="2024-03-14",
            session_id="session_001",
            session_title="Plenarsitzung 20. Wahlperiode",
            topic="Energiewende und Klimaschutz",
        ),
        Speech(
            id="mock_003",
            speaker_name="Olaf Scholz",
            speaker_party="SPD",
            text=(
                "Sehr geehrte Frau Präsidentin! Meine Damen und Herren! "
                "Deutschland steht fest an der Seite der Ukraine. "
                "Wir haben mehr Waffen geliefert als jedes andere europäische Land. "
                "Gleichzeitig setzen wir alles daran, eine Eskalation zu verhindern. "
                "Mein Ziel ist: Frieden in Europa – ohne Aufgabe der ukrainischen Souveränität."
            ),
            date="2024-03-13",
            session_id="session_002",
            session_title="Plenarsitzung 20. Wahlperiode",
            topic="Ukraine-Hilfe und Außenpolitik",
        ),
        Speech(
            id="mock_004",
            speaker_name="Christian Lindner",
            speaker_party="FDP",
            text=(
                "Herr Präsident, sehr geehrte Damen und Herren! "
                "Die Schuldenbremse ist kein Dogma, sie ist Vernunft. "
                "Wer glaubt, man könne sich dauerhaft auf Kosten künftiger Generationen finanzieren, "
                "der irrt. Wir brauchen Strukturreformen, keine neuen Schulden."
            ),
            date="2024-03-12",
            session_id="session_002",
            session_title="Plenarsitzung 20. Wahlperiode",
            topic="Bundeshaushalt und Schuldenbremse",
        ),
        Speech(
            id="mock_005",
            speaker_name="Nancy Faeser",
            speaker_party="SPD",
            text=(
                "Sehr geehrte Frau Präsidentin! "
                "Die irreguläre Migration stellt unser Land vor Herausforderungen. "
                "Wir handeln mit Augenmaß und humanitärer Verantwortung. "
                "Die Grenzkontrollen zeigen Wirkung, die Zahlen gehen zurück. "
                "Abschiebungen von Straftätern werden wir konsequent durchsetzen."
            ),
            date="2024-03-11",
            session_id="session_003",
            session_title="Plenarsitzung 20. Wahlperiode",
            topic="Migrationspolitik",
        ),
    ]


def _mock_sessions() -> list:
    return [
        {"id": "session_001", "title": "165. Sitzung", "date": "2024-03-15", "session_number": "165"},
        {"id": "session_002", "title": "164. Sitzung", "date": "2024-03-13", "session_number": "164"},
        {"id": "session_003", "title": "163. Sitzung", "date": "2024-03-11", "session_number": "163"},
    ]


# ─── FastAPI app ──────────────────────────────────────────────────────────────

app = FastAPI(
    title="Zwillingstag – CDU Digital Twin",
    description="Real-time simulation of CDU/CSU Bundestag member reactions.",
    version="1.0.0",
)


def _env(request: Request):
    return request.scope["env"]


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/members")
async def get_members(request: Request):
    members = await fetch_members(_env(request).KV_CACHE)
    return [m.model_dump() for m in members]


@app.get("/api/sessions")
async def get_sessions(request: Request):
    env = _env(request)
    api_key = getattr(env, "BUNDESTAG_API_KEY", "") or ""
    return await fetch_recent_sessions(api_key)


@app.get("/api/speeches")
async def get_speeches(request: Request):
    env = _env(request)
    api_key = getattr(env, "BUNDESTAG_API_KEY", "") or ""
    speeches = await fetch_speeches(env.KV_CACHE, api_key)
    return [s.model_dump() for s in speeches]


@app.get("/api/speeches/{speech_id}")
async def get_speech(speech_id: str, request: Request):
    env = _env(request)
    api_key = getattr(env, "BUNDESTAG_API_KEY", "") or ""
    speech = await get_speech_by_id(env.KV_CACHE, api_key, speech_id)
    if not speech:
        raise HTTPException(status_code=404, detail="Speech not found")
    return speech.model_dump()


@app.get("/api/reactions/{speech_id}")
async def get_reactions(speech_id: str, request: Request):
    env = _env(request)
    kv = env.KV_CACHE
    api_key_bundestag = getattr(env, "BUNDESTAG_API_KEY", "") or ""
    api_key_openai = getattr(env, "OPENAI_API_KEY", "") or ""
    model = getattr(env, "OPENAI_MODEL", "gpt-4o-mini") or "gpt-4o-mini"
    speech = await get_speech_by_id(kv, api_key_bundestag, speech_id)
    if not speech:
        raise HTTPException(status_code=404, detail="Speech not found")
    members = await fetch_members(kv)
    reactions = await generate_reactions(kv, speech, members, api_key_openai or None, model)
    return [r.model_dump() for r in reactions]


@app.get("/api/state")
async def get_state(request: Request):
    env = _env(request)
    kv = env.KV_CACHE
    api_key_bundestag = getattr(env, "BUNDESTAG_API_KEY", "") or ""
    api_key_openai = getattr(env, "OPENAI_API_KEY", "") or ""
    model = getattr(env, "OPENAI_MODEL", "gpt-4o-mini") or "gpt-4o-mini"
    return await get_simulation_state(kv, api_key_bundestag, api_key_openai or None, model)


# ─── Worker entry point ───────────────────────────────────────────────────────


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        """Handle all incoming requests.

        WebSocket upgrades (/ws) are handled directly using the Workers
        WebSocket API.  All other requests are forwarded to the FastAPI app
        via the ASGI bridge.
        """
        url = request.url
        upgrade = request.headers.get("upgrade", "")

        if upgrade.lower() == "websocket" and "/ws" in url:
            return await self._handle_websocket(request)

        import asgi
        return await asgi.fetch(app, request.js_object, self.env)

    async def _handle_websocket(self, request):
        """Accept a WebSocket connection and stream simulation state."""
        from js import WebSocketPair, Response

        pair = WebSocketPair.new()
        client_ws = pair["0"]
        server_ws = pair["1"]
        server_ws.accept()

        env = self.env
        kv = env.KV_CACHE
        api_key_bundestag = getattr(env, "BUNDESTAG_API_KEY", "") or ""
        api_key_openai = getattr(env, "OPENAI_API_KEY", "") or ""
        model = getattr(env, "OPENAI_MODEL", "gpt-4o-mini") or "gpt-4o-mini"

        # Send current state immediately on connect
        try:
            state = await get_simulation_state(kv, api_key_bundestag, api_key_openai or None, model)
            server_ws.send(json.dumps(state))
        except Exception as e:
            logger.error(f"WS initial state error: {e}")

        # Handle incoming messages via event listener
        @server_ws.addEventListener("message")
        async def on_message(event):
            try:
                msg = json.loads(event.data)
                action = msg.get("action")
                if action == "select_speech":
                    await kv_put(kv, "current_speech_id", msg["speech_id"])
                    new_state = await get_simulation_state(
                        kv, api_key_bundestag, api_key_openai or None, model
                    )
                    server_ws.send(json.dumps(new_state))
                elif action == "refresh":
                    # Clear the speeches cache so fresh data is fetched
                    await kv.delete("speeches")
                    new_state = await get_simulation_state(
                        kv, api_key_bundestag, api_key_openai or None, model
                    )
                    server_ws.send(json.dumps(new_state))
            except Exception as e:
                logger.error(f"WS message handler error: {e}")

        return Response.new(None, status=101, webSocket=client_ws)
