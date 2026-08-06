# Navigating unfamiliar code: build the model before touching anything

The goal is never to understand the whole codebase. It's to build a *sufficient
working model of the slice you'll change* — and to know where that slice's
boundaries are. Reading everything is procrastination wearing diligence's clothes.

## First ten minutes: the skeleton

- Layout scan: top-level directories, the build/config files (`pyproject.toml`,
  `package.json`, `.plcproj`), the README if honest. You're asking: what kind of
  animal is this, what are its layers, where does execution start?
- Find the entry points: `main`, route registrations, task/cycle configuration,
  CLI definitions. Every behavior hangs off one of them.
- Read one representative test file, if tests exist. Tests are the only
  documentation that can't drift: they state what the authors *meant* the code
  to do, in executable form.

## The two tracing moves

Nearly all code comprehension is one of these, applied repeatedly:

**Trace backwards from the observable.** Take a user-visible string — the error
message, the label, the log line — and grep for it. That lands you at the scene.
Then walk callers upward until you understand how execution arrives there. This is
the fastest route from "symptom" to "relevant code" in any codebase, any language.

**Trace forward with one concrete value.** Pick a single real datum (one request,
one row, one sensor signal) and follow it end to end: where it enters, every
transformation, where it's stored, where it exits. Following *data* beats reading
*files* because it enforces the actual execution order and skips everything
irrelevant. Where the data's shape changes is where the interesting decisions live.

While tracing, keep a scratch map: `file:function — role — questions`. The map is
your externalized model; the questions column tells you when you're done reading
(when the load-bearing ones are answered — not all of them).

## Reading the culture, not just the code

Before writing anything, find the *nearest neighbor*: the existing feature most
similar to what you're adding, and read it as a template. How does this codebase
do validation, errors, logging, tests, naming? Local convention beats your
preference — a "better" pattern used once is worse than a mediocre pattern used
consistently, because every future reader must now learn both. If conventions
conflict (older and newer styles coexisting), imitate the one in the code nearest
to where you're working, or the one the tests favor.

Watch for the codebase's *load-bearing idioms*: a base class everything inherits,
a decorator on every handler, a registry things must be added to. Missing one of
these ("it compiles but the new command never appears") is the classic
unfamiliar-codebase failure — the nearest-neighbor comparison catches it.

## Verify your model by prediction

A model you haven't tested is a guess. Before relying on your understanding, make
one falsifiable prediction and check it: "if I'm right, changing this string will
alter that output" / "this log line will fire on startup" / "this test covers that
branch, so breaking it fails the suite." One confirmed prediction is worth an hour
of additional reading — and a failed one just saved you from editing under a false
model, which is the expensive way to find out.

## Editing rules in someone else's house

- Smallest change consistent with the goal and local conventions. Resist the
  drive-by refactor of code you half-understand (note it for later instead).
- Chesterton's fence: code that looks pointless may guard an edge case. Check
  blame/history/tests before deleting weirdness; delete confidently only when you
  can explain why it existed.
- Match the blast radius to your model quality: high-confidence slice → edit
  freely; foggy area → characterization tests first (see `testing.md`), then edit.
- When your change fights the existing structure, stop and re-read — either
  you found real design debt (raise it explicitly) or your model is wrong (more
  often, this one).
