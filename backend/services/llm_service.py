"""
LLM service for generating CDU/CSU member reactions to Bundestag speeches.
Uses OpenAI (configurable) with a single call per speech to minimise API usage.
"""

import json
import logging
import os
import random
from typing import List, Optional

from models import Member, Reaction, ReactionType, Speech

logger = logging.getLogger(__name__)


class LLMService:
    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o-mini"):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = model
        self._client = None

    def _get_client(self):
        if self._client is None and self.api_key:
            try:
                from openai import AsyncOpenAI
                self._client = AsyncOpenAI(api_key=self.api_key)
            except ImportError:
                logger.warning("openai package not installed – falling back to mock")
        return self._client

    def _build_prompt(self, speech: Speech, members: List[Member]) -> str:
        members_summary = "\n".join(
            f"- ID:{m.id} | {m.name} ({m.party}, {m.state}) | Stil: {m.political_style[:120]}"
            for m in members
        )
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

Berücksichtige: Kommt die Rede von Regierung/Koalition? CDU/CSU ist Opposition – bei Regierungsreden eher kritisch/still/Zwischenrufe. Bei positiv bewerteten Aussagen auch mal Applaus.

Gib NUR valides JSON zurück (kein Markdown), exakt dieses Format:
{{"reactions": [{{"member_id": "...", "reaction_type": "clap|remark|question|silent", "intensity": 1, "text": null}}]}}
"""

    async def generate_reactions(
        self, speech: Speech, members: List[Member]
    ) -> List[Reaction]:
        """Generate reactions for all members with a single LLM call."""
        client = self._get_client()
        if client is None:
            logger.info("No OpenAI client – using mock reactions")
            return self._mock_reactions(members, speech)

        prompt = self._build_prompt(speech, members)
        try:
            response = await client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Du bist ein präziser politischer Simulator. "
                            "Antworte ausschließlich mit validem JSON, ohne Markdown-Formatierung."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.8,
                max_tokens=4000,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content
            data = json.loads(raw)
            reactions = []
            member_ids = {m.id for m in members}
            for item in data.get("reactions", []):
                mid = item.get("member_id")
                if mid not in member_ids:
                    continue
                try:
                    r_type = ReactionType(item.get("reaction_type", "silent"))
                except ValueError:
                    r_type = ReactionType.SILENT
                reactions.append(
                    Reaction(
                        member_id=mid,
                        reaction_type=r_type,
                        intensity=max(1, min(5, int(item.get("intensity", 1)))),
                        text=item.get("text"),
                    )
                )
            # Fill in missing members as silent
            reacted_ids = {r.member_id for r in reactions}
            for m in members:
                if m.id not in reacted_ids:
                    reactions.append(Reaction(member_id=m.id, reaction_type=ReactionType.SILENT))
            return reactions
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return self._mock_reactions(members, speech)

    def _mock_reactions(self, members: List[Member], speech: Optional[Speech] = None) -> List[Reaction]:
        """Generate deterministic mock reactions based on member profile.

        CDU/CSU is in opposition (20th Bundestag). They applaud their own faction
        and heckle the governing coalition (SPD/GRÜNE/FDP).
        """
        reactions = []
        # True when CDU should react positively (own faction speaking)
        own_faction_speaking = False
        if speech and speech.speaker_party:
            own_faction_speaking = speech.speaker_party.upper() in ("CDU", "CSU", "CDU/CSU")

        rnd = random.Random(
            hash(speech.id) if speech else 42
        )

        remarks_pool = [
            "Hören Sie doch auf!",
            "Das glauben Sie doch selbst nicht!",
            "Das ist doch absurd!",
            "Schämen Sie sich!",
            "Das können Sie besser!",
            "Und die Fakten?",
            "Sehr fragwürdig!",
            "Das ist falsch!",
            "Wo sind die Ergebnisse?",
            "Eine Katastrophe!",
        ]
        questions_pool = [
            "Wann legen Sie endlich konkrete Zahlen vor?",
            "Welche Alternativen haben Sie geprüft?",
            "Wie erklären Sie das den Bürgerinnen?",
            "Ist das mit Ihrem Koalitionspartner abgestimmt?",
            "Was kostet das den Steuerzahler?",
        ]

        for m in members:
            roll = rnd.random()
            if own_faction_speaking:
                # Speech by CDU/CSU – enthusiastic applause and affirmative remarks
                if roll < 0.60:
                    reactions.append(Reaction(
                        member_id=m.id,
                        reaction_type=ReactionType.CLAP,
                        intensity=rnd.randint(3, 5),
                    ))
                elif roll < 0.75:
                    reactions.append(Reaction(
                        member_id=m.id,
                        reaction_type=ReactionType.REMARK,
                        text=rnd.choice(["Sehr gut!", "Richtig so!", "Sehr wahr!", "Bravo!", "Genau!"]),
                    ))
                else:
                    reactions.append(Reaction(member_id=m.id, reaction_type=ReactionType.SILENT))
            else:
                # Speech by governing coalition (SPD/GRÜNE/FDP) or other party – critical
                if roll < 0.08:
                    # Very few CDU members applaud government speeches
                    reactions.append(Reaction(
                        member_id=m.id,
                        reaction_type=ReactionType.CLAP,
                        intensity=rnd.randint(1, 2),
                    ))
                elif roll < 0.30:
                    reactions.append(Reaction(
                        member_id=m.id,
                        reaction_type=ReactionType.REMARK,
                        text=rnd.choice(remarks_pool),
                    ))
                elif roll < 0.42:
                    reactions.append(Reaction(
                        member_id=m.id,
                        reaction_type=ReactionType.QUESTION,
                        text=rnd.choice(questions_pool),
                    ))
                else:
                    reactions.append(Reaction(member_id=m.id, reaction_type=ReactionType.SILENT))
        return reactions
