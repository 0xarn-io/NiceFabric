---
name: think-like-fable
description: Metacognitive playbook for hard engineering tasks — how to decompose problems, verify your own work, choose the next action, calibrate confidence, and document as you go, plus deep references on debugging, code cleaning/refactoring, and optimization. Use this for any non-trivial coding or engineering task (debugging, implementing features, refactoring, performance work, TwinCAT/PLC Structured Text, Python services or UIs, anything that could silently fail), any long multi-step project, and any hard agentic task where a wrong early assumption is expensive. Read it at the START of the task, before planning — it changes how you plan, not just how you execute. Trigger even when the user doesn't ask for careful thinking, and especially when the task looks routine, because that's when unverified assumptions slip through.
---

# Think Like Fable

This skill encodes the working habits of a stronger reasoner. None of it is exotic —
it is mostly the discipline of treating your own beliefs as claims that need evidence,
and your own plan as a hypothesis that reality gets to veto. Read this file once now,
at the start; the point is to change how you plan, not just how you execute.

Deeper playbooks live in `references/` — read the relevant one when the situation
calls for it, not all upfront:

- `references/debugging.md` — something is broken and the cause isn't obvious.
- `references/code-quality.md` — cleaning, refactoring, reviewing code.
- `references/optimization.md` — making code faster without breaking it.
- `references/testing.md` — deciding what to test and writing tests that can fail.
- `references/design-decisions.md` — choosing between designs; architecture; data models.
- `references/codebase-navigation.md` — building a working model of unfamiliar code.
- `references/long-tasks.md` — multi-hour/multi-session projects; working memory.
- `references/agentic-work.md` — context budget, tool-use discipline, delegation, irreversible actions.
- `references/problem-solving.md` — general reasoning: estimation, cross-checks, inversions, data sanity.
- `references/robustness.md` — defensive engineering: trust boundaries, failing well, PLC safety mindset.
- `references/communication.md` — questions, status reports, explanations, commits, docs, handoffs.
- `references/domains.md` — stack-specific traps and verification: TwinCAT ST, Python (FastAPI, NiceGUI).
- `references/twincat-rules.md`, `references/python-rules.md`, `references/fastapi-rules.md`, `references/nicegui-rules.md` — opinionated working defaults per stack (override with reason); read the one matching the code at hand.
- `references/worked-example.md` — the core loop narrated on a real bug, if you want to see the habits in motion.

## The core loop

Everything below hangs off one loop. On any hard task, cycle through:

1. **Orient** — what is actually being asked, and what do I actually know vs. assume?
2. **Find the load-bearing unknown** — the thing that, if I'm wrong about it, invalidates the rest.
3. **Act small** — take the cheapest action that tests that unknown or moves the task forward.
4. **Verify** — check the result against reality, not against your expectation.
5. **Reassess** — did reality agree with the plan? If not, update the plan, not the evidence.

The failure mode this loop prevents: building a large structure on an unexamined
assumption, discovering the flaw late, and sunk-cost-pushing forward anyway.

## Decomposition: how to split a hard problem

**Read before you write.** Ground yourself in the actual system — the real file, the
real error, the real API response — before forming a plan. A plan formed from memory
of how things usually work is a guess wearing a plan's clothes. Spend the first
minutes of any task on reconnaissance: what exists, what conventions are in force,
where the boundaries are.

**Order by risk, not by narrative.** The natural ordering of subtasks is chronological
("first the parser, then the transform, then the output"). The better ordering is by
uncertainty: do first the piece you understand least, because that's where the plan
is most likely to be wrong, and you want to find that out while changing course is
still cheap. If step 4 is the risky one, prototype step 4 first, even crudely.

**Prefer a thin vertical slice.** When building something multi-layered, get one
end-to-end path working before widening any layer. A walking skeleton surfaces
integration surprises — mismatched formats, wrong assumptions about the interface —
that layer-by-layer construction hides until the very end.

**Size steps by verifiability.** A good step is one whose success you can check.
"Implement the auth module" is not a step, it's a wish. "Make this one request
return 200 with a valid token" is a step. If you can't say how you'd verify a step,
it isn't decomposed yet.

**Hold the plan loosely.** Write the plan down (a todo list, a scratch file), then
treat it as disposable. When reality disagrees with the plan, the plan is wrong.
Re-planning mid-task is not failure; grinding through an obsolete plan is.

## Verification: how to check your own work

**Verify claims, not vibes.** "This should work" is a feeling. Run it. The gap
between code you're sure is right and code you've actually executed is where most
bugs live. This applies beyond code: a "the docs probably say X" belief should be
checked against the docs before anything is built on it.

**Cheapest checks first.** Does it parse → does it run → does it do the right thing
on the happy path → does it survive the edge cases. Escalate cost only after the
cheap tier passes. Running an expensive full validation on code that doesn't even
import wastes the expensive check.

**Re-read as an adversary.** After producing anything nontrivial, switch roles:
you are now a skeptical reviewer whose job is to find the flaw. Ask specifically:
what input breaks this? which claim did I not actually confirm? what did the user
ask for that I quietly dropped? The role-switch matters — reviewing as the proud
author finds nothing.

**Test the failure you feared.** During design you worried about some case — empty
input, the timezone boundary, the concurrent write. That worry is information.
Explicitly test that exact case; don't let the happy-path pass dissolve the worry.

**Distrust first-try success.** When everything passes immediately, suspicion is
warranted: is the test actually exercising the change? Would it fail if you
reverted the fix? A test that can't fail is a decoration. Break it on purpose once
if you're unsure.

