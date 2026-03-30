from django.shortcuts import render, redirect
from django.views.decorators.http import require_http_methods, require_POST

from djn_engine.run import run_djn_once, moderator_check, build_assumptions
from djn_engine.logger import log_run, read_last_runs

from djn_db.models import DJNRun
from djn_db.stats import update_stats_for_run

import os
import re
from django.conf import settings
from django.http import HttpResponseBadRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

try:
    from djn_db.db_writer import upsert_run, write_round
except Exception:
    upsert_run = None
    write_round = None


CHAT_KEY = "jury_chat"
STATE_KEY = "jury_state"  
GDOCS_SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive.file",
]

GDOCS_CREDS_KEY = "gdocs_creds"
GDOCS_PENDING_TEXT_KEY = "gdocs_pending_text"
GDOCS_PENDING_TITLE_KEY = "gdocs_pending_title"
GDOCS_STATE_KEY = "gdocs_oauth_state"
GDOCS_LAST_URL_KEY = "gdocs_last_url"
GDOCS_PENDING_QUERY_KEY = "gdocs_pending_query"

PENDING_QUERY_KEY = "djn_pending_query"
CLARIFY_QS_KEY = "djn_clarify_qs"
CLARIFY_A_KEY = "djn_clarify_ans"

FORCE_LOW_CONF_KEY = "djn_force_low_conf"

LAST_RUN_ID_KEY = "djn_last_run_id"
LAST_FINAL_IDX_KEY = "djn_last_final_idx"  


def _get_chat(request):
    return request.session.get(CHAT_KEY, [])


def _set_chat(request, chat):
    request.session[CHAT_KEY] = chat
    request.session.modified = True


def _push(request, role, text):
    chat = _get_chat(request)
    chat.append({"role": role, "text": text})
    _set_chat(request, chat)

def _gdocs_client_secrets_file():
    p = os.getenv("GOOGLE_CLIENT_SECRETS_FILE", "credentials.json")
    if os.path.isabs(p):
        return p
    return os.path.join(settings.BASE_DIR, p)


def _gdocs_redirect_uri(request):
    return os.getenv("GOOGLE_OAUTH_REDIRECT_URI", request.build_absolute_uri("/gdocs/callback/"))


def _get_gdocs_creds(request):
    data = request.session.get(GDOCS_CREDS_KEY)
    if not data:
        return None
    try:
        return Credentials.from_authorized_user_info(data, GDOCS_SCOPES)
    except Exception:
        return None


def _save_gdocs_creds(request, creds: Credentials):
    request.session[GDOCS_CREDS_KEY] = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": creds.scopes,
    }
    request.session.modified = True


