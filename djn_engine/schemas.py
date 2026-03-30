# djn_engine/schemas.py
from __future__ import annotations

from typing import List, Literal, Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator, ConfigDict

Category = Literal["coding", "career", "planning", "factual", "opinion", "general"]
Role = Literal["PROPOSER", "CRITIC", "REFINER", "RISK"]
Confidence = Literal["HIGH", "MEDIUM", "LOW"]

def _norm_label(s: str) -> str:
    s = (s or "").strip().upper().replace(" ", "_")
    s = "".join(ch for ch in s if ch.isalnum() or ch == "_")[:64] or "UNKNOWN"

    POS = {"YES", "APPROVE", "RECOMMEND", "RECOMMENDED", "GO", "GO_AHEAD", "DO_IT", "AGREE", "SUPPORT"}
    NEG = {"NO", "REJECT", "AVOID", "DISAGREE", "OPPOSE"}
    COND = {"CONDITIONAL", "DEPENDS", "MAYBE", "PARTIAL", "MIXED", "QUALIFIED", "YES_BUT", "CONDITIONAL_YES"}
    UNK = {"UNKNOWN", "UNCLEAR", "NOT_SURE", "INSUFFICIENT_INFO"}

    if s in POS or s.startswith("YES"):
        return "YES"
    if s in NEG or s.startswith("NO"):
        return "NO"
    if s in COND or "CONDITIONAL" in s or "DEPENDS" in s or "MAYBE" in s:
        return "CONDITIONAL"
    if s in UNK:
        return "UNKNOWN"
    return s  

class ModeratorOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: Category
    category_confidence: float = Field(ge=0.0, le=1.0)
    missing_critical: List[str] = Field(default_factory=list)
    clarifier_questions: List[str] = Field(default_factory=list, max_length=3)
    
class AssumptionsOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    q_final: str = Field(min_length=1)
    assumptions: List[str] = Field(default_factory=list)

class JurorOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict_label: str
    tldr: str
    reasoning: List[str] = Field(min_length=3, max_length=20)

    @field_validator("verdict_label")
    @classmethod
    def verdict_label_norm(cls, v: str) -> str:
        return _norm_label(v)

    @field_validator("tldr")
    @classmethod
    def tldr_cap(cls, v: str) -> str:
        v = (v or "").strip()
        words = v.split()
        return " ".join(words[:90])

class RoundSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    common_ground: List[str] = Field(default_factory=list)
    key_disagreements: List[str] = Field(default_factory=list)
    open_questions: List[str] = Field(default_factory=list)
    current_best_label: str
    why_this_label: str

    @field_validator("current_best_label")
    @classmethod
    def best_label_norm(cls, v: str) -> str:
        return _norm_label(v)


class JudgeOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    final_recommendation: str = Field(min_length=40, max_length=1200)
    why: list[str] = Field(min_length=2, max_length=6)
    confidence: str  
    common_ground: list[str] = Field(default_factory=list, max_length=8)
    main_disagreement: list[str] = Field(default_factory=list, max_length=6)
    conditional_guidance: list[str] = Field(default_factory=list, max_length=8)


class CallStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool
    err: Optional[str] = None
    raw: Optional[str] = None

class JurorResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    juror_id: str
    model_id: str
    output: Optional[JurorOut] = None
    status: CallStatus

class RoundResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    round: int
    outputs: List[JurorResult]
    agreement: float
    majority_label: str
    improvement: Optional[float] = None