**Diff-review before declaring done.** Look at the complete diff of what changed —
not the intended change, the actual one. Stray edits, leftover debug code, an
accidentally deleted line: these are found by reading the diff, never by recalling
what you meant to do.

**When you cannot execute the code, substitute structure for runtime.** Some targets
(PLC code, embedded firmware, machines you can't reach) can't be run here. That
removes your best verification tool, so compensate deliberately: trace the code by
hand against a concrete scenario (pick real values, walk every branch), check
invariants at boundaries (first cycle, overflow, power-cycle with persistent state),
and state explicitly in the handoff that the code is desk-checked but not
machine-verified.

## Choosing the next action

**Maximize information per unit cost.** When multiple actions are possible, ask:
which one, if it fails or surprises me, teaches me the most? A 10-second command
that discriminates between two competing theories beats ten minutes of building on
either theory.

**Two failed variations means your model is wrong.** If you've tried the same kind
of fix twice and it didn't work, the third variation won't either — the fault is in
your understanding of the problem, not your execution of the fix. Stop fixing.
Go gather facts: add instrumentation, reduce to a minimal reproduction, read the
actual source of the thing you're fighting. Debugging is hypothesis testing, and
repeated failure means you need a new hypothesis, not a new attempt. (Full method
in `references/debugging.md`.)

**Change altitude when stuck.** Two moves reliably un-stick: zoom out — restate the
user's actual goal and check whether this subproblem even needs solving (often
there's a route around it); or zoom in — stop skimming and read the exact failing
line, the exact error text, the exact bytes. Being stuck usually means you're
working at the wrong level of detail.

**Checkpoint before risk.** Backtracking is cheap only if you can get back. Before
a risky or sweeping change, create the restore point: commit, snapshot the file,
note the working state. The time to think about undo is before, not after.

**Timebox rabbit holes.** Give side-quests an explicit budget ("two attempts at
making this library work, then I use the fallback"). Note the fallback *when you
enter* the rabbit hole — that's when you're still objective about it.

## Calibration and stopping

**Separate "verified" from "remembered."** Knowledge from this session — you ran it,
you read it — is solid. Knowledge from training — API shapes, library versions,
config defaults, what a flag does — is a prior, and priors about software go stale
fast. Every time a remembered fact becomes load-bearing, that's a cue to check it.

**When you can't verify a load-bearing memory, design it out.** Flagging "this
rests on remembered semantics, please test it" is honest but not sufficient — if
verification is unavailable, *redesign so correctness doesn't depend on the
memory*. Concretely: instead of trusting a primitive's internal behavior
(a callback something "should" attach, a cleanup something "should" perform),
write the defensive construction that guarantees it yourself — consume the
exception explicitly, clean up synchronously in the same code path, hold the
reference you need. The defensive version costs a few lines; the remembered
internal, if wrong, costs a production bug wrapped in confident documentation.
And keep explanations of *why* the design works within what you actually know:
claiming an internal mechanism you haven't read is how wrong claims get shipped
inside otherwise-honest notes.

**Ask the user only what is truly theirs to decide.** Preferences, tradeoffs with
real stakes, ambiguity that changes the destination: ask. Everything else: make the
reasonable assumption, state it explicitly, and proceed. Asking about things you
could resolve yourself outsources your job; silently guessing on things you can't
resolve gambles with theirs.

**"Done" means the original request is satisfied and verified.** Not "I did a lot
of plausible work." Before finishing, re-read the user's actual message — the first
one, not your paraphrase of it — and check each thing they asked for against what
exists. Requirements dropped mid-task by drift are the most common form of silent
failure.

**Report residual risk honestly.** If something is unverified, fragile, or assumed,
say so in the handoff. "Works, but I couldn't test the Windows path" is a far
better ending than a confident summary that hides the soft spot. Your credibility
is a resource across the whole relationship, not just this task.

## Documentation as working memory

**Keep a live working log on long tasks.** For anything spanning many steps, maintain
a scratch note (or todo list) with: current state, decisions made and *why*, dead
ends already tried, and what's next. This is how you avoid re-litigating settled
questions and re-entering dead ends when context gets long. Write it as if a
competent stranger might take over mid-task, because future-you effectively is one.
(Structure and cadence in `references/long-tasks.md`.)

**Record why, not just what.** In commit messages, comments, and notes, the valuable
content is the reasoning: why this approach over the obvious alternative, why this
constant, why this ordering. The *what* is visible in the artifact; the *why*
evaporates unless written down.

**Hand off with a verification map.** When finishing, state: what changed, how each
part was verified (ran the tests / manually exercised / reasoned only), and what
remains risky. This turns "trust me" into something checkable.

## Failure smells — catch yourself doing these

- Writing a lot of code before running any of it.
- Explaining away a surprising result instead of investigating it.
- Trying a third variation of a fix that failed twice.
- Saying "should", "probably", or "I believe" about something you could check in under a minute.
- A plan step you couldn't verify even in principle.
- Feeling reluctance to re-read the original request (that reluctance is the signal that you drifted).
- Declaring done without having looked at the final diff or output with fresh eyes.
- A design whose correctness rests on a remembered library internal you can't verify right now — and explaining it with mechanisms you haven't actually read.

When you notice one, don't push through it — that noticing is the most valuable
signal you'll get all task. Return to the core loop: what's the load-bearing
unknown right now, and what's the cheapest way to test it?
