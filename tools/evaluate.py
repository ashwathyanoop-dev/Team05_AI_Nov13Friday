"""Comprehension evaluation: can a newcomer answer key questions from the comments alone?

For each synthetic sample we list the questions a developer new to the code typically has to
answer during migration analysis, plus evidence phrases that a correct answer must contain.
A question counts as "answerable" when every evidence phrase appears in the file's comment
lines (case-insensitive). We compare:

  before - the comments that were already in the source
  after  - original comments + generated comments at the default "essential" level, no review

This is an automated proxy, not a user study; see docs/EVALUATION.md for the human protocol.
Run:  python tools/evaluate.py   (writes docs/EVALUATION.md)
"""
from __future__ import annotations

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from lcc.commenter import marker_regex  # noqa: E402
from lcc.engine import analyze, comment_line_set, render_file, split_source  # noqa: E402

QUESTIONS = {
    "PAYROLL.cbl": [
        ("Which external dataset (DD name) supplies the employee input?", ["EMP-FILE", "EMPIN"]),
        ("When is an hourly employee paid overtime?", ["EMP-HOURS is greater than WS-STD-HRS"]),
        ("How is gross pay computed for salaried staff?", ["EMP-SALARIED", "/ 26"]),
        ("Which employee types count as hourly?", ["EMP-HOURLY", "'H', 'P'"]),
        ("What happens when the TAXCALC call fails?", ["TP-RETURN-CD", "WS-FED-TAX to ZERO"]),
        ("Is the 401(k) deduction capped, and by what?", ["WS-401K-MAX"]),
        ("Is overtime pay rounded or truncated?", ["WS-OT-PAY", "truncated"]),
        ("Which return code signals records in error?", ["RETURN-CODE to 4"]),
        ("Which paragraphs run for every employee record?", ["2200-CALC-GROSS-PAY", "2500-WRITE-PAY-RECORD"]),
        ("Which constructs are risky to migrate?", ["GO TO", "REDEFINES"]),
        ("Which fields must not become floating point in Java?", ["COMP-3", "BigDecimal"]),
    ],
    "loan_servicing.pkb": [
        ("What happens to a payment on a closed loan?", ["REJECTED_CLOSED"]),
        ("Is interest settled before principal?", ["p_amount is at least v_interest"]),
        ("When is a late fee charged?", ["v_dpd is greater than 30", "c_late_fee"]),
        ("When does a loan move to DEFAULT?", ["days_past_due is greater than 90"]),
        ("Which error rejects non-positive payments?", ["ORA-20010"]),
        ("Which tables does apply_payment change?", ["modifies LOANS and PAYMENTS"]),
        ("Are any errors silently swallowed?", ["WHEN OTHERS THEN NULL"]),
        ("Is there a transaction-boundary risk in the monthly accrual?", ["COMMIT inside a loop"]),
        ("How is the risk grade decided?", ["return 'D'", "return 'A'"]),
        ("Is there an SQL-injection risk?", ["SQL-injection"]),
    ],
    "trg_payment_limits.trg": [
        ("When does the trigger fire?", ["before insert/update on PAYMENTS"]),
        ("What is the daily payment limit and what happens above it?", ["50000", "ORA-20020"]),
    ],
    "NIGHTPAY.jcl": [
        ("How is the employee file sorted before payroll runs?", ["bytes 37", "bytes 1"]),
        ("Which records are kept by the sort?", ["keeps only records"]),
        ("When is the PAYROLL step skipped?", ["STEP020 is bypassed", "greater than 4"]),
        ("Where does the payroll output go?", ["NEW generation", "PROD.PAYROLL.PAYFILE"]),
        ("When is the error log printed?", ["STEP020 return code = 4"]),
        ("What does the GL posting step read?", ["current generation"]),
    ],
    "CUSTRISK.cob": [
        ("What utilisation makes a customer high risk?", ["is greater than 90", "'H'"]),
        ("Which tables are read and which are updated?", ["CUSTOMER", "Updates ACCOUNT"]),
        ("How is utilisation calculated?", ["WS-BALANCE", "WS-CREDIT-LMT", "100"]),
    ],
    "EMPREC.cpy": [
        ("How long is an employee record?", ["80 bytes"]),
        ("What does EMP-STATUS 'T' mean?", ["EMP-TERMINATED", "'T'"]),
    ],
}


def comment_corpus(text: str, language: str, dialect: str, ext: str) -> str:
    lines, _, _ = split_source(text)
    idx = comment_line_set(lines, language, dialect, ext)
    rx = marker_regex("AI")
    out = []
    for i, ln in enumerate(lines, 1):
        if i in idx or rx.match(ln):
            out.append(ln.split("[AI]", 1)[-1])
    # Wrapped comments: join continuation lines so phrases split across lines still match.
    joined = " ".join(" ".join(l.replace("*", " ", 1).split()) for l in out)
    return " ".join(joined.split()).lower()


