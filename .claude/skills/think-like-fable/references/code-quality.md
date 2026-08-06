# Cleaning and refactoring: changing structure without changing behavior

Refactoring has one iron rule: behavior stays identical while structure improves.
Everything in this file serves that rule, because a "cleanup" that changes behavior
is a bug with good intentions.

## Before touching anything

- **Establish the safety net first.** What proves behavior is preserved? Existing
  tests (run them now, record what passes — a pre-existing failure discovered later
  will otherwise be blamed on you), or characterization tests you write against
  current behavior (capture what the code *does*, even where that's ugly), or at
  minimum a recorded input/output snapshot you can re-run.
- **Read until you can explain it.** Refactoring code you don't understand converts
  hidden behavior into deleted behavior. If a block resists understanding, that
  block is where the risk is — trace it with concrete values before restructuring.
  Beware Chesterton's fence: weird code sometimes guards a real edge case. Check
  history/comments/blame before deleting weirdness; if it's truly dead, delete it
  fully (don't comment it out — version control remembers).
- **Agree on scope.** "Clean this up" has ambiguity the user should resolve only if
  it changes the destination: cosmetic pass vs. structural redesign. Default to
  improving what's there, in place, in the codebase's existing style — not
  rewriting it into your favorite style. Consistency with the surrounding code
  beats your aesthetic preference.

## The mechanics: small, reversible, verified steps

Work in the smallest steps that keep the code working. After each step, re-run the
safety net. The discipline feels slow and is actually fast, because you never spend
an hour finding which of forty changes broke things.

- **Never mix refactoring and behavior change** in one step or one commit. When you
  spot a bug mid-refactor (you will), note it, finish the refactor step, then fix
  the bug as its own change with its own test. Mixed diffs are unreviewable and
  unbisectable.
- Prefer sequences of mechanical moves: rename → run tests → extract function →
  run tests → inline variable → run tests. Each step trivially correct, chain
  arbitrarily powerful.
- Commit (or snapshot) at every green state. That's your undo ladder.

## What "cleaner" actually means — in priority order

1. **Correct names.** The single highest-leverage cleanup. A name should say what
   the thing *is for*, so the reader doesn't have to open it. If you can't name a
   function honestly ("process_data_and_send_email_and_update_cache"), the name has
   diagnosed a design problem: it does too much. Struggling to name = wrong
   abstraction boundary.
2. **Dead code removed.** Unused functions, unreachable branches, commented-out
   blocks, imports nobody uses, flags that are always false. Dead code is not
   harmless — every reader pays to rule it out.
3. **Shallow nesting.** Guard clauses and early returns beat pyramid-of-doom
   nesting. Handle the error/edge case and return; keep the happy path at
   indentation level one.
4. **Duplication merged — but only real duplication.** Apply the rule of three:
   two similar blocks may be coincidence; three are a pattern worth extracting.
   And only merge code that is the same *because it must be* (same reason to
   change). Code that is accidentally similar today will diverge tomorrow, and a
   wrong abstraction is more expensive than duplication — it forces every future
   change through a lie.
5. **Functions that do one thing**, at one level of abstraction, with few
   parameters. Long parameter lists and boolean flags ("do_it(data, True, False)")
   signal a function that is several functions in a trench coat.
6. **Honest error handling.** No swallowed exceptions (`except: pass` is a crime
   scene), no error codes silently ignored, failures loud and early. Catch narrow
   exception types, at the level that can actually do something about them.
7. **Comments that explain why.** Delete comments that restate the code (they rot
   into lies); keep and add comments that carry non-obvious *reasoning*: why not
   the obvious approach, what invariant holds, what external constraint forced this.

## Reviewing (your own or others' code)

Review the diff, not the intention. Read it twice with different questions:

- Pass 1, correctness: what input breaks this? which edge case is unhandled? does
  the error path release/close/unlock what it acquired? off-by-ones at boundaries?
- Pass 2, design: will the next person understand it? is anything named
  misleadingly? did the change leak abstraction across a boundary? is there a test
  that would catch the most likely future regression?

Two ranked severities in feedback: things that are wrong (must fix) vs. things you'd
prefer (say so, once, without blocking). Don't dress taste up as correctness.

## Done means

The safety net is green, the diff contains only what the scope agreed to, the code
reads better than it did (ask: would a newcomer understand this faster than the
original?), and nothing behaves differently — verified, not asserted.
