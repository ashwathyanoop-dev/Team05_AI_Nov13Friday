"""z/OS JCL analyzer (jobs, steps, DD statements, procedures, in-stream DFSORT cards)."""
from __future__ import annotations

import re

from .models import Collector, OutlineNode
from .vocab import join_list, shorten

SORT_PGMS = {"SORT", "ICEMAN", "DFSORT", "SYNCSORT", "ICETOOL"}
UTIL = {
    "IEBGENER": "copies a sequential dataset (SYSUT1 → SYSUT2)", "IEBCOPY": "copies/merges PDS members",
    "IDCAMS": "VSAM/catalog utility (define, delete, REPRO copy)", "IEFBR14": "does nothing — used only to allocate or delete datasets via DD DISP",
    "IKJEFT01": "runs TSO in batch (often DB2 programs via DSN RUN)", "IKJEFT1B": "runs TSO in batch (often DB2 programs via DSN RUN)",
    "DFHCSDUP": "CICS resource definition utility", "ADRDSSU": "DFDSS dump/restore utility",
    "FTP": "transfers files to/from another system",
}
DISP_STATUS = {"NEW": "creates it", "OLD": "uses it exclusively", "SHR": "reads it (shared)", "MOD": "appends to it (creates if missing)"}
DISP_END = {"CATLG": "catalog it", "KEEP": "keep it", "DELETE": "delete it", "PASS": "pass it to later steps", "UNCATLG": "uncatalog it"}
COND_REL = {"GT": "is less than", "GE": "is at most", "EQ": "equals", "LT": "is greater than", "LE": "is at least", "NE": "differs from"}


def split_operands(s: str) -> list[str]:
    out, cur, depth, q = [], "", 0, False
    for ch in s:
        if ch == "'":
            q = not q
        elif not q and ch == "(":
            depth += 1
        elif not q and ch == ")":
            depth -= 1
        if ch == "," and depth == 0 and not q:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    if cur:
        out.append(cur)
    return out


def params(operands: str) -> tuple[list[str], dict[str, str]]:
    pos, kw = [], {}
    for part in split_operands(operands):
        if "=" in part and not part.startswith("("):
            k, v = part.split("=", 1)
            kw[k.strip().upper()] = v.strip()
        elif part:
            pos.append(part.strip())
    return pos, kw


def _first_field(s: str) -> tuple[str, str]:
    """Split the operand field from trailing comments (first blank outside quotes/parens)."""
    depth, q = 0, False
    for i, ch in enumerate(s):
        if ch == "'":
            q = not q
        elif not q and ch == "(":
            depth += 1
        elif not q and ch == ")":
            depth -= 1
        elif ch == " " and not q and depth <= 0:
            return s[:i], s[i:]
    return s, ""


def disp_text(disp: str) -> str:
    parts = [p.strip().upper() for p in disp.strip("()").split(",")]
    while len(parts) < 3:
        parts.append("")
    st = parts[0] or "NEW"
    normal = parts[1] or ("DELETE" if st == "NEW" else "KEEP")
    abnormal = parts[2] or normal
    out = DISP_STATUS.get(st, st.lower())
    if parts[1] or st == "NEW":
        out += f"; on success {DISP_END.get(normal, normal.lower())}"
    if parts[2]:
        out += f"; if the step abends {DISP_END.get(abnormal, abnormal.lower())}"
    return out


def cond_text(cond: str) -> str:
    c = cond.strip().upper()
    if c in ("EVEN", "ONLY"):
        return {"EVEN": "runs even if an earlier step abended", "ONLY": "runs only if an earlier step abended"}[c]
    tests = re.findall(r"\(?\s*(\d+)\s*,\s*(GT|GE|EQ|LT|LE|NE)\s*(?:,\s*([\w.]+))?\s*\)?", c)
    parts = []
    for code, op, step in tests:
        who = f"step {step}" if step else "any earlier step"
        parts.append(f"{who}'s return code {COND_REL[op]} {code}")
    extra = " (also runs after an abend)" if "EVEN" in c else (" (runs only after an abend)" if "ONLY" in c else "")
    return ("is bypassed if " + " or ".join(parts) + extra) if parts else f"has condition {cond}"


