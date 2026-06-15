"""YOUR mitigation + observability layer. The simulator calls mitigate() around the
opaque agent (a REAL LLM) for every request. This is the ONLY place observability can
live -- the agent is silent. Legal moves: retry / cache / route / guardrail / sanitize
/ fallback / session-reset / PROMPT ROUTING, plus your own logging/tracing/metrics.
Illegal: hardcoding answers, importing the agent internals, reading instructor files,
network exfiltration.

  call_next(question, config) -> result   # the only way to reach the black box
  context = {"session_id","turn_index","qid","cache": <shared dict>, "cache_lock": <Lock>}
  result  = {"answer","status","steps","trace","meta":{latency_ms,usage,...}}
"""
from __future__ import annotations

import os
import re
import sys
import time

# Make the LLM SDK (openai) importable inside the frozen, PYTHONPATH-isolated binary:
# the bundled agent imports `openai` lazily but does NOT ship it, and a PyInstaller
# onefile ignores PYTHONPATH. We vendor it under <repo>/_libs and prepend that here
# (harmless no-op when _libs is absent, e.g. on a graders box that bundles openai).
_LIBS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_libs")
if os.path.isdir(_LIBS) and _LIBS not in sys.path:
    sys.path.append(_LIBS)            # append: bundled modules keep priority, _libs fills gaps

# --- Day 13 telemetry toolkit (stdlib-only, degrades gracefully if absent) ---------
try:
    from telemetry.logger import logger, new_correlation_id, set_correlation_id
    from telemetry.cost import cost_from_usage
    from telemetry.redact import redact
except Exception:  # pragma: no cover - telemetry is optional
    logger = None

    def new_correlation_id():
        return "req-0"

    def set_correlation_id(_cid):
        return None

    def cost_from_usage(_model, _usage):
        return 0.0

    def redact(s):
        return (s, 0)


# --- the rewritten system prompt, loaded once from solution/prompt.txt --------------
def _load_prompt():
    here = os.path.dirname(os.path.abspath(__file__))
    try:
        with open(os.path.join(here, "prompt.txt"), encoding="utf-8") as fh:
            return fh.read().strip()
    except Exception:
        return ""


_SYSTEM_PROMPT = _load_prompt()

# Order-note injection markers: "GHI CHU", instruction verbs, fake price overrides.
_INJECTION = re.compile(
    r"(ghi\s*ch[uú]|b[oỏ]\s*qua|ignore|disregard|system\s*:|"
    r"gi[aá]\s*(?:la|=|:)|set\s*price|free\s*ship|mi[eễ]n\s*ph[ií]|0\s*vnd)",
    re.IGNORECASE,
)
_NOTE_SPLIT = re.compile(r"(ghi\s*ch[uú]\s*:?)", re.IGNORECASE)


def _cache_key(question, config):
    return "%s|%s|%s" % (
        (question or "").strip().lower(),
        config.get("model"),
        config.get("temperature"),
    )


def _sanitize(question):
    """Neutralise prompt-injection hidden in order notes (the private twist).

    Notes are DATA: we strip the text after a 'GHI CHU' marker when it carries
    instruction/price-override content, so the agent never sees an injected command.
    Returns (clean_question, fired_bool)."""
    if not question:
        return question, False
    parts = _NOTE_SPLIT.split(question)
    if len(parts) <= 1:
        # No explicit note marker: drop only clearly injected instruction clauses.
        if _INJECTION.search(question):
            cleaned = re.sub(
                r"[.;\n][^.;\n]*(?:b[oỏ]\s*qua|ignore|set\s*price|gi[aá]\s*(?:la|=|:))[^.;\n]*",
                "",
                question,
                flags=re.IGNORECASE,
            )
            return cleaned.strip(), cleaned != question
        return question, False
    head = parts[0]
    note = "".join(parts[1:])
    if _INJECTION.search(note):
        return head.strip(), True
    return question, False


def mitigate(call_next, question, config, context):
    cache = context.get("cache")
    lock = context.get("cache_lock")
    t0 = time.time()

    # one correlation id per request so every log line of this request shares an id
    set_correlation_id(new_correlation_id())

    # --- input sanitize: strip injected instructions from order notes --------------
    clean_q, injected = _sanitize(question)

    # --- prompt routing: force OUR system prompt on every request ------------------
    conf = dict(config)
    if _SYSTEM_PROMPT:
        conf["system_prompt"] = _SYSTEM_PROMPT

    # --- cache: skip the LLM entirely for an identical, already-seen request -------
    ckey = _cache_key(clean_q, conf)
    if cache is not None and lock is not None:
        with lock:
            hit = cache.get(ckey)
        if hit is not None:
            _log("CACHE_HIT", context, {"qid": context.get("qid"), "wall_ms": 0})
            return hit

    # --- call the black box with retry/backoff on transient failure ---------------
    retry = config.get("retry", {}) or {}
    attempts = max(1, int(retry.get("max_attempts", 1))) if retry.get("enabled") else 1
    backoff = float(retry.get("backoff_ms", 0)) / 1000.0
    result, last_err = None, None
    for attempt in range(attempts):
        try:
            result = call_next(clean_q, conf)
        except Exception as exc:  # transient LLM/tool error -> retry
            last_err = repr(exc)
            result = None
        if result is not None and result.get("status") == "ok" and result.get("answer"):
            break
        if attempt < attempts - 1:
            time.sleep(backoff * (attempt + 1))

    if result is None:
        result = {"answer": None, "status": "wrapper_error", "steps": 0, "trace": [],
                  "meta": {}}

    # --- output guardrail: redact any PII that leaked into the answer --------------
    ans = result.get("answer")
    pii_n = 0
    if isinstance(ans, str):
        red, pii_n = redact(ans)
        if pii_n:
            result["answer"] = red

    # --- observability: the ONLY place these signals exist -------------------------
    meta = result.get("meta", {}) or {}
    usage = meta.get("usage", {}) or {}
    trace = result.get("trace", []) or []
    tools = meta.get("tools_used", []) or []
    _log("AGENT_CALL", context, {
        "qid": context.get("qid"),
        "session": context.get("session_id"),
        "turn": context.get("turn_index"),
        "status": result.get("status"),
        "steps": result.get("steps"),
        "wall_ms": int((time.time() - t0) * 1000),
        "latency_ms": meta.get("latency_ms"),
        "tokens": usage,
        "cost_usd": cost_from_usage(meta.get("model", ""), usage),
        "tools_used": tools,
        "tool_count": len(tools),
        "repeated_actions": _count_repeats(trace),
        "pii_redacted": pii_n,
        "injection_stripped": injected,
        "retries": attempts - 1,
        "error": last_err,
    })

    # --- store successful results for the cache ------------------------------------
    if cache is not None and lock is not None and result.get("status") == "ok":
        with lock:
            cache[ckey] = result
    return result


def _count_repeats(trace):
    """Count repeated identical tool actions in a trace (infinite-loop signal)."""
    seen, repeats = {}, 0
    for step in trace:
        if not isinstance(step, dict):
            continue
        key = (step.get("action") or step.get("tool"), str(step.get("args") or step.get("input")))
        seen[key] = seen.get(key, 0) + 1
        if seen[key] > 1:
            repeats += 1
    return repeats


def _log(event, context, data):
    if logger:
        try:
            logger.log_event(event, data)
        except Exception:
            pass
