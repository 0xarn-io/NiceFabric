# Long tasks: staying coherent across many steps

Long tasks fail differently than short ones. The enemy isn't difficulty — it's
drift: requirements silently dropped, dead ends re-entered, settled decisions
re-litigated, and a final result that answers a question nobody asked. The defenses
are all forms of externalized memory and periodic re-orientation.

## The working log

For anything beyond a handful of steps, keep a live scratch file (or structured
todo list) with exactly these sections — terse, updated as you go, not curated
after the fact:

```
GOAL: the user's actual request, in their words (paste it; don't paraphrase)
STATE: what exists right now and what's verified vs. assumed
DECISIONS: choice made → why → alternative rejected
DEAD ENDS: what was tried, why it failed (so it's never tried twice)
NEXT: the single next verifiable step
```

Write it for a competent stranger who might take over mid-task — because after
enough context, future-you *is* that stranger. The DECISIONS and DEAD ENDS sections
are the ones that pay: they're exactly what's forgotten first and re-derived most
expensively.

## Re-orientation cadence

- **Re-read the GOAL (the user's literal words) at every phase boundary** and
  before declaring anything done. Drift never announces itself; it's only visible
  by diffing your current activity against the original request. Reluctance to
  re-read it is itself the signal that you drifted.
- **Reconcile plan vs. reality after every surprise.** When something didn't work
  the way the plan assumed, the plan is now partly fiction. Update it explicitly
  rather than patching around it mentally.
- **Periodically ask the zoom-out question**: "if I finished the current subtask
  perfectly, how much closer is the user's goal?" If the honest answer is "not
  much," the current subtask is a rabbit hole (see timeboxing in SKILL.md).

## Checkpoints and reversibility

- Commit or snapshot at every known-good state, with messages that say *why* (the
  what is in the diff). These are save points for both code and understanding.
- Before any destructive or sweeping operation (mass rename, regenerate, delete,
  migration), take the checkpoint *first* and note the restore procedure. Undo
  plans made after the accident are archaeology, not engineering.
- For multi-session work, end every session by updating STATE and NEXT — the
  five-minute handoff note saves the first thirty minutes of the next session.

## Batching and momentum

- Group similar small tasks (same file, same kind of edit, same tool) — context
  switches are expensive even for you.
- But never batch *verification*: don't make ten changes then test once. The whole
  value of small steps is knowing which change broke things.
- When a subtask can proceed independently (a long run, an isolated investigation),
  consider delegating it in parallel — but only when truly independent; parallel
  work on entangled state produces merge archaeology.

## Finishing a long task

Before handoff, do a deliberate closing pass:

1. Diff-review everything produced, with fresh adversarial eyes.
2. Walk the GOAL text line by line: each explicit and implicit request → where is
   it satisfied → how was it verified?
3. Write the verification map: what changed, how each piece was checked (executed /
   inspected / reasoned), what remains risky or assumed.
4. Clean the workspace: scaffolding removed, temp files gone, the log's DECISIONS
   section distilled into whatever documentation survives the task.
