# Domain grounding: TwinCAT ST and Python (FastAPI / NiceGUI)

The habits in SKILL.md are general. This file is where they bite in the two stacks
you'll meet most, plus the domain-specific traps that masquerade as mysteries.

## TwinCAT / IEC 61131-3 Structured Text

**The execution model is the master key.** Everything runs cyclically: the whole
program executes top to bottom every task cycle (often every 1–10 ms), forever.
Most ST bugs that look mysterious are cyclic-execution bugs:

- An `IF` condition that's true for 200 ms runs its body ~20–200 times, not once.
  Anything that must happen once per event needs an edge (R_TRIG/F_TRIG or a
  hand-rolled `x AND NOT x_prev`) or a state change that removes the condition.
- State machines advance at most one step per cycle unless written otherwise —
  and if written otherwise (multiple transitions per cycle), verify that's
  intended, because inputs can't change mid-cycle.
- Ask the first-cycle question: what do outputs, timers, and persistent variables
  hold on the very first cycle after download vs. after power-cycle? VAR PERSISTENT
  survives restarts — decide per variable whether that's a feature or a stale-state
  bug waiting for the next power blip.
- Timers (TON/TOF) must be *called* every cycle to update; a timer inside an IF
  that goes false freezes, it doesn't reset.

**Verification without execution.** You usually can't run PLC code here, so
substitute structure for runtime deliberately: hand-trace the state machine across
cycles with a concrete scenario table (cycle #, inputs, state, outputs); walk every
transition including the ones "that can't happen"; check what each fault path does
to outputs (machine safety: where do outputs land when this FB is in error?). Say
explicitly in the handoff: desk-checked, not machine-verified — and list the
scenarios traced.

**Language traps worth checking rather than remembering:**
- Integer width and promotion: mixed-width arithmetic promotes to DINT in ways
  that surprise; overflow wraps silently. When a computed value is load-bearing,
  trace it with worst-case values.
- Assignment `:=` vs. comparison `=` — a classic in review.
- Division of integers truncates; REAL comparison for equality is a bug pattern.
- CASE without ELSE silently ignores unexpected values — decide whether that's
  acceptable per state machine.
- Raw process data (EtherCAT, IO-Link): byte order and packing against the actual
  device documentation, not memory. The load-bearing unknown in I/O work is nearly
  always the mapping/layout — verify against the project's actual linked variables.

**Deployment awareness.** An online change and a download-with-reset are different
events with different state consequences; a "fix" that behaves differently across
them isn't done. Flag which one the change needs.

## Python services and UIs (FastAPI, NiceGUI)

**Here you can execute — so execute.** Start the app, send a real request, read
the real response. `pip show <pkg>` + a quick import beats remembered API shapes;
these libraries move fast and trained knowledge about them goes stale. When
behavior contradicts the docs in your head, trust the running code and read the
installed version's docs.

**The async event loop is the recurring load-bearing unknown.**
- A blocking call (`time.sleep`, `requests`, heavy CPU, sync DB driver) inside an
  `async def` handler freezes *every* request/UI update, not just this one. The
  symptom is "the whole app stutters under light load." Fixes: async-native
  libraries, or push sync work to a thread (`run_in_executor`,
  `asyncio.to_thread`, or in NiceGUI `run.io_bound` / `run.cpu_bound`).
- FastAPI nuance: a *sync* (`def`) endpoint runs in a threadpool and can block
  safely; an `async def` endpoint runs on the loop and must not block. Choosing
  `async def` out of habit while calling sync I/O is the classic self-inflicted
  wound.

**FastAPI specifics:**
- Pydantic does the validating; when requests 422, read the error body — it names
  the exact field and reason. Don't debug validation by staring at the model.
- Mind Pydantic v1 vs. v2 differences (`.dict()` vs `.model_dump()`, config
  style) — check which is installed before writing model code.
- Mutable module-level state (caches, connections) is shared across requests and
  workers can each have their own copy — a cache that "randomly" misses under
  gunicorn with 4 workers isn't random.
- Test endpoints for real with `TestClient`/`httpx` — status code, body, *and* the
  failure cases (missing field, wrong type, unauthorized).

**NiceGUI specifics:**
- The state question decides everything: module-level / app-level state is shared
  by *all* connected clients; per-client state must live in the page-builder scope
  or `app.storage.client`/`user`. "Works with one browser tab, chaos with two" is
  this bug, every time. Decide shared vs. per-client deliberately for each piece
  of state.
- UI updates from background work: long work in a handler freezes the UI (same
  event loop as above); use `run.io_bound`/`run.cpu_bound`, and for periodic
  refresh use `ui.timer`.
- Element updates: mutating data doesn't repaint by itself in all cases —
  bindings, `.refresh()` on `@ui.refreshable`, or explicit `update()` are the
  mechanisms; verify visually in a real browser session when possible.

**Cross-stack habit.** In both stacks, the most valuable single test is the
boundary you feared while designing: the first PLC cycle after power loss, the
second simultaneous browser client, the request with the field missing. Test the
feared case by name.
