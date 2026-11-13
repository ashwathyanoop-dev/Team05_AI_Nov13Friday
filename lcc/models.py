"""Core data structures shared by every language analyzer."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

# Annotation kinds, in the order they are emitted when several share a line.
KINDS = ("summary", "business-rule", "logic", "data", "io", "dependency", "warning", "note")
KIND_LABELS = {
    "summary": "SUMMARY",
    "business-rule": "RULE",
    "logic": "LOGIC",
    "data": "DATA",
    "io": "I/O",
    "dependency": "DEPENDENCY",
    "warning": "RISK",
    "note": "NOTE",
}
LABEL_TO_KIND = {v: k for k, v in KIND_LABELS.items()}


@dataclass
class Annotation:
    line: int                 # 1-based source line the comment is placed ABOVE
    kind: str
    text: str
    confidence: float = 0.8
    source: str = "rule"      # rule | llm | user | import
    status: str = "suggested" # suggested | accepted | edited | rejected
    anchor: str = ""          # unit the annotation belongs to (paragraph, procedure, step)
    detail: bool = False      # True = only shown at "detailed" level
    alt_text: str = ""        # rule-based text kept when an LLM rewrote the comment
    id: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class OutlineNode:
    name: str
    kind: str                 # division, section, paragraph, package, procedure, function, step, ...
    line: int
    end_line: int = 0
    detail: str = ""
    children: list["OutlineNode"] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind,
            "line": self.line,
            "end_line": self.end_line,
            "detail": self.detail,
            "children": [c.to_dict() for c in self.children],
        }


@dataclass
class Dependency:
    kind: str                 # program, copybook, table, file, dataset, package, proc, cics, ...
    name: str
    lines: list[int] = field(default_factory=list)
    ops: list[str] = field(default_factory=list)
    detail: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class Collector:
    """Accumulates analyzer output with de-duplication."""

    def __init__(self) -> None:
        self.annotations: list[Annotation] = []
        self._deps: dict[tuple[str, str], Dependency] = {}
        self.outline: list[OutlineNode] = []
        self.call_graph: list[tuple[str, str]] = []
        self.summary: str = ""
        self.facts: dict = {}

    def note(self, line: int, kind: str, text: str, confidence: float = 0.8,
             anchor: str = "", detail: bool = False) -> Annotation | None:
        text = " ".join(text.split())
        if not text or line < 1:
            return None
        for a in self.annotations:
            if a.line == line and a.kind == kind and a.text == text:
                return a
        ann = Annotation(line=line, kind=kind, text=text, confidence=round(confidence, 2),
                         anchor=anchor, detail=detail)
        self.annotations.append(ann)
        return ann

    def dep(self, kind: str, name: str, line: int, op: str = "", detail: str = "") -> None:
        name = name.strip().strip("'\"")
        if not name:
            return
        key = (kind, name.upper())
        d = self._deps.get(key)
        if d is None:
            d = self._deps[key] = Dependency(kind=kind, name=name)
        if line not in d.lines:
            d.lines.append(line)
        if op and op not in d.ops:
            d.ops.append(op)
        if detail and detail not in d.detail.split("; "):
            d.detail = f"{d.detail}; {detail}" if d.detail else detail

    def edge(self, src: str, dst: str) -> None:
        if (src, dst) not in self.call_graph:
            self.call_graph.append((src, dst))

    @property
    def dependencies(self) -> list[Dependency]:
        return sorted(self._deps.values(), key=lambda d: (d.kind, d.name.upper()))
