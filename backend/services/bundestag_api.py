"""
Bundestag DIP API + Plenarprotokoll XML integration.

Workflow:
  1. Query the DIP search API (https://search.dip.bundestag.de/api/v1/plenarprotokoll)
     to discover recent Bundestag (BT) plenary protocol documents.
  2. Each BT protocol includes an xml_url pointing to a structured stenographic report
     on dserver.bundestag.de.
  3. Download and parse those XML files to extract individual speeches with full text,
     speaker name, party (Fraktion), and agenda topic (Tagesordnungspunkt).
  4. Parsed protocols are cached to data/protocol_cache/ (6 h TTL) so repeated
     requests are served from disk.

Falls back to bundled mock speeches when no BUNDESTAG_API_KEY is configured.
"""

import hashlib
import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import httpx

from models import Speech

logger = logging.getLogger(__name__)

DIP_API_BASE = "https://search.dip.bundestag.de/api/v1"
DSERVER_BASE = "https://dserver.bundestag.de"

DATA_DIR = Path(__file__).parent.parent / "data"
CACHE_DIR = DATA_DIR / "protocol_cache"
CACHE_TTL_SECONDS = 6 * 3600  # 6 hours

# How many recent BT protocols to load on startup / refresh
PROTOCOLS_TO_LOAD = 3

# Topic text thresholds
_TOPIC_MIN_LEN = 10   # discard very short / empty titles
_TOPIC_MAX_LEN = 120  # truncate very long titles


