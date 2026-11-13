"""Render annotations as non-intrusive comment lines, and remove/import them again.

Guarantee: the only change ever made to a source file is the insertion of whole comment
lines carrying the [AI] marker. `strip(render(src)) == src` holds byte-for-byte, which the
test-suite verifies for every sample.
"""
from __future__ import annotations

import re
import textwrap

from .models import KIND_LABELS, KINDS, LABEL_TO_KIND, Annotation

GENERIC_PREFIX = {
    ".f": "C ", ".for": "C ", ".f77": "C ", ".f90": "! ", ".f95": "! ", ".rpg": "      * ", ".rpgle": "// ",
    ".sqlrpgle": "// ", ".asm": "* ", ".mlc": "* ", ".bas": "' ", ".vb": "' ", ".cls": "' ", ".frm": "' ",
    ".nat": "* ", ".pli": "/* ", ".pl1": "/* ", ".rexx": "/* ", ".cmd": "REM ", ".bat": "REM ",
    ".sh": "# ", ".pl": "# ", ".tcl": "# ", ".c": "// ", ".h": "// ", ".java": "// ", ".pas": "// ",
}
BLOCK_CLOSE = {"/* ": " */"}

# Any comment line whose body starts with the marker, in every supported syntax.
def marker_regex(tag: str = "AI") -> re.Pattern:
    t = re.escape(f"[{tag}]")
    return re.compile(rf"^(?:.{{6}}\*{t}|\s*(?:\*>|\*|--|//\*|//|#|!|'|C|REM|/\*)\s?{t})")


def style(language: str, dialect: str = "", ext: str = "") -> dict:
    if language == "cobol":
        if dialect == "fixed":
            return {"prefix": lambda ind: "      *", "width": 72, "space": False, "suffix": ""}
        return {"prefix": lambda ind: ind + "*> ", "width": 100, "space": True, "suffix": ""}
    if language == "plsql":
        return {"prefix": lambda ind: ind + "-- ", "width": 110, "space": True, "suffix": ""}
    if language == "jcl":
        return {"prefix": lambda ind: "//*", "width": 71, "space": False, "suffix": ""}
    p = GENERIC_PREFIX.get(ext.lower(), "# ")
    keep_indent = p not in ("C ", "      * ")
    return {"prefix": (lambda ind: ind + p) if keep_indent else (lambda ind: p), "width": 100,
            "space": True, "suffix": BLOCK_CLOSE.get(p, "")}


_ASCII = {"→": "->", "←": "<-", "×": "*", "÷": "/", "—": "-", "–": "-", "≥": ">=", "≤": "<=", "≠": "<>",
          "…": "...", "‘": "'", "’": "'", "“": '"', "”": '"', "•": "-", " ": " "}


def to_ascii(text: str) -> str:
    """Mainframe compilers, EBCDIC code pages and file-transfer tools often reject non-ASCII bytes."""
    for k, v in _ASCII.items():
        text = text.replace(k, v)
    return text.encode("ascii", "replace").decode("ascii")


def comment_block(ann: Annotation, st: dict, indent: str, tag: str = "AI", ascii_only: bool = True) -> list[str]:
    prefix = st["prefix"](indent)
    suffix = st["suffix"]
    marker = f"[{tag}]"
    head = f"{marker} {KIND_LABELS.get(ann.kind, 'NOTE')}: "
    cont = f"{marker}   "
    avail = max(len(head) + 10, st["width"] - len(prefix) - len(suffix))
    wrapper = textwrap.TextWrapper(width=avail, initial_indent=head, subsequent_indent=cont,
                                   break_long_words=True, break_on_hyphens=False)
    text = " ".join(ann.text.split())
    if ascii_only:
        text = to_ascii(text)
    if suffix:
        text = text.replace("*/", "* /")   # never close a block comment early
    body = wrapper.wrap(text) or [head.rstrip()]
    return [prefix + chunk + suffix for chunk in body]


def _order(a: Annotation) -> tuple:
    return (KINDS.index(a.kind) if a.kind in KINDS else 99,)


def render(lines: list[str], annotations: list[Annotation], language: str, dialect: str = "", ext: str = "",
           tag: str = "AI", protected: set[int] | None = None, newline: str = "\n",
           trailing_newline: bool = True, ascii_only: bool = True) -> str:
    st = style(language, dialect, ext)
    protected = protected or set()
    by_line: dict[int, list[Annotation]] = {}
    n = len(lines)
    for a in annotations:
        if a.status == "rejected" or not a.text.strip():
            continue
        line = min(max(1, a.line), n + 1)
        while line in protected and line > 1:
            line -= 1
        by_line.setdefault(line, []).append(a)
    out: list[str] = []
    for i in range(1, n + 2):
        anns = by_line.get(i)
        if anns:
            ref = lines[i - 1] if i <= n else (lines[-1] if lines else "")
            indent = ref[: len(ref) - len(ref.lstrip())] if st["space"] else ""
            for a in sorted(anns, key=_order):
                out.extend(comment_block(a, st, indent, tag, ascii_only))
        if i <= n:
            out.append(lines[i - 1])
    text = newline.join(out)
    return text + newline if trailing_newline and out else text


def strip(text: str, tag: str = "AI") -> str:
    rx = marker_regex(tag)
    nl = "\r\n" if "\r\n" in text else "\n"
    trailing = text.endswith("\n")
    kept = [ln for ln in text.replace("\r\n", "\n").split("\n") if not rx.match(ln)]
    if trailing and kept and kept[-1] == "":
        kept.pop()
    out = nl.join(kept)
    return out + nl if trailing else out


def extract(lines: list[str], tag: str = "AI") -> tuple[list[str], list[Annotation]]:
    """Remove existing [AI] comment lines and return them as annotations on the clean source."""
    rx = marker_regex(tag)
    marker = f"[{tag}]"
    clean: list[str] = []
    pending: list[Annotation] = []
    found: list[Annotation] = []
    for ln in lines:
        if rx.match(ln):
            body = ln[ln.index(marker) + len(marker):]
            body = re.sub(r"\s*\*/\s*$", "", body)
            m = re.match(r"\s([A-Z/]+):\s?(.*)$", body)
            if m and m.group(1) in LABEL_TO_KIND:
                pending.append(Annotation(line=0, kind=LABEL_TO_KIND[m.group(1)], text=m.group(2).strip(),
                                          source="import", status="accepted", confidence=1.0))
            elif pending:
                pending[-1].text += " " + body.strip()
            else:
                pending.append(Annotation(line=0, kind="note", text=body.strip(), source="import",
                                          status="accepted", confidence=1.0))
            continue
        clean.append(ln)
        for a in pending:
            a.line = len(clean)
            found.append(a)
        pending = []
    for a in pending:
        a.line = len(clean) + 1
        found.append(a)
    return clean, found
