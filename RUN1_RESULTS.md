# Run 1 results (runs/20261104-143922-84bf)

The run folders named here aren't in this repo. Only Run 5's cycle log is, in `runs/`.

5 agents, 7-day steps, 3 cycles, every role on Spark Contributor. 14:39 → 15:36 local (56.8 min), about $0.10.
Stop: `max_cycles`; picked g2-01 (`final.json`).

## Time
| Cycle | Per step (5 agents) | Per agent step | Eval | Generation + cleaner |
|---|---|---|---|---|
| 1 | 2.1–2.7 min | ~29 s | 2.7 min | 1.3 + 1.4 min |
| 2 | 3.0–3.9 min | ~39 s | 4.1 min | 2.2 + 1.7 min |
| 3 | 3.4–4.2 min | ~47 s | 4.2 min | final pick 14 s |
Mean 38 s per agent step (60 steps, 2,299 s). Source: `t` of `step`, `cycle_end`, `generation`, `cleaner` in log.jsonl.

## The main finding
Most scores are the starter strategy's score. The score is cycle return minus an equal-weight buy-and-hold
(`apex/env_connector/__init__.py:91`); the starter strategy is equal weight rebalanced daily
(`starter_strategy.py`), so an agent that never changes strategy.py scores "benchmark minus fees": −0.000686
(cycle 1), −0.000941 (cycle 2), 0.0000888 (cycle 3), the same numbers as the fake run.
8 of 11 agents' strategy.py equal the starter byte for byte (g0-02..05, g1-02, g1-03, g2-01, g2-03).
The picked agent g2-01 is one of them: it won a tie.

## 15 hypotheses
Confirmed (seen in the run's files):
1. The 18k token cap ends a step at turn 4. It counts input and output over all turns, and the whole conversation
   is re-sent each turn (inputs 2.6k → 3.3k → 3.5k → 5k). Most steps end `cap:call_tokens` at 4 turns.
2. Turns 1–3 of every step are orientation: `list_files` → `read_file` ×4 → `backtest_report` / `read_prices`.
   About 8.5k tokens go before any work (logs/g0-01.jsonl, every step).
3. 8 of 11 agents never changed strategy.py, so they trade the starter all run.
4. The one working turn goes to exploration scripts (explore.py, peek.py, test_mr.py, check.py, explore_ctx.py) whose
   output the agent never reads: the cap ends the step right after.
5. The step prompt sets no priority: "Do your work for this step, then call finish" (`apex/prompts.py:77`). It never
   says the score comes only from strategy.py, or that the starter is the benchmark (score ≈ 0 minus fees).
6. Agents don't know their budget: the prompts say nothing about 18k tokens or ~4 turns, so they plan long
   exploration.
7. The final pick is a tie-break among starter agents (g2-01 = g0-02 = g1-02 = g2-03 in cycle 3).

Likely (some evidence):
8. Replies cut at max_output_tokens 4000: 21 of 230 agent replies are `incomplete`; g0-01 needed 3,741 output tokens
   for one write_file. A cut write_file is lost.
9. New generations inherit the starter: children copy a parent's files (g1-02 and g2-01 carry g0-02's explore.py
   and test_mr.py), so evolution has nothing to select on.
10. Code changes between cycles: g1-01's strategy.py lacks two lines of g0-01's (`_prev_set = None`). The cleaner
    (5 + 9 deletions) or Mutation did it; not traced yet.
11. The starter trades every day (65–67 trades per step) and pays fees; the benchmark pays none, so "doing nothing"
    starts slightly negative. Design, but it hides the starter as "a strategy".

Untested:
12. Hidden reasoning counts as output tokens, leaving less room for code in each reply.
13. Reading prices into the conversation (`read_prices`) instead of through `run_script` grows the input each turn.
14. Subagents are never used (no spawn call seen), so their 5k pool is wasted.
15. The signal is too small to evolve on: 4 weekly steps per cycle, excess returns of ±0.1–1%, 3 cycles; Eval and
    selection compare noise.

## Run 3 (runs/20261104-165313-32ca), stopped at check 2
3 agents, 100k tokens per step, the creative prompts, interpretation.md and the replay helper. Launched 16:53 local;
step 0 ended 16:57; check 2 (16:59) found nothing changed, so it was stopped with `run.py stop`:
`final.json` reason `stopped_by_user`, no pick (no cycle scored).

What happened: in step 0, every agent's first call came back `incomplete` with 4000 output tokens, no text and no
tool calls (logs/g0-0*.jsonl). All 4000 tokens went to hidden reasoning, and max_output_tokens is 4000 per call.
`call_agent` treats a reply with no tool calls as the agent being done (`ended_by: reply`), so each step ended
after 1 turn: strategy.py still the starter, interpretation.md still empty, no replay. Run 1's first turns used
67–400 output tokens; the new, longer and more open instructions make the model think much longer before acting.
Hypothesis 12 (reasoning counts as output) is now confirmed; fix D (output cap 4k → 8k) was not applied.

## Run 3, relaunched (runs/20261104-171249-57a0): 16k output cap, 60-min limit
17:12 → ~17:46 local, `max_cycles`, picked g0-01. Checks every 5 min: all GO (no failed calls, no errors).
Agents: Phase-Lock Kuramoto Synchronizer (g0-01), Hawkes SIR Contagion Mapper (g0-02), Return-Grammar Entropy
Trader (g0-03). All three wrote interpretation.md, replaced the starter and ran the replay 1–3 times per step.

