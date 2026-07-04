# Spec -> backlog grooming (v1)

When the repo has **no usable checkbox backlog** but **does** have a spec / design
doc / PRD (`SPEC.md`, `DESIGN.md`, `PLAN.md`, an RFC, a linked doc the user pastes),
the design layer grooms it into an ordered `BACKLOG.md` and then **converges to the
markdown adapter** — the harness only ever reads checkboxes, never the spec.

A **prose backlog counts as a spec**: a `BACKLOG.md` with bullets/sections but zero
`- [ ]` checkboxes (symphony: prose items, removed when done) cannot drive the
adapter. Groom it like any spec — but write the result to a **separate file**
(`NOCTURNE_BACKLOG.md`) and set `backlog.path` to it. The repo's own backlog keeps
its convention untouched; the two files coexist (theirs = intent, ours = the
machine-checkable work-list for this run).

This is the `interactive` adapter of spec §6, seeded from a file instead of a chat
goal. The decomposition is an LLM job (prose -> tasks), not a parser job. Do it in
the design layer, once, before the loop starts.

## Output contract

Produce a `BACKLOG.md` (or `NOCTURNE_BACKLOG.md` when the repo's own backlog uses
a different convention — see above) where:

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
- **Flag, don't invent.** An ambiguous spec item becomes a *flagged* line in the
  preview (not a silent guess). The user resolves it before GO. Flag **both** kinds:
  - *Behavioral / sizing* — what should it do, or is this one task or five?
    ("reject bad input gracefully" → which errors, which exception type?).
  - *Interface shape* — **public API surface, import path, file layout.** What is
    the importable interface? ("exposes plain module-level functions" → package-root
    functions, submodules with a re-export, or bare submodule paths?). A silent guess
    here compiles and passes lint but breaks the caller's import (`pkg.foo` →
    `AttributeError`), so the gate won't catch it. Flag it.
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
   is now the source of truth; the spec stays as reference. When the spec later grows,
   reconcile with the **Spec-sync** pass below (append-only, human-gated); fully
   automatic self-grooming remains a future enhancement (§17).

## Spec-sync (re-groom an existing backlog)

When the repo has **both** a checkbox `BACKLOG.md` **and** a spec, the backlog stays
the source of truth — but the spec may have grown requirements the backlog doesn't
list yet. Spec-sync is a **manual, human-gated reconcile pass** that appends only
what's missing. It is the hand-cranked step toward self-grooming (spec §17); it never
runs unattended.

**Algorithm (append-only, idempotent):**

1. **Build the "already covered" set** = existing backlog tasks (both `- [ ]` and
   `- [x]`) **∪** current repo state (what the code already implements). A spec
   requirement is covered if it's already listed *or* already built.
2. **Diff** the spec's deliverables against that union; what remains is the *missing*
   set.
3. **Append only the missing tasks** as new `- [ ]` lines, each under the right `##`
   unit (add a new `## unit` only if none fits). Apply the same sizing/ordering rules
   as a fresh groom.
4. **Never** rewrite, reorder, re-word, or re-check an existing line, and never
   uncheck a `- [x]`. Spec-sync is strictly additive.
5. **Flag, don't invent** — same two ambiguity kinds as a fresh groom (behavioral /
   sizing *and* interface shape).
6. **Preview** the new-task count + flagged items + the derived gate; require **GO**.
7. On GO the run converges to the markdown adapter unchanged.

**Idempotent by construction:** run it twice with no spec change and the second run
finds the first run's appended tasks already in the "covered" set → it appends
nothing. Already-done or already-listed work yields no task.
