# loop-creator — fast-follow backlog

Code lives under `.claude/skills/loop-creator/`: harness `templates/orchestrator.py`,
adapter `adapters/markdown_adapter.py`. Tests go in `tests/` (importable via
`tests/conftest.py`). Each task must add pytest tests that pin the new behavior.

- [x] Add `stop` and `status` subcommands to `.claude/skills/loop-creator/templates/orchestrator.py`: `python orchestrator.py stop` creates `.loop/STOP`, `python orchestrator.py status` prints `.loop/report.md` (or a "no run yet" notice); add tests for a `cmd_stop`/`cmd_status` helper (spec §11).
- [x] Add stuck-detection to the harness: a pure `no_progress(prev_diff, cur_diff) -> bool` helper, and break the per-task retry loop early when an attempt's diff equals the previous attempt's diff (stop wasting budget); add tests for the helper (spec §8.1).
- [x] Add per-task model tiering to `orchestrator.py`: parse an optional trailing `[simple|complex|very-complex]` tag on a backlog task title, add `pick_model(task, config)` and `escalate(model, config)`, and use them in the run loop (escalate one tier on gate-failure retry); add tests for tier→model mapping and escalation (spec §8.4).
- [x] Add an anti-gaming diff-guard: `is_suppressing_diff(diff_text) -> bool` in `orchestrator.py` that flags a diff adding `skip`/`xfail`/`@ts-ignore`/`# type: ignore`/`# noqa`/`eslint-disable` or removing assertions; make the harness reject an otherwise-green attempt whose diff is suppressing unless the task title is tagged `[modifies-tests]`; add tests for the classifier on sample diffs (spec §8.5).
