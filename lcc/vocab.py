"""Vocabulary helpers: turn legacy identifiers and expressions into plain English."""
from __future__ import annotations

import re

ABBR = {
    "ACC": "account", "ACCT": "account", "ACCTS": "accounts", "ADDR": "address", "ADJ": "adjustment",
    "AMT": "amount", "AMTS": "amounts", "APPL": "application", "AVG": "average", "BAL": "balance",
    "BILL": "billing", "BRCH": "branch", "CALC": "calculate", "CALCS": "calculations", "CD": "code",
    "CHK": "check", "CLM": "claim", "CNT": "count", "CNTR": "counter", "CTR": "counter", "CUR": "current",
    "CURR": "current", "CUST": "customer", "DED": "deduction", "DEDS": "deductions", "DEL": "delete",
    "DEPT": "department", "DESC": "description", "DISC": "discount", "DT": "date", "DTL": "detail",
    "DY": "day", "EMP": "employee", "EMPL": "employee", "EOF": "end-of-file", "ERR": "error",
    "EXP": "expense", "FED": "federal", "FIN": "finalize", "FL": "file", "FLG": "flag", "FS": "file status",
    "GRS": "gross", "GRSS": "gross", "HDR": "header", "HR": "hour", "HRS": "hours", "ID": "identifier",
    "IDX": "index", "IND": "indicator", "INIT": "initialize", "INS": "insert", "INT": "interest",
    "INV": "invoice", "LIM": "limit", "LMT": "limit", "LN": "loan", "MAX": "maximum", "MIN": "minimum",
    "MO": "month", "MSG": "message", "MTD": "month-to-date", "MTH": "month", "NBR": "number",
    "NM": "name", "NUM": "number", "OT": "overtime", "PCT": "percent", "PMT": "payment", "POL": "policy",
    "PREM": "premium", "PREV": "previous", "PRIN": "principal", "PROC": "process", "PRT": "print",
    "QTY": "quantity", "RD": "read", "REC": "record", "RECS": "records", "RPT": "report", "RT": "rate",
    "RTN": "routine", "SAL": "salary", "SEQ": "sequence", "SS": "social security", "ST": "state",
    "STAT": "status", "STS": "status", "SUB": "subscript", "SW": "switch", "TBL": "table",
    "TERM": "terminate", "TMP": "temporary", "TOT": "total", "TOTS": "totals", "TRAN": "transaction",
    "TRANS": "transaction", "TRL": "trailer", "TX": "tax", "TXN": "transaction", "UPD": "update",
    "VAL": "validate", "WK": "work", "WRK": "work", "WRT": "write", "YR": "year", "YTD": "year-to-date",
}

# Prefixes that carry storage-section meaning rather than business meaning.
_NOISE_PREFIX = re.compile(r"^(?:WS|LS|LK|W|L|FD|SD|V|P|G|C|GC|GV|LV|TRG|PKG|SP|FN|USP|PRC)[-_]", re.I)
_LEADING_NUM = re.compile(r"^[0-9]+[A-Z]?[-_]", re.I)


def humanize(name: str) -> str:
    """'2000-CALC-GROSS-PAY' -> 'calculate gross pay', 'v_cust_bal' -> 'customer balance'."""
    if not name:
        return ""
    n = name.strip().strip("'\"")
    n = n.split(".")[-1]
    n = _LEADING_NUM.sub("", n)
    n = _NOISE_PREFIX.sub("", n)
    words = [w for w in re.split(r"[-_$#]+", n) if w]
    out = []
    for w in words:
        if w.isdigit():
            out.append(w)
            continue
        out.append(ABBR.get(w.upper(), w.lower()))
    return " ".join(out)


def label(name: str) -> str:
    """Identifier with a humanized hint when the hint adds information."""
    h = humanize(name)
    plain = name.lower().replace("-", " ").replace("_", " ")
    if not h or h == plain or h.replace(" ", "") == plain.replace(" ", ""):
        return name
    return f"{name} ({h})"


