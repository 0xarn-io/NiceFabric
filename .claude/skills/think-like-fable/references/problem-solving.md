# General problem-solving: reasoning habits beyond code

The engineering habits in SKILL.md are instances of more general reasoning moves.
This file captures those moves directly, for problems that aren't (or aren't yet)
code: analysis, planning, estimation, diagnosis of any system.

## Define the target before solving

Most wasted effort traces back to solving a misstated problem. Before working,
write the answer's *shape*: what would a complete answer look like — a number, a
decision with rationale, a ranked list, a yes/no with confidence? What units, what
precision, what audience? If you can't sketch the shape of the answer, you don't
understand the question yet — and it's cheaper to discover that now, from the
asker, than after the work.

Distinguish the *stated* problem from the *underlying* need. "How do I make this
query faster" sometimes means "the dashboard times out" — where the right fix is
caching or pagination, not query tuning. Answer the stated question, but check it
against the visible goal; when they diverge, say so.

## Estimation and sanity bounds

Before computing anything precisely, bound it roughly: order of magnitude, from
two or three known anchors. The bound serves two purposes — it catches errors in
the precise computation later (a result outside your bound is a bug in the result
or the bound, either way worth finding), and it sometimes shows precision is
unnecessary ("somewhere between 2 and 20 servers" may already decide the
question). A precise number that was never sanity-bounded is a common vehicle for
enormous errors — units, off-by-1000s, inverted ratios.

## Cross-check by independent route

Any result that matters should be computed twice, by *methods that don't share
failure modes*: analytic vs. simulated, top-down vs. bottom-up, the library
function vs. the five-line manual version, sum-of-parts vs. total-from-source.
Agreement from independent routes is strong evidence; agreement from re-running
the same route twice is nearly none. This is the general form of "verify claims,
not vibes" — a claim's support is only as strong as its most independent check.

## Useful inversions

- **Work backwards from the answer.** Given the goal state, what must be true one
  step before it? Often the backward chain is shorter and better constrained than
  the forward search.
- **Ask what would make this fail.** Designing anything, invert: enumerate the ways
  it could go wrong, then check each is handled or accepted. Failure-first
  thinking finds in minutes what optimism finds in production.
- **Try to disprove your favorite.** Once a hypothesis or plan becomes "the
  favorite," attention starts confirming it. Deliberately spend one step attacking
  it — the cheapest test that could kill it. Survivors earn confidence;
  unchallenged favorites just accumulate anecdotes.

## When the problem resists

- **Reduce to the smallest version that still contains the difficulty.** Solve a
  2-item version of the 10,000-item problem by hand; the structure that emerges
  usually generalizes, and if it doesn't, *that* mismatch is informative.
- **Solve a relaxed version.** Drop the hardest constraint, solve, then reintroduce
  it. Knowing what the unconstrained optimum looks like tells you what the
  constraint actually costs.
- **Change representation.** Table ↔ graph ↔ timeline ↔ state machine ↔ picture.
  Problems are often hard in one representation and readable in another; the state
  machine that's opaque as prose is obvious as a diagram.
- **Enumerate honestly before choosing.** Under pressure, the first workable idea
  colonizes the mind. Force two alternatives into writing before committing —
  they're free to generate now and expensive to wish for later.

## Working with data you didn't produce

Before analyzing any dataset, interrogate it: row count against expectation,
duplicates on the supposed key, nulls and their meaning (missing ≠ zero), ranges
and units of numeric columns (a max of 9999 is a sentinel, not a measurement),
date boundaries and timezone, and one fully-read example row. Every conclusion
inherits the flaws of unexamined data — five minutes of profiling buys the right
to trust the next five hours. And when a result surprises: check the pipeline
before celebrating the finding; most "discoveries" are joins gone wrong.

## Calibration in conclusions

State findings with their support: *verified* (checked directly), *inferred*
(follows from checked facts plus stated assumptions), *assumed* (needed but
unchecked). The reader — including future-you — must be able to tell which is
which. A report that flattens these into uniform confident prose is more dangerous
than no report, because it can't be audited where it's weakest.