def _build_docs_requests_from_text(text: str):
    """
    Converts simple markdown-ish output into Google Docs formatting:
    - # / ## / ### => headings
    - - / * => bullets
    - 1. / 2. => numbered list
    Everything else => normal paragraphs
    """
    text = (text or "").replace("\r\n", "\n").strip() + "\n"

    lines = text.split("\n")
    starts = []
    idx = 1
    for ln in lines:
        starts.append(idx)
        idx += len(ln) + 1

    requests = [
        {"insertText": {"location": {"index": 1}, "text": text}}
    ]

    def _set_heading(line_i, heading_named_style):
        s = starts[line_i]
        e = s + len(lines[line_i])
        if e <= s:
            return
        requests.append({
            "updateParagraphStyle": {
                "range": {"startIndex": s, "endIndex": e + 1},
                "paragraphStyle": {"namedStyleType": heading_named_style},
                "fields": "namedStyleType",
            }
        })

    bullet_blocks = []
    number_blocks = []

    def _is_bullet(ln): return ln.startswith("- ") or ln.startswith("* ")
    def _is_number(ln): return bool(re.match(r"^\d+\.\s+", ln))

    for i, ln in enumerate(lines):
        if ln.startswith("### "):
            _set_heading(i, "HEADING_3")
        elif ln.startswith("## "):
            _set_heading(i, "HEADING_2")
        elif ln.startswith("# "):
            _set_heading(i, "HEADING_1")

    i = 0
    while i < len(lines):
        ln = lines[i]

        if _is_bullet(ln):
            s = starts[i]
            j = i
            while j < len(lines) and _is_bullet(lines[j]):
                j += 1
            e = starts[j - 1] + len(lines[j - 1]) + 1
            bullet_blocks.append((s, e))
            i = j
            continue

        if _is_number(ln):
            s = starts[i]
            j = i
            while j < len(lines) and _is_number(lines[j]):
                j += 1
            e = starts[j - 1] + len(lines[j - 1]) + 1
            number_blocks.append((s, e))
            i = j
            continue

        i += 1

    for s, e in bullet_blocks:
        requests.append({
            "createParagraphBullets": {
                "range": {"startIndex": s, "endIndex": e},
                "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE",
            }
        })

    for s, e in number_blocks:
        requests.append({
            "createParagraphBullets": {
                "range": {"startIndex": s, "endIndex": e},
                "bulletPreset": "NUMBERED_DECIMAL_NESTED",
            }
        })

    requests.append({
        "replaceAllText": {
            "containsText": {"text": "### ", "matchCase": True},
            "replaceText": ""
        }
    })
    requests.append({
        "replaceAllText": {
            "containsText": {"text": "## ", "matchCase": True},
            "replaceText": ""
        }
    })
    requests.append({
        "replaceAllText": {
            "containsText": {"text": "# ", "matchCase": True},
            "replaceText": ""
        }
    })
    requests.append({
        "replaceAllText": {
            "containsText": {"text": "- ", "matchCase": True},
            "replaceText": ""
        }
    })
    requests.append({
        "replaceAllText": {
            "containsText": {"text": "* ", "matchCase": True},
            "replaceText": ""
        }
    })


    return requests


def _create_google_doc(request, title: str, query: str, content: str):
    creds = _get_gdocs_creds(request)
    if not creds:
        return None

    docs = build("docs", "v1", credentials=creds)

    doc = docs.documents().create(body={"title": title}).execute()
    doc_id = doc["documentId"]
    doc_text = f"# Query\n{(query or '').strip()}\n\n# Final Response\n{(content or '').strip()}\n"
    reqs = _build_docs_requests_from_text(doc_text)

    docs.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": reqs}
    ).execute()

    return f"https://docs.google.com/document/d/{doc_id}/edit"


def _basic_crosscheck_questions(user_text: str):
    """
    Cheap heuristic cross-checks. If it returns [], we fall back to Moderator LLM check.
    """
    t = (user_text or "").strip()
    if not t:
        return ["What’s your query? Please type it in one line."][:2]

    qs = []
    if len(t) < 12:
        qs.append("Can you add a bit more detail—what exactly do you want DJN to decide or produce?")
        qs.append("Any constraints (format, scope, assumptions) I should follow?")
        return qs[:2]

    vague_words = ["something", "anything", "help", "explain", "tell me", "about it", "details"]
    if any(w in t.lower() for w in vague_words) and len(t) < 40:
        qs.append("What’s the exact deliverable you want (answer, plan, code, comparison, etc.)?")
        qs.append("Any context (who it’s for, level, deadline) so the jury doesn’t guess?")
        return qs[:2]

    return []


def _build_final_query(request, base_q: str) -> str:
    """
    Build q_final = base_q + clarifications (if any).
    """
    base_q = (base_q or "").strip()
    answers = request.session.get(CLARIFY_A_KEY, []) or []
    answers = [a.strip() for a in answers if a and a.strip()]

    if not base_q:
        return ""

    if answers:
        return base_q + "\n\nClarifications:\n- " + "\n- ".join(answers)

    return base_q