_COBOL_OPS = [
    (r"\bIS\s+GREATER\s+THAN\s+OR\s+EQUAL\s+TO\b", " is at least "),
    (r"\bGREATER\s+THAN\s+OR\s+EQUAL\s+TO\b", " is at least "),
    (r"\bIS\s+LESS\s+THAN\s+OR\s+EQUAL\s+TO\b", " is at most "),
    (r"\bLESS\s+THAN\s+OR\s+EQUAL\s+TO\b", " is at most "),
    (r"\bIS\s+NOT\s+GREATER\s+THAN\b", " is not greater than "),
    (r"\bIS\s+NOT\s+LESS\s+THAN\b", " is not less than "),
    (r"\bIS\s+GREATER\s+THAN\b|\bGREATER\s+THAN\b|\bGREATER\b", " is greater than "),
    (r"\bIS\s+LESS\s+THAN\b|\bLESS\s+THAN\b|\bLESS\b", " is less than "),
    (r"\bIS\s+NOT\s+EQUAL\s+TO\b|\bNOT\s+EQUAL\s+TO\b|\bNOT\s+EQUAL\b", " is not "),
    (r"\bIS\s+EQUAL\s+TO\b|\bEQUAL\s+TO\b|\bEQUALS\b", " = "),
    (r"\bIS\s+NOT\s+NUMERIC\b|\bNOT\s+NUMERIC\b", " is not numeric "),
    (r"\bIS\s+NUMERIC\b|\bNUMERIC\b", " is numeric "),
    (r"\bIS\s+POSITIVE\b|\bPOSITIVE\b", " is positive "),
    (r"\bIS\s+NEGATIVE\b|\bNEGATIVE\b", " is negative "),
    (r"NOT\s*=", " is not "),
    (r">=", " is at least "),
    (r"<=", " is at most "),
    (r"(?<![<>])>(?!=)", " is greater than "),
    (r"(?<![<>])<(?![=>])", " is less than "),
    (r"\bZEROS?\b|\bZEROES\b", "0"),
    (r"\bSPACES?\b", "blank"),
    (r"\bHIGH-VALUES?\b", "high-values"),
    (r"\bLOW-VALUES?\b", "low-values"),
    (r"\bAND\b", " and "),
    (r"\bOR\b", " or "),
    (r"\bNOT\b", " not "),
]

_SQL_OPS = [
    (r"\bIS\s+NOT\s+NULL\b", " is present "),
    (r"\bIS\s+NULL\b", " is empty (NULL) "),
    (r"<>|!=|\^=", " is not "),
    (r">=", " is at least "),
    (r"<=", " is at most "),
    (r"(?<![<>])>(?!=)", " is greater than "),
    (r"(?<![<>])<(?![=>])", " is less than "),
    (r"\bNOT\s+IN\b", " is not one of "),
    (r"\bIN\b", " is one of "),
    (r"\bBETWEEN\b", " is between "),
    (r"\bAND\b", " and "),
    (r"\bOR\b", " or "),
    (r"\bNOT\b", " not "),
]

_STR = re.compile(r"'[^']*'|\"[^\"]*\"")


def _translate(expr: str, rules, upper: bool = False) -> str:
    # Protect string literals from operator rewriting.
    lits: list[str] = []

    def keep(m):
        lits.append(m.group(0))
        return f"\x00{len(lits) - 1}\x00"

    s = _STR.sub(keep, expr)
    if upper:
        # Case-insensitive language: normalise, then match case-sensitively so the
        # lower-case English produced by one rule is never re-matched by a later rule.
        s = s.upper()
    for pat, rep in rules:
        s = re.sub(pat, rep, s, flags=0 if upper else re.I)
    s = re.sub(r"\x00(\d+)\x00", lambda m: lits[int(m.group(1))], s)
    return " ".join(s.split())


def verbalize_cobol(cond: str, conditions: dict | None = None) -> str:
    """Translate a COBOL condition. `conditions` maps 88-level names -> (parent, values)."""
    s = _translate(cond, _COBOL_OPS, upper=True)
    if conditions:
        def sub88(m):
            word = m.group(0)
            info = conditions.get(word.upper())
            if not info:
                return word
            parent, values = info
            return f"{word} [{parent} in {values}]" if "," in values else f"{word} [{parent} = {values}]"
        s = re.sub(r"[A-Z0-9][A-Z0-9-]*[A-Z0-9]", sub88, s, flags=re.I)
    return s


def verbalize_sql(cond: str) -> str:
    return _translate(cond, _SQL_OPS)


def arith(expr: str) -> str:
    """Make an arithmetic expression easier to read."""
    s = " ".join(expr.split())
    s = re.sub(r"\s\*\*\s", " ^ ", s)
    s = re.sub(r"(?<=\s)\*(?=\s)", "×", s)
    s = re.sub(r"(?<=\s)/(?=\s)", "÷", s)
    return s


def shorten(text: str, limit: int = 160) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def join_list(items, limit: int = 5) -> str:
    items = [i for i in dict.fromkeys(items) if i]
    if not items:
        return ""
    if len(items) > limit:
        return ", ".join(items[:limit]) + f" and {len(items) - limit} more"
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


