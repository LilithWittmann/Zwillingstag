"""
Bundestag MdB XML API service.

Fetches all active CDU/CSU Bundestag members from the official XML feed at
  https://www.bundestag.de/xml/v2/mdb/index.xml
including their profile pictures and biographical data.

Results are stored in the KV store (no expiry) so that subsequent server
restarts are instant.  Falls back to in-memory cache when no KV store is
configured and to the static data/cdu_members.json file when the remote API
is unreachable.
"""

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import List, Optional

import httpx

from models import Member
from services.kv_store import KVStore

logger = logging.getLogger(__name__)

INDEX_URL = "https://www.bundestag.de/xml/v2/mdb/index.xml"
DATA_DIR = Path(__file__).parent.parent / "data"
KV_KEY_MEMBERS = "mdb:members"
# Concurrent HTTP requests when enriching individual member XMLs
ENRICH_CONCURRENCY = 15


class MdbService:
    """Loads CDU/CSU member data from the Bundestag XML API."""

    def __init__(self, kv_store: Optional[KVStore] = None) -> None:
        self.kv_store = kv_store
        self._client = httpx.AsyncClient(
            timeout=30.0,
            headers={"User-Agent": "Zwillingstag/1.0 (research project)"},
        )
        # In-memory cache used when no KV store is available
        self._mem_cache: Optional[List[Member]] = None

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    async def fetch_members(self) -> List[Member]:
        """Return all active CDU/CSU members, using KV store when available."""
        # 1. Try KV store (persistent across Workers restarts)
        if self.kv_store is not None:
            cached = await self.kv_store.get_json(KV_KEY_MEMBERS)
            if cached is not None:
                try:
                    logger.info("Using KV-cached MdB data")
                    return [Member(**m) for m in cached]
                except Exception as e:
                    logger.warning(f"KV member cache parse error: {e}")
        # 2. Try in-memory cache (local dev without KV)
        elif self._mem_cache is not None:
            logger.info("Using in-memory MdB data")
            return self._mem_cache

        logger.info("Fetching CDU/CSU member data from Bundestag XML API…")
        try:
            basic = await self._fetch_index()
            enriched = await self._enrich_all(basic)
            await self._save_cache(enriched)
            logger.info(f"Loaded and cached {len(enriched)} CDU/CSU members")
            return enriched
        except Exception as e:
            logger.error(f"Failed to fetch from Bundestag API: {e}")
            logger.warning("Falling back to static cdu_members.json")
            return self._load_static_fallback()

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    async def _save_cache(self, members: List[Member]) -> None:
        serialised = [m.model_dump() for m in members]
        if self.kv_store is not None:
            await self.kv_store.put_json(KV_KEY_MEMBERS, serialised)
        else:
            self._mem_cache = members

    def _load_static_fallback(self) -> List[Member]:
        path = DATA_DIR / "cdu_members.json"
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        return [Member(**m) for m in raw]

    # ------------------------------------------------------------------
    # XML parsing
    # ------------------------------------------------------------------

    async def _fetch_index(self) -> List[dict]:
        """Fetch the index XML and return a list of basic member dicts."""
        resp = await self._client.get(INDEX_URL)
        resp.raise_for_status()
        return self._parse_index_xml(resp.content)

    def _parse_index_xml(self, content: bytes) -> List[dict]:
        import xml.etree.ElementTree as ET

        root = ET.fromstring(content)
        members = []
        for mdb in root.findall(".//mdb"):
            fraktion = mdb.get("fraktion", "")
            if "CDU" not in fraktion and "CSU" not in fraktion:
                continue

            mdb_id_el = mdb.find("mdbID")
            if mdb_id_el is None or mdb_id_el.get("status") != "Aktiv":
                continue

            # Name: index format is "LastName, FirstName"
            name_el = mdb.find("mdbName")
            raw_name = (name_el.text or "").strip() if name_el is not None else ""
            parts = raw_name.split(", ", 1)
            if len(parts) == 2:
                full_name = f"{parts[1]} {parts[0]}".strip()
            else:
                full_name = raw_name

            foto_url = self._text(mdb.find("mdbFotoURL"))
            foto_gross_url = self._text(mdb.find("mdbFotoGrossURL"))

            members.append(
                {
                    "mdb_id": mdb_id_el.text or "",
                    "name": full_name,
                    "state": self._text(mdb.find("mdbLand")) or "",
                    "photo_url": foto_gross_url or foto_url,
                    "info_xml_url": self._text(mdb.find("mdbInfoXMLURL")),
                    # party will be filled from individual XML; default to CDU
                    "party": "CDU",
                    "role": None,
                    "focus_areas": [],
                    "political_style": "",
                    "bio": None,
                }
            )
        return members

    async def _enrich_all(self, basic_members: List[dict]) -> List[Member]:
        """Fetch individual XMLs in parallel to add party/bio/role data."""
        semaphore = asyncio.Semaphore(ENRICH_CONCURRENCY)

        async def enrich_one(m: dict) -> Member:
            url = m.get("info_xml_url")
            if not url:
                return self._dict_to_member(m)
            async with semaphore:
                try:
                    resp = await self._client.get(url)
                    resp.raise_for_status()
                    return self._parse_individual_xml(m, resp.content)
                except Exception as e:
                    logger.debug(f"Failed to enrich {m['name']}: {e}")
                    return self._dict_to_member(m)

        results = await asyncio.gather(*[enrich_one(m) for m in basic_members])
        return list(results)

    def _parse_individual_xml(self, base: dict, content: bytes) -> Member:
        import xml.etree.ElementTree as ET

        root = ET.fromstring(content)
        info = root.find(".//mdbInfo")
        if info is None:
            return self._dict_to_member(base)

        partei = self._text(info.find("mdbPartei"))
        beruf = self._text(info.find("mdbBeruf"))
        bio_raw = self._text(info.find("mdbBiografischeInformationen")) or ""
        bio_clean = self._strip_html(bio_raw)[:500].strip()

        # Derive role from committee memberships
        role = self._extract_role(info, base["name"])

        # Build a short political style description for LLM prompting
        political_style = self._build_political_style(
            name=base["name"],
            party=partei or base["party"],
            state=base["state"],
            beruf=beruf,
            bio=bio_clean,
        )

        return Member(
            id=self._name_to_id(base["name"]),
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

    def _extract_role(self, info, name: str) -> Optional[str]:
        """Try to find a notable role from committee/fraction data in the XML."""
        # Look for Fraktionsvorstand or similar
        bio_raw = self._text(info.find("mdbBiografischeInformationen")) or ""
        bio = bio_raw.lower()

        role_keywords = [
            ("Fraktionsvorsitzender", "Fraktionsvorsitzende/-r CDU/CSU"),
            ("Parlamentarischer Geschäftsführer", "Parlamentarische/-r Geschäftsführer/-in"),
            ("Parlamentarische Staatssekretärin", "Parlamentarische/-r Staatssekretär/-in"),
            ("Parlamentarischer Staatssekretär", "Parlamentarische/-r Staatssekretär/-in"),
            ("Vorsitzender der", None),
            ("Vorsitzende der", None),
            ("Sprecher", None),
            ("Sprecherin", None),
        ]
        for keyword, label in role_keywords:
            if keyword.lower() in bio:
                return label or keyword
        return None

    def _build_political_style(
        self,
        name: str,
        party: str,
        state: str,
        beruf: Optional[str],
        bio: str,
    ) -> str:
        """
        Generate a concise political style description for the LLM prompt.
        Uses real bio text where available.
        """
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
            # Take first meaningful sentence of bio as context
            first_sentence = bio.split(".")[0].strip()
            if len(first_sentence) > 20:
                lines.append(first_sentence[:200])
        return "; ".join(lines)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _dict_to_member(self, d: dict) -> Member:
        return Member(
            id=self._name_to_id(d["name"]),
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

    @staticmethod
    def _name_to_id(name: str) -> str:
        """Convert full name to a stable snake_case id."""
        import unicodedata

        normalized = unicodedata.normalize("NFKD", name)
        ascii_name = normalized.encode("ascii", "ignore").decode("ascii")
        return re.sub(r"[^a-z0-9]+", "_", ascii_name.lower()).strip("_")

    @staticmethod
    def _text(el) -> Optional[str]:
        if el is None:
            return None
        return (el.text or "").strip() or None

    @staticmethod
    def _strip_html(text: str) -> str:
        """Remove HTML tags and normalize whitespace."""
        clean = re.sub(r"<[^>]+>", " ", text)
        clean = re.sub(r"&[a-z]+;", " ", clean)
        clean = re.sub(r"\s+", " ", clean)
        return clean.strip()
