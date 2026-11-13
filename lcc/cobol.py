"""COBOL analyzer (fixed and free format, programs and copybooks)."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from .models import Collector, OutlineNode
from .vocab import arith, humanize, join_list, label, shorten, sql_describe, sql_tables, verbalize_cobol

VERBS = {
    "ACCEPT", "ADD", "ALTER", "CALL", "CANCEL", "CLOSE", "COMPUTE", "CONTINUE", "DELETE", "DISPLAY",
    "DIVIDE", "EVALUATE", "EXEC", "EXIT", "GO", "GOBACK", "IF", "INITIALIZE", "INSPECT", "MERGE", "MOVE",
    "MULTIPLY", "OPEN", "PERFORM", "READ", "RELEASE", "RETURN", "REWRITE", "SEARCH", "SET", "SORT",
    "START", "STOP", "STRING", "SUBTRACT", "UNSTRING", "WRITE",
}
STRUCT = {"ELSE", "END-IF", "END-EVALUATE", "END-PERFORM", "WHEN", "END-SEARCH", "."}
SCOPE_END = {"END-READ", "END-WRITE", "END-COMPUTE", "END-ADD", "END-SUBTRACT", "END-MULTIPLY",
             "END-DIVIDE", "END-CALL", "END-STRING", "END-UNSTRING", "END-RETURN", "END-REWRITE",
             "END-START", "END-DELETE", "END-ACCEPT", "END-DISPLAY"}
RESERVED_PARA = {"EXIT", "GOBACK", "CONTINUE", "END-IF", "END-EVALUATE", "END-PERFORM", "ELSE",
                 "STOP", "END-EXEC", "END-READ", "END-WRITE", "END-SEARCH"}
TECH_WORDS = re.compile(r"EOF|END-OF|FILE-STAT|-FS\b|^FS-|SQLCODE|SQLSTATE|RETURN-CODE|RETURN-CD|-RC\b|EIBRESP|"
                        r"-SW\b|SWITCH|FLAG|FIRST-TIME|MORE-", re.I)

TOKEN = re.compile(
    r"'(?:[^']|'')*'?|\"(?:[^\"]|\"\")*\"?"
    r"|[+-]?[0-9]+(?:\.[0-9]+)?(?=[\s.,;)]|$)"
    r"|[A-Za-z0-9][A-Za-z0-9-]*"
    r"|>=|<=|\*\*|[=<>()+\-*/,:;&]"
    r"|\.(?=\s|$)|\S"
)


@dataclass
class Stmt:
    verb: str
    toks: list[str]
    line: int
    para: str = ""


@dataclass
class Node:
    stmt: Stmt
    kind: str = "simple"          # simple | if | evaluate | perform | search
    then: list = field(default_factory=list)
    other: list = field(default_factory=list)
    whens: list = field(default_factory=list)   # [(Stmt, [Node])]


@dataclass
class DataItem:
    level: int
    name: str
    line: int
    text: str
    pic: str = ""
    usage: str = ""
    occurs: int = 1
    redefines: str = ""
    children: list = field(default_factory=list)
    size: int = 0


# ------------------------------------------------------------------ format helpers
def detect_format(lines: list[str]) -> str:
    text = "\n".join(lines[:50]).upper()
    if ">>SOURCE FORMAT FREE" in text or ">>SOURCE FREE" in text:
        return "free"
    fixed = total = 0
    for ln in lines:
        if not ln.strip():
            continue
        total += 1
        if len(ln) >= 7 and ln[6] in " *-/Dd" and (not ln[:6].strip() or ln[:6].strip().isalnum()):
            fixed += 1
        elif len(ln) < 7 and not ln.strip():
            fixed += 1
    return "fixed" if total and fixed / total >= 0.8 else "free"


def _strip_inline(code: str) -> str:
    out, q = [], ""
    i = 0
    while i < len(code):
        c = code[i]
        if q:
            if c == q:
                q = ""
        elif c in "'\"":
            q = c
        elif code.startswith("*>", i):
            break
        out.append(c)
        i += 1
    return "".join(out)


def logical_lines(lines: list[str], fmt: str):
    """Yield (lineno, code, area_a, is_comment)."""
    for i, ln in enumerate(lines, 1):
        if fmt == "fixed":
            ind = ln[6] if len(ln) > 6 else " "
            if ind in "*/" or ind in "Dd":
                yield i, "", False, ind in "*/"
                continue
            code = ln[7:72] if len(ln) > 7 else ""
            area_a = bool(ln[7:11].strip()) if len(ln) > 7 else False
            stripped = _strip_inline(code)
            yield i, stripped.rstrip(), area_a, False
        else:
            s = ln.strip()
            if s.startswith("*>") or s.startswith(">>"):
                yield i, "", False, s.startswith("*>")
                continue
            code = _strip_inline(ln)
            yield i, code.rstrip(), (len(ln) - len(ln.lstrip())) < 4, False


_WORDCH = "A-Z0-9-"
_LIT = re.compile(r"('[^']*'?|\"[^\"]*\"?)")


def _upper_code(code: str) -> str:
    """COBOL is case-insensitive: normalise code to upper case, leaving literals untouched."""
    return "".join(part if part[:1] in ("'", '"') else part.upper() for part in _LIT.split(code))


def parse_replacing(text: str) -> list[tuple[str, str, str]]:
    """'==:P:== BY ==WS== LEADING ==X-== BY ==Y-==' -> [(mode, old, new)] (mode TEXT/LEADING/TRAILING)."""
    pairs = []
    text = re.sub(r"\.\s*$", "", text.strip())
    for m in re.finditer(r"(LEADING\s+|TRAILING\s+)?(==.*?==|'[^']*'|\S+)\s+BY\s+(==.*?==|'[^']*'|\S+)", text, re.I):
        mode = (m.group(1) or "").strip().upper() or "TEXT"
        old, new = m.group(2), m.group(3)
        old = old[2:-2] if old.startswith("==") else old
        new = new[2:-2] if new.startswith("==") else new
        old, new = " ".join(old.split()).upper(), " ".join(new.split()).upper()
        if old:
            pairs.append((mode, old, new))
    return pairs


def apply_replacing(code: str, pairs: list[tuple[str, str, str]]) -> str:
    """Apply REPLACE / COPY REPLACING substitutions outside literals."""
    def sub(seg: str) -> str:
        for mode, old, new in pairs:
            if mode == "LEADING":
                seg = re.sub(rf"(?<![{_WORDCH}]){re.escape(old)}", lambda m: new, seg)
            elif mode == "TRAILING":
                seg = re.sub(rf"{re.escape(old)}(?![{_WORDCH}])", lambda m: new, seg)
            else:
                pat = r"\s+".join(re.escape(t) for t in old.split())
                lb = rf"(?<![{_WORDCH}])" if re.match(r"[A-Z0-9]", old) else ""
                la = rf"(?![{_WORDCH}])" if re.search(r"[A-Z0-9]$", old) else ""
                seg = re.sub(lb + pat + la, lambda m: new, seg)
        return seg
    return "".join(p if p[:1] in ("'", '"') else sub(p) for p in _LIT.split(code))


def prepare(lines: list[str], fmt: str, replacing: list | None = None):
    """Logical lines after compile-time text manipulation, with line numbers preserved.

    Returns (rows, events). rows: (lineno, code, area_a, is_comment) with code upper-cased outside
    literals, REPLACE / COPY REPLACING applied, and REPLACE / END PROGRAM statements blanked out.
    events: ("replace", line, pairs) | ("replace-off", line, []) | ("end-program", line, name).
    """
    rows, events = [], []
    active: list = []
    pending: list | None = None
    for lineno, code, area_a, is_com in logical_lines(lines, fmt):
        code = _upper_code(code)
        u = code.strip()
        if pending is not None:
            pending[1] += " " + u
            rows.append((lineno, "", False, False))
            if re.search(r"\.\s*$", u):
                active = parse_replacing(pending[1][len("REPLACE"):])
                events.append(("replace", pending[0], active))
                pending = None
            continue
        if re.match(rf"REPLACE(?![{_WORDCH}])", u):
            rows.append((lineno, "", False, False))
            if re.match(r"REPLACE\s+(LAST\s+)?OFF\b", u):
                active = []
                events.append(("replace-off", lineno, []))
            elif re.search(r"\.\s*$", u):
                active = parse_replacing(u[len("REPLACE"):])
                events.append(("replace", lineno, active))
            else:
                pending = [lineno, u]
            continue
        m = re.match(r"END\s+PROGRAM\s+['\"]?([A-Z0-9][A-Z0-9-]*)", u)
        if m:
            events.append(("end-program", lineno, m.group(1)))
            rows.append((lineno, "", False, False))
            continue
        if replacing:
            code = apply_replacing(code, replacing)
        if active:
            code = apply_replacing(code, active)
        rows.append((lineno, code, area_a, is_com))
    return rows, events


def find_copies(rows) -> list[tuple[int, str, list]]:
    """COPY statements (which may span lines): [(line, member, replacing_pairs)]."""
    parts, starts, pos = [], [], 0
    for lineno, code, _, _ in rows:
        if code.strip():
            starts.append((pos, lineno))
            parts.append(code)
            pos += len(code) + 1
    text = " ".join(parts)
    out = []
    rx = re.compile(rf"(?<![{_WORDCH}])COPY\s+(['\"]?)([A-Z0-9][A-Z0-9-]*)\1(?:\s+(?:OF|IN)\s+[A-Z0-9-]+)?"
                    r"(?:\s+SUPPRESS)?(?:\s+REPLACING\s+(.*?))?\s*\.(?=\s|$)", re.S)
    for m in rx.finditer(text):
        line = next((ln for p, ln in reversed(starts) if p <= m.start()), 1)
        out.append((line, m.group(2), parse_replacing(m.group(3) or "")))
    return out


def describe_pairs(pairs) -> str:
    return join_list([f"'{o}' -> '{n}'" + (f" ({mode.lower()})" if mode != "TEXT" else "") for mode, o, n in pairs], 4)


def count_comments(lines: list[str], fmt: str) -> int:
    n = 0
    for ln in lines:
        if fmt == "fixed" and len(ln) > 6 and ln[6] in "*/":
            n += 1
        elif ln.strip().startswith("*>") or (fmt == "free" and "*>" in ln):
            n += 1
    return n


# ------------------------------------------------------------------ PIC helpers
def pic_info(pic: str, usage: str) -> dict:
    p = pic.upper().rstrip(".")
    exp = re.sub(r"(.)\((\d+)\)", lambda m: m.group(1) * int(m.group(2)), p)
    signed = exp.startswith("S")
    info = {"signed": signed, "int": 0, "dec": 0, "len": 0, "cat": "alphanumeric"}
    if exp and set(exp) <= set("9SVP"):
        body = exp.replace("S", "")
        ip, _, dp = body.partition("V")
        info.update(cat="numeric", int=ip.count("9"), dec=dp.count("9"))
        digits = info["int"] + info["dec"]
        info["len"] = digits
    elif exp and set(exp) <= set("X"):
        info.update(cat="alphanumeric", len=len(exp))
    elif exp and set(exp) <= set("A"):
        info.update(cat="alphabetic", len=len(exp))
    else:
        info.update(cat="numeric-edited" if re.search(r"[9Z*]", exp) else "alphanumeric", len=len(exp))
    digits = info["int"] + info["dec"]
    u = usage.upper()
    if info["cat"] == "numeric":
        if u in ("COMP-3", "PACKED-DECIMAL", "COMPUTATIONAL-3"):
            info["bytes"] = digits // 2 + 1
        elif u in ("COMP", "COMP-4", "COMP-5", "BINARY", "COMPUTATIONAL", "COMPUTATIONAL-4", "COMPUTATIONAL-5"):
            info["bytes"] = 2 if digits <= 4 else 4 if digits <= 9 else 8
        else:
            info["bytes"] = digits
    else:
        info["bytes"] = info["len"]
    if u in ("COMP-1", "COMPUTATIONAL-1"):
        info["bytes"] = 4
    if u in ("COMP-2", "COMPUTATIONAL-2"):
        info["bytes"] = 8
    if u in ("INDEX", "POINTER"):
        info["bytes"] = 4
    return info


def modern_type(info: dict, usage: str) -> str:
    if info["cat"] == "numeric":
        digits = info["int"] + info["dec"]
        if info["dec"]:
            return f"DECIMAL({digits},{info['dec']}) / BigDecimal"
        if usage.upper().startswith(("COMP", "BINARY")) and "3" not in usage:
            return "int" if digits <= 9 else "long"
        return f"DECIMAL({digits},0) / long" if digits > 9 else f"DECIMAL({digits},0) / int"
    if info["cat"] == "numeric-edited":
        return "formatted display string (format on output)"
    return f"CHAR({info['len']}) / String"


# ------------------------------------------------------------------ main analyzer
class CobolAnalyzer:
    def __init__(self, lines: list[str], fmt: str | None = None, replacing: list | None = None):
        self.lines = lines
        self.fmt = fmt or detect_format(lines)
        self.replacing = replacing or []
        self.c = Collector()
        self.conditions: dict[str, tuple[str, str]] = {}   # 88 name -> (parent, values)
        self.files: dict[str, dict] = {}                    # logical file -> info
        self.record_file: dict[str, str] = {}               # record name -> file
        self.paragraphs: dict[str, dict] = {}               # name -> facts
        self.para_order: list[str] = []
        self.program_id = ""
        self.program_line = 0
        self.open_modes: dict[str, str] = {}
        self.level01: list[str] = []
        self.resolved: dict[str, int] = {}                  # copybook -> definitions imported

    # .............................................................. entry
    def run(self) -> Collector:
        ll, events = prepare(self.lines, self.fmt, self.replacing)
        divisions: list[OutlineNode] = []
        current_div = None
        current_sec = None
        data_lines, env_lines, proc_lines = [], [], []
        section_name = ""
        has_div = any(re.match(r"\s*(IDENTIFICATION|ID|PROCEDURE|DATA)\s+DIVISION", c, re.I) for _, c, _, _ in ll)
        self.last_line = max((ln for ln, code, _, _ in ll if code.strip()), default=len(self.lines))

        for kind, line, data in events:
            if kind == "replace":
                self.c.note(line, "logic", f"REPLACE: from here on the compiler substitutes {describe_pairs(data)} in "
                            "the source text. The explanations below already use the replaced text.", 0.85)
            elif kind == "replace-off":
                self.c.note(line, "logic", "REPLACE OFF: compile-time text substitution stops here.", 0.85)
        for line, name, pairs in find_copies(ll):
            self.c.dep("copybook", name, line, "include")
            if name in self.resolved:
                msg = (f"Includes copybook {name} (found in this upload): its {self.resolved[name]} "
                       "field and condition definitions are used to explain the logic below.")
            else:
                msg = (f"Includes copybook {name}: its source is inserted here at compile time "
                       f"(typically a shared record layout). Upload {name} too to resolve its fields.")
            if pairs:
                msg += f" REPLACING {describe_pairs(pairs)} customises the copied names for this program."
            self.c.note(line, "dependency", msg, 0.9)

        for lineno, code, area_a, _ in ll:
            if not code.strip():
                continue
            u = code.strip().upper()
            m = re.match(r"(IDENTIFICATION|ID|ENVIRONMENT|DATA|PROCEDURE)\s+DIVISION\b(.*)", u)
            if m:
                name = "IDENTIFICATION" if m.group(1) == "ID" else m.group(1)
                current_div = OutlineNode(f"{name} DIVISION", "division", lineno)
                divisions.append(current_div)
                current_sec = None
                section_name = name
                if name == "PROCEDURE":
                    using = re.search(r"USING\s+(.*?)\.?$", m.group(2))
                    if using:
                        self.c.note(lineno, "data", "Program entry parameters (passed by the caller): "
                                    + join_list(using.group(1).replace(",", " ").split()) + ".", 0.85)
                continue
            m = re.search(r"PROGRAM-ID\.?\s+([A-Z0-9][A-Z0-9-]*)", u)
            if m and not self.program_id:
                self.program_id, self.program_line = m.group(1), lineno
            if section_name == "PROCEDURE" or (not has_div and not re.match(r"\d{1,2}\s", u) and not u.startswith(("FD ", "SD "))):
                if not has_div and section_name != "PROCEDURE":
                    section_name = "PROCEDURE"
                ms = re.match(r"([A-Z0-9][A-Z0-9-]*)\s+SECTION\s*\.(.*)$", u)
                mp = re.match(r"([A-Z0-9][A-Z0-9-]*)\s*\.(\s+.*)?$", u)
                if ms and (area_a or self.fmt == "free"):
                    current_sec = OutlineNode(ms.group(1), "section", lineno)
                    (current_div.children if current_div else divisions).append(current_sec)
                    self._start_para(ms.group(1), lineno, "section")
                    rest = ms.group(2).strip()
                    if rest:
                        proc_lines.append((lineno, rest))
                    continue
                if mp and (area_a or self.fmt == "free") and mp.group(1) not in RESERVED_PARA \
                        and not mp.group(1).startswith("END-"):
                    node = OutlineNode(mp.group(1), "paragraph", lineno)
                    parent = current_sec or current_div
                    (parent.children if parent else divisions).append(node)
                    self._start_para(mp.group(1), lineno, "paragraph",
                                     current_sec.name if current_sec is not None and current_sec.kind == "section" else "")
                    rest = (mp.group(2) or "").strip()
                    if rest:
                        proc_lines.append((lineno, rest))
                    continue
                proc_lines.append((lineno, code))
            elif section_name == "DATA" or (not has_div):
                ms = re.match(r"([A-Z0-9-]+)\s+SECTION\s*\.", u)
                if ms:
                    current_sec = OutlineNode(f"{ms.group(1)} SECTION", "section", lineno)
                    (current_div.children if current_div else divisions).append(current_sec)
                    data_lines.append((lineno, f"\x00SECTION {ms.group(1)}."))
                    continue
                data_lines.append((lineno, code))
            elif section_name == "ENVIRONMENT":
                ms = re.match(r"([A-Z0-9-]+)\s+SECTION\s*\.", u)
                if ms:
                    current_sec = OutlineNode(f"{ms.group(1)} SECTION", "section", lineno)
                    (current_div.children if current_div else divisions).append(current_sec)
                    continue
                env_lines.append((lineno, code))

        self._env(env_lines)
        self._data(data_lines, divisions)
        self._procedure(proc_lines)
        self._close_outline(divisions, self.last_line)
        self.c.outline = divisions
        self._summaries()
        return self.c

    def _start_para(self, name: str, line: int, kind: str, section: str = ""):
        self.paragraphs[name] = {"line": line, "kind": kind, "performs": [], "loops": [], "reads": [],
                                 "writes": [], "computes": [], "rules": 0, "calls": [], "sql": [],
                                 "gotos": [], "ends": False, "displays": 0, "stmts": 0, "exits": 0,
                                 "section": section}
        self.para_order.append(name)

    def _close_outline(self, nodes: list[OutlineNode], last: int):
        for i, n in enumerate(nodes):
            n.end_line = (nodes[i + 1].line - 1) if i + 1 < len(nodes) else last
            if n.children:
                self._close_outline(n.children, n.end_line)

    # .............................................................. entries joined to the period
    @staticmethod
    def _entries(lines):
        buf, start = [], 0
        for lineno, code in lines:
            if not buf:
                start = lineno
            buf.append(code.strip())
            joined = " ".join(buf)
            if re.search(r"\.\s*$", joined) and joined.count("'") % 2 == 0:
                yield start, joined.rstrip(". ").strip()
                buf = []
        if buf:
            yield start, " ".join(buf).rstrip(". ").strip()

    # .............................................................. ENVIRONMENT DIVISION
    def _env(self, lines):
        for line, text in self._entries(lines):
            u = text.upper()
            m = re.search(r"SELECT\s+(?:OPTIONAL\s+)?([A-Z0-9-]+)\s+ASSIGN\s+(?:TO\s+)?(\S+)", u)
            if not m:
                continue
            fname, assign = m.group(1), m.group(2).strip("'\"")
            dd = re.sub(r"^(?:UT|DA|UR)-(?:S|D|R|I)-", "", assign)
            org = re.search(r"ORGANIZATION\s+(?:IS\s+)?(LINE\s+SEQUENTIAL|INDEXED|SEQUENTIAL|RELATIVE)", u)
            acc = re.search(r"ACCESS\s+(?:MODE\s+)?(?:IS\s+)?(SEQUENTIAL|RANDOM|DYNAMIC)", u)
            key = re.search(r"RECORD\s+KEY\s+(?:IS\s+)?([A-Z0-9-]+)", u)
            fs = re.search(r"FILE\s+STATUS\s+(?:IS\s+)?([A-Z0-9-]+)", u)
            organization = (org.group(1).lower() if org else "sequential")
            self.files[fname] = {"dd": dd, "org": organization, "line": line}
            self.c.dep("file", fname, line, "", f"DD/assign {dd}")
            text_out = f"Logical file {fname} is bound to external name {dd} (the JCL DD statement or environment variable that supplies the dataset)."
            if organization == "indexed":
                text_out += " Indexed organisation (typically VSAM KSDS)"
                text_out += f" keyed on {key.group(1)}." if key else "."
            elif organization != "sequential":
                text_out += f" Organisation: {organization}."
            if acc and acc.group(1) != "SEQUENTIAL":
                text_out += f" Access mode {acc.group(1).lower()} (records fetched by key)."
            if fs:
                text_out += f" I/O status codes land in {fs.group(1)}."
            self.c.note(line, "io", text_out, 0.9)

    # .............................................................. DATA DIVISION
    def _data(self, lines, divisions):
        items: list[DataItem] = []
        current_fd = None
        last_parent = None
        stack: list[DataItem] = []
        for line, text in self._entries(lines):
            u = text.upper()
            if u.startswith("\x00SECTION"):
                current_fd, stack = None, []
                continue
            m = re.match(r"(FD|SD)\s+([A-Z0-9-]+)", u)
            if m:
                current_fd = m.group(2)
                info = self.files.get(current_fd, {})
                kind = "Sort work file" if m.group(1) == "SD" else "File description"
                extra = f" (external name {info['dd']})" if info.get("dd") else ""
                self.c.note(line, "io", f"{kind} for {current_fd}{extra}: the record layout(s) that follow describe each record read from or written to it.", 0.9)
                stack = []
                continue
            m = re.match(r"(\d{1,2})\s+([A-Z0-9][A-Z0-9-]*)?\s*(.*)$", u)
            if not m:
                continue
            level = int(m.group(1))
            name = m.group(2) or "FILLER"
            rest = m.group(3) or ""
            if name in ("PIC", "PICTURE", "VALUE", "VALUES", "REDEFINES", "OCCURS", "USAGE"):
                rest = name + " " + rest
                name = "FILLER"
            if level == 88:
                vm = re.search(r"VALUES?\s+(?:ARE\s+|IS\s+)?(.*)$", rest)
                vals = vm.group(1) if vm else rest
                vals = re.sub(r"\s+(THRU|THROUGH)\s+", " through ", vals)
                vals = ", ".join(v for v in re.split(r"\s*,\s*|\s+(?=(?:'[^']*'|[^'\s]+)(?:\s|$))", vals) if v)
                parent = last_parent.name if last_parent else "?"
                self.conditions[name] = (parent, vals)
                kind = "data" if TECH_WORDS.search(parent) or TECH_WORDS.search(name) else "business-rule"
                pretty = humanize(name)
                self.c.note(line, kind, f"Condition-name {name} ({pretty}) is true when {parent} is {vals}. "
                            f"'IF {name}' and 'SET {name} TO TRUE' test/assign this value.", 0.85)
                continue
            if level == 66:
                continue
            item = DataItem(level=level, name=name, line=line, text=rest)
            pm = re.search(r"\bPIC(?:TURE)?\s+(?:IS\s+)?(\S+)", rest)
            if pm:
                item.pic = pm.group(1)
            um = re.search(r"\b(COMP(?:UTATIONAL)?(?:-[1-5])?|PACKED-DECIMAL|BINARY|INDEX|POINTER)\b", rest)
            if um:
                item.usage = um.group(1)
            om = re.search(r"\bOCCURS\s+(\d+)(?:\s+TO\s+(\d+))?", rest)
            if om:
                item.occurs = int(om.group(2) or om.group(1))
            rm = re.search(r"\bREDEFINES\s+([A-Z0-9-]+)", rest)
            if rm:
                item.redefines = rm.group(1)
            # place in hierarchy
            if level in (1, 77):
                self.level01.append(name)
                stack = [item]
                items.append(item)
                if current_fd and level == 1:
                    self.record_file[name] = current_fd
            else:
                while stack and stack[-1].level >= level:
                    stack.pop()
                if stack:
                    stack[-1].children.append(item)
                else:
                    items.append(item)
                stack.append(item)
            last_parent = item
            self._annotate_item(item, rest)

        for it in items:
            self._size(it)
            if it.level == 1 and it.children:
                n_fields = self._count_fields(it)
                owner = f" (record of file {self.record_file[it.name]})" if it.name in self.record_file else ""
                packed, binary = self._usage_names(it)
                extra = ""
                if packed:
                    extra += (f" Packed-decimal (COMP-3) fields {join_list(packed, 4)} hold exact money/quantity "
                              "values: map them to DECIMAL/BigDecimal, never to floating point.")
                if binary:
                    extra += f" Binary (COMP) fields: {join_list(binary, 4)}."
                self.c.note(it.line, "data",
                            f"Record layout {label(it.name)}{owner}: {n_fields} elementary fields, "
                            f"about {it.size} bytes. Maps naturally to a class/DTO or table row.{extra}",
                            0.8)

    def _usage_names(self, item: DataItem) -> tuple[list[str], list[str]]:
        packed, binary = [], []
        for ch in item.children:
            if ch.children:
                p, b = self._usage_names(ch)
                packed += p
                binary += b
            elif ch.usage.upper() in ("COMP-3", "PACKED-DECIMAL", "COMPUTATIONAL-3"):
                packed.append(ch.name)
            elif ch.usage.upper().startswith(("COMP", "BINARY")) and ch.usage.upper() not in ("COMP-1", "COMP-2"):
                binary.append(ch.name)
        return packed, binary

    def _annotate_item(self, item: DataItem, rest: str):
        if item.redefines:
            self.c.note(item.line, "warning",
                        f"{item.name} REDEFINES {item.redefines}: both names share the same storage, so the bytes are "
                        f"read two different ways. Migration must model this as a union/variant or explicit conversion.",
                        0.85)
        om = re.search(r"\bOCCURS\s+(\d+)(?:\s+TO\s+(\d+))?.*?(?:DEPENDING\s+ON\s+([A-Z0-9-]+))?(?:.*?INDEXED\s+BY\s+([A-Z0-9-]+))?", rest)
        if om:
            n = om.group(2) or om.group(1)
            txt = f"{item.name} is a table (array) of {n} entries"
            if om.group(3):
                txt += f"; the active entry count is held in {om.group(3)} (variable-length)"
            if om.group(4):
                txt += f"; walked with index {om.group(4)}"
            self.c.note(item.line, "data", txt + ". Indexes/subscripts are 1-based in COBOL.", 0.85)
        if item.pic:
            info = pic_info(item.pic, item.usage)
            u = item.usage.upper()
            if info["cat"] == "numeric" and u in ("COMP-3", "PACKED-DECIMAL", "COMPUTATIONAL-3"):
                self.c.note(item.line, "data",
                            f"{item.name}: packed decimal (COMP-3), {'signed, ' if info['signed'] else ''}"
                            f"{info['int']} integer + {info['dec']} decimal digits in {info['bytes']} bytes. "
                            f"Target type: {modern_type(info, u)}.", 0.9, detail=True)
            elif info["cat"] == "numeric" and u.startswith(("COMP", "BINARY")):
                self.c.note(item.line, "data",
                            f"{item.name}: binary integer ({u}), {info['bytes']} bytes. Target type: {modern_type(info, u)}.",
                            0.85, detail=True)
            elif info["cat"] == "numeric" and info["dec"]:
                self.c.note(item.line, "data",
                            f"{item.name}: zoned decimal with an implied decimal point ({info['int']}.{info['dec']} digits; "
                            f"no '.' is stored). Target type: {modern_type(info, u)}.", 0.8, detail=True)

    def _size(self, item: DataItem) -> int:
        if item.children:
            total = sum(self._size(ch) for ch in item.children if not ch.redefines)
        elif item.pic:
            total = pic_info(item.pic, item.usage)["bytes"]
        else:
            total = pic_info("X", item.usage)["bytes"] if item.usage else 0
        item.size = total * max(1, item.occurs)
        return item.size

    def _count_fields(self, item: DataItem) -> int:
        if not item.children:
            return 1
        return sum(self._count_fields(c) for c in item.children)

    # .............................................................. PROCEDURE DIVISION
    def _procedure(self, proc_lines):
        para_at = sorted((v["line"], k) for k, v in self.paragraphs.items())
        stmts: list[Stmt] = []

        def para_for(line: int) -> str:
            name = ""
            for pl, pn in para_at:
                if pl <= line:
                    name = pn
                else:
                    break
            return name

        cur: Stmt | None = None
        exec_stmt: Stmt | None = None
        exec_rx = re.compile(r"\bEXEC(?:UTE)?\b", re.I)
        end_rx = re.compile(r"\bEND-EXEC\b", re.I)

        def tokenize(lineno: int, code: str):
            nonlocal cur
            for tok in TOKEN.findall(code):
                up = tok.upper()
                if up in VERBS or up in STRUCT:
                    cur = Stmt(up, [], lineno, para_for(lineno))
                    stmts.append(cur)
                    if up == ".":
                        cur = None
                    continue
                if up in SCOPE_END:
                    continue
                if cur is None:
                    cur = Stmt("?", [], lineno, para_for(lineno))
                    stmts.append(cur)
                cur.toks.append(tok)

        for lineno, code in proc_lines:
            rest = code
            while rest:
                if exec_stmt is not None:
                    m = end_rx.search(rest)
                    if not m:
                        exec_stmt.toks.extend(rest.split())
                        rest = ""
                        break
                    exec_stmt.toks.extend(rest[:m.start()].split())
                    exec_stmt = None
                    rest = rest[m.end():]
                    continue
                m = exec_rx.search(rest)
                if not m or rest[:m.start()].count("'") % 2:
                    tokenize(lineno, rest)
                    break
                tokenize(lineno, rest[:m.start()])
                exec_stmt = cur = Stmt("EXEC", [], lineno, para_for(lineno))
                stmts.append(cur)
                rest = rest[m.end():]

        self.stmts = stmts
        self._pos = 0
        tree = self._block(set())
        for node in tree:
            self._walk(node, 0)

    def _block(self, stops: set) -> list[Node]:
        nodes: list[Node] = []
        st = self.stmts
        while self._pos < len(st):
            s = st[self._pos]
            v = s.verb
            if v in stops:
                return nodes
            if v == ".":
                self._pos += 1
                continue
            if v in ("ELSE", "END-IF", "END-EVALUATE", "END-PERFORM", "END-SEARCH", "WHEN"):
                self._pos += 1     # stray terminator
                continue
            if v == "IF":
                node = Node(s, "if")
                self._pos += 1
                inner = {"ELSE", "END-IF", ".", "WHEN", "END-EVALUATE", "END-PERFORM", "END-SEARCH"}
                node.then = self._block(inner)
                if self._pos < len(st) and st[self._pos].verb == "ELSE":
                    self._pos += 1
                    node.other = self._block(inner)
                if self._pos < len(st) and st[self._pos].verb == "END-IF":
                    self._pos += 1
                nodes.append(node)
                continue
            if v in ("EVALUATE", "SEARCH"):
                node = Node(s, "evaluate" if v == "EVALUATE" else "search")
                end = "END-EVALUATE" if v == "EVALUATE" else "END-SEARCH"
                self._pos += 1
                if v == "SEARCH":
                    node.then = self._block({"WHEN", end, "."})
                while self._pos < len(st) and st[self._pos].verb == "WHEN":
                    w = st[self._pos]
                    self._pos += 1
                    body = self._block({"WHEN", end, ".", "END-PERFORM", "END-IF"})
                    node.whens.append((w, body))
                if self._pos < len(st) and st[self._pos].verb == end:
                    self._pos += 1
                nodes.append(node)
                continue
            if v == "PERFORM" and self._is_inline_perform(s):
                node = Node(s, "perform")
                self._pos += 1
                node.then = self._block({"END-PERFORM", ".", "ELSE", "END-IF", "WHEN", "END-EVALUATE"})
                if self._pos < len(st) and st[self._pos].verb == "END-PERFORM":
                    self._pos += 1
                nodes.append(node)
                continue
            nodes.append(Node(s))
            self._pos += 1
        return nodes

    def _is_inline_perform(self, s: Stmt) -> bool:
        t = [x.upper() for x in s.toks]
        if not t:
            return True
        if t[0] in ("UNTIL", "VARYING", "WITH", "TEST", "FOREVER"):
            return True
        if len(t) >= 2 and t[1] == "TIMES" and t[0] not in self.paragraphs:
            return True
        return False

    # .............................................................. descriptions
    def _brief(self, node: Node) -> str:
        s = node.stmt
        t = s.toks
        tu = [x.upper() for x in t]
        v = s.verb
        if node.kind == "if":
            return "check " + shorten(verbalize_cobol(" ".join(x for x in t if x.upper() != "THEN"), self.conditions), 60)
        if node.kind == "evaluate":
            subj = " ".join(t)
            return "apply a decision table" if subj.upper() in ("", "TRUE") else f"decide on {subj}"
        if node.kind == "perform":
            return "loop " + shorten(" ".join(t), 50)
        if v == "MOVE" and "TO" in tu:
            k = tu.index("TO")
            return f"set {join_list(t[k + 1:], 3)} to {' '.join(t[:k])}"
        if v == "COMPUTE":
            target = t[0] if t else "?"
            return f"compute {target}"
        if v == "ADD" and "TO" in tu:
            k = tu.index("TO")
            return f"add {' '.join(t[:k])} to {' '.join(t[k + 1:])}"
        if v == "SUBTRACT" and "FROM" in tu:
            k = tu.index("FROM")
            return f"subtract {' '.join(t[:k])} from {' '.join(t[k + 1:])}"
        if v == "PERFORM":
            return f"perform {t[0] if t else ''}" + (f" thru {t[2]}" if len(tu) > 2 and tu[1] in ("THRU", "THROUGH") else "")
        if v == "CALL":
            return f"call {t[0].strip(chr(39)) if t else ''}"
        if v == "GO":
            targets, var = self._goto_targets(t, tu)
            if var:
                return f"jump to {'/'.join(targets)} depending on {var}"
            return f"jump to {targets[0]}" if targets else "jump to an ALTERed target"
        if v in ("WRITE", "REWRITE"):
            return f"{v.lower()} {t[0] if t else ''}"
        if v == "READ":
            return f"read {t[0] if t else ''}"
        if v == "SET" and "TRUE" in tu:
            return f"set {t[0]} on"
        if v == "SET" and "TO" in tu:
            k = tu.index("TO")
            return f"set {' '.join(t[:k])} to {' '.join(t[k + 1:])}"
        if v == "STOP":
            return "stop the run"
        if v == "GOBACK":
            return "return to the caller"
        if v == "DISPLAY":
            return "display " + shorten(" ".join(t), 40)
        if v == "INITIALIZE":
            return f"reset {join_list(t, 3)}"
        if v == "CONTINUE":
            return "do nothing"
        if v == "EXEC":
            return "run embedded " + (t[0].upper() if t else "SQL")
        if v == "EXIT":
            return "exit"
        return v.lower() + (" " + " ".join(t[:3]) if t else "")

    @staticmethod
    def _goto_targets(t: list[str], tu: list[str]) -> tuple[list[str], str]:
        """GO TO a b c DEPENDING ON x -> (['a','b','c'], 'x'); GO TO a -> (['a'], '')."""
        if "DEPENDING" in tu:
            k = tu.index("DEPENDING")
            var = " ".join(x for x in t[k + 1:] if x.upper() != "ON")
            return [x for x in t[:k] if x.upper() not in ("TO", ",")], var
        return [x for x in t if x.upper() not in ("TO", ",")][:1], ""

    def _branch(self, nodes: list[Node], limit: int = 3) -> str:
        if not nodes:
            return "nothing"
        parts = [self._brief(n) for n in nodes[:limit]]
        out = ", ".join(parts)
        if len(nodes) > limit:
            out += f" (+{len(nodes) - limit} more)"
        return out

    # .............................................................. walk tree -> annotations
    def _walk(self, node: Node, depth: int):
        s = node.stmt
        p = self.paragraphs.get(s.para)
        t, tu = s.toks, [x.upper() for x in s.toks]
        if p is not None:
            p["stmts"] += 1
            if s.verb in ("EXIT", "CONTINUE") and tu[:1] != ["PROGRAM"]:
                p["exits"] += 1
        para = s.para

        if node.kind == "if":
            cond = " ".join(x for x in t if x.upper() != "THEN")
            en = verbalize_cobol(cond, self.conditions)
            kind = "logic" if TECH_WORDS.search(cond) else "business-rule"
            txt = f"If {shorten(en, 140)} → {self._branch(node.then)}"
            if node.other:
                txt += f"; otherwise → {self._branch(node.other)}"
            self.c.note(s.line, kind, txt + ".", 0.8 if depth < 2 else 0.7, para, detail=depth >= 3)
            if p is not None and kind == "business-rule":
                p["rules"] += 1
            for ch in node.then + node.other:
                self._walk(ch, depth + 1)
            return
        if node.kind == "evaluate":
            subj = " ".join(t) or "TRUE"
            cases = []
            for w, body in node.whens[:6]:
                cond = " ".join(w.toks) or "?"
                cases.append(f"{shorten(verbalize_cobol(cond, self.conditions), 40)} → {self._branch(body, 2)}")
            more = f"; +{len(node.whens) - 6} more cases" if len(node.whens) > 6 else ""
            subj_en = "the first true condition" if subj.upper() == "TRUE" else label(subj)
            self.c.note(s.line, "business-rule",
                        f"Decision table on {subj_en}: " + "; ".join(cases) + more + ".", 0.8, para)
            if p is not None:
                p["rules"] += 1
            for _, body in node.whens:
                for ch in body:
                    self._walk(ch, depth + 1)
            return
        if node.kind == "search":
            tbl = t[1] if tu[:1] == ["ALL"] and len(t) > 1 else (t[0] if t else "?")
            how = "binary search (table must be sorted on its key)" if tu[:1] == ["ALL"] else "sequential scan"
            whens = "; ".join(f"when {shorten(verbalize_cobol(' '.join(w.toks), self.conditions), 50)} → {self._branch(b, 2)}"
                              for w, b in node.whens[:3])
            at_end = f"; if not found → {self._branch(node.then, 2)}" if node.then else ""
            self.c.note(s.line, "logic", f"Table lookup in {tbl} using a {how}: {whens}{at_end}.", 0.8, para)
            for _, body in node.whens:
                for ch in body:
                    self._walk(ch, depth + 1)
            return
        if node.kind == "perform":
            hdr = " ".join(t)
            m = re.match(r"VARYING\s+(\S+)\s+FROM\s+(\S+)\s+BY\s+(\S+)\s+UNTIL\s+(.*)", hdr, re.I)
            if m:
                loop = f"for {m.group(1)} from {m.group(2)} step {m.group(3)} until {verbalize_cobol(m.group(4), self.conditions)}"
            elif tu[:1] == ["UNTIL"] or "UNTIL" in tu:
                k = tu.index("UNTIL")
                loop = "until " + verbalize_cobol(" ".join(t[k + 1:]), self.conditions)
            elif len(tu) >= 2 and tu[1] == "TIMES":
                loop = f"{t[0]} times"
            else:
                loop = shorten(hdr, 60) or "forever"
            self.c.note(s.line, "logic", f"Inline loop, repeated {shorten(loop, 120)}: {self._branch(node.then)}.", 0.8, para)
            if p is not None:
                p["loops"].append(shorten(loop, 60))
            for ch in node.then:
                self._walk(ch, depth + 1)
            return

        v = s.verb
        if v == "PERFORM" and t:
            target = t[0]
            thru = t[2] if len(tu) > 2 and tu[1] in ("THRU", "THROUGH") else ""
            self.c.edge(para or "(main)", target)
            if thru:
                self.c.edge(para or "(main)", thru)
            if p is not None:
                p["performs"].append(target)
            rest_u = tu[3:] if thru else tu[1:]
            rest = t[3:] if thru else t[1:]
            loop = ""
            if "UNTIL" in rest_u:
                k = rest_u.index("UNTIL")
                pre = " ".join(rest[:k])
                vm = re.search(r"VARYING\s+(\S+)\s+FROM\s+(\S+)\s+BY\s+(\S+)", pre, re.I)
                loop = (f"for {vm.group(1)} from {vm.group(2)} step {vm.group(3)} " if vm else "") + \
                       "until " + verbalize_cobol(" ".join(rest[k + 1:]), self.conditions)
            elif len(rest_u) >= 2 and rest_u[1] == "TIMES":
                loop = f"{rest[0]} times"
            rng = f"{target} through {thru}" if thru else target
            if loop:
                self.c.note(s.line, "logic", f"Runs paragraph {label(rng)} repeatedly, {shorten(loop, 120)}.", 0.85, para)
                if p is not None:
                    p["loops"].append(f"{target} {shorten(loop, 50)}")
            elif thru:
                self.c.note(s.line, "logic", f"Runs paragraphs {target} through {thru} in source order, then returns here "
                            "(PERFORM THRU: inserting paragraphs between them changes behaviour).", 0.75, para)
            return
        if v == "COMPUTE" and "=" in tu:
            k = tu.index("=")
            targets = [x for x in t[:k] if x.upper() != "ROUNDED"]
            expr = " ".join(t[k + 1:])
            expr = re.split(r"\b(?:ON\s+SIZE\s+ERROR|NOT\s+ON\s+SIZE)\b", expr, flags=re.I)[0]
            txt = f"Calculates {join_list([label(x) for x in targets])} = {arith(expr)}"
            if "ROUNDED" in tu:
                txt += " (rounded half-up to the target's decimal places)"
            elif any(pic_info(self._pic_of(x), "")["cat"] == "numeric" for x in targets if self._pic_of(x)):
                txt += " (no ROUNDED: extra decimal places are truncated, not rounded; preserve this when migrating)"
            if "SIZE" in tu:
                txt += "; overflow is trapped by ON SIZE ERROR"
            self.c.note(s.line, "logic", txt + ".", 0.85, para)
            if p is not None:
                p["computes"].extend(targets)
            return
        if v in ("ADD", "SUBTRACT", "MULTIPLY", "DIVIDE"):
            if p is not None:
                tgt = t[-1] if t else ""
                if "GIVING" in tu:
                    tgt = t[tu.index("GIVING") + 1]
                p["computes"].append(tgt.rstrip(","))
            self.c.note(s.line, "logic", self._arith_text(v, t, tu) + ".", 0.75, para, detail=True)
            return
        if v == "READ" and t:
            f = t[0]
            if p is not None:
                p["reads"].append(f)
            dd = self.files.get(f, {}).get("dd")
            txt = f"Reads the next record from {f}" + (f" (DD {dd})" if dd else "")
            if "KEY" in tu:
                txt = f"Reads the record of {f} matching key {t[tu.index('KEY') + 2] if len(t) > tu.index('KEY') + 2 else ''}".rstrip()
            if "INTO" in tu:
                txt += f" into {t[tu.index('INTO') + 1]}"
            if "END" in tu:
                txt += "; the following statement runs at end-of-file"
            if "INVALID" in tu:
                txt += "; INVALID KEY handles 'record not found'"
            self.c.note(s.line, "io", txt + ".", 0.85, para)
            return
        if v in ("WRITE", "REWRITE") and t:
            rec = t[0]
            f = self.record_file.get(rec.upper(), "")
            if p is not None:
                p["writes"].append(f or rec)
            verb = "Writes" if v == "WRITE" else "Rewrites (updates in place)"
            txt = f"{verb} record {rec}" + (f" to file {f}" if f else "")
            if "FROM" in tu:
                txt += f", copying it from {t[tu.index('FROM') + 1]}"
            if "ADVANCING" in tu or "AFTER" in tu or "BEFORE" in tu:
                txt += " as a printed report line (ADVANCING controls line/page feed)"
            self.c.note(s.line, "io", txt + ".", 0.85, para)
            return
        if v == "OPEN":
            modes, cur_mode = [], None
            for tok in tu:
                if tok in ("INPUT", "OUTPUT", "I-O", "EXTEND"):
                    cur_mode = tok
                    continue
                if cur_mode:
                    modes.append(f"{tok} for {({'INPUT': 'reading', 'OUTPUT': 'writing (replaces contents)', 'I-O': 'update', 'EXTEND': 'appending'})[cur_mode]}")
                    self.open_modes[tok] = cur_mode
            self.c.note(s.line, "io", "Opens " + join_list(modes, 6) + ".", 0.85, para)
            return
        if v == "CLOSE":
            self.c.note(s.line, "io", "Closes " + join_list(t, 6) + " (flushes buffers and releases the datasets).", 0.8, para, detail=True)
            return
        if v == "CALL" and t:
            target = t[0]
            literal = target.startswith(("'", '"'))
            name = target.strip("'\"")
            self.c.dep("program", name if literal else f"{name} (dynamic)", s.line, "call")
            self.c.edge(para or "(main)", "CALL " + name)
            if p is not None:
                p["calls"].append(name)
            using = ""
            if "USING" in tu:
                k = tu.index("USING")
                args = [x for x in t[k + 1:] if x.upper() not in ("BY", "REFERENCE", "CONTENT", "VALUE", ",")]
                using = f", passing {join_list(args, 6)} (by reference unless stated: the callee can change them)"
            txt = (f"Calls external program {name}{using}." if literal else
                   f"Dynamic call: the program name is taken from variable {name} at run time{using}. "
                   "Static analysis cannot know the target; trace the values assigned to it.")
            self.c.note(s.line, "dependency", txt, 0.85, para)
            return
        if v == "EXEC" and t:
            self._exec(s, t, para, p)
            return
        if v == "GO":
            targets, var = self._goto_targets(t, tu)
            for target in targets:
                self.c.edge(para or "(main)", target)
                if p is not None:
                    p["gotos"].append(target)
            if not targets and p is not None:
                p["gotos"].append("a target set at run time by ALTER")
            if var:
                cases = "; ".join(f"{tg} if {var} = {i}" for i, tg in enumerate(targets[:8], 1))
                txt = (f"Computed GO TO: jumps to {cases}. Any other value of {var} falls through to the "
                       "next statement. Control does not return.")
            elif targets:
                txt = f"Unconditional jump to {targets[0]} (GO TO). Control does not return here."
            else:
                txt = ("GO TO without a target: the destination is set at run time by an ALTER statement, "
                       "so it cannot be known statically.")
            self.c.note(s.line, "warning", txt + " Unstructured flow: restructure into PERFORM/loops when migrating.", 0.85, para)
            return
        if v == "ALTER":
            self.c.note(s.line, "warning", "ALTER rewrites a GO TO target at run time (self-modifying control flow). "
                        "High migration risk: behaviour depends on execution history.", 0.9, para)
            return
        if v == "STOP" and tu[:1] == ["RUN"]:
            if p is not None:
                p["ends"] = True
            self.c.note(s.line, "logic", "Ends the program and the run unit; control returns to the operating system (JCL step ends).", 0.9, para)
            return
        if v == "GOBACK" or (v == "EXIT" and tu[:1] == ["PROGRAM"]):
            if p is not None:
                p["ends"] = True
            self.c.note(s.line, "logic", "Returns control to the calling program (or to the OS if this is the main program).", 0.85, para)
            return
        if v in ("SORT", "MERGE") and t:
            keys = re.findall(r"(ASCENDING|DESCENDING)\s+(?:KEY\s+)?([A-Z0-9-]+)", " ".join(tu))
            using = t[tu.index("USING") + 1] if "USING" in tu else ("an INPUT PROCEDURE" if "INPUT" in tu else "?")
            giving = t[tu.index("GIVING") + 1] if "GIVING" in tu else ("an OUTPUT PROCEDURE" if "OUTPUT" in tu else "?")
            self.c.note(s.line, "io", f"{v.title()}s records of {t[0]} by " +
                        join_list([f"{k[1]} {k[0].lower()}" for k in keys]) + f", reading {using} and writing {giving}.", 0.8, para)
            return
        if v == "MOVE" and "TO" in tu and any(x in ("RETURN-CODE",) for x in tu):
            self.c.note(s.line, "logic", f"Sets the program return code to {t[0]}; JCL COND/IF tests on later steps react to it.", 0.85, para)
            return
        if v in ("INSPECT", "STRING", "UNSTRING"):
            what = {"INSPECT": "Counts or replaces characters in", "STRING": "Concatenates fields into",
                    "UNSTRING": "Splits delimited text from"}[v]
            target = t[0] if v != "STRING" else (t[tu.index("INTO") + 1] if "INTO" in tu else "?")
            self.c.note(s.line, "logic", f"{what} {target}.", 0.7, para, detail=True)
            return
        if v == "DISPLAY" and p is not None:
            p["displays"] += 1
        if v == "ACCEPT" and t:
            src = " ".join(t[2:]) if "FROM" in tu else "the console / SYSIN"
            self.c.note(s.line, "io", f"Accepts {t[0]} from {src}.", 0.75, para, detail=True)

    def _arith_text(self, v: str, t: list[str], tu: list[str]) -> str:
        j = lambda xs: " ".join(xs)
        try:
            if v == "ADD":
                if "GIVING" in tu:
                    g = tu.index("GIVING")
                    return f"Sets {t[g + 1]} = {' + '.join(x for x in t[:g] if x.upper() != 'TO')}"
                k = tu.index("TO")
                return f"Adds {j(t[:k])} into {j(t[k + 1:])} (running total)"
            if v == "SUBTRACT":
                k = tu.index("FROM")
                if "GIVING" in tu:
                    g = tu.index("GIVING")
                    return f"Sets {t[g + 1]} = {j(t[k + 1:g])} - {j(t[:k])}"
                return f"Subtracts {j(t[:k])} from {j(t[k + 1:])}"
            if v == "MULTIPLY":
                k = tu.index("BY")
                if "GIVING" in tu:
                    g = tu.index("GIVING")
                    return f"Sets {t[g + 1]} = {j(t[:k])} × {j(t[k + 1:g])}"
                return f"Multiplies {j(t[k + 1:])} by {j(t[:k])}"
            if v == "DIVIDE":
                if "INTO" in tu:
                    k = tu.index("INTO")
                    if "GIVING" in tu:
                        g = tu.index("GIVING")
                        return f"Sets {t[g + 1]} = {j(t[k + 1:g])} ÷ {j(t[:k])}"
                    return f"Divides {j(t[k + 1:])} by {j(t[:k])}"
                k = tu.index("BY")
                g = tu.index("GIVING") if "GIVING" in tu else len(t)
                tgt = t[g + 1] if g < len(t) - 1 else t[0]
                return f"Sets {tgt} = {j(t[:k])} ÷ {j(t[k + 1:g])}"
        except (ValueError, IndexError):
            pass
        return f"{v.title()} {j(t)}"

    def _pic_of(self, name: str) -> str:
        return getattr(self, "_pics", {}).get(name.upper(), "")

    def _exec(self, s: Stmt, t: list[str], para: str, p):
        kind = t[0].upper()
        body = " ".join(t[1:])
        bu = body.upper()
        if kind == "SQL":
            for tbl, op in sql_tables(body):
                self.c.dep("table", tbl, s.line, op)
                if p is not None:
                    p["sql"].append(f"{op} {tbl}")
            desc = sql_describe(body)
            if not desc:
                if bu.startswith("INCLUDE"):
                    member = body.split()[1] if len(body.split()) > 1 else "?"
                    desc = ("Includes the SQL communication area: SQLCODE/SQLSTATE report each statement's outcome "
                            "(0 = OK, 100 = no row, negative = error)." if member.upper() == "SQLCA"
                            else f"Includes SQL member {member} (host-variable declarations).")
                    if member.upper() != "SQLCA":
                        self.c.dep("copybook", member, s.line, "sql include")
                elif bu.startswith("DECLARE") and "CURSOR" in bu:
                    m = re.match(r"DECLARE\s+(\S+)\s+CURSOR.*?\bFOR\s+(.*)$", body, re.I | re.S)
                    desc = f"Declares cursor {m.group(1)}: {sql_describe(m.group(2))}" if m else "Declares an SQL cursor."
                elif bu.startswith("OPEN"):
                    desc = f"Opens cursor {body.split()[1] if len(body.split()) > 1 else ''}: runs its query and positions before the first row."
                elif bu.startswith("FETCH"):
                    m = re.match(r"FETCH\s+(\S+)\s+INTO\s+(.*)", body, re.I)
                    desc = f"Fetches the next row of cursor {m.group(1)} into {shorten(m.group(2), 80)}; SQLCODE 100 means no more rows." if m else "Fetches the next cursor row."
                elif bu.startswith("CLOSE"):
                    desc = f"Closes cursor {body.split()[1] if len(body.split()) > 1 else ''}."
                elif bu.startswith("COMMIT"):
                    desc = "Commits all database changes made so far (unit of work boundary)."
                elif bu.startswith("ROLLBACK"):
                    desc = "Rolls back uncommitted database changes."
                else:
                    desc = f"Embedded SQL: {shorten(body, 100)}."
            else:
                desc = "Embedded SQL. " + desc + " Check SQLCODE afterwards."
            self.c.note(s.line, "io", desc, 0.85, para)
        elif kind == "CICS":
            cmd = body.split()[0].upper() if body.split() else "?"
            prog = re.search(r"PROGRAM\s*\(\s*'?([A-Z0-9$#@]+)'?\s*\)", bu)
            ds = re.search(r"(?:DATASET|FILE)\s*\(\s*'?([A-Z0-9$#@.]+)'?\s*\)", bu)
            mp = re.search(r"MAP\s*\(\s*'?([A-Z0-9$#@]+)'?\s*\)", bu)
            if prog:
                self.c.dep("program", prog.group(1), s.line, cmd.lower())
            if ds:
                self.c.dep("file", ds.group(1), s.line, cmd.lower())
            self.c.dep("cics", cmd, s.line, "command")
            meaning = {
                "LINK": "calls another program and returns", "XCTL": "transfers control to another program (no return)",
                "RETURN": "ends the task / returns to CICS", "SEND": "sends a screen/message to the terminal",
                "RECEIVE": "receives terminal input", "READ": "reads a VSAM record", "WRITE": "writes a VSAM record",
                "REWRITE": "updates a VSAM record", "DELETE": "deletes a VSAM record", "STARTBR": "starts a file browse",
                "READNEXT": "reads the next record in a browse", "ENDBR": "ends a file browse",
                "SYNCPOINT": "commits the unit of work", "HANDLE": "registers an error handler (implicit GO TO)",
                "ABEND": "abnormally terminates the task",
            }.get(cmd, "online transaction service call")
            obj = (prog or ds or mp)
            txt = f"CICS {cmd}: {meaning}" + (f" ({obj.group(1)})" if obj else "") + "."
            kind_out = "warning" if cmd == "HANDLE" else "io"
            self.c.note(s.line, kind_out, txt, 0.8, para)
        else:
            self.c.note(s.line, "io", f"Embedded {kind} block: {shorten(body, 100)}.", 0.6, para)

    # .............................................................. summaries
    def _summaries(self):
        callers: dict[str, list[str]] = {}
        for a, b in self.c.call_graph:
            callers.setdefault(b, []).append(a)
        total_rules = 0
        for name in self.para_order:
            p = self.paragraphs[name]
            total_rules += p["rules"]
            facts = []
            if p["loops"]:
                facts.append("loops: " + join_list(p["loops"], 3))
            others = [x for x in p["performs"] if not any(x in l for l in p["loops"])]
            if others:
                facts.append("runs " + join_list(others, 6))
            if p["reads"]:
                facts.append("reads " + join_list(p["reads"]))
            if p["writes"]:
                facts.append("writes " + join_list(p["writes"]))
            if p["computes"]:
                facts.append("calculates " + join_list(p["computes"], 4))
            if p["sql"]:
                facts.append("SQL: " + join_list(p["sql"], 4))
            if p["calls"]:
                facts.append("calls program " + join_list(p["calls"]))
            if p["rules"]:
                facts.append(f"applies {p['rules']} business rule{'s' if p['rules'] > 1 else ''}")
            if p["gotos"]:
                facts.append("jumps (GO TO) to " + join_list(p["gotos"]))
            if p["ends"]:
                facts.append("ends the program")
            if p["displays"]:
                facts.append(f"writes {p['displays']} message{'s' if p['displays'] > 1 else ''} to the console/job log (DISPLAY)")
            real = p["stmts"] - p["exits"]
            members = [n for n in self.para_order if self.paragraphs[n].get("section") == name]
            if p["kind"] == "section" and members and real <= 0:
                facts.append(f"groups paragraphs {join_list(members, 6)}; PERFORM {name} runs them all, in order")
            elif not facts and real <= 0:
                facts.append("exit point / placeholder (no logic)")
            elif not facts:
                facts.append(f"{real} simple statement{'s' if real > 1 else ''} (data moves, flags or initialisation)")
            who = [c for c in callers.get(name, []) if c != name]
            purpose = humanize(name)
            kind = p["kind"].title()
            txt = f"{kind} {name}" + (f" — {purpose}" if purpose else "") + ". "
            txt += (facts[0][0].upper() + facts[0][1:] + ("; " + "; ".join(facts[1:]) if len(facts) > 1 else "") + ".") if facts else ""
            if who:
                txt += f" Invoked from {join_list(who, 4)}."
            elif name == self.para_order[0]:
                txt += " Entry point: execution starts here."
            self.c.note(p["line"], "summary", txt, 0.85, name)
            self.c.facts.setdefault("units", []).append({"name": name, "line": p["line"], "kind": p["kind"]})

        # program summary
        ins = [f for f, m in self.open_modes.items() if m == "INPUT"]
        outs = [f for f, m in self.open_modes.items() if m in ("OUTPUT", "EXTEND")]
        upd = [f for f, m in self.open_modes.items() if m == "I-O"]
        calls = [d.name for d in self.c.dependencies if d.kind == "program"]
        tables = [d.name for d in self.c.dependencies if d.kind == "table"]
        books = [d.name for d in self.c.dependencies if d.kind == "copybook"]
        cics = any(d.kind == "cics" for d in self.c.dependencies)
        parts = []
        if self.program_id:
            kind = "online CICS program" if cics else "batch program"
            parts.append(f"Program {self.program_id} — {kind}.")
        else:
            parts.append(f"Copybook defining {join_list(self.level01) or 'shared declarations'} "
                         f"with {len(self.conditions)} condition-names; programs pull it in with COPY.")
        if ins:
            parts.append("Inputs: " + join_list([f"{f} ({self.files.get(f, {}).get('dd', '?')})" for f in ins]) + ".")
        if outs:
            parts.append("Outputs: " + join_list([f"{f} ({self.files.get(f, {}).get('dd', '?')})" for f in outs]) + ".")
        if upd:
            parts.append("Updates in place: " + join_list(upd) + ".")
        if tables:
            parts.append("DB2 tables: " + join_list(tables) + ".")
        if calls:
            parts.append("Calls: " + join_list(calls) + ".")
        if books:
            parts.append("Copybooks: " + join_list(books) + ".")
        if self.para_order:
            first = self.para_order[0]
            flow = self.paragraphs[first]
            seq = flow["performs"][:6]
            if seq:
                parts.append(f"Main flow ({first}): " + " → ".join(seq) + ".")
            parts.append(f"{len(self.para_order)} paragraphs/sections, {total_rules} business rules.")
        self.c.summary = " ".join(parts)
        line = self.program_line or 1
        if self.program_id:
            self.c.note(line, "summary", self.c.summary, 0.8, "program")


def _pic_index(rows) -> dict[str, str]:
    pics = {}
    for _, code, _, _ in rows:
        m = re.match(r"\s*\d{1,2}\s+([A-Z0-9][A-Z0-9-]*)\s+.*?\bPIC(?:TURE)?\s+(?:IS\s+)?(\S+)", code, re.I)
        if m:
            pics[m.group(1).upper()] = m.group(2).rstrip(".")
    return pics


def _analyze_one(lines: list[str], fmt: str, library: dict[str, str] | None,
                 inherit: tuple[dict, dict] | None = None):
    """Analyze one program (or copybook). `inherit` = (conditions, pics) visible from a containing program."""
    a = CobolAnalyzer(lines, fmt)
    rows, _ = prepare(lines, fmt)
    pics = _pic_index(rows)          # lets COMPUTE tell whether truncation applies
    if inherit:
        a.conditions.update(inherit[0])
        pics = {**inherit[1], **pics}
    if library:
        lib = {k.upper(): v for k, v in library.items()}
        copies = {line: (name, pairs) for line, name, pairs in find_copies(rows)}
        fd = None
        for lineno, code, _, _ in rows:
            u = code.strip()
            m = re.match(r"(FD|SD)\s+([A-Z0-9-]+)", u)
            if m:
                fd = m.group(2)
            if re.match(r"(WORKING-STORAGE|LINKAGE|LOCAL-STORAGE)\s+SECTION|PROCEDURE\s+DIVISION", u):
                fd = None
            if lineno not in copies:
                continue
            name, pairs = copies[lineno]
            src = lib.get(name)
            if not src:
                continue
            sub_lines = src.replace("\r\n", "\n").split("\n")
            sub = CobolAnalyzer(sub_lines, replacing=pairs)
            sub.run()
            a.conditions.update(sub.conditions)
            sub_rows, _ = prepare(sub_lines, sub.fmt, pairs)
            sub_pics = _pic_index(sub_rows)
            pics.update(sub_pics)
            if fd:
                for rec in sub.level01:
                    a.record_file[rec] = fd
            a.resolved[name] = len(sub_pics) + len(sub.conditions)
    a._pics = pics
    return a.run(), a, pics


def analyze(lines: list[str], library: dict[str, str] | None = None) -> tuple[Collector, str]:
    """`library` maps copybook names to their source so COPY members can be resolved.

    Source files holding several programs (nested programs, or a batch of programs each closed by
    END PROGRAM) are analyzed one program at a time on a copy of the file in which the other
    programs' lines are blanked, so every line number stays exact.
    """
    fmt = detect_format(lines)
    rows, events = prepare(lines, fmt)
    starts = [ln for ln, code, _, _ in rows if re.match(r"\s*(IDENTIFICATION|ID)\s+DIVISION\b", code)]
    if len(starts) <= 1:
        c, a, _ = _analyze_one(lines, fmt, library)
        progs = [{"name": a.program_id, "line": a.program_line, "parent": ""}] if a.program_id else []
        return _finish(c, lines, fmt, progs, set(a.resolved)), fmt

    ends = {line: name for kind, line, name in events if kind == "end-program"}
    entries, stack, roots = [], [], []
    for i, s in enumerate(starts):
        e = starts[i + 1] - 1 if i + 1 < len(starts) else len(lines)
        masked = [ln if s <= k <= e else "" for k, ln in enumerate(lines, 1)]
        parent = stack[-1] if stack else None
        inherit = (parent["a"].conditions, parent["pics"]) if parent else None
        c, a, pics = _analyze_one(masked, fmt, library, inherit)
        pid = a.program_id or f"PROGRAM-{i + 1}"
        node = OutlineNode(pid, "program", s, e, detail=f"nested in {parent['name']}" if parent else "",
                           children=c.outline)
        (parent["node"].children if parent else roots).append(node)
        entry = {"name": pid, "a": a, "c": c, "pics": pics, "node": node, "line": a.program_line or s,
                 "parent": parent["name"] if parent else ""}
        entries.append(entry)
        stack.append(entry)
        for ln in sorted(l for l in ends if s <= l <= e):
            while stack:
                top = stack.pop()
                top["node"].end_line = ln
                if top["name"] == ends[ln]:
                    break
        if not ends:
            stack.clear()          # separately compiled programs without END PROGRAM: siblings

    names = {e["name"]: e for e in entries}
    merged = Collector()
    for e in entries:
        c = e["c"]
        children = [x["name"] for x in entries if x["parent"] == e["name"]]
        for ann in c.annotations:
            if ann.kind == "summary" and ann.anchor == "program":
                if e["parent"]:
                    ann.text = re.sub(r"^Program (\S+) — ",
                                      f"Nested program \\1 (contained in {e['parent']}; callable only from its "
                                      "container unless declared COMMON) — ", ann.text)
                if children:
                    ann.text += f" Contains nested program{'s' if len(children) > 1 else ''}: {join_list(children)}."
            m = re.match(r"Calls external program ([A-Z0-9][A-Z0-9-]*)", ann.text)
            if ann.kind == "dependency" and m and m.group(1) in names:
                tgt = m.group(1)
                ann.text = ann.text.replace(f"Calls external program {tgt}",
                                            f"Calls nested program {tgt} (defined at line {names[tgt]['line']} "
                                            "of this file, not a separate load module)", 1)
        merged.annotations.extend(c.annotations)
        for d in c.dependencies:
            for ln in d.lines:
                merged.dep(d.kind, d.name, ln, "", d.detail)
            for op in d.ops:
                merged.dep(d.kind, d.name, d.lines[0], op)
        for edge in c.call_graph:
            merged.edge(*edge)
        merged.facts.setdefault("units", []).extend(c.facts.get("units", []))
    for name in names:
        d = merged._deps.get(("program", name.upper()))
        if d is not None:
            d.detail = "nested program in this file"
            if "nested" not in d.ops:
                d.ops.append("nested")
    merged.outline = roots
    tops = [e for e in entries if not e["parent"]]
    nested = [e["name"] for e in entries if e["parent"]]
    merged.summary = " ".join(e["c"].summary for e in tops)
    if nested:
        merged.summary += f" Nested programs: {join_list(nested)}."
    progs = [{"name": e["name"], "line": e["line"], "parent": e["parent"]} for e in entries]
    resolved = set().union(*(set(e["a"].resolved) for e in entries))
    return _finish(merged, lines, fmt, progs, resolved), fmt


def _finish(c: Collector, lines: list[str], fmt: str, programs: list[dict], resolved: set) -> Collector:
    c.facts["format"] = fmt
    c.facts["program_id"] = programs[0]["name"] if programs else ""
    c.facts["programs"] = programs
    c.facts["comment_lines"] = count_comments(lines, fmt)
    c.facts["copybooks_resolved"] = sorted(resolved)
    return c
