"""Aggregate the wrapper's telemetry (logs/*.log AGENT_CALL events) into the metrics
needed to fill solution/findings.json with REAL observed evidence.

  python tools/analyze_telemetry.py
"""
from __future__ import annotations
import glob, json, statistics as st
from collections import Counter, defaultdict

events = []
for f in sorted(glob.glob("logs/*.log")):
    for line in open(f, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except Exception:
            continue
        if o.get("event") in ("AGENT_CALL", "CACHE_HIT", "BASELINE"):
            events.append(o)

calls = [e["data"] for e in events if e["event"] in ("AGENT_CALL", "BASELINE")]
hits = [e for e in events if e["event"] == "CACHE_HIT"]
n = len(calls)
if not n:
    print("No AGENT_CALL telemetry found in logs/. Run the simulator first."); raise SystemExit

def pct(xs, p):
    xs = sorted(x for x in xs if isinstance(x, (int, float)))
    if not xs: return None
    k = max(0, min(len(xs)-1, int(round((p/100)*(len(xs)-1)))))
    return xs[k]

lat = [c.get("latency_ms") or c.get("wall_ms") for c in calls]
lat = [x for x in lat if isinstance(x, (int, float)) and x > 0]
cost = [c.get("cost_usd") or 0 for c in calls]
tools = [c.get("tool_count") or 0 for c in calls]
reps = [c.get("repeated_actions") or 0 for c in calls]
pii = sum(1 for c in calls if (c.get("pii_redacted") or c.get("pii_in_answer") or 0) > 0)
inj = sum(1 for c in calls if c.get("injection_stripped"))
retries = sum(c.get("retries") or 0 for c in calls)
status = Counter(c.get("status") for c in calls)
ptok = sum((c.get("tokens") or {}).get("prompt_tokens", 0) for c in calls)
ctok = sum((c.get("tokens") or {}).get("completion_tokens", 0) for c in calls)

# drift proxy: ok-rate by turn_index
byturn = defaultdict(lambda: [0, 0])
for c in calls:
    t = c.get("turn")
    if t is None: continue
    byturn[t][0] += 1
    if c.get("status") == "ok": byturn[t][1] += 1

print(f"=== TELEMETRY SUMMARY ({n} AGENT_CALL, {len(hits)} cache hits) ===")
print(f"status            : {dict(status)}")
print(f"error rate        : {100*(n-status.get('ok',0))/n:.1f}%   retries total={retries}")
if lat:
    print(f"latency ms        : P50={pct(lat,50)}  P95={pct(lat,95)}  P99={pct(lat,99)}  max={max(lat)}")
print(f"cost usd          : total={sum(cost):.6f}  avg/req={sum(cost)/n:.6f}")
print(f"tokens            : prompt={ptok:,}  completion={ctok:,}  total={ptok+ctok:,}")
print(f"tool calls/req    : avg={sum(tools)/n:.2f}  max={max(tools) if tools else 0}  dist={dict(Counter(tools))}")
print(f"repeated actions  : reqs_with_repeat={sum(1 for r in reps if r>0)}  total={sum(reps)}")
print(f"PII redacted       : {pii} requests had email/phone in the answer")
print(f"injection stripped : {inj} requests had an injected order-note neutralised")
if byturn:
    print("ok-rate by turn   : " + "  ".join(f"t{t}={v[1]}/{v[0]}" for t, v in sorted(byturn.items())))
