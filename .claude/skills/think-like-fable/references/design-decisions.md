# Design and architecture decisions: choosing what to build

Design quality is mostly decided by two questions asked early: *what's the simplest
thing that satisfies the actual requirement?* and *which of these decisions will be
expensive to reverse?* Almost everything else is negotiable later; these two set
the cost curve.

## Simplicity has to be defended

The default pressure in design is always toward more: more flexibility, more
abstraction, more configurability "while we're here." Resist by making complexity
buy its way in — each layer, parameter, or abstraction must answer for a
requirement that exists *today*. Speculative generality (the plugin system with
one plugin, the config option nobody sets) is the most common self-inflicted
architecture wound: you pay its comprehension tax on every read, forever, for
flexibility that usually turns out to be the *wrong* flexibility when the future
actually arrives. YAGNI, and the rule of three: don't build the abstraction until
the third concrete case proves its shape.

Corollary — **design for deletion.** Optimize for how easily a piece can be ripped
out and replaced, not for how gracefully it can be extended. Replaceable modules
with narrow interfaces age better than extensible frameworks, because prediction
fails but decoupling doesn't.

## Sort decisions by reversibility

Most decisions are two-way doors: pick reasonably, move on, change it later for
cheap. A few are one-way doors, and they deserve real deliberation:

- data schemas and anything persisted (migrations are where optimism dies),
- public APIs and wire formats (someone else now depends on your mistake),
- choice of platform/framework/language for a component,
- names and concepts exposed to users (they colonize everything downstream).

Spend your design effort proportionally. Agonizing over an internal helper's
structure while waving a schema through is inverted priorities — the helper can be
refactored next week; the schema will outlive the team's memory of why.

## Get the data model right first

Show me your data structures and the code writes itself; get them wrong and no
cleverness downstream fully compensates. Before writing logic, write down the core
entities, their relationships, their invariants — and try two or three concrete
scenarios against the model on paper, especially the awkward ones (the order with
zero lines, the sensor that reports twice, the user in two groups). Where the
model creaks on paper, it will break in production.

Make illegal states unrepresentable when it's cheap: an enum instead of two
booleans that can contradict, a type that can't hold the invalid combination,
required fields actually required. Every invariant enforced by structure is a
class of bugs that no longer needs testing, reviewing, or debugging.

## Boundaries: deep modules, separated I/O

- Prefer **deep modules**: small interface, substantial implementation behind it.
  The interface is the cost (everyone pays to learn it); the implementation is the
  value. Many shallow pass-through layers invert this — maximum interface,
  minimum value.
- **Separate logic from I/O** (functional core, imperative shell): pure
  decision-making inside, side effects (network, disk, PLC I/O, UI) pushed to a
  thin outer layer. This single habit buys testability (the core tests without
  mocks), reusability, and comprehension — most "hard to test" complaints are
  really "logic entangled with I/O" complaints.

## API design instincts (module, function, or endpoint)

Make it hard to misuse, not just possible to use: good defaults so the naive call
is the right call; loud failures over silent wrong behavior; accept the caller's
natural data shape rather than demanding ceremony; no boolean-flag parameters that
fork behavior (`export(data, True, False)` — those are two functions). Design the
call site first — write the code you *wish* callers could write, then implement
whatever makes that real.

## Deciding between alternatives

For any decision worth a pause: write the candidates down (two or three, rarely
more) with a one-line cost and benefit each — writing forces the vagueness out.
Pick using: satisfies today's requirement → cheapest to reverse → simplest to
understand, in that order. Then record choice + why + the rejected alternative in
your working log's DECISIONS section (`long-tasks.md`); six months from now, "why
didn't we just X?" gets answered in one line instead of one afternoon.

When genuinely uncertain between designs, don't debate — **spike**: a throwaway
prototype of the riskiest slice of each, an hour each, then decide from evidence.
The one iron rule of spikes: they are for learning, not shipping. Extract the
knowledge, write the real version with tests; the spike's code goes in the bin,
however endearing it became.

## When the requirement itself is the question

If two readings of the request lead to different architectures, that ambiguity is
the user's to resolve — ask before building (see calibration in SKILL.md). If the
readings converge on the same structure, pick the likelier one, state the
assumption, and keep moving.
