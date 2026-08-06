# NiceGUI: working defaults

Defaults for NiceGUI apps — override with reason, local conventions win. Assumes
`python-rules.md`; the async defaults from `fastapi-rules.md` apply too (NiceGUI
runs on the same event loop world).
NiceGUI's API moves fast — verify against the installed version, not memory.

## State: decide the scope of every variable (rule zero)

"Works in one tab, chaos with two" is always this. For each piece of state, choose
its scope on purpose:

- **Module-level / `app.storage.general`** → shared by *all* clients. Correct for
  machine status, shared dashboards; a bug for anything user-specific.
- **`app.storage.user`** → per browser (survives reload). Preferences, session
  identity.
- **`app.storage.client` / locals in the page function** → per tab/connection.
  Form state, wizard progress.

Everything inside a `@ui.page` function is naturally per-visit — that's the
default home for UI state. A module-level `selected_items = []` in a multi-user
app is the NiceGUI edition of the mutable default argument.

## Layout vs. logic

Keep the decision-making out of the widget tree: logic in plain testable
functions/classes (functional core — `design-decisions.md`), and page code that
only builds widgets and wires callbacks. Group each screen's UI into a builder
function or small class; a 400-line page function of nested `with` blocks is the
NiceGUI code smell. Callbacks stay thin: read inputs → call logic → update UI.

## Updates and the event loop

- **Never block a handler.** A `time.sleep` or `requests` call in a button
  callback freezes *every* user's UI. Async handlers with async libraries, or
  `run.io_bound(...)` / `run.cpu_bound(...)` for sync/heavy work — same contract
  as FastAPI's rule zero.
- Know your update mechanism per element and use one deliberately: value
  **bindings** (`bind_value`) for simple two-way state; `@ui.refreshable` +
  `.refresh()` for rebuilding a section from data; `ui.timer` for polling
  (machine data, job progress). Mutating a Python list does not repaint a table
  by itself — the repaint call is part of the change.
- Long-running background work talks to the UI through state + a timer or
  explicit refresh, not by touching widgets from arbitrary contexts.

## Machine-HMI specifics (the common Warak case)

For dashboards over PLC/machine data: one background reader per data source
(not per client!) writing to shared state, clients rendering from it via
timer/refreshable — N browser tabs must not mean N PLC connections. Poll rates
deliberate (the PLC's cycle is milliseconds; the UI needs 2–10 Hz at most).
Commands from the UI to the machine are external input to the PLC: validate
against machine state before sending, confirm destructive actions in the UI, and
reflect the *machine's* acknowledged state back, not the button's optimism.

## Verification default

NiceGUI's real test is behavioral: run it and open **two** browser tabs — the
shared-vs-per-client mistakes are invisible with one. Check: does tab B see tab
A's data when it should (and only then)? Does the UI stay responsive during the
slow operation? Does a reload land the user back in a sane state
(`app.storage` scopes doing their job)? When you can't run it (this environment
sometimes can't), desk-check every module-level name against the scope table
above and say so in the handoff.
