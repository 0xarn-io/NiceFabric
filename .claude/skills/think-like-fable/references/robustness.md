# Robustness and defensive engineering

How to make things that keep working — or fail safely — when reality misbehaves.
This is the mindset that treats every input as hostile until validated, every
dependency as eventually unavailable, and every state as eventually corrupted.
Apply proportionally: a throwaway script doesn't need a fortress; anything facing
users, networks, or machinery does.

## Trust boundaries: validate at the door

Draw the boundary explicitly: everything arriving from outside your code —
user input, HTTP payloads, files, environment variables, sensor readings, another
team's service — is unverified data. Validate it *at the boundary*, once,
thoroughly; then the inside of the system can trust its own types. Validation
scattered through the middle means every function re-checks (or worse, some
assume someone else did).

- Validate structure (parseable, right types — in Python, let Pydantic do it),
  then semantics (in range, consistent, authorized *for this caller*).
- Reject, don't repair: silently "fixing" bad input (clamping, guessing encodings,
  defaulting missing fields) converts loud errors into quiet data corruption.
  If repair is a requirement, log it loudly and count it.
- Injection is the boundary failure with teeth: parameterized queries always
  (never string-built SQL), never `eval`/`exec`/`pickle.loads` on external data,
  shell commands built from lists not interpolated strings, paths resolved and
  checked against a base directory before use.

## Secrets and configuration

Secrets live in the environment or a secrets manager — never in code, never in
version control (a secret that ever touched a commit is burned; rotate it, don't
just delete it). Config that differs per environment (URLs, credentials, flags)
comes from outside the artifact; config baked into code is a deploy-time landmine.
Log values may travel far — never log credentials, tokens, or personal data;
assume logs are semi-public.

## Failing well

The design question is never "will it fail?" but "what does it do then?"

- **Fail fast and loud at startup** for what's mandatory (missing config, broken
  DB) — a service that half-starts and limps is worse than one that refuses.
- **Fail contained at runtime**: one bad request, one bad row, one bad message
  must not take down the batch, the worker, or the machine. Catch narrowly at the
  unit-of-work boundary, record, continue — and *count* the failures; a 2% error
  rate discovered in a log at month-end was an incident, not a statistic.
- **Timeouts on everything that waits.** Every network call, every lock, every
  queue read gets an explicit timeout; the default (often "forever") is how one
  slow dependency becomes a system-wide hang. Retries only with backoff and a
  cap, and only for operations that are safe to repeat —
- **which means designing for idempotency**: any operation that a retry, a
  double-click, or a redelivered message can invoke twice must be safe to run
  twice (idempotency keys, upserts, "already done" checks). Exactly-once is a
  myth at boundaries; at-least-once plus idempotency is the honest contract.
- **Crash-consistent state**: write-then-rename for files, transactions for
  multi-step DB changes, and ask of every persistent structure: "what does
  recovery look like if we die *between* these two writes?"

## The PLC/machinery variant

On machines, robustness is safety's sibling and the stakes are physical:

- Define every output's state for every fault path — "what do the outputs do when
  this FB errors, when comms drop, when the E-stop chain opens?" is the first
  review question, not an afterthought. Fail *de-energized/safe* by default.
- Never trust a single sensor reading at a decision boundary: debounce,
  plausibility-check against physics (a tank can't empty in one cycle), and
  design for the sensor's failure modes (stuck-high reads as "part always
  present" — what does the state machine do then?).
- Interlocks in logic mirror, never replace, hardwired safety; and persistent
  state (`VAR PERSISTENT`) must be re-validated after power-up, not trusted
  (see `domains.md` on first-cycle questions).
- Commands from HMI/SCADA/network are external input — validate range and state
  ("is this command legal in this machine state?") exactly like an HTTP payload.

## Proportionality — the judgment call

Robustness has a cost: code volume, complexity, latency. Spend it where failure
is expensive or invisible; skip it where failure is cheap and loud. A data
pipeline that runs once, supervised, can just crash; an unattended nightly job
needs the full failing-well treatment (see the worked example — its whole bug was
a robustness decision made by default instead of on purpose). The unforgivable
version isn't the missing handler — it's the *swallowed* error: robustness
theater that converts crashes into silent corruption. When in doubt, crash loudly
over continuing wrongly.