def if_text(expr: str) -> str:
    s = expr.strip()
    s = re.sub(r"\b([\w.]+)\.RC\b", r"\1 return code", s, flags=re.I)
    s = re.sub(r"\bRC\b", "return code", s, flags=re.I)
    s = re.sub(r"\bABEND\b", "an abend occurred", s, flags=re.I)
    s = re.sub(r"\bABENDCC\b", "abend code", s, flags=re.I)
    s = re.sub(r"\b(GT|>)\b|(?<!\w)>(?!=)", " > ", s, flags=re.I)
    s = re.sub(r"\b(LT)\b|(?<!\w)<(?!=)", " < ", s, flags=re.I)
    s = re.sub(r"\bEQ\b|(?<![<>=!])=(?!=)", " = ", s, flags=re.I)
    s = re.sub(r"\bAND\b|&", " and ", s, flags=re.I)
    s = re.sub(r"\bOR\b|\|", " or ", s, flags=re.I)
    return " ".join(s.split())


def sort_text(cards: list[str]) -> str:
    out = []
    text = " ".join(c.strip() for c in cards)
    m = re.search(r"\bSORT\s+FIELDS=\(([^)]*)\)", text, re.I)
    if m:
        f = [x.strip() for x in m.group(1).split(",")]
        if f and f[0].upper() == "COPY":
            out.append("copies records without sorting")
        else:
            fm = re.search(r"FORMAT=(\w+)", text, re.I)
            default_fmt = fm.group(1) if fm else "?"
            if len(f) % 4 == 0 and all(f[k + 3].upper() in ("A", "D") for k in range(0, len(f), 4)):
                groups = [(f[k], f[k + 1], f[k + 2], f[k + 3]) for k in range(0, len(f), 4)]
            elif len(f) % 3 == 0:
                groups = [(f[k], f[k + 1], default_fmt, f[k + 2]) for k in range(0, len(f), 3)]
            else:
                groups = []
            keys = []
            names = {"CH": "text", "ZD": "zoned decimal", "PD": "packed decimal", "BI": "binary", "FI": "signed binary"}
            for start, ln, fmt, order in groups:
                try:
                    end = int(start) + int(ln) - 1
                except ValueError:
                    keys = []
                    break
                keys.append(f"bytes {start}–{end} ({names.get(fmt.upper(), fmt)}) "
                            f"{'ascending' if order.upper() == 'A' else 'descending'}")
            if keys:
                out.append("sorts by " + join_list(keys))
    m = re.search(r"\b(INCLUDE|OMIT)\s+COND=\((.*?)\)(?:\s|$)", text, re.I)
    if m:
        out.append(("keeps only" if m.group(1).upper() == "INCLUDE" else "drops") + f" records matching ({shorten(m.group(2), 60)})")
    if re.search(r"\bSUM\s+FIELDS=NONE", text, re.I):
        out.append("removes duplicate keys")
    elif re.search(r"\bSUM\s+FIELDS=", text, re.I):
        out.append("totals numeric fields per key")
    if re.search(r"\b(OUTREC|INREC|BUILD)\b", text, re.I):
        out.append("reformats the record layout")
    return "; ".join(out)


