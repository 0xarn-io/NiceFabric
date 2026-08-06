# Python: working defaults

Opinionated defaults for Python code — not laws. Follow them unless there's a
concrete reason not to, and when you deviate, say why. Local project conventions
always win — consistency beats preference. The theme: make wrong code look wrong
and make the interpreter and tools catch what they can, so humans only review what
machines can't.

## Data and types

- **Type hints on every public function.** Not for ceremony — they're machine-
  checked documentation, they catch the string-where-int-expected class of bug
  before runtime, and they make editors and reviewers smarter.
- **Structured data gets a structure.** A dict passed between functions
  (`user["adress"]` — typo compiles fine) becomes a dataclass or Pydantic model
  the moment it crosses a function boundary. Dicts are for genuinely dynamic
  shapes and boundaries, not for domain objects.
- **Never a mutable default argument** (`def f(x, acc=[])` — shared across every
  call). Default to `None`, create inside. This one recurs enough to be a rule,
  not a reminder.
- `pathlib.Path` over string paths and `os.path`; f-strings over `%`/`.format`;
  enums over string constants that must match everywhere.

## Errors and resources

- **Catch narrow, catch late.** Catch the exception type you can actually handle,
  at the level that can handle it. Bare `except:` / `except Exception: pass`
  converts crashes into silent corruption (see `robustness.md`) — if you truly
  must continue past failures, log loudly and count them.
- **Context managers for everything that opens/locks/connects** (`with` — files,
  connections, locks). Cleanup that depends on remembering is cleanup that
  eventually doesn't happen.
- **`logging` over `print` in anything that outlives the afternoon** — levels,
  timestamps, and the ability to silence or redirect without editing code.
  Loggers named `__name__`, configuration owned by the application, not the
  library.

## Shape of the code

- Small modules with one purpose; a `main()` behind `if __name__ == "__main__":`
  so everything stays importable (and therefore testable).
- Comprehensions while they fit on a line or two and stay flat; loops once logic
  nests. Generators for streams you traverse once; lists when you need to hold it
  all anyway.
- Pure logic separated from I/O (functional core, imperative shell — see
  `design-decisions.md`): the function that *decides* takes data and returns
  data; the thin wrapper does the reading and writing. This is the single
  biggest testability lever in Python.
- Module-level mutable state is a decision, not an accident — in servers it's
  shared across requests/clients (see `fastapi-rules.md`, `nicegui-rules.md`).

## Environment and dependencies

- Every project in its own venv; dependencies declared (pyproject.toml /
  requirements) with versions pinned for applications. "Works on my machine" is
  usually an undeclared dependency.
- Before using a remembered library API, `pip show` the installed version and
  check with a quick import — trained memory of fast-moving libraries goes stale
  (see SKILL.md, verified vs. remembered).
- Run a formatter and linter (black/ruff or the project's choice) rather than
  hand-enforcing style — style debates are automation's job.

## Testing default

pytest, tests next to or mirroring the source, and the priorities from
`testing.md`: feared cases, boundaries, every past bug. A Python function that's
hard to test is usually I/O-entangled — fix the design, not the test.
