import os
import time
from dataclasses import dataclass, asdict
from typing import Dict, Any, List, Optional, Tuple
import uuid

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableParallel, RunnableLambda

from .pool import JUDGE, JURORS, LLMConfig  
from .llms import build_llm

try:
    from djn_db.selector import select_jury_roster
except Exception:
    select_jury_roster = None

from .json_enforce import parse_with_repair
from .schemas import (
    JurorOut,
    JudgeOut,
    ModeratorOut,
    CallStatus,
    JurorResult,
    RoundSummary,  
)

try:
    from .schemas import AssumptionsOut
except Exception:
    try:
        from pydantic import BaseModel
        class AssumptionsOut(BaseModel):
            q_final: str
            assumptions: List[str]
    except Exception:
        AssumptionsOut = None



ASSUMPTIONS_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You are the DJN Assumption Builder.\n"
     "Goal: convert the user's raw query + any clarifier answers into a clean, executable query.\n"
     "You MUST output ONLY valid JSON. No markdown/backticks. No extra keys.\n\n"
     "Rules:\n"
     "- If some details are missing, you may add reasonable assumptions, but keep them explicit.\n"
     "- Assumptions must be short, concrete, and testable.\n"
     "- q_final should include the refined query AND a short 'Assumptions:' list.\n\n"
     "Schema:\n"
     "{{\n"
     '  "q_final": "STRING",\n'
     '  "assumptions": ["STRING","STRING"]\n'
     "}}"
    ),
    ("user",
     "Raw query:\n{q_raw}\n\n"
     "Clarifier answers (may be empty):\n{clarifier_answers}\n\n"
     "Return JSON now.")
])

JUROR_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You are a DJN juror.\n"
     "You MUST output ONLY valid JSON.\n"
     "No markdown. No backticks. No commentary. No extra keys.\n"
     "Return EXACTLY this schema:\n"
     "{{\n"
     '  "verdict_label": "STRING",\n'
     '  "tldr": "STRING (<= 90 words)",\n'
     '  "reasoning": ["STRING","STRING","STRING"]\n'
     "}}\n"),
    ("user",
     "User query:\n{query}\n\n"
     "Round context (if any):\n{round_context}\n\n"
     "Now output ONLY the JSON object.")
])

JUDGE_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You are the DJN Moderator/Judge.\n"
     "You MUST output ONLY valid JSON. No markdown/backticks.\n"
     "No extra keys. Follow schema exactly.\n\n"

     "Quality rules:\n"
     "- final_recommendation MUST be a complete answer (at least 2-6 sentences).\n"
     "- why MUST have 2-6 bullet-like strings, each concrete.\n"
     "- confidence MUST be one of HIGH, MEDIUM, LOW.\n"
     "- Mention why consensus is strong/weak using jurors' agreement.\n\n"

     "Schema:\n"
     "{{\n"
     '  "final_recommendation": "STRING (2-6 sentences)",\n'
     '  "why": ["STRING","STRING"],\n'
     '  "confidence": "HIGH|MEDIUM|LOW",\n'
     '  "common_ground": ["STRING"],\n'
     '  "main_disagreement": ["STRING"],\n'
     '  "conditional_guidance": ["STRING"]\n'
     "}}\n"
    ),
    ("user",
     "User query:\n{query}\n\n"
     "Validated juror outputs (raw JSON text):\n{juror_text}\n\n"
     "Now output ONLY the JSON object.")
])

MODERATOR_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You are the DJN Moderator.\n"
     "Task: decide if the user's query is sufficiently specified to run the jury.\n"
     "If insufficient, ask 1-2 clarifying questions.\n"
     "You MUST output ONLY valid JSON. No markdown. No extra keys.\n\n"
     "Schema:\n"
     "{{\n"
     '  "category": "coding|career|planning|factual|opinion|general",\n'
     '  "category_confidence": 0.0,\n'
     '  "missing_critical": ["STRING"],\n'
     '  "clarifier_questions": ["STRING"]\n'
     "}}"
    ),
    ("user",
     "User query:\n{query}\n\n"
     "Return JSON now.")
])