def _classify_query(q_raw: str):
    """
    Returns (cat, cat_conf, missing_critical[]). Applies v1 rule: low confidence => general.
    """
    cat = "general"
    cat_conf = 0.0
    missing = []
    try:
        mod = moderator_check(q_raw)
        if mod.get("ok") and mod.get("output"):
            out = mod["output"]
            cat = (getattr(out, "category", None) or "general").strip().lower()
            cat_conf = float(getattr(out, "category_confidence", 0.0) or 0.0)
            missing = list(getattr(out, "missing_critical", []) or [])
    except Exception:
        pass

    if cat_conf < 0.55:
        cat = "general"

    return cat, cat_conf, missing


def _run_and_persist(request, q_raw: str, q_final: str, cat: str, cat_conf: float, missing, assumptions):
    """
    Runs DJN, pushes final answer, logs to JSONL, optionally mirrors to DB.
    Also sets LAST_RUN_ID_KEY + LAST_FINAL_IDX_KEY for 👍👎 UI.
    """
    res = run_djn_once(q_final, category=cat)

    if not res.get("ok"):
        _push(request, "assistant", f"DJN run failed: {res.get('error', 'unknown error')}")
        return res
    _push(request, "assistant", res.get("final_display", res.get("final", "")))
    if res.get("run_id"):
        request.session[LAST_RUN_ID_KEY] = res["run_id"]
    request.session[LAST_FINAL_IDX_KEY] = len(_get_chat(request))
    request.session.modified = True
    try:
        log_run({
            "q_raw": q_raw,
            "q_final": q_final,

            "query": q_final,

            "ok": res.get("ok"),
            "final_display": res.get("final_display"),
            "judge": res.get("judge"),
            "jurors": res.get("jurors"),
            "jury_roster": res.get("jury_roster", []),
            "role_map": res.get("role_map", {}),
            "metrics": res.get("metrics"),
            "meta": res.get("meta"),
            "rounds": res.get("rounds"),
            "run_stop": res.get("run_stop"),
            "run_metrics": res.get("run_metrics"),
        })


    except Exception:
        pass
    if upsert_run and write_round and res.get("ok"):
        try:
            db_payload = {
                "session_id": (res.get("run_id") or (request.session.session_key or "")),
                "q_raw": q_raw,
                "q_final": q_final,
                "category": cat,
                "category_confidence": cat_conf,
                "missing_fields": missing,
                "assumptions": assumptions,
                "jury_roster": res.get("jury_roster") or [],
                "role_map": res.get("role_map") or {},
                "rounds": [],
                "final": {
                    "final_label": "",
                    "final_answer": res.get("final", "") or "",
                    "confidence": (res.get("run_stop") or {}).get("final_confidence_level") or "",
                    "stop_reason": (res.get("run_stop") or {}).get("stop_reason") or "",
                },
                "duration_ms": None,
            }

            role_map = db_payload["role_map"] or {}

            for rr in (res.get("rounds") or []):
                outs = rr.get("outputs", []) or []
                for o in outs:
                    jid = o.get("juror_id", "")
                    if jid and not o.get("role"):
                        o["role"] = role_map.get(jid, "") or ""

                db_payload["rounds"].append({
                    "round": rr.get("round"),
                    "agreement": rr.get("agreement_score"),
                    "majority_label": rr.get("majority_label"),
                    "improvement": rr.get("improvement_score"),
                    "stagnation_flag": rr.get("stagnation_flag", False),
                    "verdict_distribution": rr.get("verdict_distribution", {}) or {},
                    "handoff_tldr": {},
                    "latency_ms": rr.get("latency_ms_per_round"),
                    "outputs": outs,
                    "tldr_similarity_score": rr.get("tldr_similarity_score"),
                    "effective_agreement_score": rr.get("effective_agreement_score"),
                })

            run_row = upsert_run(db_payload)
            for rnd in db_payload["rounds"]:
                write_round(run_row, rnd)

        except Exception as e:
            print("[DJN][DB] write skipped:", repr(e))

    return res


