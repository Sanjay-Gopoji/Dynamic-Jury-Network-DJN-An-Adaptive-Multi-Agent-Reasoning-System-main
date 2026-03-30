from __future__ import annotations
from typing import Any, Dict, List, Optional
from django.db import transaction
from django.utils import timezone

from .models import DJNRun, DJNRound, JurorResponse, LLMPool


def _get_model_row(model_id: str):
    try:
        return LLMPool.objects.get(model_id=model_id)
    except LLMPool.DoesNotExist:
        return None


@transaction.atomic
def upsert_run(payload: Dict[str, Any]) -> DJNRun:

    sid = payload["session_id"]
    run, _ = DJNRun.objects.get_or_create(session_id=sid, defaults={
        "created_at": timezone.now(),
        "q_raw": payload.get("q_raw", payload.get("q_final", "")),
    })

    run.category = payload.get("category", run.category)
    run.q_final = payload.get("q_final", run.q_final)
    run.assumptions_json = payload.get("assumptions", run.assumptions_json) or []
    run.jury_roster_json = payload.get("jury_roster", run.jury_roster_json) or []
    run.role_map_json = payload.get("role_map", run.role_map_json) or {}
    run.missing_fields_json = payload.get("missing_fields", run.missing_fields_json) or []
    run.category_confidence = payload.get("category_confidence", run.category_confidence) or 0.0

    final = payload.get("final") or {}
    run.final_label = final.get("final_label", run.final_label)
    run.final_answer = final.get("final_answer", run.final_answer)
    run.final_confidence = final.get("confidence", run.final_confidence)
    run.stop_reason = final.get("stop_reason", run.stop_reason)

    run.duration_ms = payload.get("duration_ms", run.duration_ms)

    run.save()
    return run


@transaction.atomic
def write_round(run: DJNRun, round_payload: Dict[str, Any]) -> DJNRound:

    idx = int(round_payload["round"])
    r, _ = DJNRound.objects.get_or_create(run=run, round_index=idx)

    r.agreement = round_payload.get("agreement")
    r.majority_label = round_payload.get("majority_label", "") or ""
    r.improvement = round_payload.get("improvement")
    r.stagnation_flag = bool(round_payload.get("stagnation_flag", False))
    r.verdict_distribution_json = round_payload.get("verdict_distribution", {}) or {}
    r.tldr_similarity_score = round_payload.get("tldr_similarity_score")
    r.effective_agreement_score = round_payload.get("effective_agreement_score")
    r.handoff_tldr_json = round_payload.get("handoff_tldr", {}) or {}
    r.latency_ms = round_payload.get("latency_ms")
    r.save()

    for o in (round_payload.get("outputs") or []):
        juror_id = o.get("juror_id", "")
        jr, _ = JurorResponse.objects.get_or_create(round=r, juror_id=juror_id)

        jr.role = o.get("role", jr.role) or ""
        mid = o.get("model_id", "") or ""
        jr.model = _get_model_row(mid)
        jr.model_id_snapshot = mid

        jr.verdict_label = o.get("verdict_label", "") or ""
        jr.tldr = o.get("tldr", "") or ""
        jr.reasoning_json = o.get("reasoning", []) or []

        jr.status = o.get("status", "OK") or "OK"
        jr.schema_valid = bool(o.get("schema_valid", True))
        jr.error_msg = o.get("error_msg", "") or ""

        jr.latency_ms = o.get("latency_ms")
        jr.token_in = o.get("token_in")
        jr.token_out = o.get("token_out")
        jr.cost_estimate = o.get("cost_estimate")
        jr.save()

    return r