ROUND_SUMMARY_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You summarize juror outputs to drive the NEXT round.\n"
     "Output ONLY valid JSON. No markdown. No extra keys.\n"
     "Schema:\n"
     "{{\n"
     '  "common_ground": ["STRING"],\n'
     '  "key_disagreements": ["STRING"],\n'
     '  "open_questions": ["STRING"],\n'
     '  "current_best_label": "YES|NO|CONDITIONAL|UNKNOWN",\n'
     '  "why_this_label": "STRING"\n'
     "}}"
    ),
    ("user",
     "User query:\n{query}\n\n"
     "Validated juror outputs (raw JSON):\n{juror_text}\n\n"
     "Return JSON now.")
])


def _msg_text(x) -> str:
    """AIMessage -> content; otherwise stringify."""
    return getattr(x, "content", str(x))


def _safe_parse_juror(juror_id: str, model_id: str, msg) -> JurorResult:
    raw = _msg_text(msg)
    try:
        obj = parse_with_repair(JurorOut, raw)
        if obj.reasoning and len(obj.reasoning) > 6:
            obj.reasoning = obj.reasoning[:6]

        return JurorResult(
            juror_id=juror_id,
            model_id=model_id,
            output=obj,
            status=CallStatus(ok=True, raw=raw),
        )
    except Exception as e:
        return JurorResult(
            juror_id=juror_id,
            model_id=model_id,
            output=None,
            status=CallStatus(ok=False, err=f"{type(e).__name__}: {e}", raw=raw),
        )


def _safe_parse_judge(msg) -> Dict[str, Any]:
    raw = _msg_text(msg)
    try:
        obj = parse_with_repair(JudgeOut, raw)
        return {"ok": True, "output": obj, "raw": raw}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "raw": raw}


def _safe_parse_round_summary(msg) -> Dict[str, Any]:
    raw = _msg_text(msg)
    try:
        obj = parse_with_repair(RoundSummary, raw)
        return {"ok": True, "output": obj, "raw": raw}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "raw": raw}


def _agreement_from_ok(juror_results: List[JurorResult]) -> Dict[str, Any]:
    ok = [x for x in juror_results if x.status.ok and x.output is not None]
    n = len(ok)
    if n == 0:
        return {"n_ok": 0, "agreement": 0.0, "majority_label": "UNKNOWN"}

    counts: Dict[str, int] = {}
    for x in ok:
        lbl = x.output.verdict_label
        counts[lbl] = counts.get(lbl, 0) + 1

    majority = max(counts, key=counts.get)
    agreement = counts[majority] / n
    return {"n_ok": n, "agreement": agreement, "majority_label": majority}


def moderator_check(query: str) -> Dict[str, Any]:
    """
    Uses Gemini (JUDGE) as Moderator in v1 to decide if query is sufficient.
    Returns:
      { ok: bool, output: ModeratorOut|None, raw: str, error?: str }
    """
    query = (query or "").strip()
    if not query:
        return {"ok": True, "output": None, "raw": "", "error": "Empty query."}

    llm = build_llm(JUDGE)
    chain = MODERATOR_PROMPT | llm
    msg = chain.invoke({"query": query})
    raw = _msg_text(msg)

    try:
        out = parse_with_repair(ModeratorOut, raw)
        return {"ok": True, "output": out, "raw": raw}
    except Exception as e:
        return {"ok": False, "output": None, "raw": raw, "error": f"{type(e).__name__}: {e}"}