@require_http_methods(["GET", "POST"])
def jury_discussion(request):
    chat = _get_chat(request)
    state = request.session.get(STATE_KEY, "idle")

    if request.method == "GET" and not chat:
        _push(
            request,
            "assistant",
            "Welcome to DJN JuryDiscussion. Ask your query. If anything is unclear, I’ll ask 1–2 cross-check questions before running the jury rounds."
        )
        request.session[STATE_KEY] = "idle"
        request.session[PENDING_QUERY_KEY] = ""
        request.session[CLARIFY_QS_KEY] = []
        request.session[CLARIFY_A_KEY] = []
        request.session[FORCE_LOW_CONF_KEY] = False
        request.session[LAST_RUN_ID_KEY] = None
        request.session[LAST_FINAL_IDX_KEY] = None
        request.session.modified = True

    if request.method == "POST":
        msg = (request.POST.get("message") or "").strip()
        if not msg:
            return redirect("jury_discussion")

        _push(request, "user", msg)

        msg_l = msg.lower().strip()
        state = request.session.get(STATE_KEY, "idle")

        if msg_l not in ("skip",):
            request.session[LAST_RUN_ID_KEY] = None
            request.session[LAST_FINAL_IDX_KEY] = None
            request.session.modified = True

        if state == "need_clarify":
            base_q = (request.session.get(PENDING_QUERY_KEY) or "").strip()
            if not base_q:
                request.session[STATE_KEY] = "idle"
                request.session.modified = True
                _push(request, "assistant", "I lost the pending query. Please ask again.")
                return redirect("jury_discussion")

            if msg_l == "skip":
                request.session[FORCE_LOW_CONF_KEY] = True
                request.session[CLARIFY_A_KEY] = []
            else:
                ans = request.session.get(CLARIFY_A_KEY, []) or []
                ans.append(msg)
                request.session[CLARIFY_A_KEY] = ans

            q_raw = base_q
            clarifier_answers = request.session.get(CLARIFY_A_KEY, []) or []

            cat, cat_conf, missing = _classify_query(q_raw)

            assumptions = []
            q_final = q_raw
            try:
                ares = build_assumptions(q_raw, clarifier_answers)
                if ares.get("ok") and ares.get("output"):
                    out = ares["output"]
                    q_final = (getattr(out, "q_final", None) or q_raw).strip()
                    assumptions = list(getattr(out, "assumptions", []) or [])
                else:
                    q_final = _build_final_query(request, q_raw)
            except Exception:
                q_final = _build_final_query(request, q_raw)

            if bool(request.session.get(FORCE_LOW_CONF_KEY, False)):
                q_final = (
                    q_final
                    + "\n\n[MODERATOR NOTE: The user skipped clarifications. You MUST set confidence to LOW and briefly mention what key info is missing.]"
                )

            _run_and_persist(request, q_raw, q_final, cat, cat_conf, missing, assumptions)
            request.session[STATE_KEY] = "idle"
            request.session[PENDING_QUERY_KEY] = ""
            request.session[CLARIFY_QS_KEY] = []
            request.session[CLARIFY_A_KEY] = []
            request.session[FORCE_LOW_CONF_KEY] = False
            request.session.modified = True

            return redirect("jury_discussion")

        request.session[PENDING_QUERY_KEY] = msg
        request.session[CLARIFY_QS_KEY] = []
        request.session[CLARIFY_A_KEY] = []
        request.session[FORCE_LOW_CONF_KEY] = False
        request.session.modified = True

        qs = _basic_crosscheck_questions(msg)
        if not qs:
            try:
                mod = moderator_check(msg)
                if mod.get("ok") and mod.get("output") and getattr(mod["output"], "clarifier_questions", None):
                    qs = list(mod["output"].clarifier_questions)[:2]
            except Exception:
                pass

        if qs:
            request.session[STATE_KEY] = "need_clarify"
            request.session[CLARIFY_QS_KEY] = qs
            request.session[CLARIFY_A_KEY] = []
            request.session.modified = True

            text = "Before I run the jury, quick cross-check:\n- " + "\n- ".join(qs)
            _push(request, "assistant", text)
            return redirect("jury_discussion")

        q_raw = msg
        cat, cat_conf, missing = _classify_query(q_raw)

        assumptions = []
        q_final = q_raw
        try:
            ares = build_assumptions(q_raw, [])
            if ares.get("ok") and ares.get("output"):
                out = ares["output"]
                q_final = (getattr(out, "q_final", None) or q_raw).strip()
                assumptions = list(getattr(out, "assumptions", []) or [])
        except Exception:
            pass

        _run_and_persist(request, q_raw, q_final, cat, cat_conf, missing, assumptions)

        request.session[STATE_KEY] = "idle"
        request.session[PENDING_QUERY_KEY] = ""
        request.session[CLARIFY_QS_KEY] = []
        request.session[CLARIFY_A_KEY] = []
        request.session[FORCE_LOW_CONF_KEY] = False
        request.session.modified = True

        return redirect("jury_discussion")

    last_assistant_idx = None
    for i, m in enumerate(chat, start=1):
        if m.get("role") != "user":
            last_assistant_idx = i

    last_final_idx = request.session.get(LAST_FINAL_IDX_KEY)
    doc_url = request.session.pop(GDOCS_LAST_URL_KEY, None)

    run_id = request.session.get(LAST_RUN_ID_KEY)
    feedback_value = None
    if run_id:
        try:
            feedback_value = DJNRun.objects.values_list("user_feedback", flat=True).get(session_id=run_id)
        except DJNRun.DoesNotExist:
            pass

    return render(request, "webapp/jury_discussion.html", {
        "chat": chat,
        "state": state,
        "run_id": run_id,
        "last_assistant_idx": last_assistant_idx,
        "last_final_idx": last_final_idx,
        "feedback_value": feedback_value,
        "gdocs_last_url": doc_url,
    })


