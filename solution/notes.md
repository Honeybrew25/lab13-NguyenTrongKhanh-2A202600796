# Diagnosis scratchpad — measured evidence

Telemetry is built in `wrapper.py` (`mitigate()` logs one `AGENT_CALL` JSON line/request to
`logs/*.log`). Diagnosed by comparing a **baseline** run (shipped bad config, observe-only:
`tools/baseline_config.json` + `tools/baseline_wrapper.py`) against the **fixed** solution, both
over the fixed public set. Aggregate with `python tools/analyze_telemetry.py`.

## Measured before → after (public fixed set, gpt-4o-mini)

| fault | metric | baseline (bad config) | fixed (solution) | fix |
|---|---|---|---|---|
| infinite_loop | max_steps / repeated actions | 19/120 max_steps, 34 req w/ repeats | **0** | loop_guard=true, max_steps=6 |
| latency_spike | latency P95 / P99 | **66031 / 80885 ms** | **12197 / 13160 ms** | timeout, cache, loop_guard |
| error_spike | non-ok rate | **15.8%** | **0.0%** | tool_error_rate=0, retry on |
| tool_overuse | tool calls avg / max | 3.53 / **13** | 2.61 / 5 | prompt (each tool once), tool_budget=4 |
| pii_leak | answers w/ email/phone | **25/120** | **0** emitted | prompt + redact_pii + wrapper redact |
| cost_blowup | $/req · tokens | $0.00361 · 2.71M | **$0.00153** (even w/ self_consistency=3) | verbose off, tier std, fewer tokens |
| tool_failure | obs vs reality | MacBook forced 'het hang'; diacritic city misfires | grounded | clear catalog_override, normalize_unicode |
| arithmetic_error | exact total | estimated (temp 1.6) | exact `…*(100-pct)//100 + ship` | temp 0.2, formula, self_consistency, verify |
| fabrication | refuse unavailable | invents totals | refuses w/ no total (AirPods/MacBook) | prompt grounding |
| quality_drift | ok-rate by turn | degrades late (drift 0.06) | stable across turns | drift=0, context_reset_every=6 |
| prompt_injection | obeys note price | PRIVATE phase only | defended | prompt: notes=DATA; wrapper sanitize |

Result: fixed solution = **120/120 status ok** on the public fixed set.
