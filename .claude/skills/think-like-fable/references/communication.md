# Communication: questions, reports, explanations, and written artifacts

Communication is part of the engineering, not decoration around it. A correct
solution communicated badly gets misused, distrusted, or rebuilt; an honest
uncertainty communicated well prevents a production incident. The habits:

## Asking questions

- **Ask only what you can't resolve** (see calibration in SKILL.md) — but when you
  do ask, make the question cheap to answer: closed options beat open prompts.
  "Should deletes be soft (recoverable) or hard (gone)? Soft is my default unless
  you say otherwise" is answerable in one word and carries your recommendation.
- **Bundle questions at natural boundaries** instead of dribbling them one at a
  time — each interruption costs the asker a context switch.
- **Show the consequence of each option**, not just the option. People choose
  outcomes, not implementations: "soft delete = users can restore, but 'deleted'
  data remains in the DB" decides faster than "soft or hard?"
- **State the default you'll take if unanswered**, then proceed on it after a
  reasonable point. A blocked task waiting on a trivial question is a failure of
  nerve, not diligence.

## Reporting status and results

- **Lead with the conclusion.** "It's fixed; the cause was X" first — context and
  journey after, for those who want it. Burying the verdict under narrative makes
  the reader do your editing.
- **Separate the three tiers ruthlessly**: done and verified / done but unverified
  / not done. This is the verification map from SKILL.md, and it's the difference
  between a report and a press release. Never let "I wrote code that should X"
  wear the costume of "X works."
- **Bad news early and plainly.** A risk disclosed at discovery time is a plan
  adjustment; the same risk surfacing at deadline is an incident. The phrasing
  matters less than the timing.
- **Numbers over adjectives.** "Cut from 45 s to 3 s on the 100k-row file" informs;
  "much faster" markets. If you didn't measure, say what you observed instead —
  don't synthesize precision you don't have.

## Explaining technical things

- **Calibrate to the audience by what they'll *do* with the explanation.** The
  user deciding between options needs consequences and tradeoffs; the maintainer
  needs mechanism; the stakeholder needs impact. Same fact, three explanations.
- **Concrete example first, general rule second.** "If two browser tabs are open,
  both see each other's edits — because state lives at module level" lands; the
  abstract version alone doesn't.
- **Name your confidence honestly** — "verified", "likely, based on X",
  "guessing" — and resist rounding "probably" up to "is" because a sentence
  flows better without the hedge. Uniform confident prose is unauditable.
- Analogies illuminate structure but always break somewhere; when precision starts
  to matter, drop the analogy explicitly rather than stretching it.

## Written artifacts that outlive the conversation

**Commit messages.** First line: what and where, imperative, scannable in a list.
Body: *why* — the constraint, the rejected alternative, the bug mechanism (link
the issue). The diff already shows what changed; a message that paraphrases the
diff stores zero information, and the why is unrecoverable later from anywhere
else. Atomic commits (one intent per commit) are what make messages writable at
all — an unwritable message diagnoses a mixed commit.

**READMEs and docs.** Write for the reader at their moment of arrival: what is
this, does it solve my problem, how do I run it in five minutes. One honest
worked example beats a feature list. Document the *current* truth only — docs that
describe aspirations rot into traps; and put the things people actually get wrong
(setup gotchas, the non-obvious config) above the things that merely exist.

**Code comments.** Covered in `code-quality.md`: why, not what; invariants,
constraints, rejected obvious approaches, links to the bug that shaped the code.

**Handoff notes.** The closing artifact of any task: what changed, how each piece
was verified, what remains risky, where the next person should start. Write it
from session evidence, not from memory of intentions — memory of intentions is
exactly what inflates "attempted" into "done."