def answerable(corpus: str, evidence: list[str]) -> bool:
    return all(" ".join(e.lower().split()) in corpus for e in evidence)


def lib() -> dict:
    sd = os.path.join(ROOT, "samples")
    return {os.path.splitext(n)[0]: open(os.path.join(sd, n), encoding="utf-8").read()
            for n in os.listdir(sd) if n.endswith(".cpy")}


def main() -> int:
    library = lib()
    rows, qrows = [], []
    tot_b = tot_a = tot_q = 0
    for name, qs in QUESTIONS.items():
        with open(os.path.join(ROOT, "samples", name), encoding="utf-8", newline="") as f:
            src = f.read()
        res = analyze(src, name, library=library)
        res["annotations"] = [a for a in res["annotations"] if not a["detail"]]   # essential level, unreviewed
        text, m = render_file(res)   # default export settings (ASCII-safe)
        before = comment_corpus(src, res["language"], res["dialect"], res["ext"])
        after = comment_corpus(text, res["language"], res["dialect"], res["ext"])
        b = sum(answerable(before, e) for _, e in qs)
        a = sum(answerable(after, e) for _, e in qs)
        tot_b, tot_a, tot_q = tot_b + b, tot_a + a, tot_q + len(qs)
        rows.append((name, res["language_name"], m, b, a, len(qs)))
        for q, e in qs:
            qrows.append((name, q, answerable(before, e), answerable(after, e)))

    out = ["# Evaluation: does the generated commentary improve code comprehension?", "",
           f"_Generated {time.strftime('%Y-%m-%d %H:%M')} by `python tools/evaluate.py` on the synthetic sample codebase._", "",
           "## Method", "",
           "Each sample has questions a developer new to the code must answer during migration analysis "
           "(business rules, data flow, dependencies, risks). Each question has evidence phrases that a correct "
           "answer must contain. A question is **answerable** when all its evidence appears in the file's comment "
           "lines. *Before* uses only the original comments. *After* adds the generated comments at the default "
           "**Essential** level, with no human review or edits and no LLM, so this is the rule engine's floor.", "",
           "## Results", "",
           "| File | Language | Questions answerable before | after | Comment density before → after | Units with header comment before → after | Rules surfaced | Risks surfaced |",
           "|---|---|---|---|---|---|---|---|"]
    for name, lang, m, b, a, n in rows:
        out.append(f"| {name} | {lang} | {b}/{n} | **{a}/{n}** | {m['density_before']:.0%} → {m['density_after']:.0%} | "
                   f"{m['units_documented_before']}/{m['units']} → {m['units_documented_after']}/{m['units']} | {m['business_rules']} | {m['risks']} |")
    out += ["", f"**Overall: {tot_b}/{tot_q} questions answerable from the original comments, "
            f"{tot_a}/{tot_q} ({tot_a / tot_q:.0%}) with the generated comments.**", "",
            "## Question detail", "", "| File | Question | Before | After |", "|---|---|---|---|"]
    for name, q, b, a in qrows:
        out.append(f"| {name} | {q} | {'✓' if b else '✗'} | {'✓' if a else '✗'} |")
    out += ["", "## Limitations", "",
            "- This is an automated proxy. It shows the information is *present* in the comments, not that a reader "
            "understands it faster. The questions were written by the tool's authors for synthetic code, so treat the "
            "after-score as an upper bound for real client code.",
            "- Comment density over 100% means more comment lines than code lines. Reviewers normally reject or trim "
            "some suggestions, and the *Essential* level already hides field-by-field data notes.",
            "", "## Recommended human study (for a client pilot)", "",
            "1. Pick two comparable modules from the anonymised client codebase and two developers with no prior exposure.",
            "2. Each developer gets one module raw and the other annotated (counterbalanced), plus the same 8–10 questions.",
            "3. Record time to answer, correctness (scored by an SME), and confidence (1–5).",
            "4. Report the per-module deltas, and log which generated comments the SME marked wrong. Those logs feed rule "
            "improvements.", ""]
    path = os.path.join(ROOT, "docs", "EVALUATION.md")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out))
    for name, lang, m, b, a, n in rows:
        print(f"{name:<24} {b:>2}/{n:<2} -> {a:>2}/{n:<2}   density {m['density_before']:.0%} -> {m['density_after']:.0%}")
    print(f"TOTAL {tot_b}/{tot_q} -> {tot_a}/{tot_q}   (wrote docs/EVALUATION.md)")
    missed = [(n, q) for n, q, _, a in qrows if not a]
    for n, q in missed:
        print(f"  not answerable after: {n}: {q}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