class JclAnalyzer:
    def __init__(self, lines: list[str], library: dict[str, str] | None = None):
        self.lines = lines
        self.library = {k.upper(): v for k, v in (library or {}).items()}
        self.c = Collector()
        self.protected: set[int] = set()

    def statements(self):
        stmts = []
        instream_dlm = None      # delimiter that ends the current in-stream dataset
        instream_data = False    # DD DATA: lines starting with // are data too
        cur = None
        comments = 0
        for i, ln in enumerate(self.lines, 1):
            if instream_dlm is not None:
                if ln.startswith(instream_dlm):
                    instream_dlm = None
                    self.protected.add(i)      # never insert comments above the delimiter
                    continue
                if ln.startswith("//") and not instream_data:
                    instream_dlm = None        # DD * ends implicitly at the next JCL statement
                else:
                    self.protected.add(i)
                    if stmts and stmts[-1].get("instream") is not None:
                        stmts[-1]["instream"].append(ln)
                    continue
            if ln.startswith("//*"):
                comments += 1
                continue
            if not ln.startswith("//"):
                continue
            body = ln[2:71]
            if not body.strip():
                stmts.append({"name": "", "op": "NULL", "operands": "", "line": i})
                cur = None
                continue
            if cur is not None and cur["continues"] and body.startswith(" "):
                field, _ = _first_field(body.strip())
                cur["operands"] += field
                cur["continues"] = field.endswith(",")
                cur["end"] = i
                continue
            name = "" if body.startswith(" ") else body.split()[0]
            rest = body[len(name):].strip()
            op, _, operands = rest.partition(" ")
            field, _ = _first_field(operands.strip())
            cur = {"name": name, "op": op.upper(), "operands": field, "line": i, "end": i, "continues": field.endswith(",")}
            stmts.append(cur)
            if cur["op"] == "DD":
                pos, kw = params(field)
                if pos and pos[0] in ("*", "DATA"):
                    cur["instream"] = []
                    instream_dlm = kw.get("DLM", "/*").strip("'")
                    instream_data = pos[0] == "DATA"
        self.c.facts["comment_lines"] = comments
        return stmts

    # ---------------------------------------------------------------- procedures & symbols
    @staticmethod
    def proc_defs(stmts: list[dict]) -> dict[str, dict]:
        """PROC ... PEND blocks (in-stream) or a whole cataloged-procedure member."""
        procs: dict[str, dict] = {}
        first = next((s for s in stmts if s["op"] != "NULL"), None)
        cataloged = first is not None and first["op"] == "PROC"
        i = 0
        while i < len(stmts):
            st = stmts[i]
            if st["op"] == "PROC":
                _, kw = params(st["operands"])
                j = i + 1
                body = []
                while j < len(stmts) and stmts[j]["op"] not in ("PEND", "PROC", "JOB"):
                    body.append(stmts[j])
                    j += 1
                end = stmts[j]["line"] if j < len(stmts) and stmts[j]["op"] == "PEND" else (body[-1]["line"] if body else st["line"])
                procs[(st["name"] or "PROC").upper()] = {
                    "name": st["name"] or "PROC", "line": st["line"], "end": end, "body": body,
                    "defaults": {k: unquote(v) for k, v in kw.items()}, "instream": not cataloged}
                i = j
            i += 1
        return procs

    def library_proc(self, name: str) -> dict | None:
        src = self.library.get(name.upper())
        if src is None:
            return None
        sub = JclAnalyzer(src.replace("\r\n", "\n").split("\n"))
        procs = self.proc_defs(sub.statements())
        if not procs:
            return None
        pdef = procs.get(name.upper()) or next(iter(procs.values()))
        return {**pdef, "instream": False}

    def expand(self, pdef: dict, symbols: dict, overrides: list[dict]) -> list[dict]:
        """Procedure steps with symbols substituted and the caller's DD overrides applied."""
        steps, cur = [], None
        for st in pdef["body"]:
            text, _, unres = substitute(st["operands"], symbols)
            pos, kw = params(text)
            if st["op"] == "EXEC":
                pgm = kw.get("PGM")
                cur = {"name": st["name"] or "?", "pgm": pgm,
                       "proc": kw.get("PROC") or (pos[0] if pos and not pgm else None),
                       "cond": kw.get("COND"), "dds": [], "unresolved": set(unres)}
                steps.append(cur)
            elif st["op"] == "DD" and cur is not None:
                cur["unresolved"].update(unres)
                if st["name"]:
                    cur["dds"].append({"dd": st["name"].upper(), "kw": kw, "pos": pos, "instream": st.get("instream") is not None})
        for ov in overrides:
            step = next((s for s in steps if s["name"].upper() == ov["pstep"]), None)
            if step is None:
                continue
            dd = next((d for d in step["dds"] if d["dd"] == ov["dd"]), None)
            if dd is None:
                step["dds"].append({"dd": ov["dd"], "kw": ov["kw"], "pos": ov["pos"], "added": True, "instream": False})
                continue
            if ov["pos"] or "DSN" in ov["kw"] or "DSNAME" in ov["kw"]:
                dd["pos"] = ov["pos"]
                if "DUMMY" in ov["pos"]:
                    dd["kw"] = {k: v for k, v in dd["kw"].items() if k not in ("DSN", "DSNAME", "DISP", "SYSOUT")}
            dd["kw"] = {**dd["kw"], **ov["kw"]}
            dd["overridden"] = True
        return steps

    # ---------------------------------------------------------------- main pass
    def run(self) -> Collector:
        stmts = self.statements()
        procs = self.proc_defs(stmts)
        cataloged = next((p for p in procs.values() if not p["instream"]), None)
        job = None
        job_node = None
        steps: list[dict] = []
        roots: list[OutlineNode] = []
        cur_step = None
        if_stack: list[str] = []
        symbols: dict[str, str] = {}
        in_proc: str | None = None
        proc_nodes: dict[str, OutlineNode] = {}
        resolved_procs: list[str] = []
        unresolved_in_proc: dict[str, set] = {}

        for st in stmts:
            op, name, line = st["op"], st["name"], st["line"]
            scope = {**symbols, **(procs[in_proc]["defaults"] if in_proc else {})}
            text, used, unres = substitute(st["operands"], scope)
            if in_proc:
                unresolved_in_proc.setdefault(in_proc, set()).update(unres)
            pos, kw = params(text)
            if op == "JOB":
                job = st
                job_node = OutlineNode(name or "JOB", "job", line)
                roots.append(job_node)
                facts = []
                if pos:
                    facts.append(f"accounting {pos[0]}")
                if len(pos) > 1:
                    facts.append(f"programmer/description {pos[1]}")
                if "CLASS" in kw:
                    facts.append(f"job class {kw['CLASS']}")
                if "MSGCLASS" in kw:
                    facts.append(f"output class {kw['MSGCLASS']}")
                if "RESTART" in kw:
                    facts.append(f"restarts at {kw['RESTART']}")
                st["facts"] = facts
                continue
            if op == "PROC":
                in_proc = (name or "PROC").upper()
                pdef = procs[in_proc]
                node = OutlineNode(pdef["name"], "proc", line, pdef["end"])
                proc_nodes[in_proc] = node
                (job_node.children if job_node and pdef["instream"] else roots).append(node)
                if pdef["instream"]:
                    defaults = join_list([f"{k}={v or '(empty)'}" for k, v in pdef["defaults"].items()], 6) or "none"
                    self.c.note(line, "summary", f"In-stream procedure {pdef['name']} (lines {line}-{pdef['end']}): a reusable "
                                f"step sequence that runs only where a step says EXEC {pdef['name']}. Symbol defaults: {defaults}.",
                                0.85, pdef["name"])
                continue
            if op == "PEND":
                in_proc = None
                continue
            if op == "EXEC":
                pgm = kw.get("PGM")
                proc = kw.get("PROC") or (pos[0] if pos and not pgm else None)
                cur_step = {"name": name or f"(step at line {line})", "line": line, "pgm": pgm, "proc": proc,
                            "inputs": [], "outputs": [], "kw": kw, "sysin": None, "if": list(if_stack),
                            "in_proc": in_proc, "overrides": [], "pdef": None}
                steps.append(cur_step)
                node = OutlineNode(cur_step["name"], "step", line, detail=pgm or proc or "")
                cur_step["node"] = node
                parent = proc_nodes.get(in_proc) if in_proc else job_node
                (parent.children if parent else roots).append(node)
                if pgm:
                    self.c.dep("program", pgm, line, "exec")
                    self.c.edge(name or "step", pgm)
                if proc:
                    self.c.dep("proc", proc, line, "exec")
                    pdef = procs.get(proc.upper())
                    source = f"in-stream definition at line {pdef['line']}" if pdef else ""
                    if pdef is None:
                        pdef = self.library_proc(proc)
                        source = f"library member {proc} found in this upload" if pdef else ""
                    if pdef is not None:
                        call = {k: unquote(v) for k, v in kw.items() if k not in EXEC_KEYWORDS and "." not in k}
                        cur_step["pdef"] = pdef
                        cur_step["source"] = source
                        cur_step["call_symbols"] = call
                        cur_step["symbols"] = {**symbols, **pdef["defaults"], **call}
                        if proc.upper() not in resolved_procs:
                            resolved_procs.append(proc.upper())
                if "COND" in kw:
                    self.c.note(line, "logic", f"Step {cur_step['name']} {cond_text(kw['COND'])}.", 0.85, cur_step["name"])
                if "PARM" in kw:
                    self.c.note(line, "data", f"Passes PARM {kw['PARM']} to the program (read via the LINKAGE SECTION / PROCEDURE DIVISION USING).",
                                0.75, cur_step["name"], detail=True)
                self._note_symbols(line, used, cur_step["name"])
                continue
            if op == "DD":
                step_name = cur_step["name"] if cur_step else ""
                dsn = kw.get("DSN") or kw.get("DSNAME")
                disp = kw.get("DISP", "")
                dd = name
                if "." in dd and cur_step is not None and cur_step.get("proc"):
                    pstep, ddn = dd.upper().split(".", 1)
                    cur_step["overrides"].append({"pstep": pstep, "dd": ddn, "kw": kw, "pos": pos})
                    what = "DUMMY (no data)" if "DUMMY" in pos else (dsn or ("spool" if "SYSOUT" in kw else "new attributes"))
                    tail = "" if cur_step.get("pdef") else " (the procedure is not in this upload, so the original DD is unknown)"
                    self.c.note(line, "io", f"Override: replaces DD {ddn} of procedure step {pstep} with {what} for this "
                                f"invocation only{tail}.", 0.85, step_name)
                    if dsn:
                        self.c.dep("dataset", re.sub(r"\([+-]?\d+\)$", "", dsn), line,
                                   (disp.strip("()").split(",")[0] or "OLD").lower(), f"DD {ddn}")
                    continue
                if dd in ("STEPLIB", "JOBLIB") and dsn:
                    self.c.dep("library", dsn, line, "load")
                    self.c.note(line, "dependency", f"{dd}: load modules (compiled programs) are fetched from {dsn}.", 0.8, step_name, detail=True)
                    continue
                if st.get("instream") is not None:
                    cards = st["instream"]
                    if cur_step is not None:
                        cur_step["sysin"] = cards
                    pgm = (cur_step or {}).get("pgm") or ""
                    if pgm.upper() in SORT_PGMS and dd in ("SYSIN", "DFSPARM", "") or (cards and re.search(r"\bSORT\s+FIELDS=", " ".join(cards), re.I)):
                        stxt = sort_text(cards)
                        if stxt:
                            self.c.note(line, "logic", f"DFSORT control statements (in-stream, {len(cards)} lines): {stxt}.", 0.85, step_name)
                            continue
                    preview = shorten(" | ".join(c.strip() for c in cards[:3]), 90)
                    self.c.note(line, "data", f"In-stream input for {dd or 'the step'} ({len(cards)} lines): {preview}.", 0.75, step_name)
                    continue
                if "SYSOUT" in kw:
                    if cur_step is not None and dd not in ("SYSOUT", "SYSPRINT", "SYSUDUMP", "SYSABEND", "CEEDUMP", "SYSDBOUT"):
                        cur_step["outputs"].append(f"{dd} → spool (printed report)")
                    continue
                if "DUMMY" in pos or (dsn or "").upper() == "NULLFILE":
                    self.c.note(line, "io", f"{dd} is DUMMY: the program sees an empty input / discarded output.", 0.75, step_name, detail=True)
                    continue
                if not dsn:
                    continue
                info = dd_info(kw, pos)
                self.c.dep("dataset", info["ds_name"], line, info["status"].lower(), f"DD {dd}")
                if cur_step is not None:
                    target = cur_step["outputs"] if info["writes"] else cur_step["inputs"]
                    target.append(f"{dd} {'→' if info['writes'] else '←'} {dsn}")
                notable = info["status"] in ("NEW", "MOD", "OLD") or info["gdg"] or info["temp"]
                txt = f"DD {dd}: {info['desc'] or dsn}"
                if disp:
                    txt += f" — {disp_text(disp)}"
                dcb = re.search(r"LRECL=(\d+)", text)
                if dcb:
                    txt += f"; fixed record length {dcb.group(1)} bytes" if "FB" in text else f"; record length {dcb.group(1)}"
                orig = re.search(r"DSN(?:AME)?=([^,]+)", st["operands"])
                if used and orig and orig.group(1) != dsn:
                    txt += f" (coded as {orig.group(1)}; symbols resolved)"
                self.c.note(line, "io", txt + ".", 0.8, step_name, detail=not notable and not used)
                if unres and not in_proc:
                    self._note_unresolved(line, unres, step_name)
                continue
            if op == "IF":
                expr = re.sub(r"\s*THEN\s*$", "", text or "", flags=re.I)
                full = " ".join(self.lines[line - 1][2:71].split()[1 if name else 0:])
                m = re.search(r"IF\s*(.*?)\s*THEN", full, re.I)
                expr = m.group(1) if m else expr
                if_stack.append(if_text(expr))
                self.c.note(line, "business-rule", f"Conditional execution: the steps up to the matching ELSE/ENDIF run only when {if_text(expr)}.", 0.85)
                continue
            if op == "ELSE":
                if if_stack:
                    self.c.note(line, "logic", f"Otherwise (when not {if_stack[-1]}) the following steps run instead.", 0.75, detail=True)
                continue
            if op == "ENDIF":
                if if_stack:
                    if_stack.pop()
                continue
            if op == "INCLUDE":
                mem = kw.get("MEMBER", "")
                self.c.dep("include", mem, line, "include")
                self.c.note(line, "dependency", f"Includes JCL member {mem} from the JCLLIB/procedure library at submission time.", 0.85)
                continue
            if op == "JCLLIB":
                self.c.note(line, "dependency", f"Procedure/INCLUDE libraries searched (in order): {kw.get('ORDER', '')}. "
                            "EXEC statements without PGM= look up their procedure here.", 0.8)
                continue
            if op == "SET":
                for k, v in kw.items():
                    symbols[k] = unquote(v)
                self.c.note(line, "data", "Sets JCL symbols " + join_list([f"&{k}={unquote(v)}" for k, v in kw.items()], 6)
                            + "; every later &name (and procedures called later) uses these values.", 0.8)
                continue

        # ------------------------------------------------------------ step summaries
        for s in steps:
            pgm = s["pgm"]
            parts = []
            if s.get("pdef"):
                parts.append(self._proc_summary(s))
            else:
                what = f"runs program {pgm}" if pgm else f"invokes procedure {s['proc']}"
                if pgm and pgm.upper() in UTIL:
                    what += f" ({UTIL[pgm.upper()]})"
                if pgm and pgm.upper() in SORT_PGMS:
                    what += " (DFSORT: sort/merge/copy utility)"
                if s["proc"] and not pgm:
                    what += " — its definition is not in this upload; add the PROCLIB member to expand its steps"
                parts.append(f"Step {s['name']} {what}.")
                if s["in_proc"]:
                    parts.append(f"Part of procedure {procs[s['in_proc']]['name']}: runs each time the procedure is invoked.")
                if s["inputs"]:
                    parts.append("Reads " + join_list(s["inputs"], 5) + ".")
                if s["outputs"]:
                    parts.append("Writes " + join_list(s["outputs"], 5) + ".")
            if s["if"]:
                parts.append("Runs only when " + " and ".join(s["if"]) + ".")
            self.c.note(s["line"], "summary", " ".join(parts), 0.85, s["name"])
            self.c.facts.setdefault("units", []).append({"name": s["name"], "line": s["line"], "kind": "step"})

        # cataloged procedure member: describe it as a whole
        if cataloged is not None:
            psteps = [s for s in steps if s["in_proc"] == cataloged["name"].upper()]
            chain = " → ".join(f"{s['name']} ({s['pgm'] or s['proc']})" for s in psteps[:8])
            defaults = join_list([f"{k}={v or '(empty)'}" for k, v in cataloged["defaults"].items()], 6) or "none"
            missing = sorted(unresolved_in_proc.get(cataloged["name"].upper(), set()))
            txt = (f"Cataloged procedure {cataloged['name']}: {len(psteps)} steps ({chain}). Jobs run it with "
                   f"EXEC {cataloged['name']} and may override symbols and DDs. Symbol defaults: {defaults}.")
            if missing:
                txt += f" Symbols with no default (the calling job must supply them): {join_list(['&' + m for m in missing], 6)}."
            self.c.summary = txt
            self.c.note(cataloged["line"], "summary", txt, 0.85, cataloged["name"])

        last = len(self.lines)
        for r in roots:
            if r.kind != "proc":
                r.end_line = last
            self._close(r)
        self.c.outline = roots
        if job:
            top = [s for s in steps if not s["in_proc"]]
            chain = " → ".join(f"{s['name']} ({s['pgm'] or s['proc']})" for s in top[:8])
            txt = f"Batch job {job['name']}: {len(top)} steps" + (f": {chain}" if chain else "") + "."
            if job.get("facts"):
                facts = "; ".join(job["facts"])
                txt += " " + facts[:1].upper() + facts[1:] + "."
            self.c.summary = txt
            self.c.note(job["line"], "summary", txt, 0.85, job["name"])
        elif cataloged is None:
            self.c.summary = f"JCL with {len(steps)} steps."
        self.c.facts["protected_lines"] = sorted(self.protected)
        self.c.facts["procs_resolved"] = resolved_procs
        return self.c

    def _close(self, node: OutlineNode):
        for i, ch in enumerate(node.children):
            if ch.kind == "proc step":
                continue
            if not ch.end_line or ch.kind == "step":
                nxt = next((c.line for c in node.children[i + 1:] if c.kind != "proc step"), None)
                ch.end_line = nxt - 1 if nxt else node.end_line
            self._close(ch)

    def _note_symbols(self, line: int, used: list, step: str):
        if used:
            self.c.note(line, "data", "Symbols resolved on this statement: " +
                        join_list([f"&{k}={v}" for k, v in dict(used).items()], 6) + ".", 0.8, step, detail=True)

    def _note_unresolved(self, line: int, names, step: str):
        self.c.note(line, "warning", f"Symbol{'s' if len(names) > 1 else ''} {join_list(['&' + n for n in sorted(set(names))])} "
                    "has no value here: check the SET statements or the procedure defaults. The dataset name cannot be "
                    "fully resolved.", 0.8, step)

    def _proc_summary(self, s: dict) -> str:
        """Expand a procedure call into a readable step-by-step description (annotated on the EXEC line)."""
        pdef = s["pdef"]
        psteps = self.expand(pdef, s["symbols"], s["overrides"])
        line = s["line"]
        sym = s["call_symbols"]
        head = f"Step {s['name']} runs procedure {pdef['name']} ({s['source']})"
        if sym:
            head += " with " + join_list([f"&{k}={v}" for k, v in sym.items()], 6)
        descs, unresolved = [], set()
        for ps in psteps:
            unresolved |= ps["unresolved"]
            node = OutlineNode(ps["name"], "proc step", line, line, detail=ps["pgm"] or ps["proc"] or "")
            s["node"].children.append(node)
            if ps["pgm"]:
                self.c.dep("program", ps["pgm"], line, "exec", f"via procedure {pdef['name']} step {ps['name']}")
                self.c.edge(s["name"], ps["pgm"])
            ins, outs = [], []
            for d in ps["dds"]:
                mark = " (overridden here)" if d.get("overridden") else (" (added here)" if d.get("added") else "")
                if "DUMMY" in d["pos"]:
                    ins.append(f"{d['dd']} = DUMMY{mark}")
                    continue
                if "SYSOUT" in d["kw"]:
                    if d["dd"] not in ("SYSOUT", "SYSPRINT", "SYSUDUMP", "SYSABEND", "CEEDUMP"):
                        outs.append(f"{d['dd']} → spool{mark}")
                    continue
                if d.get("instream"):
                    ins.append(f"{d['dd']} ← in-stream data")
                    continue
                info = dd_info(d["kw"], d["pos"])
                if not info["dsn"]:
                    continue
                self.c.dep("dataset", info["ds_name"], line, info["status"].lower(), f"DD {d['dd']}")
                (outs if info["writes"] else ins).append(f"{d['dd']} {'→' if info['writes'] else '←'} {info['dsn']}{mark}")
            what = f"{ps['name']} runs {ps['pgm'] or 'procedure ' + str(ps['proc'])}"
            if ps["pgm"] and ps["pgm"].upper() in UTIL:
                what += f" ({UTIL[ps['pgm'].upper()].split(' (')[0]})"
            if ins:
                what += ", reading " + join_list(ins, 4)
            if outs:
                what += ", writing " + join_list(outs, 4)
            if ps["cond"]:
                what += f"; it {cond_text(ps['cond'])}"
            descs.append(what)
        txt = head + ". Expanded: " + "; ".join(descs) + "."
        if unresolved:
            self._note_unresolved(line, unresolved, s["name"])
        return txt


