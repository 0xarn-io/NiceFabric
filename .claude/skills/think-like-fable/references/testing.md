# Test design: writing tests that earn their keep

A test's entire value is its ability to fail. A test that passes no matter what the
code does is a decoration with a maintenance cost. So the design question for every
test is: *which realistic future bug would make this fail, and how clearly would the
failure explain itself?*

## What to test, in priority order

1. **The feared case.** Whatever you worried about while designing — the empty
   input, the timezone boundary, the second concurrent client, the retry after
   failure — test that exact case, by name. Design-time worry is the best bug
   predictor you have.
2. **Boundaries.** Zero elements, one element, many, exactly-at-the-limit,
   one-past-the-limit, malformed, duplicate, already-processed. Most bugs live at
   edges; most happy-path tests never visit them.
3. **The contract, not the implementation.** Test what the function promises
   (inputs → observable outcomes), not how it currently achieves it. Tests welded
   to internals (call order, private state, over-specified mocks) break on every
   refactor while catching few real bugs — they train people to ignore red.
4. **Every bug that ever happened.** The minimal reproduction from each debugging
   session becomes a permanent regression test. Bugs recur in families; this is
   the cheapest insurance there is.
5. **The error paths.** What happens on bad input, on the dependency timing out,
   on the file missing? Untested error handling is usually broken error handling —
   it's the least-executed code in the system.

## What not to test

The framework itself, trivial pass-throughs, third-party libraries' internals, and
private helpers already exercised through the public surface. Deleting a
low-value test is a legitimate improvement.

## Making tests trustworthy

- **See it fail once.** New test: check it fails when the behavior is broken
  (write it before the fix, or sabotage the code momentarily). A test born green
  has never proven anything.
- **One behavior per test, named as a sentence.** `test_expired_token_is_rejected`
  reads as documentation and fails as a diagnosis. A test asserting ten things
  fails as a shrug.
- **Arrange–act–assert, visibly.** Setup, the single action under test, the
  checks. If arrange takes twenty lines, that's design feedback about the code
  under test (too many dependencies), not just test ugliness.
- **Deterministic or fixed.** A flaky test is a bug — in the test or the code —
  and either way it's telling you about hidden time/order/concurrency coupling.
  Control the clock, seed the randomness, own the ordering. Never quarantine-and-
  forget.
- **Independent.** Any test runnable alone, in any order. Shared mutable fixtures
  create action-at-a-distance failures that cost afternoons.

## Mocking: as little as possible

Mock at *your system's boundaries* (network, clock, filesystem, external services) —
not your own internals. Every internal mock is a bet that the real component
behaves like your imitation; enough of those and the suite tests your imagination.
Prefer real objects in-memory (SQLite, tmp dirs, FastAPI's TestClient) over mocks
when cheap. When you must mock, assert on *outcomes*, not on "was called with" —
call-signature assertions are implementation-welding in disguise.

## Pytest mechanics worth defaulting to

- `@pytest.mark.parametrize` to turn one test into a boundary table — this is the
  natural home for the edge-case list above.
- `tmp_path` for filesystem work, `monkeypatch` for env/attrs, fixtures for shared
  setup with visible scope.
- Plain `assert` with rich diffs; on failure, the message should point at the
  culprit without a debugger.

## Coverage: a flashlight, not a target

Use coverage to find *untested important paths* — then decide deliberately. Chasing
a percentage produces assertion-free tests that execute code without checking it,
which is worse than nothing: it manufactures false confidence. 100% coverage with
weak assertions loses to 70% coverage of contracts, boundaries, and feared cases.
