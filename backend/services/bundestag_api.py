"""
Bundestag DIP API integration.
Docs: https://dip.bundestag.de/api/v1/
"""

import httpx
import logging
from typing import List, Optional
from datetime import datetime
from models import Speech

logger = logging.getLogger(__name__)

BUNDESTAG_API_BASE = "https://search.dip.bundestag.de/api/v1"


class BundestagAPI:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self.client = httpx.AsyncClient(timeout=30.0)

    def _params(self, **kwargs) -> dict:
        params = {}
        if self.api_key:
            params["apikey"] = self.api_key
        params.update(kwargs)
        return params

    async def get_recent_speeches(self, limit: int = 20) -> List[Speech]:
        """Fetch recent plenary speeches."""
        if not self.api_key:
            return self._mock_speeches()
        try:
            resp = await self.client.get(
                f"{BUNDESTAG_API_BASE}/aktivitaet",
                params=self._params(
                    vorgangstyp="Rede",
                    zuordnung="BT",
                    f_aktivitaetsart_p="Rede",
                    format="json",
                    num=limit,
                ),
            )
            resp.raise_for_status()
            data = resp.json()
            speeches = []
            for item in data.get("documents", []):
                speeches.append(self._parse_activity(item))
            return [s for s in speeches if s is not None]
        except Exception as e:
            logger.error(f"Failed to fetch speeches from DIP API: {e}")
            return self._mock_speeches()

    async def get_speech(self, speech_id: str) -> Optional[Speech]:
        """Get a specific speech by id."""
        if not self.api_key:
            return next((s for s in self._mock_speeches() if s.id == speech_id), None)
        try:
            resp = await self.client.get(
                f"{BUNDESTAG_API_BASE}/aktivitaet/{speech_id}",
                params=self._params(),
            )
            resp.raise_for_status()
            item = resp.json()
            return self._parse_activity(item)
        except Exception as e:
            logger.error(f"Failed to fetch speech {speech_id}: {e}")
            return None

    async def get_recent_sessions(self, limit: int = 10) -> list:
        """Fetch recent plenary session headers."""
        if not self.api_key:
            return self._mock_sessions()
        try:
            resp = await self.client.get(
                f"{BUNDESTAG_API_BASE}/plenarprotokoll",
                params=self._params(f_wahlperiode=20, format="json", num=limit),
            )
            resp.raise_for_status()
            data = resp.json()
            sessions = []
            for item in data.get("documents", []):
                sessions.append(
                    {
                        "id": item.get("id", ""),
                        "title": item.get("titel", ""),
                        "date": item.get("datum", ""),
                        "session_number": item.get("sitzungsnummer", ""),
                    }
                )
            return sessions
        except Exception as e:
            logger.error(f"Failed to fetch sessions: {e}")
            return self._mock_sessions()

    def _parse_activity(self, item: dict) -> Optional[Speech]:
        try:
            text = item.get("aktivitaetsbezug", "") or item.get("abstrakt", "") or ""
            if not text:
                text = item.get("titel", "")

            # Resolve speaker name: prefer structured redner field, fall back to autor_einzel
            speaker = item.get("redner") or {}
            redner_name = f"{speaker.get('vorname', '')} {speaker.get('nachname', '')}".strip()
            if not redner_name:
                autor_list = item.get("autor_einzel")
                if isinstance(autor_list, list) and autor_list:
                    redner_name = autor_list[0].get("titel", "")
            speaker_name = redner_name or "Unbekannt"

            # Resolve party
            fraktion = item.get("fraktion")
            speaker_party = fraktion.get("bezeichnung") if isinstance(fraktion, dict) else None

            return Speech(
                id=str(item.get("id", "")),
                speaker_name=speaker_name,
                speaker_party=speaker_party,
                text=text,
                date=item.get("datum", datetime.now().strftime("%Y-%m-%d")),
                session_id=str(item.get("plenarprotokoll_id", "")),
                topic=item.get("titel", ""),
            )
        except Exception as e:
            logger.error(f"Error parsing activity: {e}")
            return None

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