| Step | trades / fees / cash (g0-01) | excess g0-01 | excess g0-02 | excess g0-03 | benchmark |
|---|---|---|---|---|---|
| 0 | starter | −0.11% | −0.11% | −0.11% | +0.61% |
| 1 | 19 / $108 / 80% | +0.98% | −0.10% | +0.43% | −1.03% |
| 2 | 7 / $1 / 80% | −0.58% | −3.18% | −2.23% | +1.93% |
| 3 | 7 / $1 / 80% | −1.26% | −3.96% | −2.55% | +2.95% |

Why all lost to buy-and-hold: cash drag in a rising month (g0-01 80% cash, g0-02 47–56%, g0-03 35–45%); fees
from heavy trading (g0-03 ~$390, g0-02 ~$280 over two steps); week 1 on the starter; one 4-week cycle is noise.
Eval's hidden notes found the real flaws (one-asset collapse, underexposure, replay +6.4% vs live −1.26% =
overfit, sparse or self-neutralizing signals, gap filling bias). They are not corrected because: 1 cycle (no
Mutation); agents never see Eval notes; children start from the starter, not the parent's code; the replay rewards
fitting the last 120 days.
Open: a cut-off reply with no tool call still ends an agent's step (g0-03 step 1).

## Run 4 (runs/20261104-180102-fd17): 4 agents, sequential, tilt rule, advice below 0
18:01 → 19:45 local (104 min), `time_limit` after 2 cycles, 1 generation; Op. Orch final pick g0-01 (Wavelet Phase
Surfer, cycle excess +0.04%, +0.22%, the only agent positive in both); ~$0.18; 0 failed calls.
- Step 0 took 19 min, later steps 9–12 min (4 agents one after another); cycle ≈ 52 min.
- Cycle 1 (benchmark +2.95%): g0-02 +0.13%, g0-01 +0.04%, g0-03 −0.37%, g0-04 −1.53%. Cash 0–1%: the tilt rule ended
  run 3's cash drag.
- Advice never fired: both survivors scored above `advice_below` 0.0.
- The step summary was empty every step (`summary_output_tokens` 1000; likely hidden reasoning used it).
- Children: g1-01 got new axioms but its parent's strategy.py byte for byte; g1-02 started from the starter.

## Run 5 (runs/20261104-200512-07b8): 6 parallel agents, Op. Orch on Wonder, asset names cleaned
20:05 → 22:07 local (122 min), stopped by the user after cycle 4 (4 cycles scored, 4 generations); fallback pick
g2-03 (best loop score); ~$0.71; 0 failed calls. Parallel agents: step 0 6.2 min, later steps 2–6 min; cycle ≈ 30–37
min (Eval, one agent after another, ~5.5–7.5 min of it). Wonder gen 0: 72 s.

| Cycle | Benchmark | Best real trader | Note |
|---|---|---|---|
| 1 | +2.95% | g0-06 Ising Thermometer +0.28% | g0-02 (45% cash) −2.88%, g0-04 (56% cash) −1.78%: dropped |
| 2 | +1.19% | **g1-01 Detrended Wavelet Lead-Lag Surfer +0.86%** | Mutation's fix of g0-01's FFT trend leak (g0-01 −0.09%) |
| 3 | −1.79% | g2-02 Hawkes R0 Contagion Governor +0.50% | g2-03 +1.79% with 100% cash, 0 trades |
| 4 | −3.66% | g3-03 Activator Inhibitor Turing Allocator +1.17% | g2-03 +3.66% with 100% cash, 0 trades |

Worked:
- Parallel agents: ~4× faster steps with 50% more agents; no 429s or failed calls.
- Advice reached survivors (cycles 2–4); g0-06 removed its stale-hold gates and ffill zeros the same step. Not every
  agent followed it (g0-03 kept 70% cash).
- Mutation diagnosed real code bugs (ffill zeros, FFT trend leak, sign errors); Op. Orch (Wonder) rejected 2 of 6
  drafts per generation with sound reasons and approved 3 new Eval axes (calendar, cost, benchmark-relativity).
- No "Asset X" names left in agent folders after the cleaner.

Found (not fixed):
1. Scoring rewards doing nothing in a falling market: g2-03 never traded in cycles 3–4 (weights() returned
   nothing; 0 errors) and scored +1.79%, +3.66%; it survived both cycles and won the fallback pick.
2. Eval reads the code, not the backtest: it praised g2-03 for "forcing full investment" while it held 100% cash.
   Fix: give Eval each agent's cycle numbers (trades, cash share, fees).
3. A second agent sat in cash for a week: g3-03 (parents g2-04, g2-01, not g2-03) wraps weights() in
   `except Exception: return None`; None means hold, and a cycle starts in cash, so an error silently holds cash
   with 0 errors logged. It fixed this in its next step. g2-03's cause (it returns a dict) is not confirmed.
4. A stop mid-run gives a fallback pick (best loop score) with no Op. Orch check; `final.json` says cycles 5 when the
   stop came after cycle 4's generation (the counter had moved on).
5. Eval runs one agent after another (~1 min each): the largest serial part of a parallel cycle.
6. Gen 0 ideas repeat across runs (phase/wavelet, contagion, entropy, Kalman): the brief's examples steer them.