# ---------------------------------------------------------------- SQL helpers
_SQL_STOP = r"(?:\bWHERE\b|\bGROUP\b|\bORDER\b|\bHAVING\b|\bUNION\b|\bCONNECT\b|\bFOR\s+UPDATE\b|\bJOIN\b|\bINNER\b|\bLEFT\b|\bRIGHT\b|\bFULL\b|\bCROSS\b|\bFETCH\b|\bWITH\b|;|$)"
_IDENT = r"[A-Za-z_][\w$#]*(?:\.[A-Za-z_][\w$#]*)?"


def sql_tables(sql: str) -> list[tuple[str, str]]:
    """Return [(table, op)] referenced by an SQL statement."""
    s = " ".join(_STR.sub("''", sql).split())
    u = s.upper()
    found: list[tuple[str, str]] = []

    def add(name, op):
        n = name.strip().upper()
        if n and n not in ("DUAL", "TABLE", "SELECT", "(") and not n.startswith(":"):
            if (n, op) not in found:
                found.append((n, op))

    head = u.lstrip("( ").split(" ", 1)[0] if u.strip() else ""
    if head in ("INSERT",):
        m = re.search(r"\bINTO\s+(" + _IDENT + ")", u)
        if m:
            add(m.group(1), "insert")
    if head == "UPDATE":
        m = re.match(r"\s*UPDATE\s+(" + _IDENT + ")", u)
        if m:
            add(m.group(1), "update")
    if head == "DELETE":
        m = re.match(r"\s*DELETE\s+(?:FROM\s+)?(" + _IDENT + ")", u)
        if m:
            add(m.group(1), "delete")
    if head == "MERGE":
        m = re.search(r"\bMERGE\s+INTO\s+(" + _IDENT + ")", u)
        if m:
            add(m.group(1), "merge")
        m = re.search(r"\bUSING\s+(" + _IDENT + ")", u)
        if m:
            add(m.group(1), "read")
    for m in re.finditer(r"\bFROM\s+(.*?)" + _SQL_STOP, u):
        seg = m.group(1)
        if head == "DELETE" and m.start() < 12:
            continue
        for part in seg.split(","):
            part = part.strip()
            if not part or part.startswith("("):
                continue
            add(part.split()[0], "read")
    for m in re.finditer(r"\bJOIN\s+(" + _IDENT + ")", u):
        add(m.group(1), "read")
    return found


def sql_describe(sql: str) -> str:
    """One-line English description of an SQL statement."""
    s = " ".join(sql.split()).rstrip(";")
    u = s.upper()
    tables = sql_tables(s)
    names = lambda op: join_list([t for t, o in tables if o == op])
    where = ""
    m = re.search(r"\bWHERE\s+(.*?)(?:\bGROUP\b|\bORDER\b|\bFOR\s+UPDATE\b|\bRETURNING\b|$)", s, re.I)
    if m:
        where = " where " + shorten(verbalize_sql(m.group(1)), 90)
    if u.startswith("SELECT") or u.startswith("WITH"):
        cols = ""
        m = re.match(r"SELECT\s+(.*?)\s+(?:BULK\s+COLLECT\s+)?(?:INTO|FROM)\b", s, re.I | re.S)
        if m:
            cols = shorten(m.group(1), 70)
        into = ""
        m = re.search(r"\bINTO\s+(.*?)\s+FROM\b", s, re.I)
        if m:
            into = " into " + shorten(m.group(1), 60)
        bulk = " (bulk fetch)" if re.search(r"BULK\s+COLLECT", u) else ""
        return f"Reads {cols or 'data'} from {names('read') or 'a query'}{where}{into}{bulk}."
    if u.startswith("INSERT"):
        src = " from a query" if re.search(r"\bSELECT\b", u) else ""
        return f"Inserts a new row into {names('insert')}{src}."
    if u.startswith("UPDATE"):
        sets = ""
        m = re.search(r"\bSET\s+(.*?)(?:\bWHERE\b|$)", s, re.I)
        if m:
            cols = [c.split("=")[0].strip() for c in re.split(r",(?![^(]*\))", m.group(1))]
            sets = " setting " + join_list(cols, 4)
        return f"Updates {names('update')}{sets}{where}."
    if u.startswith("DELETE"):
        return f"Deletes rows from {names('delete')}{where}."
    if u.startswith("MERGE"):
        return f"Upserts (MERGE) into {names('merge')} from {names('read') or 'a source query'}."
    return ""
