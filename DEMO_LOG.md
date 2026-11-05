# Apex: demo log (runs of 2026-11-04)

Everything needed to script the video, with exact numbers, quotes and file paths. Source paths such as
`hidden/eval/` are inside the run's folder, which isn't in this repo; only Run 5's cycle log is, in `runs/`.
Times are local (CET). Run 5 is the demo run; run 4 is the backup.

---

## 1. What Apex is (for the voice-over)

A generic agent-evolution engine (`apex/`) plus one test task behind a connector (`apex/env_connector/`). The core
knows nothing about markets; the task here is: manage a portfolio of 13 disguised assets (stocks, bonds, gold,
crypto…), day by day through 2025, and beat an equal-weight buy-and-hold.

Roles (all LLM calls):
- **Op. Orch** (orchestrator): drafts the first agents (gen 0), approves or rejects new ones, makes the final pick.
  Run 5: Muse Wonder. Every other role: Muse Spark.
- **Agents**: each has axioms (its idea), `strategy.py` (code that returns portfolio weights), `interpretation.md`
  (its own reading of each axiom, kept as memory) and `notes.md`. Each step, an agent sees its last report, works
  with tools (read data, write files, run scripts in a sandbox, replay its strategy on past days), then finishes.
- **Eval**: a hidden reviewer; per agent, per cycle: strengths, weaknesses, axiom flaws.
- **Mutation**: reads the scores and Eval's notes, diagnoses what failed, drafts new agents that combine two parents.
- **Cleaner**: between cycles erases dates, price levels and asset names from agents' folders (no memorising).

Loop: 1 step = 7 market days revealed; 4 steps = 1 cycle (~4 weeks, starts from $100,000 cash). After each cycle:
score → Eval → keep 2 survivors → Mutation drafts → Op. Orch approves → cleaner → next cycle.

Score per cycle = the agent's return − equal-weight buy-and-hold's return (buy-and-hold pays no fees; agents pay
0.1% per trade). Cycles walk forward through 2025, so every cycle trades days no agent has seen.

---

## 2. The five runs in one table

| Run | When | Setup | Result | Lesson that changed the next run |
|---|---|---|---|---|
| 1 | 14:39–15:36 | 5 agents, 18k tokens/step | 8 of 11 agents never changed the starter strategy; pick won a tie | budget ran out in orientation → bigger budget, files shown in the prompt, a "your score comes only from strategy.py" line |
| 3a | 16:53–16:59 | creative prompts, 100k tokens | stopped: every first call spent its 4,000 output tokens thinking, no action | output cap 4k → 16k |
| 3 | 17:12–17:46 | 3 agents, 1 cycle | agents creative (Kuramoto, Hawkes, entropy) but all lost (−1.3 to −4.0%): 35–80% cash in a rising month | brief: "stay fully invested, tilt away from equal weight"; reviewer advice to agents |
| 4 | 18:01–19:45 | 4 agents, sequential | 2 of 4 beat buy-and-hold in cycle 1; pick g0-01 positive in both cycles; 52 min per cycle | too slow (2 cycles in 104 min) → parallel agents |
| 5 | 20:05–22:07 | 6 agents **in parallel**, Wonder Op. Orch, asset names erased | 4 cycles, 4 generations; best real cycle +0.86% (gen-1 child); scoring flaw found | see section 6 |

(Run 2 was a config that was never launched.)

Spend: run 4 ~$0.18, run 5 ~$0.71 ($0.30, $0.15, $0.14, $0.13 per cycle). No failed API call in runs 4–5.

---

## 3. Run 5 setup

- Run id `20261104-200512-07b8`, log `runs/run5-20261104-2005.log`, config `configs/run5.json`.
- 6 agents, all 6 work at the same time (`operation.parallel_agents: 6`, new tonight).
- 100k tokens per agent step, 16k output per call; 2025 data, 7-day steps, 4 steps per cycle.
- Survivors scoring below +1% get their own Eval weaknesses as advice, framed "you may ignore it".
- Stopped by the user after cycle 4 (time); final pick = fallback (best average score, no model call).

