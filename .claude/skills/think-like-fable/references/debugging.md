# Debugging: hypothesis-driven fault isolation

Debugging is not "trying fixes." It is an experimental science: form a hypothesis
about the cause, design the cheapest experiment that could falsify it, run it,
update. Fixes come at the end, once the cause is understood. A fix applied before
the cause is understood is a bet, and unexplained bets that "work" are the most
dangerous outcome — the bug is usually still there, wearing a different shirt.

## Phase 0 — Reproduce before anything else

You cannot debug what you cannot reproduce. First goal: a minimal, deterministic
reproduction — smallest input, fewest steps, no unrelated machinery.

- Shrink aggressively: cut the input in half repeatedly; delete code paths not
  needed to trigger it. Every element removed halves the search space.
- If it only reproduces sometimes, that intermittency is itself evidence: suspect
  timing, shared state, uninitialized values, ordering (dict/set iteration,
  filesystem listing), external state (clock, network, other clients).
- If you truly can't reproduce it, don't guess-fix. Instrument the real environment
  (logging around the suspected region) and wait for the next occurrence with
  better eyes.

## Phase 1 — Read the actual evidence

- **Read the whole error, actually.** Not the shape of it — the words. The exact
  exception type, the exact line, the values in the message. Most "mysterious" bugs
  are named plainly in text that got skimmed.
- **First error, not last.** In a cascade, later errors are debris from the first.
  Scroll up. Fix the first, re-run, reassess.
- **Symptom site ≠ cause site.** The crash is where the bad value was *used*, not
  where it was *created*. Trace the bad value backwards: what produced it, what
  produced that. Ask "what is the earliest moment something was already wrong?"
- **Look at real data, not imagined data.** Print the actual value, its type, its
  length, its bytes. `repr()` over `str()` — invisible characters, wrong types
  masquerading (string "3" vs int 3), and trailing whitespace live in the gap.

## Phase 2 — Hypothesize and discriminate

Maintain (in your working notes) an explicit list of candidate causes. Then choose
experiments that *discriminate* between them — the best experiment is the one whose
outcome differs depending on which hypothesis is true.

- Prefer experiments in this cost order: read the code path carefully → print/log a
  value → write a 5-line reproduction script → bisect → step through.
- **Bisect relentlessly.** It's the highest-leverage move in debugging. Bisect
  history (`git bisect` — works even with a rough "good" commit), bisect the code
  (disable half the pipeline; which half still shows the bug?), bisect the input
  (which half of the file triggers it?). Log₂ of anything is small.
- **One variable at a time.** Change one thing, observe, revert if it taught you
  nothing. If you change three things and it works, you've learned almost nothing
  and shipped two superstitions.
- **The bug is almost always in your code.** The compiler, the standard library,
  the framework are wrong occasionally, your new code is wrong constantly. Exhaust
  your own code first. When evidence really does point at a dependency: check the
  installed version against your assumption, then search its issue tracker —
  if it's real, someone has usually hit it first.

## Phase 3 — Understand, then fix

Before writing the fix, you should be able to answer, in one or two sentences:
*why did it break, and why does the fix address that mechanism?* If you can't,
you're at Phase 2 still, even if a candidate patch "makes the symptom go away."

After the fix:

- **Prove the fix is load-bearing.** Re-run the reproduction: fails before, passes
  after. If you can, revert the fix once and watch it fail — a fix that can't be
  shown to matter probably doesn't.
- **Add the regression test** — the minimal reproduction *is* the test; encode it.
- **Hunt the siblings.** A bug is rarely an only child. Grep for the same pattern
  elsewhere: the same copy-pasted block, the same misused API, the same off-by-one
  idiom. Fixing the class of bug beats fixing the instance.
- **Remove the scaffolding.** Debug prints, commented-out experiments, temporary
  hacks — check the final diff for them.

## When it fights back

- **Two failed fix attempts → stop fixing.** Your model of the problem is wrong.
  Return to Phase 1/2: gather facts, re-derive the mechanism. Track your attempts
  in the working log so you notice this threshold.
- **Heisenbugs** (vanish under observation): the observation changes timing or
  state. Suspect race conditions, buffering (output you added may be flushed
  differently), or reading uninitialized memory/state.
- **"That's impossible" moments**: the impossible doesn't happen; one of your
  certainties is false. List everything you're *sure* of about the failing path and
  verify them one by one — the bug lives inside one of those certainties. Classic
  culprits: you're editing a different file than the one running, a stale build or
  cache, the wrong environment/interpreter, the service didn't actually restart.
- **Explaining away is the cardinal sin.** A surprising observation that you
  narrate into plausibility ("probably just a timing thing") is a lead abandoned.
  Surprise = your model is wrong somewhere = exactly where to dig.

## Debug log discipline

For any bug that survives past 15 minutes, keep a running note: hypotheses
considered, experiment run, result, verdict. It prevents circling (re-trying a
disproven idea an hour later), makes the "two failures" threshold visible, and
becomes the handoff/postmortem for free.
