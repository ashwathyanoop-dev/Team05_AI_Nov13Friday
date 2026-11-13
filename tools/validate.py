"""Validate the commenter on a real (anonymised) codebase, then score SME review of its comments.

Step 1 - automated checks + review sheet:
    python tools/validate.py CODE_DIR [--out validation] [--sample 60] [--seed 7]
  For every file: analysis must not crash; export must strip back to the original byte-for-byte;
  COBOL fixed-format comments must stay within column 72 and JCL within 71; nothing may be inserted
  inside JCL in-stream data. It also reports coverage, speed, inventory gaps, and files where the
  analyzer probably missed structure. It writes:
      validation/VALIDATION_REPORT.md   checks and metrics per file, plus pass/fail gates
      validation/review_sheet.csv       a stratified random sample of comments for SMEs to judge

Step 2 - SMEs fill the "verdict" column (correct / partly / wrong / unclear), then:
    python tools/validate.py --score validation/review_sheet.csv
  writes validation/ACCURACY.md: accuracy per comment kind and language with 95% confidence
  intervals, and lists every comment judged wrong (input for rule fixes).
"""
from __future__ import annotations

import argparse
import collections
import csv
import math
import os
import random
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from lcc import commenter, engine  # noqa: E402
from lcc.commenter import marker_regex  # noqa: E402
from lcc.exporters import system_map  # noqa: E402

TEXT_EXT_SKIP = {".png", ".jpg", ".gif", ".zip", ".exe", ".dll", ".pdf", ".xls", ".xlsx", ".doc", ".docx", ".bin"}
LIB_EXT = {".cpy", ".cpb", ".proc", ".prc", ".jcl", ".cntl", ".prclib"}
GATES = {"no crashes": 1.0, "byte-exact round trip": 1.0, "column/width rules": 1.0, "in-stream data intact": 1.0,
         "units documented": 0.95}


def read(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace", newline="") as f:
        return f.read()


def collect(code_dir: str) -> list[str]:
    out = []
    for dirpath, _, names in os.walk(code_dir):
        for n in sorted(names):
            if os.path.splitext(n)[1].lower() not in TEXT_EXT_SKIP and not n.startswith("."):
                out.append(os.path.join(dirpath, n))
    return out


def check_file(path: str, text: str, library: dict, base: str = ".") -> dict:
    name = os.path.basename(path)
    row = {"file": os.path.relpath(path, base).replace(os.sep, "/"), "name": name, "issues": []}
    t0 = time.perf_counter()
    try:
        res = engine.analyze(text, name, library=library)
    except Exception as e:  # noqa: BLE001 - a crash is a finding, not a stop
        row.update(crashed=True, issues=[f"analysis crashed: {type(e).__name__}: {e}"], language="?", lines=text.count("\n"))
        return row
    row["ms"] = (time.perf_counter() - t0) * 1000
    row.update(crashed=False, res=res, language=res["language"], lines=res["line_count"])
    text_out, m = engine.render_file(res)
    row["metrics"] = m
    row["roundtrip"] = commenter.strip(text_out) == text
    if not row["roundtrip"]:
        row["issues"].append("export does not strip back to the original")
    rx = marker_regex("AI")
    out_lines = text_out.replace("\r\n", "\n").split("\n")
    width_ok = True
    for ln in out_lines:
        if rx.match(ln):
            if res["language"] == "cobol" and res["dialect"] == "fixed" and (len(ln) > 72 or not ln.startswith("      *[AI]")):
                width_ok = False
            if res["language"] == "jcl" and (len(ln) > 71 or not ln.startswith("//*[AI]")):
                width_ok = False
    row["width_ok"] = width_ok
    if not width_ok:
        row["issues"].append("generated comment breaks a column rule")
    src_lines = res["content"].replace("\r\n", "\n").split("\n")
    protected = set(res.get("protected_lines", []))
    instream_ok = True
    if protected:
        j = 0
        prev_ai = False
        for ln in out_lines:
            if rx.match(ln):
                prev_ai = True
                continue
            j += 1
            if j in protected and prev_ai:
                instream_ok = False
            prev_ai = False
    row["instream_ok"] = instream_ok
    if not instream_ok:
        row["issues"].append("a comment was inserted inside JCL in-stream data")
    units = res["units"]
    row["units"] = len(units)
    if res["language"] == "cobol" and "PROCEDURE DIVISION" in text.upper() and not [u for u in units if u["kind"] in ("paragraph", "section")]:
        row["issues"].append("PROCEDURE DIVISION present but no paragraphs found (layout not understood?)")
    if res["language"] == "plsql" and "BEGIN" in text.upper() and not units:
        row["issues"].append("PL/SQL blocks present but no units found")
    if res["language"] == "jcl" and " EXEC " in text.upper() and not units:
        row["issues"].append("EXEC statements present but no steps found")
    if res["language"] == "generic":
        row["issues"].append("language not recognised: generic analysis only")
    if m["units"] and m["units_documented_after"] < m["units"]:
        row["issues"].append(f"{m['units'] - m['units_documented_after']} units without a header comment")
    missing_books = [d["name"] for d in res["dependencies"] if d["kind"] == "copybook" and d["name"] not in res.get("copybooks_resolved", [])]
    missing_procs = [d["name"] for d in res["dependencies"] if d["kind"] == "proc" and d["name"].upper() not in res.get("procs_resolved", [])]
    if missing_books:
        row["issues"].append("copybooks not supplied: " + ", ".join(missing_books[:8]))
    if missing_procs:
        row["issues"].append("procedures not supplied: " + ", ".join(missing_procs[:8]))
    return row


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    r = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (c - r) / d), min(1.0, (c + r) / d)