Speed (parallel vs run 4's sequential):

| | Run 4 (4 agents, one after another) | Run 5 (6 agents at once) |
|---|---|---|
| First step | 19 min | 6.2 min |
| Later steps | 9–12 min | 2–6 min |
| Gen 0 → first scores | 51 min | 20 min |
| Cycles in ~2 h | 2 | 4 |

Live parallel check before the run (`tools/parallel_calls.py`): 12 calls at once, 12/12 ok, 0 retries, 4.1 s
(vs ~19 s one after another). Wonder alone 1.8 s, Spark alone 1.5 s. Wonder's gen 0 in the run: 72 s.

---

## 4. Run 5, cycle by cycle

Benchmark = equal-weight buy-and-hold's return over the cycle. Excess = agent − benchmark.

| Cycle | Benchmark | Agents (excess) | Kept | Dropped |
|---|---|---|---|---|
| 1 | +2.95% | g0-06 Ising Thermometer **+0.28**, g0-03 Symbolic Entropy Scout +0.05, g0-01 Spectral Phase Surfer −0.09, g0-05 Lotka-Volterra Gardener −0.11, g0-04 Kalman Helm −1.78, g0-02 Contagion Epidemiologist −2.88 | g0-06, g0-03 | g0-04, g0-02 (sat in 45–56% cash in the up week) |
| 2 | +1.19% | **g1-01 Detrended Wavelet Lead-Lag Surfer +0.86**, g1-03 Valid-Session Bottleneck Scout −0.14, g1-04 Laplacian Diffusion Governor −0.19, g0-06 −0.53, g0-03 −1.77, g1-02 Antiferromagnetic OU Thermostat −2.89 | g1-01, g1-03 | both gen-0 survivors; g1-02 flagged worse than its parents |
| 3 | −1.79% | g2-03 Kalman LQR Drift Tracker +1.79 (**never traded**), g2-02 Hawkes R0 Contagion Governor **+0.50**, g1-03 +0.16, g1-01 −0.22, g2-04 Minority Hedge Game Allocator −0.62, g2-01 Lotka-Volterra Niche Replicator −1.03 | g2-03, g2-02 | g1-01 (cycle 2's winner) |
| 4 | −3.66% | g2-03 +3.66 (**never traded**), g3-03 Activator Inhibitor Turing Allocator **+1.17**, g3-02 Trigram Surprisal Reversal Reader +0.30, g2-02 −0.05, g3-01 Advective Diffusion Dye Tracker −0.08, g3-04 Waiting Line Reversal Clerk −0.16 | g2-03, g3-03 | — (run stopped) |

Best real trader per cycle: +0.28% → **+0.86%** → +0.50% → +1.17% (g3-03's includes one week in cash by accident,
see 6.3).

Lineage (parents from `hidden/mutation/cycle-N.json`):
- g1-01 Detrended Wavelet Lead-Lag Surfer ← g0-01 Spectral Phase Surfer + g0-06 Ising Thermometer
- g1-02 Antiferromagnetic OU Thermostat ← g0-06 + g0-04
- g1-03 Valid-Session Bottleneck Scout ← g0-03 + g0-01
- g1-04 Laplacian Diffusion Governor ← g0-02 + g0-04
- g2-01 Lotka-Volterra Niche Replicator ← g1-04 + g0-06
- g2-02 Hawkes R0 Contagion Governor ← g1-04 + g1-01
- g2-03 Kalman LQR Drift Tracker ← g1-01 + g1-04
- g2-04 Minority Hedge Game Allocator ← g1-03 + g1-02
- g3-01 Advective Diffusion Dye Tracker ← g2-03 + g2-04
- g3-02 Trigram Surprisal Reversal Reader ← g1-03 + g1-01
- g3-03 Activator Inhibitor Turing Allocator ← g2-04 + g2-01
- g3-04 Waiting Line Reversal Clerk ← g2-03 + g1-03
- gen 4 (made, never traded): Kuramoto Synchronization Oscillator, Mutual-Information Grammar Trader, Stokes Drift
  Exhaustion Gauge, Mean-Field Game Liquidity Governor

---

## 5. Demo moments (with sources)

### 5.1 Selection removes the rule-breakers (cycle 1)
The brief tells agents to stay fully invested. Two did not: Contagion Epidemiologist held 45% then 31% cash,
Kalman Helm 56%, in the week buy-and-hold rose ~3%. Contagion Epidemiologist went from +0.32% to −2.59% in one
step. Both were the bottom two and were dropped. Source: `log.jsonl`, `step` events, `cash_share`.

### 5.2 Mutation diagnoses real code bugs (after cycle 1)
`hidden/mutation/cycle-1.json`, `axis_analysis`:
- "g0-03 ffill+fill0 created ~50% artificial zero returns wrecking tercile symbols and 81-cell TE on ~100 decayed
  obs is bias-dominated"
- "g0-01 FFT on demeaned log levels leaks trend into 24/32/48 bins, coh=mean cos^2 ~0.75 always"
- "g0-06 … assumes continuation while 1-5d is reversal"

### 5.3 Op. Orch (Wonder) approves and rejects with reasons
`orch/log.jsonl`, `draft_decision` events. Cycle 1: 4 adopted, 2 rejected:
- Adopted, Detrended Wavelet Lead-Lag Surfer: "Distinct spectral test that addresses the documented trend-leakage
  and calendar problems through detrended stationary inputs and significance gating, rather than repeating the
  failed level-FFT phase extrapolation."
- Rejected, Volume-Niche Neutral Forager: "Clearly does not hold as stated: Hubbell neutral drift assumes
  functional equivalence and random fitness drift, so it supplies no basis for inferring differential return
  fitness from volume niches…"
- Rejected, Minority Crowding Game: "…recreate the sparse conditional-table failure that undermined the 81-cell
  transfer-entropy agent…"
New review axes approved after cycle 1: calendar-awareness, cost-awareness, benchmark-relativity
(`axis_decision` events).
Cycle 2: rejected Linguistic Compression Scout ("…need far longer sequences than roughly 120 valid…") and Omori
Aftershock Harvester ("shocks above 2.5 sigma occur only a few times per asset in the window…").

### 5.4 The evolution story: a diagnosed bug, fixed, wins the next cycle
g0-01 Spectral Phase Surfer: −0.09% in cycle 1, dropped. Mutation: its FFT on raw log prices leaks the trend.
Child g1-01 Detrended Wavelet Lead-Lag Surfer (detrended inputs, significance gates; 13 trades in a week, $30 fees)
wins cycle 2 with **+0.86%**, the best real cycle score of all runs. It then fell to −0.22% in cycle 3 and was
dropped: one good month is not a lasting edge.

### 5.5 Reviewer advice, acted on in the same step (cycle 2, step 0)
Advice shown to g0-06 Ising Thermometer (`logs/g0-06.jsonl`, step 4 `start` message):
> "A suggestion from a reviewer (your score last cycle was 0.002847). Weigh it against your own judgment; you may
> ignore it. … +0.0028 in one cycle with -0.0075 average looks like low-active-share luck, not skill. …
> Multiple staleness gates compound: weekend hold, max|edge_z|<0.4 hold, 0.05 deadband, 0.30 turnover
> interpolation keep stale weights…"

The agent's next lines (same log):
> "Fixing the cash and staleness drag while keeping the Ising core — first diagnosing the signal sign."
> "Removing the stale-hold gates and cash drag — rewriting the strategy to stay invested and cut churn."
> "Replay shows a large shortfall versus equal weight, so I'm running diagnostics to resolve the signal direction."

Honest note: it still scored −0.53% that cycle; g0-03 got similar advice and kept 70% cash.

### 5.6 Parallel speed
Six agents' logs grow at the same time; step 0 in 6.2 min vs 19 min for four agents in run 4.

---

## 6. What the run exposed (say it, it is a strength of the demo)

### 6.1 Doing nothing wins in a falling market
g2-03 Kalman LQR Drift Tracker held **100% cash with 0 trades** for all of cycles 3 and 4. The market fell
1.79% and 3.66%, so it "beat" buy-and-hold by exactly that. It survived both cycles and is the run's final pick
(`final.json`: `selected: g2-03`, `fallback: true`, loop score 0.361). Its code returns weights; why they never
turn into trades is not yet confirmed.

### 6.2 Eval reviews the code, not the trades
Eval's note on g2-03 after cycle 3 (`hidden/eval/cycle-3/g2-03.json`) praises it: "Gross band 0.90-1.0 with
target vol 0.012 effectively forces full investment; given scoring vs fully-invested equal-weight this avoids the
classic cash-drag error." It was 100% cash. Eval did say "rank 1 looks like luck/regime fit", for the wrong reason.

### 6.3 Errors can hide as cash
g3-03 wraps its strategy in `except Exception: return None`. None means "keep current positions", and a cycle
starts in cash, so an error silently holds cash with 0 errors logged. It was 100% cash in its first week (+1.26%
from the fall), then fixed it and traded fully invested.

### 6.4 Smaller points
- Margins are small: +0.1–1% over one month is within noise. Say "beat the benchmark this month", not "an edge".
- Gen 0 ideas repeat across runs (phase/wavelet, contagion, entropy, Kalman): the brief's examples steer them.
- Eval runs one agent after another (~1 min each), now the slowest serial part of a cycle.

Fixes, for after the demo: count a step with no trades as an error (or score it as the starter); give Eval each
agent's trades, cash share and fees; Eval in parallel.

---

## 7. Suggested storyline (≈ 3–5 min)

1. **Problem** (20 s): can a team of AI agents evolve strategies on its own? Generic engine, a market as the test.
2. **The loop** (40 s): roles diagram (section 1); one cycle = 4 weeks; score vs buy-and-hold.
3. **Iterating the system** (40 s): runs 1 → 5 table (section 2): agents that did nothing → agents that hoarded
   cash → agents that trade; 52 → 30 min per cycle with parallel agents.
4. **Run 5 live** (90 s): 6 creative agents in parallel (names); selection drops the cash hoarders (5.1);
   Mutation's diagnosis (5.2); Op. Orch rejecting a draft (5.3); the wavelet fix winning cycle 2 (5.4); the advice
   and the agent's reply (5.5).
5. **The twist** (40 s): the winner never traded (6.1) and the reviewer praised it (6.2). The loop optimises what you
   measure; next fix is to measure trades, not just returns.
6. **Close** (20 s): numbers: 4 generations, 18 agents, ~$0.71, 2 h, 0 failed calls.

---

## 8. Files to show on screen

| What | Path |
|---|---|
| Live log (cycle lines) | `runs/run5-20261104-2005.log` |
| Results write-up | `RUN1_RESULTS.md` |

Agent IDs: gN-0K = generation N, agent K.
