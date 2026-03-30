import random
from typing import Dict, List, Tuple

from django.db.models import Q

from djn_db.models import LLMPool, ModelRollingStat

JURY_SIZE = 4

ROLE_MAP: Dict[str, str] = {
    "J1": "PROPOSER",
    "J2": "CRITIC",
    "J3": "REFINER",
    "J4": "RISK",
}


def _score_model(model_row: LLMPool, category: str) -> float:
    """
    MVP scoring:
    - prefer better user_acceptance_rate if stats exist
    - tiny noise to avoid always picking same set
    """
    stat = (
        ModelRollingStat.objects.filter(model=model_row, category=category).first()
        or ModelRollingStat.objects.filter(model=model_row, category="general").first()
    )
    acc = float(getattr(stat, "user_acceptance_rate", 0.0) or 0.0)
    lat = float(getattr(stat, "avg_latency_ms", 0.0) or 0.0)

    latency_bonus = 0.0 if lat <= 0 else max(0.0, 2000.0 - lat) / 2000.0  
    return (acc * 2.0) + (latency_bonus * 0.5) + random.random() * 0.05


def select_jury_roster(category: str, k: int = JURY_SIZE) -> Tuple[List[dict], Dict[str, str]]:
    """
    Returns:
      roster: [{"juror_id":"J1","model_id":"...","provider":"...","name":"..."} ...]
      role_map: {"J1":"PROPOSER",...}
    """
    category = (category or "general").strip().lower() or "general"

    enabled = list(LLMPool.objects.filter(enabled=True))

    tagged = [m for m in enabled if category in (m.tags_json or [])]

    if len(tagged) < k:
        general_tagged = [m for m in enabled if "general" in (m.tags_json or []) and m not in tagged]
        tagged.extend(general_tagged)

    if len(tagged) < k:
        rest = [m for m in enabled if m not in tagged]
        tagged.extend(rest)

    scored = sorted(tagged, key=lambda m: _score_model(m, category), reverse=True)
    picked = scored[:k]

    juror_ids = [f"J{i}" for i in range(1, k + 1)]
    roster = []
    for jid, m in zip(juror_ids, picked):
        roster.append({
            "juror_id": jid,
            "model_id": m.model_id,
            "provider": m.provider,
            "name": m.name,
        })

    return roster, dict(ROLE_MAP)