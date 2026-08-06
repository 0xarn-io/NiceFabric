---
name: super-code
description: >-
  Self-contained bundle of the "superpowers" software-engineering skills plus a router that
  walks a coding task through the right phase. Use when the user asks for a disciplined,
  end-to-end coding workflow, or explicitly invokes "super-code" / "superpowers" — e.g. "use
  super-code on this", "run the full workflow", "do this properly with brainstorming, planning,
  TDD and review". Covers brainstorming, writing and executing plans, subagent-driven and
  parallel development, test-driven development, systematic debugging, git worktrees, requesting
  and receiving code review, verification before completion, and finishing a branch. This is NOT
  an always-on skill — invoke it when the structured workflow is wanted, then follow the phase it
  points you to.
---

# Super Code

A single entry point for disciplined software work. It bundles the fourteen **superpowers**
skills under `references/` and routes a task to the right one for the phase you're in, so the
work goes: understand → plan → build with tests → verify → review → integrate, instead of
jumping straight to code.

Each bundled skill lives in its own folder at `references/<skill-name>/`, and its main file is
`references/<skill-name>/<skill-name>.md` (some folders also hold sub-files and `scripts/`). This
router does not duplicate their content — it points you to the one you need and hands off.

## How to operate

1. **Locate the phase.** Read *Which phase am I in?* below and pick the matching skill.
2. **Open its file.** Read `references/<skill-name>/<skill-name>.md` in full before acting — do not
   work from memory of what the skill "probably" says. If it names a sub-file (e.g.
   `root-cause-tracing.md`), that file sits in the same folder; read it when the skill tells you to.
3. **Announce and follow.** State `Using <skill-name> to <purpose>` and follow the skill exactly.
   If it has a checklist, create one todo per item so nothing is skipped.
4. **Move to the next phase** when the current skill's exit conditions are met, and repeat.

A task usually passes through several skills. Don't try to hold the whole lifecycle in your head —
re-read this router whenever you finish a phase and ask which skill owns the next one.

### Path convention (important)

These skills are bundled as reference files, not installed as separate skills, so each one's entry
file was renamed from `SKILL.md` to `<skill-name>.md` (that's what lets the whole bundle install as
a single skill). The cross-references *inside* the bundled files still use skill-name syntax like
`superpowers:brainstorming` or "invoke the systematic-debugging skill". Treat every such reference
as a pointer to **`references/<that-name>/<that-name>.md`** in this bundle, and read it by path. Do
not go looking for a separately installed skill of that name.

The bundled `references/using-superpowers/using-superpowers.md` is the collection's original
always-on dispatcher. Here, *this* router plays that role, so read it only for background — you
don't need to follow its "invoke a skill before every response" rule.

## Which phase am I in?

| Situation right now | Read this skill |
|---|---|
| About to build a feature / component / behavior change, and the intent isn't fully pinned down yet | `references/brainstorming/brainstorming.md` |
| Need an isolated workspace so this work doesn't collide with the current tree | `references/using-git-worktrees/using-git-worktrees.md` |
| Have a spec or clear requirements for a multi-step task, before touching code | `references/writing-plans/writing-plans.md` |
| Have a written plan and are executing it in a fresh session with review checkpoints | `references/executing-plans/executing-plans.md` |
| Executing plan tasks that are independent, in the current session | `references/subagent-driven-development/subagent-driven-development.md` |
| Facing 2+ independent tasks with no shared state or ordering between them | `references/dispatching-parallel-agents/dispatching-parallel-agents.md` |
| Implementing any feature or bugfix, before writing the implementation | `references/test-driven-development/test-driven-development.md` |
| Hit a bug, test failure, or any unexpected behavior, before proposing a fix | `references/systematic-debugging/systematic-debugging.md` |
| About to claim something is done / fixed / passing, before committing or opening a PR | `references/verification-before-completion/verification-before-completion.md` |
| Work is complete and you want it reviewed before merging | `references/requesting-code-review/requesting-code-review.md` |
| You've *received* review feedback and are about to act on it | `references/receiving-code-review/receiving-code-review.md` |
| Implementation is done and tests pass — need to decide merge vs PR vs cleanup | `references/finishing-a-development-branch/finishing-a-development-branch.md` |
| Creating, editing, or verifying a skill itself | `references/writing-skills/writing-skills.md` |

## The usual flow

For a typical feature, the phases chain like this (skip or reorder as the task demands):

**brainstorming** → **using-git-worktrees** → **writing-plans** → execute with
**subagent-driven-development** or **executing-plans** (and **dispatching-parallel-agents** for
independent chunks), building each piece under **test-driven-development** and dropping into
**systematic-debugging** whenever something breaks → **verification-before-completion** →
**requesting-code-review** ↔ **receiving-code-review** → **finishing-a-development-branch**.

`writing-skills` is orthogonal — reach for it when the task is authoring a skill rather than
shipping product code.

## Priority when several fit

Process skills come first: they set *how* you approach the work, and implementation skills then
carry it out. So "let's build X" starts at **brainstorming**, and "fix this bug" starts at
**systematic-debugging** — not at code. Within a phase, follow the chosen skill's own rules over
any general instinct.

User instructions (a direct request, `CLAUDE.md`, `AGENTS.md`, etc.) outrank these skills, which in
turn outrank default behavior. Only skip a skill's workflow when the user has told you to.

## Index of bundled skills

| Skill | What it's for | Main file |
|---|---|---|
| brainstorming | Explore intent, requirements, and design before any creative work | `references/brainstorming/brainstorming.md` |
| writing-plans | Turn a spec into a concrete multi-step implementation plan | `references/writing-plans/writing-plans.md` |
| executing-plans | Execute a written plan in a separate session with review checkpoints | `references/executing-plans/executing-plans.md` |
| subagent-driven-development | Execute independent plan tasks within the current session | `references/subagent-driven-development/subagent-driven-development.md` |
| dispatching-parallel-agents | Split 2+ independent, shared-state-free tasks across agents | `references/dispatching-parallel-agents/dispatching-parallel-agents.md` |
| test-driven-development | Write tests before implementation for any feature or bugfix | `references/test-driven-development/test-driven-development.md` |
| systematic-debugging | Diagnose bugs and failures to root cause before fixing | `references/systematic-debugging/systematic-debugging.md` |
| using-git-worktrees | Create an isolated workspace for feature work | `references/using-git-worktrees/using-git-worktrees.md` |
| requesting-code-review | Get work reviewed before merging | `references/requesting-code-review/requesting-code-review.md` |
| receiving-code-review | Handle review feedback with technical rigor, not blind agreement | `references/receiving-code-review/receiving-code-review.md` |
| verification-before-completion | Prove work is done with evidence before claiming success | `references/verification-before-completion/verification-before-completion.md` |
| finishing-a-development-branch | Decide how to integrate finished work (merge / PR / cleanup) | `references/finishing-a-development-branch/finishing-a-development-branch.md` |
| using-superpowers | The collection's original always-on dispatcher — background only | `references/using-superpowers/using-superpowers.md` |
| writing-skills | Create, edit, and verify skills | `references/writing-skills/writing-skills.md` |
