from pydantic import BaseModel
from typing import Optional, List
from enum import Enum


class ReactionType(str, Enum):
    CLAP = "clap"
    REMARK = "remark"
    QUESTION = "question"
    SILENT = "silent"


class Member(BaseModel):
    id: str
    name: str
    party: str  # CDU or CSU
    state: str
    role: Optional[str] = None
    focus_areas: List[str] = []
    political_style: str = ""
    seat_row: int = 0
    seat_col: int = 0


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
    intensity: int = 1  # 1-5, used for clapping
    text: Optional[str] = None  # for remarks/questions


class SimulationState(BaseModel):
    current_speech: Optional[Speech] = None
    reactions: List[Reaction] = []
    available_speeches: List[Speech] = []
    is_live: bool = False