def history(request):
    runs = read_last_runs(limit=30)
    return render(request, "webapp/history.html", {"runs": runs})


@require_http_methods(["POST"])
def jury_clear(request):
    request.session.pop(CHAT_KEY, None)
    request.session.pop(STATE_KEY, None)
    request.session.pop(PENDING_QUERY_KEY, None)
    request.session.pop(CLARIFY_QS_KEY, None)
    request.session.pop(CLARIFY_A_KEY, None)
    request.session.pop(FORCE_LOW_CONF_KEY, None)
    request.session.pop(LAST_RUN_ID_KEY, None)
    request.session.pop(LAST_FINAL_IDX_KEY, None)
    request.session.modified = True
    return redirect("jury_discussion")


def home(request):
    return render(request, "webapp/home.html")


def about(request):
    return render(request, "webapp/about.html")


@require_POST
def jury_feedback(request):
    """
    Handles 👍 / 👎 feedback for a single DJN run.
    """
    run_id = request.POST.get("run_id")
    value = request.POST.get("value")

    if not run_id or value not in ("up", "down"):
        return redirect("jury_discussion")

    try:
        run = DJNRun.objects.get(session_id=run_id)
        run.user_feedback = 1 if value == "up" else -1
        run.save(update_fields=["user_feedback"])
    except DJNRun.DoesNotExist:
        pass

    try:
        update_stats_for_run(run_id)
    except Exception as e:
        print("[DJN][STATS] feedback update skipped:", repr(e))

    return redirect("jury_discussion")