def build_assumptions(q_raw: str, clarifier_answers: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    S3: ASSUMPTIONS
    Input: q_raw + clarifier answers
    Output: { ok, output(q_final, assumptions), raw, error? }
    """
    q_raw = (q_raw or "").strip()
    clarifier_answers = clarifier_answers or []

    if not q_raw:
        return {"ok": False, "output": None, "raw": "", "error": "Empty q_raw."}

    if AssumptionsOut is None:
        q_final = q_raw
        if clarifier_answers:
            q_final += "\n\nClarifications:\n- " + "\n- ".join([a.strip() for a in clarifier_answers if a and a.strip()])
        return {"ok": True, "output": {"q_final": q_final, "assumptions": []}, "raw": q_final}

    llm = build_llm(JUDGE)
    chain = ASSUMPTIONS_PROMPT | llm
    msg = chain.invoke({
        "q_raw": q_raw,
        "clarifier_answers": "\n- " + "\n- ".join([a.strip() for a in clarifier_answers if a and a.strip()]) if clarifier_answers else "(none)"
    })
    raw = _msg_text(msg)

    try:
        out = parse_with_repair(AssumptionsOut, raw)
        return {"ok": True, "output": out, "raw": raw}
    except Exception as e:
        return {"ok": False, "output": None, "raw": raw, "error": f"{type(e).__name__}: {e}"}


@dataclass
class RoundState:
    round: int
    n_ok: int
    verdict_distribution: Dict[str, int]
    majority_label: str
    agreement_score: float
    improvement_score: Optional[float]
    stagnation_flag: bool
    stop_reason: Optional[str]
    best_available_used: bool
    latency_ms_per_round: int
    model_latency_ms: Dict[str, int]
    schema_valid_rate: float


def _verdict_distribution(juror_results: List[JurorResult]) -> Tuple[Dict[str, int], str, float, int]:
    ok = [x for x in juror_results if x.status.ok and x.output is not None]
    n = len(ok)
    if n == 0:
        return {}, "UNKNOWN", 0.0, 0

    counts: Dict[str, int] = {}
    for x in ok:
        lbl = x.output.verdict_label
        counts[lbl] = counts.get(lbl, 0) + 1

    majority = max(counts, key=counts.get)
    agreement = counts[majority] / n
    return counts, majority, agreement, n


def _compute_schema_valid_rate(juror_results: List[JurorResult], total: int) -> float:
    if total <= 0:
        return 0.0
    ok = sum(1 for x in juror_results if x.status.ok and x.output is not None)
    return ok / total


def _cap_confidence(
    judge_dump: Optional[Dict[str, Any]],
    agreement: float,
    threshold: float,
    stop_reason: str
) -> None:
    """
    Ground confidence in BOTH consensus and epistemic uncertainty.
    """

    if not judge_dump:
        return

    conf = (judge_dump.get("confidence") or "MEDIUM").strip().upper()
    text = (judge_dump.get("final_recommendation") or "").lower()

    if stop_reason != "THRESHOLD_MET" and conf == "HIGH":
        conf = "MEDIUM"

    if agreement < 0.50:
        conf = "LOW"
    elif agreement < threshold and conf == "HIGH":
        conf = "MEDIUM"

    speculative_cues = [
        "speculative", "uncertain", "unknown", "cannot be predicted",
        "no consensus", "highly debated", "not guaranteed"
    ]
    if any(cue in text for cue in speculative_cues):
        conf = "MEDIUM" if agreement >= threshold else "LOW"

    judge_dump["confidence"] = conf



def _format_final_display(judge_dump: Optional[Dict[str, Any]], judge_msg, query: str) -> str:
    if judge_dump is None:
        return _msg_text(judge_msg)

    if "[MODERATOR NOTE: The user skipped clarifications." in query:
        judge_dump["confidence"] = "LOW"

    conf = (judge_dump.get("confidence") or "MEDIUM").strip().upper()
    conf_title = conf[:1] + conf[1:].lower()

    why = judge_dump.get("why") or []
    why_lines = "\n".join([f"- {w}" for w in why]) if why else "- (No reason provided.)"

    return (
        "Final Recommendation:\n"
        f"{(judge_dump.get('final_recommendation') or '').strip()}\n\n"
        f"Confidence Level: {conf_title}\n\n"
        "Reason:\n"
        f"{why_lines}"
    )


def _build_round_context(summary: RoundSummary) -> str:
    cg = summary.common_ground or []
    kd = summary.key_disagreements or []
    oq = summary.open_questions or []

    return (
        "Common ground:\n- " + ("\n- ".join(cg) if cg else "(none)") + "\n\n"
        "Key disagreements:\n- " + ("\n- ".join(kd) if kd else "(none)") + "\n\n"
        "Open questions to resolve next:\n- " + ("\n- ".join(oq) if oq else "(none)") + "\n\n"
        f"Current best label: {getattr(summary, 'current_best_label', 'UNKNOWN')}\n"
        f"Why: {getattr(summary, 'why_this_label', '').strip()}\n"
    )


def run_djn_once(query: str, category: str = "general") -> Dict[str, Any]:
    query = (query or "").strip()
    if not query:
        return {"ok": False, "error": "Empty query."}

    run_id = str(uuid.uuid4())
    max_rounds = int(os.getenv("DJN_MAX_ROUNDS", "3"))
    threshold = float(os.getenv("DJN_THRESHOLD", "0.75"))

    min_improve = float(os.getenv("DJN_MIN_IMPROVEMENT", "0.05"))
    stagnation_rounds = int(os.getenv("DJN_STAGNATION_ROUNDS", "1"))
    min_ok = int(os.getenv("DJN_MIN_OK_JURORS", "2"))

    jury_roster = []
    role_map = {"J1": "PROPOSER", "J2": "CRITIC", "J3": "REFINER", "J4": "RISK"}

    selected_cfgs = []

    if select_jury_roster:
        try:
            jury_roster, role_map = select_jury_roster(category, k=4)
            for item in jury_roster:
                selected_cfgs.append(
                    LLMConfig(
                        name=item["juror_id"],
                        provider=(item.get("provider", "") or "ollama_cloud").strip().lower(),
                        model=item["model_id"],
                        temperature=0.35,
                    )
                )
        except Exception:
            selected_cfgs = []

    if not selected_cfgs:
        juror_ids = ["J1", "J2", "J3", "J4"]
        selected_cfgs = []
        for jid, cfg in zip(juror_ids, JURORS[:4]):
            selected_cfgs.append(
                LLMConfig(
                    name=jid,
                    provider=cfg.provider,
                    model=cfg.model,
                    temperature=getattr(cfg, "temperature", 0.35),
                    base_url=getattr(cfg, "base_url", None),
                )
            )
        jury_roster = [{"juror_id": c.name, "model_id": c.model, "provider": c.provider, "name": c.name} for c in selected_cfgs]

    juror_map = {}
    for cfg in selected_cfgs:
        juror_id = cfg.name
        model_id = cfg.model

        llm = build_llm(cfg)
        chain = (
            JUROR_PROMPT
            | llm
            | RunnableLambda(lambda msg, jid=juror_id, mid=model_id: _safe_parse_juror(jid, mid, msg))
        )
        juror_map[juror_id] = chain

    parallel = RunnableParallel(juror_map)


    judge_llm = build_llm(JUDGE)
    judge_chain = JUDGE_PROMPT | judge_llm
    summary_chain = ROUND_SUMMARY_PROMPT | judge_llm

    rounds_log: List[Dict[str, Any]] = []
    prev_agreement: Optional[float] = None
    stagnation_hits = 0

    last_juror_results: List[JurorResult] = []
    last_judge_msg = None
    last_judge_dump: Optional[Dict[str, Any]] = None
    last_judge_parsed: Optional[Dict[str, Any]] = None

    stop_reason = "MAX_ROUNDS"
    best_available_used = False

    round_context = ""

    for r in range(1, max_rounds + 1):
        t0 = time.perf_counter()
        model_latency_ms: Dict[str, int] = {}

        juror_res: Dict[str, JurorResult] = parallel.invoke({
            "query": query,
            "round_context": round_context
        })
        t1 = time.perf_counter()

        last_juror_results = list(juror_res.values())
        round_latency_ms = int((t1 - t0) * 1000)

        for x in last_juror_results:
            model_latency_ms[x.juror_id] = round_latency_ms

        verdict_dist, majority_label, agreement, n_ok = _verdict_distribution(last_juror_results)
        schema_valid_rate = _compute_schema_valid_rate(last_juror_results, total=len(selected_cfgs))


        improvement = None
        stagnation_flag = False
        if prev_agreement is not None:
            improvement = agreement - prev_agreement
            stagnation_flag = (improvement < min_improve)
            stagnation_hits = (stagnation_hits + 1) if stagnation_flag else 0

        ok_jurors = [x for x in last_juror_results if x.status.ok and x.status.raw]
        juror_text = "\n\n".join([f"[{x.juror_id}]\n{x.status.raw}" for x in ok_jurors])

        jt0 = time.perf_counter()
        last_judge_msg = judge_chain.invoke({"query": query, "juror_text": juror_text})
        jt1 = time.perf_counter()
        judge_latency_ms = int((jt1 - jt0) * 1000)

        judge_parsed = _safe_parse_judge(last_judge_msg)
        last_judge_parsed = judge_parsed
        last_judge_dump = judge_parsed["output"].model_dump() if judge_parsed.get("ok") else None

        if n_ok >= min_ok and agreement >= threshold:
            stop_reason = "THRESHOLD_MET"
            best_available_used = False
        elif stagnation_hits >= stagnation_rounds and r >= 2:
            stop_reason = "STAGNATION"
            best_available_used = True
        else:
            stop_reason = "MAX_ROUNDS"
            best_available_used = False

        if last_judge_dump is not None:
            _cap_confidence(last_judge_dump, agreement, threshold, stop_reason)

        round_state = RoundState(
            round=r,
            n_ok=n_ok,
            verdict_distribution=verdict_dist,
            majority_label=majority_label,
            agreement_score=agreement,
            improvement_score=improvement,
            stagnation_flag=stagnation_flag,
            stop_reason=(stop_reason if stop_reason in ("THRESHOLD_MET", "STAGNATION") else None),
            best_available_used=(best_available_used if stop_reason != "THRESHOLD_MET" else False),
            latency_ms_per_round=round_latency_ms,
            model_latency_ms=model_latency_ms,
            schema_valid_rate=schema_valid_rate,
        )

        rs = asdict(round_state)
        rs["judge_latency_ms"] = judge_latency_ms
        rs["consensus_threshold"] = threshold

        rs["outputs"] = [
            {
                "juror_id": x.juror_id,
                "model_id": x.model_id,
                "role": role_map.get(x.juror_id, ""),
                "verdict_label": (x.output.verdict_label if (x.status.ok and x.output) else ""),
                "tldr": (x.output.tldr if (x.status.ok and x.output) else ""),
                "reasoning": (x.output.reasoning if (x.status.ok and x.output) else []),
                "status": ("OK" if x.status.ok else "FAILED"),
                "schema_valid": bool(x.status.ok and x.output is not None),
                "error_msg": (x.status.err or ""),
                "latency_ms": model_latency_ms.get(x.juror_id),
                "token_in": None,
                "token_out": None,
                "cost_estimate": None,
            }
            for x in last_juror_results
        ]

        rounds_log.append(rs)


        prev_agreement = agreement

        if r < max_rounds and stop_reason not in ("THRESHOLD_MET", "STAGNATION"):
            smsg = summary_chain.invoke({"query": query, "juror_text": juror_text})
            sparsed = _safe_parse_round_summary(smsg)
            if sparsed.get("ok"):
                round_context = _build_round_context(sparsed["output"])
            else:
                round_context = (
                    f"Current majority label: {majority_label}\n"
                    f"Agreement: {agreement:.2f}\n"
                    "Next round goal: resolve disagreements and give the best supported label.\n"
                )
        elif r < max_rounds and stop_reason in ("STAGNATION",):
            pass

        if stop_reason in ("THRESHOLD_MET", "STAGNATION"):
            break

    if stop_reason not in ("THRESHOLD_MET", "STAGNATION"):
        stop_reason = "MAX_ROUNDS"
        best_available_used = True

    agr = _agreement_from_ok(last_juror_results)

    final_display = _format_final_display(last_judge_dump, last_judge_msg, query)

    final_text = (
        (last_judge_dump.get("final_recommendation", "") if last_judge_dump else "")
        or (_msg_text(last_judge_msg) if last_judge_msg is not None else "")
    )
    print("DJN stop:", stop_reason, "rounds:", len(rounds_log), "last_agreement:", rounds_log[-1]["agreement_score"] if rounds_log else None)

    return {
        "ok": True,
        "q_raw": query,
        "q_final": query,
        "query": query,
        "run_id": run_id,
        "category": category,
        "jury_roster": jury_roster,
        "role_map": role_map,

        "jurors": [
            {
                "juror_id": x.juror_id,
                "model_id": x.model_id,
                "ok": x.status.ok,
                "err": x.status.err,
                "raw": x.status.raw,
                "parsed": (x.output.model_dump() if x.output else None),
            }
            for x in last_juror_results
        ],

        "judge": (
            last_judge_dump
            if last_judge_dump is not None
            else {"ok": False, "error": (last_judge_parsed or {}).get("error"), "raw": (last_judge_parsed or {}).get("raw")}
        ),

        "final": final_text,
        "final_display": final_display,

        "metrics": agr,
        "meta": {
            "max_rounds": max_rounds,
            "threshold": threshold,
            "min_ok_jurors": min_ok,
            "min_improvement": min_improve,
            "stagnation_rounds": stagnation_rounds,
        },

        "rounds": rounds_log,
        "run_stop": {
            "stop_reason": stop_reason,
            "best_available_used": best_available_used,
            "final_confidence_level": (last_judge_dump.get("confidence") if last_judge_dump else None),
        },
        "run_metrics": {
            "schema_valid_rate_last_round": (rounds_log[-1].get("schema_valid_rate") if rounds_log else 0.0),
            "agreement_last_round": (rounds_log[-1].get("agreement_score") if rounds_log else 0.0),
            "n_ok_last_round": (rounds_log[-1].get("n_ok") if rounds_log else 0),
        }
    }
