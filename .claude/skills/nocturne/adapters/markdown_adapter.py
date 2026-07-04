"""Markdown backlog adapter (nocturne v1).

Parses a checkbox list in BACKLOG.md / TODO.md / PLAN.md.
  - [ ] task   -> todo
  - [x] task   -> done
Marking done checks the box. Blocked state is NOT written here (the harness
keeps it in .loop/state.json) so that editing the backlog never dirties the
worktree between tasks — see the atomicity invariant in orchestrator.py.

Adapter interface (spec S6): next_task / mark_done / mark_blocked / list.
"""
import re
from dataclasses import dataclass

_CHECKBOX = re.compile(r'^(?P<indent>\s*)-\s+\[(?P<mark>[ xX])\]\s+(?P<body>.*)$')
_COMMENT = re.compile(r'<!--.*?-->')
_ACCEPTANCE = re.compile(r"@acceptance\(([^)]*)\)")
# A level-2 heading (exactly `## `) opens a unit. `#` (title) and `### ` do not.
_HEADING = re.compile(r'^##\s+(?P<title>.*)$')


def parse_acceptance(title):
    """Extract an optional @acceptance(<criterion>) marker from a task title.

    Returns (clean_title, criterion); criterion is None when no marker is
    present. The marker may sit anywhere in the title; it is removed and the
    remaining internal whitespace collapsed, so a trailing [tier] tag stays
    trailing and parse_tier keeps matching."""
    m = _ACCEPTANCE.search(title or "")
    if not m:
        return title, None
    clean = _ACCEPTANCE.sub(" ", title, count=1)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean, m.group(1).strip()


def parse_units(lines):
    """Group checkbox tasks by their most-recent preceding `## heading`.

    Pure. Returns (unit_title, [task_index, ...]) tuples in document order,
    including only units that contain at least one checkbox. Tasks appearing
    before any `## heading` belong to a default unit named "". task_index is
    the 0-based checkbox index (matches Task.index)."""
    groups = []          # list of [title, [indices]]
    current = None       # the open group, or None before the first task/heading
    idx = 0
    for line in lines:
        raw = line.rstrip("\n")
        h = _HEADING.match(raw)
        if h:
            current = [h.group("title").strip(), []]
            groups.append(current)
            continue
        if _CHECKBOX.match(raw):
            if current is None:
                current = ["", []]
                groups.append(current)
            current[1].append(idx)
            idx += 1
    return [(title, indices) for title, indices in groups if indices]


@dataclass
class Task:
    index: int          # 0-based position among all checkbox items (stable id)
    title: str
    done: bool
    raw: str
    acceptance: str | None = None
    unit: str = ""

    @property
    def id(self) -> str:
        return f"task-{self.index + 1}"


class MarkdownBacklog:
    def __init__(self, path: str):
        self.path = path

    def _read(self):
        with open(self.path, encoding="utf-8") as f:
            return f.readlines()

    def _items(self):
        """Return (lines, [(lineno, Task)])."""
        lines = self._read()
        items = []
        idx = 0
        unit = ""
        for lineno, line in enumerate(lines):
            raw = line.rstrip("\n")
            h = _HEADING.match(raw)
            if h:
                unit = h.group("title").strip()
                continue
            m = _CHECKBOX.match(raw)
            if not m:
                continue
            body = m.group("body")
            done = m.group("mark").lower() == "x"
            title = _COMMENT.sub("", body).strip()
            title, acceptance = parse_acceptance(title)
            task = Task(idx, title, done, raw, acceptance, unit)
            items.append((lineno, task))
            idx += 1
        return lines, items

    def list(self):
        _, items = self._items()
        return [t for _, t in items]

    def units(self):
        """(unit_title, [task_index, ...]) tuples in document order."""
        return parse_units(self._read())

    def next_task(self):
        """First todo task. Blocked-skipping is the harness's job (state.json)."""
        for t in self.list():
            if not t.done:
                return t
        return None

    def get(self, task_id: str):
        for t in self.list():
            if t.id == task_id:
                return t
        return None

    def _rewrite_line(self, index: int, transform):
        lines, items = self._items()
        for lineno, t in items:
            if t.index == index:
                lines[lineno] = transform(lines[lineno].rstrip("\n")) + "\n"
                break
        with open(self.path, "w", encoding="utf-8") as f:
            f.writelines(lines)

    def mark_done(self, task, sha=None):
        """Check the box. Commit sha (if any) is recorded in state.json, not here."""
        def tf(line):
            return re.sub(r"\[ \]", "[x]", line, count=1)
        self._rewrite_line(task.index, tf)

    def mark_blocked(self, task, why):
        """Interface completeness. The v1 harness tracks blocked in state.json
        instead of editing the file (keeps the worktree clean between tasks)."""
        return None