EXEC_KEYWORDS = {"PGM", "PROC", "COND", "PARM", "REGION", "TIME", "ACCT", "ADDRSPC", "DPRTY", "PERFORM", "RD",
                 "CCSID", "MEMLIMIT", "DYNAMNBR", "TVSMSG", "TVSAMCOM", "RLSTMOUT", "RLSOPT"}
SYSTEM_SYMBOLS = {"SYSUID", "SYSDATE", "SYSTIME", "SYSNAME", "SYSPLEX", "SYSCLONE", "LYYMMDD", "LYR4", "LMON",
                  "LDAY", "YYMMDD", "YR4", "MON", "DAY", "HHMMSS", "JOBNAME", "SEQ"}
_SYMBOL = re.compile(r"(?<!&)&([A-Z@#$][A-Z0-9@#$]{0,7})(\.?)")


def unquote(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] == "'":
        return v[1:-1].replace("''", "'")
    return v


def substitute(text: str, symbols: dict) -> tuple[str, list, list]:
    """Replace &NAME / &NAME. with symbol values; &&TEMP datasets and system symbols are left alone."""
    used, unresolved = [], []

    def rep(m):
        name = m.group(1)
        if name in symbols:
            used.append((name, symbols[name]))
            return symbols[name]
        if name not in SYSTEM_SYMBOLS:
            unresolved.append(name)
        return m.group(0)

    return _SYMBOL.sub(rep, text), used, unresolved


