# TwinCAT ST: working defaults

Opinionated defaults for writing IEC 61131-3 Structured Text — not laws. Follow
them unless there's a concrete reason not to, and when you deviate, say why. Local
project conventions always win: consistency within a codebase beats any global
preference. This is not a syntax reference — for language details use a dedicated
TwinCAT reference (or the installed twincat skill, if present).

## Structure

- **One state machine per behavior, CASE on an enum, not flag soup.** Named ENUM
  states (`E_FillerState.Idle/Filling/Draining/Fault`) over a pile of interacting
  BOOLs — flags multiply into unreachable combinations; an enum *is* the state,
  and the CASE reads as the machine's documentation. Give the CASE an ELSE that
  goes to Fault: an impossible state should be loud, not ignored.
- **One transition per cycle by default.** It keeps timing analyzable and traces
  readable. Allow multi-step only deliberately, with a comment saying why.
- **FBs own their behavior; programs wire them together.** An FB touches its
  inputs, outputs, and internals — never globals reached around the interface.
  Hidden global access is what makes PLC code untestable and un-reusable.
- **I/O lives in a GVL, logic uses symbolic names.** Map hardware once
  (`GVL_IO.bFillerPhotocell AT %I*`), never scatter raw addresses through logic.
  Re-wiring the cabinet should change one file.
- **Constants over magic numbers**, in a VAR CONSTANT or GVL: `T_JAM_TIMEOUT`,
  `N_BATCH_SIZE`. The number 100 in the middle of logic is a question every
  reader must answer again.

## The cyclic-execution rules (where most bugs live)

- **Events need edges.** Anything that must happen once per occurrence — counting,
  latching, sending — goes behind R_TRIG/F_TRIG, never a bare level condition.
- **Timers and edge FBs are called unconditionally, every cycle.** A TON inside
  an IF freezes when the IF goes false. Compute the IN condition, call the FB
  outside the branch: `tonJam(IN := bRun AND NOT bSensor, PT := T_JAM_TIMEOUT);`
- **Every latch has an explicit release.** For each `bAlarm := TRUE`, know the
  line that sets it FALSE and the conditions. Prefer SR/RS FBs or set/reset pairs
  in one visible place over assignments scattered through the file.
- **Outputs written in exactly one place.** An output assigned from three
  locations has a last-writer-wins bug waiting. Collect conditions, assign once,
  ideally at the block's end.
- **Answer the first-cycle and power-cycle questions per variable.** What is this
  worth on first scan after download? After power loss? VAR PERSISTENT is chosen
  per variable, on purpose, and re-validated at startup (see `robustness.md`).

## Types and arithmetic

- Match integer widths deliberately; on any counter or accumulator, ask what
  happens at the top of the range — wraparound is silent. DINT by default for
  counts; smaller types only with a reason.
- No REAL equality tests — compare against a band. No integer division where a
  fraction matters.
- Assignment is `:=`, comparison is `=` — read every `=` in review twice.

## Naming and readability

- Follow the project's prefix convention (commonly `b` BOOL, `n` integer, `r`
  REAL, `s` STRING, `t` TIME, `fb` instances, `E_`/`ST_`/`I_` for types); if the
  project has none, adopt this one consistently.
- Comment the *why* and the physical meaning: units (`// mm/s`), sensor polarity
  (`// TRUE = beam blocked`), and the reason for every timeout value. The code
  says what; on a machine, the comment must say what *in the world*.
- Keep cycle-time headroom visible: no unbounded loops, no string-heavy work in
  fast tasks; heavy work goes to a slower task or is spread across cycles with a
  state machine (see `optimization.md`, PLC note).

## Safety posture (see also robustness.md)

Fault states de-energize outputs. Interlocks in logic mirror hardwired safety,
never replace it. HMI/network commands are validated against machine state before
acting. Single sensor readings at decision boundaries get debounced and
plausibility-checked.