def sample_sheet(rows: list[dict], n: int, seed: int) -> list[dict]:
    pool = collections.defaultdict(list)
    for r in rows:
        if r.get("crashed"):
            continue
        lines = r["res"]["content"].replace("\r\n", "\n").split("\n")
        for a in r["res"]["annotations"]:
            if a["detail"]:
                continue
            ctx = " ⏎ ".join(l.strip() for l in lines[a["line"] - 1:a["line"] + 3] if l.strip())
            pool[a["kind"]].append({"file": r["file"], "language": r["language"], "line": a["line"], "kind": a["kind"],
                                    "comment": a["text"], "code_context": ctx[:400]})
    rnd = random.Random(seed)
    total = sum(len(v) for v in pool.values()) or 1
    picked = []
    for kind, items in sorted(pool.items()):
        k = min(len(items), max(3, round(n * len(items) / total)))
        picked += rnd.sample(items, k)
    rnd.shuffle(picked)
    for i, p in enumerate(picked, 1):
        p.update(id=i, verdict="", corrected_text="", notes="")
    return picked


def run(code_dir: str, out: str, n: int, seed: int) -> int:
    paths = collect(code_dir)
    texts = {p: read(p) for p in paths}
    library = {os.path.splitext(os.path.basename(p))[0]: t for p, t in texts.items()
               if os.path.splitext(p)[1].lower() in LIB_EXT}
    rows = [check_file(p, texts[p], library, code_dir) for p in paths]
    ok_rows = [r for r in rows if not r.get("crashed")]
    sm = system_map([r["res"] for r in ok_rows])
    gate_vals = {
        "no crashes": (len(ok_rows), len(rows)),
        "byte-exact round trip": (sum(r["roundtrip"] for r in ok_rows), len(ok_rows)),
        "column/width rules": (sum(r["width_ok"] for r in ok_rows), len(ok_rows)),
        "in-stream data intact": (sum(r["instream_ok"] for r in ok_rows), len(ok_rows)),
        "units documented": (sum(r["metrics"]["units_documented_after"] for r in ok_rows),
                             sum(r["metrics"]["units"] for r in ok_rows)),
    }
    total_lines = sum(r["lines"] for r in rows)
    total_ms = sum(r.get("ms", 0) for r in ok_rows)
    os.makedirs(out, exist_ok=True)
    md = ["# Validation report", "", f"_Generated {time.strftime('%Y-%m-%d %H:%M')} by `python tools/validate.py` on `{code_dir}` "
          f"({len(rows)} files, {total_lines:,} lines)._", "", "## Gates", "", "| Check | Result | Target | Status |", "|---|---|---|---|"]
    all_pass = True
    for g, (k, n_) in gate_vals.items():
        rate = k / n_ if n_ else 1.0
        passed = rate >= GATES[g]
        all_pass &= passed
        md.append(f"| {g} | {k}/{n_} ({rate:.0%}) | ≥ {GATES[g]:.0%} | {'PASS' if passed else '**FAIL**'} |")
    md += ["", f"Throughput: {total_lines / max(total_ms / 1000, 1e-6):,.0f} lines/second ({total_ms / 1000:.2f} s analysis time).",
           "", "Comment *accuracy* cannot be checked automatically. Have SMEs fill `review_sheet.csv`, then run "
           "`python tools/validate.py --score validation/review_sheet.csv`.", "",
           "## Files", "", "| File | Language | Lines | ms | Units (documented) | Rules | Risks | Density before → after | Issues |",
           "|---|---|---|---|---|---|---|---|---|"]
    by_lang = collections.Counter()
    for r in rows:
        by_lang[r["language"]] += 1
        if r.get("crashed"):
            md.append(f"| {r['file']} | ? | {r['lines']} | – | – | – | – | – | {'; '.join(r['issues'])} |")
            continue
        m = r["metrics"]
        md.append(f"| {r['file']} | {r['res']['language_name']} | {r['lines']} | {r['ms']:.0f} | {m['units']} ({m['units_documented_after']}) | "
                  f"{m['business_rules']} | {m['risks']} | {m['density_before']:.0%} → {m['density_after']:.0%} | "
                  f"{'; '.join(r['issues']) or '–'} |")
    md += ["", "## Language mix", "", ", ".join(f"{k}: {v}" for k, v in by_lang.most_common()), ""]
    if sm["unresolved"]:
        md += ["## Inventory gaps (referenced, not supplied)", ""]
        md += [f"- {u['kind']} `{u['name']}` (from {u['file']})" for u in sm["unresolved"]]
        md.append("")
    sheet = sample_sheet(rows, n, seed)
    md += ["## Review sheet", "", f"`review_sheet.csv` holds {len(sheet)} comments, a random sample stratified by kind "
           f"(seed {seed}). Allowed verdicts: `correct`, `partly`, `wrong`, `unclear`.", ""]
    with open(os.path.join(out, "VALIDATION_REPORT.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(md))
    cols = ["id", "file", "language", "line", "kind", "comment", "code_context", "verdict", "corrected_text", "notes"]
    with open(os.path.join(out, "review_sheet.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(sheet)
    for g, (k, n_) in gate_vals.items():
        print(f"{g:<24} {k}/{n_}")
    issues = sum(1 for r in rows if r["issues"])
    print(f"{len(rows)} files, {issues} with issues; gates {'PASS' if all_pass else 'FAIL'}; "
          f"report: {os.path.join(out, 'VALIDATION_REPORT.md')}; review sheet: {len(sheet)} comments")
    return 0 if all_pass else 1


def score(sheet_path: str) -> int:
    with open(sheet_path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    rated = [r for r in rows if r.get("verdict", "").strip().lower() in ("correct", "partly", "wrong")]
    if not rated:
        print("No verdicts yet: fill the 'verdict' column with correct / partly / wrong / unclear.")
        return 1

    def stats(items):
        n = len(items)
        c = sum(1 for r in items if r["verdict"].strip().lower() == "correct")
        p = sum(1 for r in items if r["verdict"].strip().lower() == "partly")
        lo, hi = wilson(c, n)
        return n, c, p, c / n if n else 0, lo, hi

    out = ["# Comment accuracy (SME review)", "",
           f"{len(rated)} of {len(rows)} sampled comments rated; 'unclear' and blank verdicts excluded.", "",
           "Strict accuracy counts only `correct`. Lenient accuracy also counts `partly` as half.", "",
           "| Group | Rated | Correct | Partly | Strict accuracy | 95% CI | Lenient |", "|---|---|---|---|---|---|---|"]

    def line(label, items):
        n, c, p, acc, lo, hi = stats(items)
        out.append(f"| {label} | {n} | {c} | {p} | {acc:.0%} | {lo:.0%}–{hi:.0%} | {(c + 0.5 * p) / n:.0%} |")

    line("**All**", rated)
    for kind in sorted({r["kind"] for r in rated}):
        line(f"kind: {kind}", [r for r in rated if r["kind"] == kind])
    for lang in sorted({r["language"] for r in rated}):
        line(f"language: {lang}", [r for r in rated if r["language"] == lang])
    wrong = [r for r in rated if r["verdict"].strip().lower() == "wrong"]
    if wrong:
        out += ["", "## Comments judged wrong", "", "| File | Line | Kind | Comment | SME correction / notes |", "|---|---|---|---|---|"]
        for r in wrong:
            fix = " ".join(x for x in (r.get("corrected_text", ""), r.get("notes", "")) if x).replace("|", "\\|")
            out.append(f"| {r['file']} | {r['line']} | {r['kind']} | {r['comment'][:160].replace('|', '/')} | {fix} |")
    path = os.path.join(os.path.dirname(os.path.abspath(sheet_path)), "ACCURACY.md")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out) + "\n")
    n, c, p, acc, lo, hi = stats(rated)
    print(f"strict accuracy {acc:.0%} (95% CI {lo:.0%}-{hi:.0%}) over {n} rated comments; wrote {path}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Validate the commenter on a codebase and score SME reviews.")
    ap.add_argument("code_dir", nargs="?")
    ap.add_argument("--out", default="validation")
    ap.add_argument("--sample", type=int, default=60, help="approximate number of comments in the review sheet")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--score", metavar="SHEET", help="score a filled review sheet instead")
    args = ap.parse_args(argv)
    if args.score:
        return score(args.score)
    if not args.code_dir:
        ap.error("CODE_DIR is required (or use --score SHEET)")
    return run(args.code_dir, args.out, args.sample, args.seed)


if __name__ == "__main__":
    sys.exit(main())
