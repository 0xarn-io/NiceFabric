# Worked example: the core loop on a real bug

A narrated debugging session, showing the habits from SKILL.md and
`debugging.md` operating together. The bug is ordinary on purpose — the *method*
is the content, not the puzzle.

**The report:** "Our nightly export script sometimes produces an empty CSV. Maybe
twice a month. Re-running it by hand in the morning always works fine."

## Orient (not: start reading code)

Restate what's actually known: *sometimes* empty (not always → not plainly broken),
*nightly* (scheduled context differs from morning re-runs), *re-run works* (state
or time dependent, not input-file corruption). Already the shape of the fault
space is visible: something about the conditions at 2 a.m. differs from 9 a.m.

Candidate hypotheses, written down: (1) a race with the upstream job that produces
the data — export runs before data lands; (2) a time-window query bug at day
boundaries; (3) environment differences between cron and shell (paths, locale,
credentials); (4) intermittent upstream failure swallowed by error handling.

## Find the load-bearing unknown

Which fact, if known, best splits this space? **What did the failing runs actually
see** — no data, or data it then discarded? Nobody knows, because (checking the
code — reconnaissance, not memory) the script logs only "Export complete." A
surprise found on the way: the fetch is wrapped in `try/except Exception: rows=[]`.
Failure and "no data" are indistinguishable by design. That's hypothesis 4 suddenly
much stronger — and a failure smell (swallowed exception) worth fixing regardless.

## Act small

Cheapest discriminating action: not a fix — **instrumentation**. Log row count,
query window boundaries, and re-raise-worthy exception details. Also grab the two
facts already available: the cron schedule (02:00) and the upstream job's history
(finishes 01:40–02:20, *aha*). That took one look at a scheduler page and strongly
supports hypothesis 1 — but "strongly supports" is not "verified," and 4 is still
live. Note both in the log; wait for the next occurrence *or* reproduce it: run
the export deliberately while the upstream job is still writing. It reproduces:
zero rows, no error — the upstream table is empty *mid-reload* because the job
truncates then reloads. Root cause mechanism, stated in one sentence: *the export
reads a table that is empty for ~15 minutes during reload, and treats empty as
success.* Both 1 and 4 were true, coupled — the race creates the condition, the
swallowed failure makes it silent.

## The two-failures rule, dodged

Notice what didn't happen: no "move cron to 03:00 and hope" (a fix-shaped bet —
the upstream job's end time drifts; it would fail again in a month and teach
nothing). The temptation to patch before mechanism-in-one-sentence is the thing
the loop exists to block.

## Fix at the mechanism, then prove it

Three changes, each aimed at the mechanism, not the symptom: the export waits on
the upstream job's completion marker instead of a clock time; zero rows is now an
explicit failure (empty output was *never* valid for this report — checked with
the owner rather than assumed); exceptions propagate loudly. Verification: re-run
the deliberate mid-reload reproduction — it now blocks, then succeeds; force an
upstream failure — export fails loudly instead of writing an empty file. The fix
is shown load-bearing, not assumed.

## Siblings and handoff

Grep for the pattern: two other scripts use the same `except Exception: rows=[]`
idiom — same latent bug, reported for fixing. Handoff states what changed, what
was *verified by execution* (both reproductions), what's still assumed (the
completion marker's reliability — flagged), and the regression test added (export
against an empty table must fail).

## What made this work

Nothing clever. Hypotheses written before evidence gathering; the load-bearing
unknown attacked with the cheapest discriminating observation; a surprise
(swallowed exception) investigated instead of stepped over; no fix before the
mechanism fit in one sentence; the fix proven against the reproduction; the bug's
siblings hunted. That sequence — not intuition — is the skill.
