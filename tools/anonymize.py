"""Anonymise a legacy codebase before validation or sharing, while preserving its structure.

    python tools/anonymize.py SRC_DIR OUT_DIR --key KEY.json [--strict] [--mask-numbers]

What changes
  * User-defined names (programs, paragraphs, fields, tables, datasets, procedures) are replaced by
    pronounceable pseudonyms of the SAME LENGTH, consistently across all files (so COPY/CALL/EXEC
    links and file names still match). Equal length keeps COBOL columns 7/8/12/72 and JCL column 71
    valid. Name parts that are generic (CALC, AMT, TOTAL...) are kept unless --strict is given.
  * String literals: letters become X and digits become 9 (length kept). JCL &SYMBOLS inside
    literals are renamed instead, so they still resolve.
  * Comment text: letters become x (comment markers, counts and line lengths kept).
  * Sequence/identification areas (COBOL columns 1-6 and 73-80): letters become X.
  * --mask-numbers also replaces digits in numeric literals (VALUE clauses, constants).
What does not change
  * Language keywords, PIC strings, level numbers, operators, layout and line structure.

The key file maps every pseudonym back to the original name. Keep it inside the client
environment. Never share it with the anonymised code.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from lcc.detect import detect  # noqa: E402
from lcc.jcl import _first_field  # noqa: E402
from lcc.vocab import ABBR  # noqa: E402

JCL_OPS = {"JOB", "EXEC", "DD", "PROC", "PEND", "SET", "IF", "ELSE", "ENDIF", "INCLUDE", "JCLLIB", "OUTPUT",
           "CNTL", "ENDCNTL", "COMMAND", "XMIT"}

COBOL_RESERVED = set("""
ACCEPT ACCESS ADD ADDRESS ADVANCING AFTER ALL ALPHABET ALPHABETIC ALPHANUMERIC ALSO ALTER ALTERNATE AND ANY ARE AREA
AREAS ASCENDING ASSIGN AT AUTHOR BEFORE BINARY BLANK BLOCK BOTTOM BY CALL CANCEL CD CF CH CHARACTER CHARACTERS CLASS
CLOSE COBOL CODE CODE-SET COLLATING COLUMN COMMA COMMON COMMUNICATION COMP COMP-1 COMP-2 COMP-3 COMP-4 COMP-5
COMPUTATIONAL COMPUTATIONAL-1 COMPUTATIONAL-2 COMPUTATIONAL-3 COMPUTATIONAL-4 COMPUTATIONAL-5 COMPUTE CONFIGURATION
CONTAINS CONTENT CONTINUE CONTROL CONTROLS CONVERTING COPY CORR CORRESPONDING COUNT CURRENCY DATA DATE DATE-COMPILED
DATE-WRITTEN DAY DAY-OF-WEEK DE DEBUGGING DECIMAL-POINT DECLARATIVES DELETE DELIMITED DELIMITER DEPENDING DESCENDING
DESTINATION DETAIL DISABLE DISPLAY DIVIDE DIVISION DOWN DUPLICATES DYNAMIC EGI ELSE EMI ENABLE END END-ADD END-CALL
END-COMPUTE END-DELETE END-DIVIDE END-EVALUATE END-EXEC END-IF END-MULTIPLY END-OF-PAGE END-PERFORM END-READ
END-RECEIVE END-RETURN END-REWRITE END-SEARCH END-START END-STRING END-SUBTRACT END-UNSTRING END-WRITE ENTER
ENVIRONMENT EOP EQUAL ERROR ESI EVALUATE EVERY EXCEPTION EXEC EXIT EXTEND EXTERNAL FALSE FD FILE FILE-CONTROL
FILLER FINAL FIRST FOOTING FOR FROM FUNCTION GENERATE GIVING GLOBAL GO GOBACK GREATER GROUP HEADING HIGH-VALUE
HIGH-VALUES I-O I-O-CONTROL ID IDENTIFICATION IF IN INDEX INDEXED INDICATE INITIAL INITIALIZE INITIATE INPUT
INPUT-OUTPUT INSPECT INSTALLATION INTO INVALID IS JUST JUSTIFIED KEY LABEL LAST LEADING LEFT LENGTH LESS LIMIT LIMITS
LINAGE LINAGE-COUNTER LINE LINE-COUNTER LINES LINKAGE LOCAL-STORAGE LOCK LOW-VALUE LOW-VALUES MEMORY MERGE MESSAGE
MODE MODULES MOVE MULTIPLE MULTIPLY NATIVE NEGATIVE NEXT NO NOT NUMBER NUMERIC NUMERIC-EDITED OBJECT-COMPUTER
OCCURS OF OFF OMITTED ON OPEN OPTIONAL OR ORDER ORGANIZATION OTHER OUTPUT OVERFLOW PACKED-DECIMAL PADDING PAGE
PAGE-COUNTER PERFORM PF PH PIC PICTURE PLUS POINTER POSITION POSITIVE PRINTING PROCEDURE PROCEDURES PROCEED PROGRAM
PROGRAM-ID PURGE QUEUE QUOTE QUOTES RANDOM RD READ RECEIVE RECORD RECORDING RECORDS REDEFINES REEL REFERENCE
REFERENCES RELATIVE RELEASE REMAINDER REMOVAL RENAMES REPLACE REPLACING REPORT REPORTING REPORTS RERUN RESERVE RESET
RETURN RETURN-CODE REVERSED REWIND REWRITE RF RH RIGHT ROUNDED RUN SAME SD SEARCH SECTION SECURITY SEGMENT
SEGMENT-LIMIT SELECT SEND SENTENCE SEPARATE SEQUENCE SEQUENTIAL SET SIGN SIZE SORT SORT-MERGE SOURCE
SOURCE-COMPUTER SPACE SPACES SPECIAL-NAMES STANDARD STANDARD-1 STANDARD-2 START STATUS STOP STRING SUB-QUEUE-1
SUBTRACT SUM SUPPRESS SYMBOLIC SYNC SYNCHRONIZED TABLE TALLYING TAPE TERMINAL TERMINATE TEST TEXT THAN THEN THROUGH
THRU TIME TIMES TO TOP TRAILING TRUE TYPE UNIT UNSTRING UNTIL UP UPON USAGE USE USING VALUE VALUES VARYING WHEN
WITH WORDS WORKING-STORAGE WRITE ZERO ZEROES ZEROS SQL SQLCA SQLCODE SQLSTATE CICS DFHCOMMAREA EIBCALEN EIBRESP
DFHRESP NOTFND DATASET RIDFLD COMMAREA LINK XCTL TRANSID MAP MAPSET HANDLE CONDITION SYNCPOINT ABEND STARTBR
READNEXT ENDBR RECEIVE SEND
""".split())

SQL_RESERVED = set("""
SELECT FROM WHERE INSERT INTO UPDATE DELETE MERGE SET VALUES BEGIN END IF THEN ELSE ELSIF LOOP FOR WHILE IN OUT
RETURN RETURNING IS AS DECLARE EXCEPTION WHEN OTHERS RAISE NULL COMMIT ROLLBACK SAVEPOINT CURSOR OPEN FETCH CLOSE
PROCEDURE FUNCTION PACKAGE BODY CREATE OR REPLACE TRIGGER BEFORE AFTER INSTEAD EACH ROW ON AND NOT CASE EXECUTE
IMMEDIATE PRAGMA TYPE SUBTYPE TABLE OF RECORD CONSTANT DEFAULT NUMBER INTEGER PLS_INTEGER BINARY_INTEGER VARCHAR2
VARCHAR CHAR DATE TIMESTAMP BOOLEAN CLOB BLOB ROWID BULK COLLECT LIMIT FORALL EXIT CONTINUE JOIN INNER LEFT RIGHT
FULL OUTER CROSS USING GROUP BY ORDER HAVING DISTINCT UNION ALL LIKE BETWEEN EXISTS ANY SOME AUTONOMOUS_TRANSACTION
EXCEPTION_INIT SYSDATE SYSTIMESTAMP USER RAISE_APPLICATION_ERROR NVL NVL2 DECODE COALESCE ROUND TRUNC GREATEST
LEAST SUM COUNT MAX MIN AVG TO_CHAR TO_DATE TO_NUMBER SUBSTR INSTR LENGTH UPPER LOWER TRIM LTRIM RTRIM REPLACE
ADD_MONTHS MONTHS_BETWEEN LAST_DAY MOD ABS CEIL FLOOR POWER SQRT REVERSE NO_DATA_FOUND TOO_MANY_ROWS
DUP_VAL_ON_INDEX ZERO_DIVIDE VALUE_ERROR INVALID_NUMBER OTHERS SQLERRM SQLCODE ROWTYPE ROWCOUNT FOUND NOTFOUND
ISOPEN DBMS_OUTPUT PUT_LINE DBMS_SQL DBMS_LOB DBMS_SCHEDULER DBMS_JOB UTL_FILE UTL_HTTP UTL_SMTP FOPEN FCLOSE
GET_LINE NEW OLD DUAL AUTHID DEFINER CURRENT_USER EDITIONABLE NONEDITIONABLE PIPELINED DETERMINISTIC NOCOPY
REF VARRAY EXTEND LAST NEXT PRIOR DELETE INDICES VALUES LOCK MODE SHARE EXCLUSIVE NOWAIT WAIT SKIP LOCKED
""".split())

JCL_RESERVED = set("""
JOB EXEC DD PROC PEND SET IF THEN ELSE ENDIF INCLUDE JCLLIB OUTPUT CNTL ENDCNTL COMMAND PGM COND PARM REGION TIME
CLASS MSGCLASS MSGLEVEL NOTIFY TYPRUN RESTART USER PASSWORD ACCT DSN DSNAME DISP SHR NEW OLD MOD CATLG UNCATLG
DELETE KEEP PASS SPACE TRK CYL RLSE CONTIG DCB RECFM LRECL BLKSIZE DSORG FB VB FBA VBA PS PO UNIT VOL SER SYSDA
SYSALLDA SYSOUT DUMMY DATA DLM ORDER MEMBER LT GT EQ NE LE GE EVEN ONLY RC ABEND ABENDCC RUN SYSUID SYSIN
SYSPRINT SYSUDUMP SYSABEND CEEDUMP SYSDBOUT SYSUT1 SYSUT2 SYSUT3 SORTIN SORTOUT SORTWK01 SORTWK02 SORTWK03
STEPLIB JOBLIB SORT FIELDS COPY OMIT CH ZD PD BI FI FORMAT SUM NONE OUTREC INREC BUILD OUTFIL OPTION EQUALS
IEFBR14 IEBGENER IEBCOPY IDCAMS IKJEFT01 IKJEFT1B ICEMAN DFSORT SYNCSORT ICETOOL ICEGENER REPRO DEFINE CLUSTER
INFILE OUTFILE INDATASET OUTDATASET NULLFILE LIKE REFDD STORCLAS MGMTCLAS DATACLAS AVGREC LABEL EXPDT RETPD
""".split())

GENERIC = set(ABBR) | set("""
TOTAL COUNT NAME DATE CODE STATUS FLAG RECORD FILE TABLE KEY INDEX AMOUNT RATE BALANCE TYPE NUMBER LINE ITEM
LIST DETAIL HEADER TRAILER INPUT OUTPUT ERROR MESSAGE REPORT PAGE MAIN INIT READ WRITE PROCESS VALID VALIDATE
CHECK UPDATE CALC COMPUTE START END FINISH OPEN CLOSE LOAD SAVE GET PUT SEND RECEIVE TEMP WORK HOLD SAVE PREV
NEXT CURRENT FIRST LAST MAX MIN SUM AVG ID DESC TEXT VALUE LIMIT YEAR MONTH DAY TIME HOUR MINUTE SECOND
SWITCH SW EOF IDX SUB CNT CTR TOT AMT QTY PCT
""".split())

PSEUDO_C = "BCDFGHJKLMNPRSTVWZ"
PSEUDO_V = "AEIOU"


class Anonymizer:
    def __init__(self, salt: str, strict: bool = False, mask_numbers: bool = False, mapping: dict | None = None):
        self.salt = salt
        self.strict = strict
        self.mask_numbers = mask_numbers
        self.map: dict[str, str] = dict(mapping or {})
        self.used = {v.upper() for v in self.map.values()}
        self.keep = COBOL_RESERVED | SQL_RESERVED | JCL_RESERVED | (set() if strict else GENERIC)

    # ---------------------------------------------------------------- names
    def pseudo(self, seg: str) -> str:
        key = seg.upper()
        if key in self.map:
            out = self.map[key]
        else:
            n, attempt = len(seg), 0
            while True:
                h = hashlib.sha256(f"{self.salt}:{key}:{attempt}".encode()).digest()
                out = "".join((PSEUDO_C if i % 2 == 0 else PSEUDO_V)[h[i % len(h)] % (18 if i % 2 == 0 else 5)]
                              for i in range(n))
                if out not in self.keep and out not in self.used and out != key:
                    break
                attempt += 1
            self.map[key] = out
            self.used.add(out)
        if seg.islower():
            return out.lower()
        if seg[:1].isupper() and seg[1:].islower():
            return out.capitalize()
        return out

    def word(self, w: str) -> str:
        if w.upper() in self.keep:
            return w
        parts = re.split(r"([-_.$#@])", w)
        out = []
        for p in parts:
            if not p or p in "-_.$#@" or len(p) <= 2 or any(ch.isdigit() for ch in p) or p.upper() in self.keep:
                out.append(p)
            else:
                out.append(self.pseudo(p))
        return "".join(out)

    # ---------------------------------------------------------------- text pieces
    def literal(self, lit: str, jcl: bool) -> str:
        q, body = lit[0], lit[1:-1] if len(lit) > 1 and lit[-1] == lit[0] else lit[1:]
        close = lit[-1] if len(lit) > 1 and lit[-1] == lit[0] else ""
        if jcl:
            pieces = re.split(r"(&[A-Za-z@#$][A-Za-z0-9@#$]*)", body)
            body = "".join("&" + self.word(p[1:]) if p.startswith("&") and len(p) > 1 else self._mask(p, "X", "9")
                           for p in pieces)
        else:
            body = self._mask(body, "X", "9")
        return q + body + close

    @staticmethod
    def _mask(s: str, letter: str, digit: str | None) -> str:
        return "".join(letter if ch.isalpha() else (digit if digit and ch.isdigit() else ch) for ch in s)

    def code(self, text: str, lang: str) -> str:
        """Rename identifiers and mask literals in a code fragment (no comments in it)."""
        ident = r"[A-Za-z][A-Za-z0-9-]*" if lang == "cobol" else (r"[A-Za-z@#$&][A-Za-z0-9@#$]*" if lang == "jcl" else r"[A-Za-z_][\w$#]*")
        rx = re.compile(r"('(?:[^']|'')*'?|\"[^\"]*\"?)|(\b\d+(?:\.\d+)?\b)|(" + ident + r")|([\s\S])")
        out, prev = [], ""
        for m in rx.finditer(text):
            lit, num, word, other = m.groups()
            if lit:
                out.append(self.literal(lit, lang == "jcl"))
            elif num:
                out.append(self._mask(num, "", "9") if self.mask_numbers and prev not in ("PIC", "PICTURE", "IS") else num)
            elif word:
                up = word.upper()
                if lang == "cobol" and prev in ("PIC", "PICTURE") or (prev == "IS" and out and "PIC" in "".join(out[-6:]).upper()):
                    out.append(word)                       # PIC strings: X(30), S9(7)V99 ...
                elif lang == "jcl" and word.startswith("&"):
                    out.append("&" + self.word(word[1:]) if len(word) > 1 else word)
                else:
                    out.append(self.word(word))
                prev = up
                continue
            else:
                out.append(other)
                if not other.isspace():
                    prev = other
                continue
            prev = ""
        return "".join(out)

    # ---------------------------------------------------------------- per language
    def cobol(self, lines: list[str]) -> list[str]:
        fixed = sum(1 for l in lines if len(l) > 6 and l[6] in " *-/Dd") >= 0.8 * max(1, sum(1 for l in lines if l.strip()))
        out = []
        for ln in lines:
            if fixed and len(ln) > 6:
                seq, ind, body, tail = ln[:6], ln[6], ln[7:72], ln[72:]
                seq, tail = self._mask(seq, "X", None), self._mask(tail, "X", None)
                if ind in "*/":
                    body = body if "[AI]" in body else self._mask(body, "x", None)
                else:
                    code, com = _split_comment(body, "*>")
                    body = self.code(code, "cobol") + (self._mask(com, "x", None) if com else "")
                out.append(seq + ind + body + tail)
            else:
                code, com = _split_comment(ln, "*>")
                out.append(self.code(code, "cobol") + (self._mask(com, "x", None) if com and "[AI]" not in com else com))
        return out

    def plsql(self, lines: list[str]) -> list[str]:
        out, in_block = [], False
        for ln in lines:
            res, rest = "", ln
            while rest:
                if in_block:
                    j = rest.find("*/")
                    seg = rest if j < 0 else rest[:j + 2]
                    res += self._mask(seg, "x", None)
                    rest = "" if j < 0 else rest[j + 2:]
                    in_block = j < 0
                    continue
                code, com = _split_comment(rest, "--")
                bcode, bcom = _split_comment(code, "/*")
                if bcom:
                    res += self.code(bcode, "plsql")
                    rest = bcom + com
                    j = rest.find("*/", 2)
                    seg = rest if j < 0 else rest[:j + 2]
                    res += self._mask(seg, "x", None)
                    rest = "" if j < 0 else rest[j + 2:]
                    in_block = j < 0
                    continue
                res += self.code(code, "plsql") + (com if "[AI]" in com else self._mask(com, "x", None))
                rest = ""
            out.append(res)
        return out

    def jcl(self, lines: list[str]) -> list[str]:
        out = []
        for ln in lines:
            if ln.startswith("//*"):
                out.append(ln if "[AI]" in ln else "//*" + self._mask(ln[3:], "x", None))
                continue
            if not ln.startswith("//") and not ln.startswith("/*"):
                out.append(self.code(ln, "jcl"))      # in-stream data / control cards
                continue
            if ln.startswith("/*"):
                out.append(ln)
                continue
            body, tail = ln[2:71], ln[71:]
            name = "" if body.startswith(" ") else body.split(" ", 1)[0]
            rest = body[len(name):]
            sp1 = rest[:len(rest) - len(rest.lstrip())]
            rest = rest.lstrip()
            tok = rest.split(" ", 1)[0] if rest else ""
            op, sp2 = "", ""
            if tok.upper() in JCL_OPS:                 # otherwise this is a continuation line of operands
                op = tok
                rest = rest[len(tok):]
                sp2 = rest[:len(rest) - len(rest.lstrip())]
                rest = rest.lstrip()
            if op.upper() in ("IF", "ELSE", "ENDIF"):
                field, comment = rest, ""
            else:
                field, comment = _first_field(rest)
            new = self.code(name, "jcl") + sp1 + op + sp2 + self.code(field, "jcl") + self._mask(comment, "x", None)
            out.append(ln[:2] + new + self._mask(tail, "X", None))
        return out

    def file(self, name: str, text: str) -> tuple[str, str]:
        lang = detect(name, text)
        nl = "\r\n" if "\r\n" in text else "\n"
        lines = text.replace("\r\n", "\n").split("\n")
        if lang == "cobol":
            lines = self.cobol(lines)
        elif lang == "plsql":
            lines = self.plsql(lines)
        elif lang == "jcl":
            lines = self.jcl(lines)
        else:
            lines = [self.code(l, "plsql") for l in lines]
        stem, ext = os.path.splitext(name)
        return self.word(stem) + ext, nl.join(lines)


def _split_comment(s: str, marker: str) -> tuple[str, str]:
    q = ""
    for i, ch in enumerate(s):
        if q:
            if ch == q:
                q = ""
        elif ch in "'\"":
            q = ch
        elif s.startswith(marker, i):
            return s[:i], s[i:]
    return s, ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--key", required=True, help="where to write (or read, to reuse) the pseudonym key; keep it private")
    ap.add_argument("--strict", action="store_true", help="also replace generic words such as CALC, TOTAL, AMT")
    ap.add_argument("--mask-numbers", action="store_true", help="also mask digits in numeric literals")
    args = ap.parse_args(argv)
    key = {}
    if os.path.exists(args.key):
        with open(args.key, encoding="utf-8") as f:
            key = json.load(f)
    an = Anonymizer(key.get("salt") or secrets.token_hex(16), args.strict, args.mask_numbers, key.get("mapping"))
    os.makedirs(args.out, exist_ok=True)
    n = 0
    for dirpath, _, names in os.walk(args.src):
        for name in sorted(names):
            path = os.path.join(dirpath, name)
            with open(path, encoding="utf-8", errors="replace", newline="") as f:
                text = f.read()
            new_name, new_text = an.file(name, text)
            rel = os.path.relpath(dirpath, args.src)
            dest_dir = os.path.join(args.out, rel) if rel != "." else args.out
            os.makedirs(dest_dir, exist_ok=True)
            with open(os.path.join(dest_dir, new_name), "w", encoding="utf-8", newline="") as f:
                f.write(new_text)
            n += 1
            print(f"{os.path.join(rel, name)} -> {os.path.join(rel, new_name)}")
    with open(args.key, "w", encoding="utf-8") as f:
        json.dump({"salt": an.salt, "strict": args.strict,
                   "mapping": an.map, "reverse": {v: k for k, v in an.map.items()}}, f, indent=1)
    print(f"{n} files anonymised into {args.out}. Pseudonym key: {args.key} (keep private, never share).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
