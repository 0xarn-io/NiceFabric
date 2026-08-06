# Optimization: measured, targeted, verified

The core discipline: optimization decisions are empirical, not intuitive. Intuition
about where time goes is wrong so often that acting on it unmeasured is closer to
vandalism than engineering — you trade clarity for speed you may not even gain.

## Before optimizing anything

1. **Define "fast enough" first.** A target ("page loads under 300 ms", "cycle time
   under 2 ms", "process the file in under a minute") turns optimization from an
   open-ended aesthetic project into a task that can finish. No target → no way to
   know when to stop → cleanliness sacrificed indefinitely.
2. **Measure the baseline.** One number, reproducible, recorded. Every later claim
   of improvement is relative to this.
3. **Profile to find where time actually goes.** The hotspot is rarely where you
   think. In Python: `cProfile` for call-level, `py-spy` for sampling a live
   process, `timeit` for micro-questions. Poor man's profiler when tools aren't
   available: coarse timers around major phases — even that beats intuition.
4. **Freeze a correctness harness.** Tests, or a recorded input→output pair on
   realistic data. Every optimization step must reproduce identical output. Fast
   and wrong is just wrong, sooner.

## Where the leverage is — work this order

**Tier 1: Do less work (algorithmic).** The only tier with order-of-magnitude wins.
Replace O(n²) with O(n log n) or O(n); replace "list membership in a loop" with a
set/dict; sort once instead of searching repeatedly; precompute what's reused.
The classic accidental quadratic: a linear scan (list `in`, string concatenation,
`remove()`) *inside* a loop. Grep for those before anything clever.

**Tier 2: Do the expensive thing fewer times (I/O and round-trips).** In most real
systems the bottleneck isn't CPU, it's waiting: network calls, disk, database.
- Batch round-trips: the N+1 query pattern (one query per item in a loop) turns
  into one query with a join or an `IN` clause. Same for API calls.
- Move invariant work out of loops: opening files, compiling regexes, creating
  sessions/connections — once, outside.
- Cache repeated pure computation (`functools.lru_cache`) and repeated fetches of
  slow-changing data — but design the invalidation story *when you add the cache*,
  not after the first stale-data bug. A cache without an invalidation plan is a
  deferred outage.

**Tier 3: Do the same work faster (mechanical sympathy).** Python-specific:
- Push loops into C: builtins (`sum`, `max`, `sorted` with keys), comprehensions
  over accumulator loops, `str.join` over `+=` concatenation, and NumPy/pandas
  vectorization when data is bulk-numeric.
- Concurrency by bottleneck type: I/O-bound → asyncio or threads (many waits can
  overlap); CPU-bound → multiprocessing (the GIL serializes threads on pure
  compute). Applying async to a CPU-bound problem is a common no-op.
- Generators/streaming over materializing giant lists when data is processed once.

**Tier 4: micro-optimizations.** Attribute-lookup hoisting, local variable tricks…
Only under a profiler's direction, only when the target isn't met yet, and only
where the profiler says the time is. Below this line, readability wins by default.

## The loop, per change

One optimization at a time: measure → change → re-measure on the same benchmark →
re-run the correctness harness → keep or revert. Record each attempt and its delta
in your working notes, including the failures ("vectorizing X: no change — the time
was in the DB call") — the failed attempts are what stop you or a successor from
re-trying them next month.

Two traps at this stage:
- **Benchmark theater**: measuring warm cache against cold, different data sizes,
  or debug vs. release settings. Keep conditions identical between A and B.
- **Improvement without significance**: a 3% change between single noisy runs is
  noise. Repeat runs; trust medians.

## Knowing when to stop

Stop when the target is met. Then re-read the final code as a reviewer (see
`code-quality.md`): every remaining trick must either pay for itself measurably or
be reverted to the clear version. Leave behind a note: baseline, final numbers, what
worked, what didn't, and where the *next* bottleneck is if more speed is ever needed
(there's always a next bottleneck; you're choosing to stop, not finishing).

## PLC/real-time note

On cyclic real-time targets (TwinCAT), the budget is the cycle: worst-case, not
average, is what matters. Don't put unbounded loops or heavy scans in one cycle —
spread work across cycles with a state machine, or move it to a slower task. A
1000-iteration loop that's fine on average and blows the cycle time once a day is
a fault, not a performance issue. Measure with the task monitor's cycle-time
statistics, and watch the max.
