"""
Orchestrates parliament debate simulation:
- loads CDU/CSU member data from the Bundestag XML API (via MdbService)
- assigns seats in semi-circular layout
- manages current speech and cached reactions
- triggers LLM generation when speech changes
"""

import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

from models import Member, Reaction, SimulationState, Speech
from services.bundestag_api import BundestagAPI
from services.kv_store import KVStore
from services.llm_service import LLMService
from services.mdb_service import MdbService

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"


class DebateSimulator:
    def __init__(
        self,
        bundestag_api: BundestagAPI,
        llm_service: LLMService,
        mdb_service: MdbService,
        kv_store: Optional[KVStore] = None,
    ):
        self.bundestag_api = bundestag_api
        self.llm_service = llm_service
        self.mdb_service = mdb_service
        self.kv_store = kv_store
        self.members: List[Member] = []
        self.available_speeches: List[Speech] = []
        self.current_speech: Optional[Speech] = None
        self.reactions: List[Reaction] = []
        # In-memory reaction cache (used when no KV store is configured)
        self._reaction_cache: Dict[str, List[Reaction]] = {}

    # ------------------------------------------------------------------
    # Member data
    # ------------------------------------------------------------------

    async def load_members(self):
        """Fetch CDU/CSU member data from the Bundestag XML API (cached)."""
        members = await self.mdb_service.fetch_members()
        self.members = self._assign_seats(members)
        logger.info(f"Loaded {len(self.members)} CDU/CSU members")

    def _assign_seats(self, members: List[Member]) -> List[Member]:
        """
        Arrange members in a semi-circular parliament layout.
        Rows go from front (row 0) to back (row N-1).
        """
        n = len(members)
        # Distribute members across rows of increasing length
        row_sizes = []
        remaining = n
        cols_in_first_row = max(6, n // 6)
        row = 0
        while remaining > 0:
            size = min(cols_in_first_row + row * 2, remaining)
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

    def get_members(self) -> List[dict]:
        return [m.model_dump() for m in self.members]

    # ------------------------------------------------------------------
    # Speeches
    # ------------------------------------------------------------------

    async def load_speeches(self):
        self.available_speeches = await self.bundestag_api.get_recent_speeches()
        if self.available_speeches and self.current_speech is None:
            await self.select_speech(self.available_speeches[0].id)

    async def select_speech(self, speech_id: str):
        speech = next((s for s in self.available_speeches if s.id == speech_id), None)
        if speech is None:
            speech = await self.bundestag_api.get_speech(speech_id)
        if speech is None:
            logger.warning(f"Speech {speech_id} not found")
            return
        self.current_speech = speech
        self.reactions = await self._get_or_generate_reactions(speech)

    async def _get_or_generate_reactions(self, speech: Speech) -> List[Reaction]:
        kv_key = f"reactions:{speech.id}"

        # 1. Try KV store (persistent across Workers restarts)
        if self.kv_store is not None:
            cached = await self.kv_store.get_json(kv_key)
            if cached is not None:
                try:
                    logger.info(f"KV cache hit for reactions:{speech.id}")
                    return [Reaction(**r) for r in cached]
                except Exception as e:
                    logger.warning(f"KV reaction cache parse error: {e}")
        # 2. Try in-memory cache
        elif speech.id in self._reaction_cache:
            logger.info(f"Memory cache hit for speech {speech.id}")
            return self._reaction_cache[speech.id]

        logger.info(f"Generating reactions for speech {speech.id}")
        reactions = await self.llm_service.generate_reactions(speech, self.members)

        if self.kv_store is not None:
            await self.kv_store.put_json(kv_key, [r.model_dump() for r in reactions])
        else:
            self._reaction_cache[speech.id] = reactions

        return reactions

    async def get_reactions(self, speech_id: str) -> List[dict]:
        speech = next((s for s in self.available_speeches if s.id == speech_id), None)
        if speech is None:
            speech = await self.bundestag_api.get_speech(speech_id)
        if speech is None:
            return []
        reactions = await self._get_or_generate_reactions(speech)
        return [r.model_dump() for r in reactions]

    async def get_current_speech(self) -> Optional[dict]:
        if self.current_speech is None:
            await self.load_speeches()
        if self.current_speech:
            return self.current_speech.model_dump()
        return None

    # ------------------------------------------------------------------
    # State & live updates
    # ------------------------------------------------------------------

    async def get_state(self) -> dict:
        if not self.available_speeches:
            await self.load_speeches()
        return SimulationState(
            current_speech=self.current_speech,
            reactions=self.reactions,
            available_speeches=self.available_speeches,
            is_live=False,
        ).model_dump()

    async def check_for_updates(self) -> bool:
        """Poll for new speeches; return True if state changed."""
        try:
            speeches = await self.bundestag_api.get_recent_speeches(limit=5)
            if not speeches:
                return False
            newest = speeches[0]
            if (
                not self.available_speeches
                or newest.id != self.available_speeches[0].id
            ):
                self.available_speeches = speeches + [
                    s for s in self.available_speeches if s.id not in {sp.id for sp in speeches}
                ]
                # Auto-select newest speech if no speech is currently selected
                if self.current_speech is None:
                    await self.select_speech(newest.id)
                return True
        except Exception as e:
            logger.error(f"check_for_updates error: {e}")
        return False

    async def refresh(self):
        self.available_speeches = []
        self.current_speech = None
        self.reactions = []
        await self.load_speeches()