@require_POST
def gdocs_share(request):
    """
    Share the selected FINAL assistant response to Google Docs.
    Writes BOTH raw query and final query (sent to jurors).
    """
    msg_idx = request.POST.get("msg_idx")
    try:
        msg_idx = int(msg_idx)
    except Exception:
        return HttpResponseBadRequest("Invalid msg_idx")

    chat = _get_chat(request)
    if not chat or msg_idx < 1 or msg_idx > len(chat):
        return HttpResponseBadRequest("Message not found")

    final_ans = (chat[msg_idx - 1].get("text") or "").strip()
    if not final_ans:
        return HttpResponseBadRequest("Empty message")

    run_id = request.session.get(LAST_RUN_ID_KEY)
    raw_q, final_q = "", ""

    if run_id:
        try:
            run = DJNRun.objects.get(session_id=run_id)
            raw_q = (run.q_raw or "").strip()
            final_q = (run.q_final or run.query or "").strip()
        except DJNRun.DoesNotExist:
            pass

    if not raw_q:
        for m in chat:
            if (m.get("role") or "").lower() == "user":
                raw_q = (m.get("text") or "").strip()
                break

    if not final_q:
        final_q = raw_q

    request.session[GDOCS_PENDING_TEXT_KEY] = final_ans
    request.session[GDOCS_PENDING_TITLE_KEY] = "DJN — Final Response"
    request.session[GDOCS_PENDING_QUERY_KEY] = raw_q
    request.session["gdocs_pending_query_final"] = final_q
    request.session.modified = True

    if _get_gdocs_creds(request):
        raw_q_s = request.session.get(GDOCS_PENDING_QUERY_KEY, "")
        final_q_s = request.session.get("gdocs_pending_query_final", "")

        url = _create_google_doc(
            request,
            request.session[GDOCS_PENDING_TITLE_KEY],
            f"Raw Query (User Input):\n{raw_q_s}\n\nFinal Query (Sent to Jurors):\n{final_q_s}",
            final_ans
        )

        if url:
            request.session[GDOCS_LAST_URL_KEY] = url
            request.session.pop(GDOCS_PENDING_TEXT_KEY, None)
            request.session.pop(GDOCS_PENDING_TITLE_KEY, None)
            request.session.pop(GDOCS_PENDING_QUERY_KEY, None)
            request.session.pop("gdocs_pending_query_final", None)
            request.session.modified = True

        return redirect("jury_discussion")

    secrets = _gdocs_client_secrets_file()
    flow = Flow.from_client_secrets_file(
        secrets,
        scopes=GDOCS_SCOPES,
        redirect_uri=_gdocs_redirect_uri(request),
    )
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    request.session[GDOCS_STATE_KEY] = state
    request.session.modified = True
    return redirect(auth_url)



def gdocs_callback(request):
    """
    OAuth callback. Exchange code -> store creds -> create doc from pending text.
    """
    state = request.session.get(GDOCS_STATE_KEY)
    if not state:
        return redirect("jury_discussion")

    secrets = _gdocs_client_secrets_file()
    flow = Flow.from_client_secrets_file(
        secrets,
        scopes=GDOCS_SCOPES,
        state=state,
        redirect_uri=_gdocs_redirect_uri(request),
    )
    if settings.DEBUG:
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
    flow.fetch_token(authorization_response=request.build_absolute_uri())

    creds = flow.credentials
    _save_gdocs_creds(request, creds)

    text = request.session.get(GDOCS_PENDING_TEXT_KEY, "")
    title = request.session.get(GDOCS_PENDING_TITLE_KEY, "DJN — Final Response")
    raw_q = request.session.get(GDOCS_PENDING_QUERY_KEY, "")
    final_q = request.session.get("gdocs_pending_query_final", "") or raw_q

    if text.strip():
        url = _create_google_doc(
            request,
            title,
            f"Raw Query (User Input):\n{raw_q}\n\nFinal Query (Sent to Jurors):\n{final_q}",
            text
        )
        if url:
            request.session[GDOCS_LAST_URL_KEY] = url

    request.session.pop(GDOCS_PENDING_TEXT_KEY, None)
    request.session.pop(GDOCS_PENDING_TITLE_KEY, None)
    request.session.pop(GDOCS_STATE_KEY, None)
    request.session.pop(GDOCS_PENDING_QUERY_KEY, None)
    request.session.pop("gdocs_pending_query_final", None)
    request.session.modified = True

    return redirect("jury_discussion")

