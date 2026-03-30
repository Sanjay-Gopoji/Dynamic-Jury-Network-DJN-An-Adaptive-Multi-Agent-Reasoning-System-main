# djn_engine/json_enforce.py
from __future__ import annotations

import json
import re
from typing import Type, TypeVar, Optional

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)

def _extract_json(text: str) -> str:
    text = (text or "").strip()
    m = _JSON_BLOCK.search(text)
    return m.group(0).strip() if m else text

def parse_strict(model: Type[T], raw: str) -> T:
    raw = _extract_json(raw)
    data = json.loads(raw)  
    return model.model_validate(data)

def repair_json_minimal(raw: str) -> Optional[str]:

    if not raw:
        return None
    s = raw.strip()
    s = s.replace("```json", "").replace("```", "").strip()
    s = _extract_json(s)
    s = re.sub(r",(\s*[}\]])", r"\1", s)
    return s

def parse_with_repair(model: Type[T], raw: str) -> T:
    try:
        return parse_strict(model, raw)
    except Exception:
        fixed = repair_json_minimal(raw)
        if not fixed:
            raise
        return parse_strict(model, fixed)
