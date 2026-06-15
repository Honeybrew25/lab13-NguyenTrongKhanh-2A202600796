"""OBSERVE-ONLY wrapper for diagnosing the SHIPPED faults (no mitigation, no prompt
routing). Logs one BASELINE event per request so tools/analyze_telemetry.py can show
the 'before' numbers. Used with tools/baseline_config.json (the bad shipped defaults)."""
from __future__ import annotations
import os, sys, time

_LIBS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_libs")
if os.path.isdir(_LIBS) and _LIBS not in sys.path:
    sys.path.append(_LIBS)

from telemetry.logger import logger, new_correlation_id, set_correlation_id
from telemetry.cost import cost_from_usage
from telemetry.redact import redact


def mitigate(call_next, question, config, context):
    set_correlation_id(new_correlation_id())
    t0 = time.time()
    err = None
    try:
        r = call_next(question, config)            # raw agent: NO prompt override, NO fixes
    except Exception as exc:
        err = repr(exc)
        r = {"answer": None, "status": "wrapper_error", "steps": 0, "trace": [], "meta": {}}
    meta = r.get("meta", {}) or {}
    usage = meta.get("usage", {}) or {}
    trace = r.get("trace", []) or []
    tools = meta.get("tools_used", []) or []
    ans = r.get("answer") or ""
    pii = redact(ans)[1] if isinstance(ans, str) else 0
    seen, reps = {}, 0
    for s in trace:
        if isinstance(s, dict):
            k = (s.get("action") or s.get("tool"), str(s.get("args") or s.get("input")))
            seen[k] = seen.get(k, 0) + 1
            if seen[k] > 1:
                reps += 1
    logger.log_event("BASELINE", {
        "qid": context.get("qid"), "turn": context.get("turn_index"),
        "status": r.get("status"), "steps": r.get("steps"),
        "wall_ms": int((time.time()-t0)*1000), "latency_ms": meta.get("latency_ms"),
        "tokens": usage, "cost_usd": cost_from_usage(meta.get("model", ""), usage),
        "tool_count": len(tools), "repeated_actions": reps, "pii_in_answer": pii, "error": err,
    })
    return r
