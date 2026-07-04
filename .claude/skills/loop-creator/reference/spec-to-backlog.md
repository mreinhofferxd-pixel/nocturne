# Spec -> backlog grooming (v1)

When the repo has **no usable checkbox backlog** but **does** have a spec / design
doc / PRD (`SPEC.md`, `DESIGN.md`, `PLAN.md`, an RFC, a linked doc the user pastes),
the design layer grooms it into an ordered `BACKLOG.md` and then **converges to the
markdown adapter** — the harness only ever reads checkboxes, never the spec.

This is the `interactive` adapter of spec §6, seeded from a file instead of a chat
goal. The decomposition is an LLM job (prose -> tasks), not a parser job. Do it in
the design layer, once, before the loop starts.

## Output contract

Produce a `BACKLOG.md` where:

- **Units = `##` headings.** A unit is the smallest set of tasks that can merge on
  its own (spec §6). Independent deliverables are their own units; a dependency
  chain collapses into one unit. No structure in the spec -> one unit.
- **Tasks = `- [ ]` checkboxes** under their unit, in dependency order.
- Each task title is **imperative + concrete**: what changes, in which file(s),
  and a one-clause acceptance hint the gate can enforce. Same shape the markdown
  adapter already parses.

## Task sizing

| Rule | Why |
|---|---|
| One task == one commit == one logical change | Atomicity invariant; the harness commits per task |
| Independently verifiable by the gate | Done requires gate-green + a real commit |
| Split oversized spec items into ordered sub-tasks | The loop must never start on a vague mega-task |
| Order by dependency; scaffolding before dependents | Later tasks build on committed earlier ones |
| No tests in the repo? First task scaffolds a test harness + one smoke test | Gate has something real to enforce (see `gate-derivation.md`) |

## Rules

- **Deliverables, not prose.** Turn "the system should be observable" into concrete
  tasks ("add `.loop/report.md` writer", "log each iteration to `.loop/log/`").
  Skip goals/non-goals/background sections — they inform ordering, not tasks.
- **Don't groom already-done work.** Diff the spec against the current repo; only
  emit tasks for what's missing. A spec section already implemented -> no task.
- **Flag, don't invent.** A spec item too ambiguous to size becomes a *flagged*
  line in the preview (not a silent guess). The user resolves it before GO.
- **Don't dump the spec.** The backlog is an ordered work-list, not a paraphrase.
  If a "task" can't be gate-verified, it's not a task — it's context.
- **Optional complexity tag.** A trailing `[simple|complex|very-complex]` is
  honored by per-task model tiering once that lands (spec §8.4, fast-follow); omit
  until then.

## Preview & convergence

1. Write `BACKLOG.md` to the repo root.
2. Preview to the user: unit count, task count, any **flagged/ambiguous** items,
   the derived gate, branch, and caps.
3. Require an explicit **GO** (the one-time human gate, SKILL step "Preview & confirm").
4. On GO the run proceeds through the **markdown adapter** unchanged. `BACKLOG.md`
   is now the source of truth; the spec stays as reference. Re-grooming after spec
   changes is a manual re-run in v1 (self-grooming is a future enhancement, §17).
