"""Oracle PL/SQL analyzer (packages, procedures, functions, triggers, anonymous blocks)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import Collector, OutlineNode
from .vocab import arith, humanize, join_list, label, shorten, sql_describe, sql_tables, verbalize_sql

STD_EXC = {
    "NO_DATA_FOUND": "the SELECT INTO found no row", "TOO_MANY_ROWS": "the SELECT INTO found more than one row",
    "DUP_VAL_ON_INDEX": "a unique key would be duplicated", "ZERO_DIVIDE": "division by zero",
    "VALUE_ERROR": "a conversion/size error", "INVALID_NUMBER": "text could not be converted to a number",
    "INVALID_CURSOR": "an invalid cursor operation", "CURSOR_ALREADY_OPEN": "the cursor was already open",
    "TIMEOUT_ON_RESOURCE": "a lock wait timed out", "OTHERS": "any other error",
}
KEYWORDS = {
    "IF", "ELSIF", "ELSE", "END", "BEGIN", "DECLARE", "EXCEPTION", "WHEN", "THEN", "LOOP", "FOR", "WHILE",
    "RETURN", "NULL", "RAISE", "COMMIT", "ROLLBACK", "SAVEPOINT", "SELECT", "INSERT", "UPDATE", "DELETE",
    "MERGE", "OPEN", "FETCH", "CLOSE", "EXIT", "CONTINUE", "GOTO", "CASE", "CURSOR", "TYPE", "SUBTYPE",
    "PRAGMA", "PROCEDURE", "FUNCTION", "CREATE", "EXECUTE", "FORALL", "PACKAGE", "TRIGGER", "WITH", "LOCK",
    "SET", "AND", "OR", "NOT", "IS", "AS", "IN", "OUT",
}
TECH = re.compile(r"%NOTFOUND|%FOUND|%ROWCOUNT|%ISOPEN|SQLCODE|SQL%|_COUNT\b|\bCOUNT\b|\bI\b|\bIDX\b|LAST|FIRST", re.I)


@dataclass
class Seg:
    line: int
    end: int
    text: str        # comments removed, strings intact
    ns: str          # comments removed, string contents masked
    word: str        # first word (upper)


@dataclass
class Unit:
    name: str
    kind: str
    line: int
    end: int = 0
    header: str = ""
    node: OutlineNode | None = None
    facts: dict = field(default_factory=lambda: {"reads": [], "writes": [], "calls": [], "rules": 0,
                                                 "raises": [], "commits": 0, "loops": 0, "cursors": [],
                                                 "handlers": [], "dynamic": 0})


def mask(text: str) -> tuple[str, str, set[int]]:
    clean, ns = list(text), list(text)
    comment_lines: set[int] = set()
    i, n, line = 0, len(text), 1

    def blank(a, b, both=True):
        nonlocal line
        for k in range(a, b):
            if text[k] == "\n":
                line += 1
                continue
            ns[k] = " "
            if both:
                clean[k] = " "

    while i < n:
        c = text[i]
        if c == "\n":
            line += 1
            i += 1
        elif text.startswith("--", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            comment_lines.add(line)
            blank(i, j)
            i = j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            start = line
            blank(i, j)
            comment_lines.update(range(start, line + 1))
            i = j
        elif c == "'":
            j = i + 1
            while j < n:
                if text[j] == "'" and j + 1 < n and text[j + 1] == "'":
                    j += 2
                    continue
                if text[j] == "'":
                    break
                j += 1
            for k in range(i + 1, min(j, n)):
                if text[k] == "\n":
                    line += 1
                else:
                    ns[k] = "_"
            i = j + 1
        else:
            i += 1
    return "".join(clean), "".join(ns), comment_lines


_WORD = re.compile(r"[A-Za-z_][\w$#]*(?:\.[A-Za-z_][\w$#]*)*|<<|>>|:=|\S")


def segments(clean: str, ns: str) -> list[Seg]:
    """Split PL/SQL into statement-ish segments on ';' and block keywords."""
    segs: list[Seg] = []
    start = 0
    words: list[str] = []
    depth = 0
    case_expr = 0
    line_at = [0] * (len(ns) + 1)
    ln = 1
    for k, ch in enumerate(ns):
        line_at[k] = ln
        if ch == "\n":
            ln += 1
    line_at[len(ns)] = ln

    def cut(end):
        nonlocal start, words, case_expr
        txt = clean[start:end]
        nss = ns[start:end]
        if nss.strip() and nss.strip() != ";":
            off = len(nss) - len(nss.lstrip())
            first = (words[0] if words else "").upper()
            segs.append(Seg(line_at[start + off], line_at[max(start, end - 1)], " ".join(txt.split()),
                            " ".join(nss.split()), first))
        start, words, case_expr = end, [], 0

    for m in _WORD.finditer(ns):
        w = m.group(0)
        wu = w.upper()
        if w == "(":
            depth += 1
        elif w == ")":
            depth = max(0, depth - 1)
        if w in ("<<", ">>"):
            continue
        if words and words[-1] == "<<":
            continue
        if depth == 0 and wu in ("BEGIN", "DECLARE") and words:
            cut(m.start())
        first0 = words[0].upper() if words else ""
        sql_ctx = first0 in ("SELECT", "INSERT", "UPDATE", "DELETE", "MERGE", "WITH", "CURSOR", "OPEN", "FORALL")
        if (depth == 0 and wu == "WHEN" and words and not case_expr and not sql_ctx
                and words[-1].upper() not in ("EXIT", "CONTINUE") and first0 not in ("CREATE", "TRIGGER")):
            cut(m.start())
        expr_ctx = bool(words) and (words[0].upper() in ("SELECT", "INSERT", "UPDATE", "DELETE", "MERGE", "RETURN",
                                                        "OPEN", "CURSOR", "WITH", "FOR", "FORALL", "PIPE")
                                    or ":=" in words)
        if wu == "CASE" and expr_ctx:
            case_expr += 1
        elif wu == "END" and case_expr:
            case_expr -= 1
            words.append(w)
            continue
        words.append(w)
        if depth or case_expr:
            if w == ";" and not depth:
                cut(m.end())
            continue
        first = words[0].upper()
        if w == ";":
            cut(m.end())
        elif first in ("SELECT", "INSERT", "UPDATE", "DELETE", "MERGE", "WITH", "CURSOR", "OPEN", "FORALL"):
            continue
        elif wu in ("THEN", "LOOP"):
            cut(m.end())
        elif wu in ("BEGIN", "DECLARE", "EXCEPTION", "ELSE") and len(words) == 1:
            cut(m.end())
        elif wu in ("IS", "AS") and (first in ("PROCEDURE", "FUNCTION", "PACKAGE")
                                     or (first == "CREATE" and not re.search(r"\bVIEW\b|\bTYPE\b(?!\s+BODY)", " ".join(words), re.I))):
            cut(m.end())
    cut(len(ns))
    return segs


class PlsqlAnalyzer:
    def __init__(self, text: str):
        self.text = text
        self.clean, self.ns, self.comment_lines = mask(text)
        # SQL*Plus statement terminators ("/" alone on a line) are not PL/SQL.
        blank = lambda m: " " * len(m.group(0))
        self.clean = re.sub(r"(?m)^[ 	]*/[ 	]*$", blank, self.clean)
        self.ns = re.sub(r"(?m)^[ 	]*/[ 	]*$", blank, self.ns)
        self.c = Collector()
        self.units: list[Unit] = []
        self.cursors: dict[str, str] = {}
        self.exceptions: set[str] = set()
        self.summarized: set[int] = set()   # segments already described inside an IF/CASE summary
        self.concat_vars: set[str] = set()  # variables built by string concatenation (dynamic SQL taint)

    # .............................................................. block structure
    def _blocks(self):
        toks = [(m.group(0), self.ns.count("\n", 0, m.start()) + 1)
                for m in re.finditer(r"[A-Za-z_][\w$#]*(?:\.[A-Za-z_][\w$#\"]*)*|[;()]", self.ns)]
        stack: list[tuple[str, Unit | None]] = []
        outline_stack: list[OutlineNode] = []
        roots: list[OutlineNode] = []
        pending: Unit | None = None
        pdepth = 0
        i = 0
        n = len(toks)

        def push_unit(u: Unit, frame: str):
            node = OutlineNode(u.name, u.kind, u.line)
            u.node = node
            (outline_stack[-1].children if outline_stack else roots).append(node)
            outline_stack.append(node)
            self.units.append(u)
            stack.append((frame, u))

        def close(u: Unit, line: int):
            u.end = line
            if u.node:
                u.node.end_line = line
            if outline_stack:
                outline_stack.pop()

        while i < n:
            w, line = toks[i]
            wu = w.upper()
            nxt = toks[i + 1][0].upper() if i + 1 < n else ""
            if pending is not None:
                if w == "(":
                    pdepth += 1
                elif w == ")":
                    pdepth -= 1
                elif pdepth == 0 and wu in ("IS", "AS") and pending.kind not in ("trigger",):
                    push_unit(pending, "PKG" if pending.kind.startswith("package") or pending.kind == "type body" else "UNIT")
                    pending = None
                elif pdepth == 0 and w == ";":
                    if pending.kind in ("procedure", "function"):
                        node = OutlineNode(pending.name, pending.kind + " spec", pending.line, line)
                        (outline_stack[-1].children if outline_stack else roots).append(node)
                    pending = None
                elif pending.kind == "trigger" and wu in ("DECLARE", "BEGIN"):
                    push_unit(pending, "UNIT")
                    pending = None
                    if wu == "BEGIN":
                        stack.append(("BEGIN", None))
                i += 1
                continue
            if wu in ("PROCEDURE", "FUNCTION") and nxt and nxt not in (";",):
                pending = Unit(toks[i + 1][0], wu.lower(), line)
                pdepth = 0
                i += 2
                continue
            if wu == "PACKAGE":
                body = nxt == "BODY"
                j = i + 2 if body else i + 1
                if j < n:
                    pending = Unit(toks[j][0], "package body" if body else "package", line)
                    pdepth = 0
                    i = j + 1
                    continue
            if wu == "TYPE" and nxt == "BODY" and i + 2 < n:
                pending = Unit(toks[i + 2][0], "type body", line)
                i += 3
                continue
            if wu == "TRIGGER" and i > 0 and toks[i - 1][0].upper() in ("REPLACE", "CREATE", "EDITIONABLE", "NONEDITIONABLE") and nxt:
                pending = Unit(toks[i + 1][0], "trigger", line)
                i += 2
                continue
            if wu == "DECLARE":
                push_unit(Unit("anonymous block", "block", line), "DECL")
            elif wu == "BEGIN":
                if not stack:
                    push_unit(Unit("anonymous block", "block", line), "DECL")
                stack.append(("BEGIN", None))
            elif wu == "CASE":
                stack.append(("CASE", None))
            elif wu == "END":
                if nxt in ("IF", "LOOP"):
                    i += 2
                    continue
                if nxt == "CASE":
                    if stack and stack[-1][0] == "CASE":
                        stack.pop()
                    i += 2
                    continue
                if stack:
                    frame, u = stack.pop()
                    if frame == "CASE":
                        pass
                    elif frame == "BEGIN":
                        if stack and stack[-1][0] in ("UNIT", "DECL"):
                            _, u2 = stack.pop()
                            close(u2, line)
                    elif frame in ("PKG", "UNIT", "DECL") and u:
                        close(u, line)
            i += 1
        last = self.text.count("\n") + 1
        for u in self.units:
            if not u.end:
                u.end = last
                if u.node:
                    u.node.end_line = last
        self.c.outline = roots

    def unit_at(self, line: int) -> Unit | None:
        best = None
        for u in self.units:
            if u.line <= line <= (u.end or line) and u.kind not in ("package", "package body", "type body"):
                if best is None or u.line >= best.line:
                    best = u
        return best

    # .............................................................. statement pass
    def _brief(self, s: Seg) -> str:
        t, w = s.text.rstrip(";"), s.word
        if w == "RAISE_APPLICATION_ERROR":
            m = re.match(r"RAISE_APPLICATION_ERROR\s*\(\s*(-?\d+)\s*,\s*(.*)\)", t, re.I)
            return f"reject with ORA{m.group(1)} {shorten(m.group(2), 60)}" if m else "raise an application error"
        if w == "RAISE":
            parts = t.split()
            return f"raise {parts[1]}" if len(parts) > 1 else "re-raise the error"
        if ":=" in t and w not in KEYWORDS:
            lhs, rhs = t.split(":=", 1)
            return f"set {lhs.strip()} := {shorten(rhs.strip(), 50)}"
        if w in ("SELECT", "INSERT", "UPDATE", "DELETE", "MERGE"):
            tbls = join_list([x for x, _ in sql_tables(t)], 3)
            return f"{w.lower()} {tbls}".strip()
        if w == "RETURN":
            return "return " + shorten(t[6:].strip(), 50)
        if w == "NULL":
            return "do nothing"
        if w in ("COMMIT", "ROLLBACK"):
            return w.lower()
        if w == "IF":
            return "check " + shorten(verbalize_sql(re.sub(r"^IF\s+|\s+THEN$", "", t, flags=re.I)), 50)
        if w in ("FOR", "WHILE", "LOOP"):
            return "loop"
        if w == "EXIT":
            return "exit the loop" + (" " + t[4:].strip() if len(t) > 4 else "")
        m = re.match(r"([\w$#.]+)\s*(\(|$)", t)
        if m and w not in KEYWORDS:
            return f"call {m.group(1)}"
        return shorten(t, 50).lower()

    def _branches(self, segs: list[Seg], i: int, stops=("ELSIF", "ELSE")) -> tuple[list[Seg], int]:
        """Collect top-level statements of a branch starting at segs[i]; return (stmts, index_of_stop)."""
        out: list[Seg] = []
        depth = 0
        while i < len(segs):
            s = segs[i]
            w = s.word
            u = s.ns.upper()
            if depth == 0 and (w in stops or u.startswith("END IF") or u.startswith("END CASE") or w == "WHEN"
                               or w == "EXCEPTION" or (w == "END" and not u.startswith(("END LOOP",)))):
                return out, i
            if w in ("IF", "CASE", "BEGIN"):
                if depth == 0:
                    out.append(s)
                depth += 1
            elif u.startswith(("END IF", "END CASE")) or (w == "END" and not u.startswith("END LOOP")):
                depth -= 1
            elif (w in ("FOR", "WHILE") or w == "LOOP") and u.endswith("LOOP"):
                if depth == 0:
                    out.append(s)
                depth += 1
            elif u.startswith("END LOOP"):
                depth -= 1
            elif depth == 0 and w not in ("ELSE", "ELSIF"):
                out.append(s)
            i += 1
        return out, i

    def _sum(self, stmts: list[Seg], limit=3) -> str:
        if not stmts:
            return "nothing"
        self.summarized.update(id(s) for s in stmts[:limit])
        parts = [self._brief(s) for s in stmts[:limit]]
        return ", ".join(parts) + (f" (+{len(stmts) - limit} more)" if len(stmts) > limit else "")

    def _statements(self):
        segs = segments(self.clean, self.ns)
        self.segs = segs
        loop_depth = 0
        block_depth = 0
        exc_depth = -1
        for i, s in enumerate(segs):
            u = self.unit_at(s.line)
            f = u.facts if u else None
            anchor = u.name if u else ""
            t = s.text.rstrip(";").strip()
            tu = s.ns.upper()
            w = s.word

            if w == "BEGIN":
                block_depth += 1
                continue
            if w == "END" and not tu.startswith(("END IF", "END LOOP", "END CASE")):
                block_depth -= 1
                if block_depth < exc_depth:
                    exc_depth = -1
                continue
            if tu.startswith("END LOOP"):
                loop_depth = max(0, loop_depth - 1)
                continue
            if w == "EXCEPTION" and tu == "EXCEPTION":
                exc_depth = block_depth
                continue
            if w in ("CREATE", "PROCEDURE", "FUNCTION", "PACKAGE"):
                if u is not None and w != "PACKAGE" and s.line == u.line:
                    u.header = t
                if w == "CREATE":
                    for uu in self.units:
                        if uu.line == s.line:
                            uu.header = t
                continue

            # ---- declarations
            m = re.match(r"CURSOR\s+([\w$#]+)\s*(\(.*?\))?\s+IS\s+(.*)$", t, re.I | re.S)
            if m:
                desc = sql_describe(m.group(3))
                self.cursors[m.group(1).upper()] = desc
                for tbl, op in sql_tables(m.group(3)):
                    self.c.dep("table", tbl, s.line, op)
                    if f is not None:
                        f["reads"].append(tbl)
                params = f" Parameters {m.group(2)}." if m.group(2) else ""
                self.c.note(s.line, "data", f"Cursor {m.group(1)}: {desc}{params}", 0.85, anchor)
                if f is not None:
                    f["cursors"].append(m.group(1))
                continue
            m = re.match(r"TYPE\s+([\w$#]+)\s+IS\s+(TABLE\s+OF|VARRAY|RECORD|REF\s+CURSOR)(.*)$", t, re.I)
            if m:
                k = m.group(2).upper()
                what = {"RECORD": "record (struct)", "REF CURSOR": "cursor variable type"}.get(
                    re.sub(r"\s+", " ", k), "in-memory collection (array/map)")
                self.c.note(s.line, "data", f"Type {m.group(1)}: {what}{(' of ' + shorten(m.group(3), 50)) if 'TABLE' in k else ''}.",
                            0.75, anchor, detail=True)
                continue
            m = re.match(r"([\w$#]+)\s+EXCEPTION$", t, re.I)
            if m:
                self.exceptions.add(m.group(1).upper())
                self.c.note(s.line, "data", f"Declares business exception {m.group(1)} ({humanize(m.group(1))}).", 0.75, anchor, detail=True)
                continue
            if w == "PRAGMA":
                if "AUTONOMOUS_TRANSACTION" in tu:
                    self.c.note(s.line, "warning", "Autonomous transaction: this unit commits independently of its caller, "
                                "so its changes persist even if the caller rolls back (common for audit logging). "
                                "Preserve this isolation in the target platform.", 0.9, anchor)
                elif "EXCEPTION_INIT" in tu:
                    m = re.search(r"EXCEPTION_INIT\s*\(\s*([\w$#]+)\s*,\s*(-?\d+)", t, re.I)
                    if m:
                        self.c.note(s.line, "data", f"Maps Oracle error {m.group(2)} to the named exception {m.group(1)}.", 0.8, anchor)
                continue

            # ---- control flow
            if w in ("IF", "ELSIF"):
                cond = re.sub(r"^(IF|ELSIF)\s+|\s+THEN$", "", t, flags=re.I)
                then, stop = self._branches(segs, i + 1)
                txt = f"{'If' if w == 'IF' else 'Else if'} {shorten(verbalize_sql(cond), 140)} → {self._sum(then)}"
                if w == "IF":
                    j = stop
                    while j < len(segs) and segs[j].word == "ELSIF":
                        _, j = self._branches(segs, j + 1)
                    if j < len(segs) and segs[j].word == "ELSE":
                        other, _ = self._branches(segs, j + 1)
                        if stop == j:
                            txt += f"; otherwise → {self._sum(other)}"
                kind = "logic" if TECH.search(cond) else "business-rule"
                self.c.note(s.line, kind, txt + ".", 0.8, anchor)
                if f is not None and kind == "business-rule":
                    f["rules"] += 1
                continue
            if w == "CASE":
                selector = t[4:].strip()
                cases = []
                j = i + 1
                while j < len(segs) and segs[j].word == "WHEN":
                    cond = re.sub(r"^WHEN\s+|\s+THEN$", "", segs[j].text, flags=re.I)
                    body, j = self._branches(segs, j + 1, stops=("ELSE",))
                    cases.append(f"{shorten(verbalize_sql(cond), 70)} → {self._sum(body, 2)}")
                if j < len(segs) and segs[j].word == "ELSE":
                    body, j = self._branches(segs, j + 1, stops=())
                    cases.append(f"anything else → {self._sum(body, 2)}")
                if cases:
                    subj = f"the value of {selector}" if selector else "the first matching condition"
                    self.c.note(s.line, "business-rule", f"Decision table on {subj}: " + "; ".join(cases[:7]) + ".", 0.8, anchor)
                    if f is not None:
                        f["rules"] += 1
                continue
            if w == "WHEN":
                if exc_depth >= 0 and exc_depth == block_depth:
                    names = re.sub(r"^WHEN\s+|\s+THEN$", "", t, flags=re.I)
                    body, _ = self._branches(segs, i + 1, stops=())
                    acts = self._sum(body)
                    meanings = [STD_EXC.get(n.strip().upper(), f"business exception {n.strip()}")
                                for n in re.split(r"\s+OR\s+", names, flags=re.I)]
                    reraises = any(b.word in ("RAISE", "RAISE_APPLICATION_ERROR") for b in body)
                    only_null = body and all(b.word == "NULL" for b in body)
                    if f is not None:
                        f["handlers"].append(names)
                    if "OTHERS" in names.upper() and (only_null or not body):
                        self.c.note(s.line, "warning", "WHEN OTHERS THEN NULL swallows every error silently: failures are "
                                    "invisible to callers and data may be left half-processed. Fix or log before migrating.", 0.95, anchor)
                    elif "OTHERS" in names.upper() and not reraises:
                        self.c.note(s.line, "warning", f"Catch-all handler for {join_list(meanings)} that does not re-raise: "
                                    f"it {acts} and continues, hiding the original error from callers.", 0.85, anchor)
                    else:
                        self.c.note(s.line, "logic", f"Error handler: if {join_list(meanings)} → {acts}.", 0.85, anchor)
                continue
            if w in ("FOR", "WHILE") or (w == "LOOP" and tu == "LOOP") or w == "FORALL":
                if tu.endswith("LOOP"):
                    loop_depth += 1
                body, _ = self._branches(segs, i + 1, stops=()) if tu.endswith("LOOP") else ([], 0)
                if f is not None:
                    f["loops"] += 1
                if w == "FOR":
                    m = re.match(r"FOR\s+([\w$#]+)\s+IN\s+(REVERSE\s+)?(.*?)\s+LOOP$", t, re.I | re.S)
                    if m:
                        src = m.group(3).strip()
                        if src.startswith("("):
                            sql = src.strip("() ")
                            for tbl, op in sql_tables(sql):
                                self.c.dep("table", tbl, s.line, op)
                                if f is not None:
                                    f["reads"].append(tbl)
                            txt = f"For each row {m.group(1)} of an inline query ({sql_describe(sql).rstrip('.')})"
                        elif ".." in src:
                            lo, hi = [x.strip() for x in src.split("..", 1)]
                            txt = f"Loops {m.group(1)} from {lo} to {hi}{' in reverse' if m.group(2) else ''}"
                        else:
                            cname = re.match(r"([\w$#]+)", src).group(1)
                            cdesc = self.cursors.get(cname.upper(), "")
                            txt = f"For each row {m.group(1)} returned by cursor {cname}" + (f" ({cdesc.rstrip('.')})" if cdesc else "")
                        self.c.note(s.line, "logic", f"{txt}: {self._sum(body)}.", 0.85, anchor)
                    continue
                if w == "WHILE":
                    cond = re.sub(r"^WHILE\s+|\s+LOOP$", "", t, flags=re.I)
                    self.c.note(s.line, "logic", f"Repeats while {shorten(verbalize_sql(cond), 100)}: {self._sum(body)}.", 0.8, anchor)
                    continue
                if w == "FORALL":
                    m = re.match(r"FORALL\s+([\w$#]+)\s+IN\s+(.*?)\s+(INSERT|UPDATE|DELETE|MERGE)(.*)$", t, re.I | re.S)
                    if m:
                        dml = m.group(3) + m.group(4)
                        for tbl, op in sql_tables(dml):
                            self.c.dep("table", tbl, s.line, op)
                            if f is not None:
                                f["writes"].append(tbl)
                        self.c.note(s.line, "io", f"Bulk DML (FORALL over {m.group(2)}): {sql_describe(dml)} One round-trip for the whole collection.", 0.85, anchor)
                    continue
                exit_seg = next((b for b in segs[i + 1:i + 40] if b.word == "EXIT"), None)
                cond = (" until " + re.sub(r"^EXIT\s+(WHEN\s+)?", "", exit_seg.text.rstrip(";"), flags=re.I)) if exit_seg else ""
                self.c.note(s.line, "logic", f"Basic loop{cond}: {self._sum(body)}.", 0.75, anchor)
                continue

            # ---- SQL
            if w in ("SELECT", "INSERT", "UPDATE", "DELETE", "MERGE", "WITH"):
                tables = sql_tables(t)
                for tbl, op in tables:
                    self.c.dep("table", tbl, s.line, op)
                    if f is not None:
                        (f["reads"] if op == "read" else f["writes"]).append(tbl)
                desc = sql_describe(t) or f"SQL: {shorten(t, 100)}."
                if w == "SELECT" and re.search(r"\bINTO\b", tu) and "BULK" not in tu:
                    desc += " Must return exactly one row (else NO_DATA_FOUND / TOO_MANY_ROWS)."
                if "FOR UPDATE" in tu:
                    desc += " Locks the selected rows until commit."
                if w in ("UPDATE", "DELETE") and not re.search(r"\bWHERE\b", tu):
                    self.c.note(s.line, "warning", f"{w} without a WHERE clause affects every row of the table.", 0.9, anchor)
                self.c.note(s.line, "io", desc, 0.85, anchor)
                continue
            if w == "OPEN":
                m = re.match(r"OPEN\s+([\w$#]+)(?:\s+FOR\s+(.*))?", t, re.I | re.S)
                if m and m.group(2):
                    for tbl, op in sql_tables(m.group(2)):
                        self.c.dep("table", tbl, s.line, op)
                    self.c.note(s.line, "io", f"Opens cursor variable {m.group(1)} for: {sql_describe(m.group(2)) or shorten(m.group(2), 80)}", 0.8, anchor)
                elif m:
                    self.c.note(s.line, "io", f"Opens cursor {m.group(1)} (executes its query).", 0.75, anchor, detail=True)
                continue
            if w == "FETCH":
                m = re.match(r"FETCH\s+([\w$#]+)\s+(BULK\s+COLLECT\s+)?INTO\s+(.*?)(?:\s+LIMIT\s+(\S+))?$", t, re.I | re.S)
                if m:
                    bulk = f" in batches of {m.group(4)}" if m.group(4) else (" (all rows at once)" if m.group(2) else "")
                    self.c.note(s.line, "io", f"Fetches {'rows' if m.group(2) else 'the next row'} of cursor {m.group(1)} into {shorten(m.group(3), 60)}{bulk}.", 0.8, anchor, detail=not m.group(2))
                continue
            if w == "COMMIT":
                if f is not None:
                    f["commits"] += 1
                if loop_depth:
                    self.c.note(s.line, "warning", "COMMIT inside a loop: a failure part-way leaves earlier batches committed "
                                "(restart logic needed) and can cause ORA-01555 on open cursors. Review transaction boundaries.", 0.9, anchor)
                else:
                    self.c.note(s.line, "logic", "Commits the transaction: all changes so far become permanent and visible to other sessions.", 0.85, anchor)
                continue
            if w == "ROLLBACK":
                self.c.note(s.line, "logic", "Rolls back " + ("to savepoint " + t.split()[-1] if " TO " in tu else "all uncommitted changes") + ".", 0.85, anchor)
                continue
            if w == "RAISE_APPLICATION_ERROR":
                m = re.match(r"RAISE_APPLICATION_ERROR\s*\(\s*(-?\d+)\s*,\s*(.*?)\)?$", t, re.I | re.S)
                if f is not None and m:
                    f["raises"].append(m.group(1))
                prev = segs[i - 1] if i else None
                guarded = prev is not None and (prev.ns.upper().endswith("THEN") or prev.word == "ELSE")
                if m:
                    self.c.note(s.line, "business-rule", f"Rejects the operation with error ORA{m.group(1)}: {shorten(m.group(2), 90)} (rolls back this call's work unless caught).",
                                0.85, anchor, detail=guarded)
                continue
            if w == "EXECUTE" and "IMMEDIATE" in tu:
                m = re.match(r"EXECUTE\s+IMMEDIATE\s+([\w$#]+)", t, re.I)
                inj = "||" in t or bool(m and m.group(1).upper() in self.concat_vars)
                if f is not None:
                    f["dynamic"] += 1
                self.c.note(s.line, "warning", "Dynamic SQL (EXECUTE IMMEDIATE): the statement is built at run time, so tables "
                            "and columns are invisible to static analysis." + (" It concatenates values into the SQL text: "
                            "SQL-injection and hard-parse risk; prefer bind variables." if inj else ""), 0.9, anchor)
                continue
            if w == "RETURN" and u and u.kind == "function":
                self.c.note(s.line, "logic", f"Returns {shorten(t[6:].strip(), 100)} to the caller.", 0.75, anchor, detail=True)
                continue
            if w == "GOTO":
                self.c.note(s.line, "warning", f"GOTO {t.split()[-1]}: unstructured jump; restructure when migrating.", 0.85, anchor)
                continue

            # ---- assignment / call
            if ":=" in t and w not in KEYWORDS:
                lhs, rhs = [x.strip() for x in t.split(":=", 1)]
                if "||" in rhs:
                    self.concat_vars.add(lhs.upper())
                self._calls_in(rhs, s.line, f)
                ru = rhs.upper()
                if ru.startswith("CASE"):
                    whens = re.findall(r"WHEN\s+(.*?)\s+THEN\s+(.*?)(?=\s+WHEN\s+|\s+ELSE\s+|\s+END\b)", rhs, re.I | re.S)
                    els = re.search(r"ELSE\s+(.*?)\s+END\b", rhs, re.I | re.S)
                    parts = [f"{shorten(verbalize_sql(c), 40)} → {shorten(v, 30)}" for c, v in whens[:6]]
                    if els:
                        parts.append(f"otherwise → {shorten(els.group(1), 30)}")
                    self.c.note(s.line, "business-rule", f"Derives {label(lhs)} by rule: " + "; ".join(parts) + ".", 0.8, anchor)
                    if f is not None:
                        f["rules"] += 1
                elif re.search(r"[-+*/]|\b(ROUND|TRUNC|MOD|POWER|ABS|CEIL|FLOOR|GREATEST|LEAST|NVL|ADD_MONTHS|MONTHS_BETWEEN)\s*\(", rhs, re.I) \
                        and not re.fullmatch(r"[\w$#.]+\s*[-+]\s*1", rhs):
                    self.c.note(s.line, "logic", f"Calculates {label(lhs)} = {arith(shorten(rhs, 140))}.", 0.8, anchor,
                                detail=id(s) in self.summarized)
                continue
            m = re.match(r"([A-Za-z_][\w$#]*(?:\.[A-Za-z_][\w$#]*)*)\s*(\(.*\))?$", t, re.S)
            if m and w not in KEYWORDS:
                self._call(m.group(1), m.group(2) or "", s.line, f, anchor)

        # :NEW / :OLD usage in triggers
        for u in self.units:
            if u.kind == "trigger":
                body = "\n".join(self.ns.splitlines()[u.line - 1:u.end])
                cols = sorted(set(re.findall(r":NEW\.([\w$#]+)", body, re.I)))
                if cols:
                    self.c.note(u.line, "data", f"Trigger reads/sets new row values: {join_list([c.lower() for c in cols], 8)} (:NEW = row after the change, :OLD = before).", 0.8, u.name, detail=True)

    def _calls_in(self, expr: str, line: int, f):
        for m in re.finditer(r"\b([A-Za-z_][\w$#]*)\.([A-Za-z_][\w$#]*)\s*\(", expr):
            pkg = m.group(1).upper()
            if pkg in ("DBMS_OUTPUT", "SYS", "STANDARD") or pkg.startswith(("R_", "REC", "L_REC", "V_REC")):
                continue
            self.c.dep("package", m.group(1), line, "call", f"{m.group(1)}.{m.group(2)}")
            if f is not None:
                f["calls"].append(f"{m.group(1)}.{m.group(2)}")

    def _call(self, name: str, args: str, line: int, f, anchor: str):
        up = name.upper()
        pkg = up.split(".")[0]
        if pkg == "DBMS_OUTPUT":
            return
        if pkg == "UTL_FILE":
            op = up.split(".")[-1]
            self.c.dep("file", "UTL_FILE (server directory)", line, op.lower())
            self.c.note(line, "io", f"UTL_FILE.{op}: server-side file I/O ({ {'FOPEN': 'opens a file', 'PUT_LINE': 'writes a line', 'GET_LINE': 'reads a line', 'FCLOSE': 'closes the file'}.get(op, op.lower()) }). Needs an Oracle DIRECTORY object; replace with storage/stream I/O on migration.", 0.8, anchor, detail=op not in ("FOPEN",))
            return
        if pkg in ("UTL_HTTP", "UTL_SMTP", "UTL_TCP", "UTL_MAIL"):
            self.c.dep("external", pkg, line, "network")
            self.c.note(line, "warning", f"{pkg}: the database makes an outbound network call. External integration to re-home in the target architecture.", 0.85, anchor)
            return
        if pkg == "DBMS_SQL":
            self.c.note(line, "warning", "DBMS_SQL dynamic SQL: statement text is only known at run time.", 0.85, anchor)
            return
        if pkg in ("DBMS_SCHEDULER", "DBMS_JOB"):
            self.c.dep("scheduler", up, line, "schedule")
            self.c.note(line, "dependency", f"{up}: schedules or controls a database job (hidden batch dependency).", 0.8, anchor)
            return
        kind = "package" if "." in name else "procedure"
        self.c.dep(kind, name.split(".")[0] if kind == "package" else name, line, "call", name)
        if f is not None:
            f["calls"].append(name)
        self.c.note(line, "dependency", f"Invokes {name}{'(' + shorten(args.strip('()'), 60) + ')' if args else ''} — {humanize(name.split('.')[-1])}.", 0.75, anchor, detail=True)

    # .............................................................. summaries
    @staticmethod
    def _params(header: str) -> tuple[list[str], list[str], str]:
        m = re.search(r"\((.*)\)", header, re.S)
        ins, outs = [], []
        if m:
            depth, cur, parts = 0, "", []
            for ch in m.group(1):
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                if ch == "," and depth == 0:
                    parts.append(cur)
                    cur = ""
                else:
                    cur += ch
            parts.append(cur)
            for p in parts:
                bits = p.split()
                if not bits:
                    continue
                mode = " ".join(bits[1:3]).upper()
                if mode.startswith("IN OUT"):
                    ins.append(bits[0])
                    outs.append(bits[0])
                elif mode.startswith("OUT"):
                    outs.append(bits[0])
                else:
                    ins.append(bits[0])
        r = re.search(r"\bRETURN\s+([\w$#.%]+)", header, re.I)
        return ins, outs, r.group(1) if r else ""

    def _summaries(self):
        for u in self.units:
            f = u.facts
            if u.kind in ("package", "package body", "type body"):
                members = [ch.name for ch in (u.node.children if u.node else [])]
                what = "Package specification (public API)" if u.kind == "package" else "Package body (implementation)"
                txt = f"{what} {u.name}: {len(members)} members" + (f" — {join_list(members, 8)}." if members else ".")
                self.c.note(u.line, "summary", txt, 0.85, u.name)
                continue
            parts = []
            if u.kind == "trigger":
                h = u.header or ""
                m = re.search(r"\b(BEFORE|AFTER|INSTEAD\s+OF)\s+(.*?)\s+ON\s+([\w$#.]+)", h, re.I)
                if m:
                    events = m.group(2).lower().replace(" or ", "/")
                    self.c.dep("table", m.group(3), u.line, "trigger")
                    each = " for each row" if re.search(r"FOR\s+EACH\s+ROW", h, re.I) else " once per statement"
                    when = re.search(r"\bWHEN\s*\((.*)\)", h, re.I)
                    parts.append(f"Fires {m.group(1).lower()} {events} on {m.group(3).upper()}{each}"
                                 + (f", only when {verbalize_sql(when.group(1))}" if when else "")
                                 + ". Hidden logic that runs on every matching DML: it must be carried into the target system")
            ins, outs, ret = self._params(u.header) if u.kind != "trigger" else ([], [], "")
            if ins:
                parts.append("inputs " + join_list(ins, 6))
            if outs:
                parts.append("outputs " + join_list(outs, 6))
            if f["reads"]:
                parts.append("reads " + join_list(sorted(set(f["reads"]))))
            if f["writes"]:
                parts.append("modifies " + join_list(sorted(set(f["writes"]))))
            if f["calls"]:
                parts.append("calls " + join_list(sorted(set(f["calls"])), 4))
            if f["rules"]:
                parts.append(f"enforces {f['rules']} business rule{'s' if f['rules'] > 1 else ''}")
            if f["raises"]:
                parts.append("can reject with " + join_list([f"ORA{r}" for r in f["raises"]]))
            if f["commits"]:
                parts.append("commits its own transaction")
            if f["dynamic"]:
                parts.append("uses dynamic SQL")
            if ret:
                parts.append(f"returns {ret}")
            purpose = humanize(u.name)
            head = f"{u.kind.title()} {u.name}" + (f" — {purpose}" if purpose and u.kind != "block" else "") + "."
            body = "; ".join(parts)
            txt = head + (" " + body[0].upper() + body[1:] + "." if body else "")
            self.c.note(u.line, "summary", txt, 0.85, u.name)
            self.c.facts.setdefault("units", []).append({"name": u.name, "line": u.line, "kind": u.kind})

        top = [u for u in self.units if u.kind in ("package", "package body")]
        procs = [u for u in self.units if u.kind in ("procedure", "function", "trigger")]
        tables = [d.name for d in self.c.dependencies if d.kind == "table"]
        writes = sorted({t for u in self.units for t in u.facts["writes"]})
        calls = [d.name for d in self.c.dependencies if d.kind in ("package", "procedure")]
        parts = []
        if top:
            parts.append(f"PL/SQL {top[0].kind} {top[0].name}.")
        parts.append(f"{len(procs)} procedures/functions/triggers.")
        if tables:
            parts.append("Tables used: " + join_list(tables, 8) + ".")
        if writes:
            parts.append("Tables modified: " + join_list(writes, 8) + ".")
        if calls:
            parts.append("External calls: " + join_list(calls, 6) + ".")
        rules = sum(u.facts["rules"] for u in self.units)
        parts.append(f"{rules} business rules detected.")
        self.c.summary = " ".join(parts)

    def run(self) -> Collector:
        self._blocks()
        self._statements()
        self._summaries()
        self.c.facts["comment_lines"] = len(self.comment_lines)
        return self.c


def analyze(text: str) -> Collector:
    return PlsqlAnalyzer(text).run()