class BundestagAPI:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers={"User-Agent": "Zwillingstag/1.0 (research project)"},
        )
        # In-memory speech index: speech_id → Speech
        self._speech_index: Dict[str, Speech] = {}

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def get_recent_speeches(self, limit: int = 20) -> List[Speech]:
        """Return the most recent speeches from the last few protocols."""
        if not self.api_key:
            return self._mock_speeches()
        try:
            speeches = await self._load_recent_speeches(limit)
            return speeches[:limit]
        except Exception as e:
            logger.error(f"get_recent_speeches error: {e}")
            return self._mock_speeches()

    async def get_speech(self, speech_id: str) -> Optional[Speech]:
        """Return a specific speech by ID."""
        if not self.api_key:
            return next((s for s in self._mock_speeches() if s.id == speech_id), None)
        # Try the in-memory index first
        if speech_id in self._speech_index:
            return self._speech_index[speech_id]
        # Otherwise load recent speeches to populate the index
        await self._load_recent_speeches()
        return self._speech_index.get(speech_id)

    async def get_recent_sessions(self, limit: int = 10) -> list:
        """Return recent session metadata."""
        if not self.api_key:
            return self._mock_sessions()
        try:
            protocols = await self._fetch_protocol_list(limit)
            return [
                {
                    "id": p["id"],
                    "title": p["titel"],
                    "date": p["datum"],
                    "session_number": p.get("dokumentnummer", ""),
                }
                for p in protocols
            ]
        except Exception as e:
            logger.error(f"get_recent_sessions error: {e}")
            return self._mock_sessions()

    # ------------------------------------------------------------------
    # Internal: DIP API
    # ------------------------------------------------------------------

    def _dip_params(self, **kwargs) -> dict:
        params = {"apikey": self.api_key, "format": "json"}
        params.update(kwargs)
        return params

    async def _fetch_protocol_list(self, limit: int = 10) -> List[dict]:
        """Query DIP for recent BT plenarprotokolle with XML URLs."""
        resp = await self.client.get(
            f"{DIP_API_BASE}/plenarprotokoll/",
            # Fetch extra documents because the list also includes BR (Bundesrat) protocols
            # that lack an xml_url and are filtered out below.
            params=self._dip_params(**{"f.herausgeber": "BT", "num": limit * 2}),
        )
        resp.raise_for_status()
        data = resp.json()
        result = []
        for doc in data.get("documents", []):
            if doc.get("herausgeber") != "BT":
                continue
            xml_url = doc.get("fundstelle", {}).get("xml_url")
            if xml_url:
                result.append(doc)
            if len(result) >= limit:
                break
        return result

    async def _load_recent_speeches(self, limit: int = 40) -> List[Speech]:
        """Fetch + parse the most recent protocols and return speeches."""
        protocols = await self._fetch_protocol_list(PROTOCOLS_TO_LOAD)
        all_speeches: List[Speech] = []
        for proto in protocols:
            xml_url = proto["fundstelle"]["xml_url"]
            session_id = str(proto["id"])
            session_title = proto["titel"]
            date_str = proto["datum"]
            speeches = await self._get_or_parse_protocol(
                xml_url, session_id, session_title, date_str
            )
            all_speeches.extend(speeches)
            # Populate index
            for s in speeches:
                self._speech_index[s.id] = s
        # Sort newest-first (protocols already ordered newest-first)
        return all_speeches

    # ------------------------------------------------------------------
    # Internal: protocol cache + XML parsing
    # ------------------------------------------------------------------

    async def _get_or_parse_protocol(
        self, xml_url: str, session_id: str, session_title: str, date_str: str
    ) -> List[Speech]:
        """Return speeches for a protocol, using disk cache when available."""
        cache_key = hashlib.md5(xml_url.encode()).hexdigest()[:12]
        cache_file = CACHE_DIR / f"{cache_key}.json"

        if cache_file.exists():
            age = time.time() - cache_file.stat().st_mtime
            if age < CACHE_TTL_SECONDS:
                try:
                    with open(cache_file, encoding="utf-8") as f:
                        raw = json.load(f)
                    return [Speech(**s) for s in raw]
                except Exception as e:
                    logger.warning(f"Cache read error for {cache_key}: {e}")

        logger.info(f"Fetching protocol XML: {xml_url}")
        try:
            resp = await self.client.get(xml_url)
            resp.raise_for_status()
            speeches = self._parse_protocol_xml(
                resp.content, session_id, session_title, date_str
            )
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump([s.model_dump() for s in speeches], f, ensure_ascii=False, indent=2)
            return speeches
        except Exception as e:
            logger.error(f"Failed to fetch/parse protocol {xml_url}: {e}")
            return []

    def _parse_protocol_xml(
        self,
        content: bytes,
        session_id: str,
        session_title: str,
        date_str: str,
    ) -> List[Speech]:
        """Parse a Bundestag plenarprotokoll XML and extract all speeches."""
        try:
            root = ET.fromstring(content)
        except ET.ParseError as e:
            logger.error(f"XML parse error: {e}")
            return []

        # Read session date from XML header (format: DD.MM.YYYY)
        sitzungsverlauf = root.find("sitzungsverlauf")
        if sitzungsverlauf is None:
            return []

        # Build map: rede_id → topic (from containing Tagesordnungspunkt)
        rede_to_topic: Dict[str, str] = {}
        for top in sitzungsverlauf:
            topic = self._extract_top_title(top)
            for rede in top.findall(".//rede"):
                rede_id = rede.get("id", "")
                if rede_id:
                    rede_to_topic[rede_id] = topic

        speeches: List[Speech] = []
        for rede in sitzungsverlauf.findall(".//rede"):
            speech = self._parse_rede(
                rede,
                session_id=session_id,
                session_title=session_title,
                date_str=date_str,
                topic=rede_to_topic.get(rede.get("id", ""), ""),
            )
            if speech:
                speeches.append(speech)

        return speeches

    def _parse_rede(
        self,
        rede: ET.Element,
        session_id: str,
        session_title: str,
        date_str: str,
        topic: str,
    ) -> Optional[Speech]:
        """Parse a single <rede> element into a Speech object."""
        rede_id = rede.get("id", "")
        if not rede_id:
            return None

        # Speaker info from <redner>
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

        # Full speech text: all <p> elements except the redner paragraph
        text_parts = []
        for p in rede:
            if p.tag == "p" and p.get("klasse") != "redner":
                t = (p.text or "").strip()
                if t:
                    text_parts.append(t)
            elif p.tag == "kommentar":
                pass  # Skip [Beifall ...] annotations
        full_text = " ".join(text_parts)

        if not full_text:
            return None

        # Normalize date to YYYY-MM-DD
        date_normalized = self._normalize_date(date_str)

        # Compound speech ID: session_id + rede_id
        speech_id = f"{session_id}:{rede_id}"

        return Speech(
            id=speech_id,
            speaker_name=speaker_name,
            speaker_party=fraktion or None,
            text=full_text,
            date=date_normalized,
            session_id=session_id,
            session_title=session_title,
            topic=topic,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_top_title(top: ET.Element) -> str:
        """Get the agenda item title from a <tagesordnungspunkt> element."""
        # Prefer bold <T_fett> paragraph, fall back to <T_NaS>
        for klasse in ("T_fett", "T_NaS"):
            for p in top:
                if p.get("klasse") == klasse:
                    text = (p.text or "").strip()
                    text = re.sub(r"\s+", " ", text)
                    if len(text) > _TOPIC_MIN_LEN:
                        return text[:_TOPIC_MAX_LEN]
        top_id = top.get("top-id", "")
        return top_id

    @staticmethod
    def _normalize_date(date_str: str) -> str:
        """Convert DD.MM.YYYY or YYYY-MM-DD to YYYY-MM-DD."""
        if not date_str:
            return datetime.now().strftime("%Y-%m-%d")
        if re.match(r"\d{2}\.\d{2}\.\d{4}", date_str):
            d, m, y = date_str[:10].split(".")
            return f"{y}-{m}-{d}"
        return date_str[:10]

    # ------------------------------------------------------------------
    # Mock fallback (used when BUNDESTAG_API_KEY is not set)
    # ------------------------------------------------------------------

    def _mock_speeches(self) -> List[Speech]:
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
                    "Ich bin sicher, dass wir damit die richtige Richtung einschlagen. "
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
                    "Wir werden die Klimaziele erreichen – entgegen allen Unkenrufen. "
                    "Die Transformation unserer Wirtschaft schafft neue Arbeitsplätze und Wohlstand."
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
                    "Mein Ziel ist: Frieden in Europa – ohne Aufgabe der ukrainischen Souveränität. "
                    "Das ist keine Schwäche, das ist verantwortungsvolle Staatskunst."
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
                    "der irrt. Wir brauchen Strukturreformen, keine neuen Schulden. "
                    "Die FDP steht für Haushaltsdisziplin und wirtschaftliche Vernunft. "
                    "Investitionen ja – aber finanziert aus Einsparungen, nicht aus Schulden."
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
                    "Gleichzeitig brauchen wir legale Zuwanderung für unseren Arbeitsmarkt. "
                    "Abschiebungen von Straftätern werden wir konsequent durchsetzen."
                ),
                date="2024-03-11",
                session_id="session_003",
                session_title="Plenarsitzung 20. Wahlperiode",
                topic="Migrationspolitik",
            ),
        ]

    def _mock_sessions(self) -> list:
        return [
            {"id": "session_001", "title": "165. Sitzung", "date": "2024-03-15", "session_number": "165"},
            {"id": "session_002", "title": "164. Sitzung", "date": "2024-03-13", "session_number": "164"},
            {"id": "session_003", "title": "163. Sitzung", "date": "2024-03-11", "session_number": "163"},
        ]
