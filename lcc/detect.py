"""Language detection and a fallback analyzer for languages without a dedicated grammar."""
from __future__ import annotations

import os
import re

from .models import Collector, OutlineNode
from .vocab import humanize

EXT = {
    "cobol": {".cbl", ".cob", ".cobol", ".cpy", ".cpb", ".ccp", ".pco", ".sqb"},
    "plsql": {".sql", ".pls", ".plsql", ".pks", ".pkb", ".pck", ".prc", ".fnc", ".trg", ".tps", ".tpb", ".plb"},
    "jcl": {".jcl", ".job", ".proc", ".cntl", ".prclib"},
}
LANG_NAMES = {"cobol": "COBOL", "plsql": "PL/SQL", "jcl": "JCL", "generic": "Other (generic)"}


def detect(filename: str, text: str) -> str:
    ext = os.path.splitext(filename.lower())[1]
    if _looks_like_jcl(text):          # JCL procedures are often saved as .prc, which is also a PL/SQL extension
        return "jcl"
    for lang, exts in EXT.items():
        if ext in exts:
            return lang
    head = text[:20000].upper()
    lines = [l for l in head.splitlines() if l.strip()][:200]
    jcl = sum(1 for l in lines if l.startswith("//"))
    if lines and jcl / len(lines) > 0.5 and re.search(r"^//\S*\s+(JOB|EXEC|DD)\b", head, re.M):
        return "jcl"
    if re.search(r"\b(IDENTIFICATION|PROCEDURE|DATA|ENVIRONMENT)\s+DIVISION\b", head) or \
            len(re.findall(r"^\s{0,12}\d{2}\s+[A-Z0-9-]+.*\bPIC(TURE)?\b", head, re.M)) >= 3:
        return "cobol"
    if re.search(r"\bCREATE\s+(OR\s+REPLACE\s+)?(PACKAGE|PROCEDURE|FUNCTION|TRIGGER|TYPE)\b", head) or \
            (re.search(r"^\s*(DECLARE|BEGIN)\b", head, re.M) and re.search(r"\bEND\s*;", head)):
        return "plsql"
    return "generic"


def _looks_like_jcl(text: str) -> bool:
    head = text[:20000].upper()
    lines = [l for l in head.splitlines() if l.strip()][:200]
    jcl = sum(1 for l in lines if l.startswith(("//", "/*")))
    return bool(lines) and jcl / len(lines) > 0.6 and bool(re.search(r"^//\S*\s+(JOB|EXEC|DD|PROC)\b", head, re.M))


def analyze_generic(lines: list[str], ext: str) -> Collector:
    """Best-effort structure for other legacy languages (RPG, Fortran, PL/I, Natural, BASIC...)."""
    c = Collector()
    roots: list[OutlineNode] = []
    header = re.compile(r"^\s*(?:(?:PUBLIC|PRIVATE|STATIC)\s+)?(SUBROUTINE|FUNCTION|PROCEDURE|PROC|SUB|DEFINE\s+SUBROUTINE|BEGSR|DCL-PROC|PROGRAM)\s+([A-Za-z_][\w$#@-]*)", re.I)
    pli = re.compile(r"^\s*([A-Za-z_][\w$#@]*)\s*:\s*(PROC|PROCEDURE)\b", re.I)
    call = re.compile(r"\b(?:CALL|CALLP|EXSR|PERFORM|GOSUB)\s+'?([A-Za-z_][\w$#@-]*)", re.I)
    comments = 0
    for i, ln in enumerate(lines, 1):
        s = ln.strip()
        if not s:
            continue
        if re.match(r"^(?:[Cc*!]\s|\*|//|#|'|REM\b|/\*)", s) or (len(ln) > 6 and ln[6] == "*" and ext in (".rpg",)):
            comments += 1
            continue
        m = header.match(ln) or pli.match(ln)
        if m:
            kind, name = (m.group(1), m.group(2)) if header.match(ln) else ("procedure", m.group(1))
            roots.append(OutlineNode(name, kind.lower().split()[-1], i))
            c.note(i, "summary", f"{kind.title()} {name} — {humanize(name)}. (Generic analyzer: enable the local LLM for a fuller explanation.)", 0.5, name)
            c.facts.setdefault("units", []).append({"name": name, "line": i, "kind": kind.lower()})
        for m in call.finditer(ln):
            c.dep("program", m.group(1), i, "call")
            c.note(i, "dependency", f"Calls {m.group(1)} ({humanize(m.group(1))}).", 0.5, detail=True)
        if re.search(r"\bGO\s*TO\b|\bGOTO\b", s, re.I):
            c.note(i, "warning", "Unstructured jump (GOTO): restructure when migrating.", 0.6)
    for k, r in enumerate(roots):
        r.end_line = roots[k + 1].line - 1 if k + 1 < len(roots) else len(lines)
    c.outline = roots
    c.facts["comment_lines"] = comments
    c.summary = f"{len(roots)} routines found by the generic analyzer."
    return c