def dd_info(kw: dict, pos: list) -> dict:
    dsn = kw.get("DSN") or kw.get("DSNAME") or ""
    disp = kw.get("DISP", "")
    gdg = re.match(r"(.*)\(([+-]?\d+)\)$", dsn)
    temp = dsn.startswith("&&")
    status = (disp.strip("()").split(",")[0].upper() if disp else "NEW" if "SPACE" in kw else "OLD") or "NEW"
    desc = ""
    writes = status in ("NEW", "MOD")
    if gdg:
        g = int(gdg.group(2))
        if g == 1:
            label = "a NEW generation" if writes else "the new generation (+1) created earlier in this job"
        else:
            label = {0: "current generation"}.get(g, f"generation {g:+d} (older)")
        desc = f"{label} of GDG {gdg.group(1)}"
    elif temp:
        desc = f"temporary dataset {dsn} (exists only for this job)"
    return {"dsn": dsn, "ds_name": gdg.group(1) if gdg else dsn, "status": status, "gdg": bool(gdg), "temp": temp,
            "writes": writes, "desc": desc}


def analyze(lines: list[str], library: dict[str, str] | None = None) -> Collector:
    """`library` maps member names to source, so cataloged procedures can be expanded."""
    return JclAnalyzer(lines, library).run()
