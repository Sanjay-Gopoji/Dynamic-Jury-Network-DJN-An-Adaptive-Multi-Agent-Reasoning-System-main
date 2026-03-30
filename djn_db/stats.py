from __future__ import annotations
from typing import Dict, Any, List
from django.db import transaction
from django.db.models import Avg

from .models import DJNRun, DJNRound, JurorResponse, ModelRollingStat, LLMPool


def _safe_rate(num: float, den: float) -> float:
    return float(num) / float(den) if den else 0.0


@transaction.atomic
def update_stats_for_run(run_id: str) -> None:

    try:
        run = DJNRun.objects.get(session_id=run_id)
    except DJNRun.DoesNotExist:
        return

    rounds = DJNRound.objects.filter(run=run).prefetch_related("juror_responses")
    if not rounds.exists():
        return

    category = run.category or "general"
    fb = run.user_feedback  # None | 1 | -1

    responses = JurorResponse.objects.filter(round__run=run)

    by_mid: Dict[str, List[JurorResponse]] = {}
    for jr in responses:
        mid = (jr.model_id_snapshot or "").strip()
        if not mid:
            continue
        by_mid.setdefault(mid, []).append(jr)

    for mid, items in by_mid.items():
        model_row = None
        try:
            model_row = LLMPool.objects.get(model_id=mid)
        except LLMPool.DoesNotExist:
            continue

        stat, _ = ModelRollingStat.objects.get_or_create(model=model_row, category=category)

        appearances = len(items)
        stat.appearances_total += appearances

        schema_ok = sum(1 for x in items if x.schema_valid)
        stat.schema_valid_rate = _safe_rate(schema_ok, appearances)

        lat_vals = [x.latency_ms for x in items if x.latency_ms is not None]
        stat.avg_latency_ms = (sum(lat_vals) / len(lat_vals)) if lat_vals else stat.avg_latency_ms

        wins = 0
        disagrees = 0
        for x in items:
            maj = x.round.majority_label
            if not maj or not x.verdict_label:
                continue
            if x.verdict_label == maj:
                wins += 1
            else:
                disagrees += 1

        judged = wins + disagrees
        stat.win_rate_in_majority = _safe_rate(wins, judged)
        stat.disagreement_rate = _safe_rate(disagrees, judged)

        if fb in (1, -1):
            stat.user_accepts_total += 1 if fb == 1 else 0
            stat.user_acceptance_rate = _safe_rate(stat.user_accepts_total, stat.appearances_total > 0 and stat.user_accepts_total + (stat.appearances_total - stat.user_accepts_total) or 1)

        stat.save()
