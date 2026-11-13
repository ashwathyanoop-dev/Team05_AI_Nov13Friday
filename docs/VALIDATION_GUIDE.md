# Validating on an anonymised client sample

The tests and evaluation in this repository use synthetic code. Before the tool's comments are relied on for a client's codebase, run this procedure **inside the client environment**. Everything runs offline, and only anonymised material and aggregate numbers should leave the client.

## 1. Pick the sample

- Choose 20–50 representative members across COBOL programs, copybooks, JCL jobs, PROCLIB members and PL/SQL. Include the ugliest code: old pre-85 style, heavy `GO TO`, CICS, `REPLACE`, nested programs, generated code.
- Include the copybooks and PROCs those members reference, so cross-references resolve.
- Convert EBCDIC to UTF-8 or ASCII with the client's usual transfer tool.

## 2. Anonymise

```bash
python tools/anonymize.py client_sample/ anon_sample/ --key ../secure/anon-key.json
```

What the anonymiser changes:

- User-defined names are replaced with pseudonyms of **the same length**, consistently across files. COPY, CALL and EXEC links and file names still match, and COBOL and JCL column rules still hold.
- String literals become `XXXX`/`9999`. Comment text becomes `xxxx`. Letters in the sequence and identification areas are masked.
- Generic name parts (CALC, AMT, TOTAL…) are kept so the explanations stay readable. Use `--strict` to replace them too, and `--mask-numbers` to hide numeric constants.
- **The key file can reverse the anonymisation.** Keep it in the client's secure area and never share it with the anonymised code. Re-using the same `--key` keeps pseudonyms stable across runs.

Check the output by eye before it leaves the client: open a few files and confirm that no client names, account numbers or comments survived.

## 3. Run the automated checks

```bash
python tools/validate.py anon_sample/ --out validation/ --sample 60
```

`validation/VALIDATION_REPORT.md` contains:

| Gate | Target | Why it matters |
|---|---|---|
| No crashes | 100% | Every file must produce output |
| Byte-exact round trip | 100% | Comments never alter code |
| Column/width rules | 100% | COBOL ≤ column 72, JCL ≤ column 71 |
| In-stream data intact | 100% | JCL SYSIN data never split |
| Units documented | ≥ 95% | Every paragraph, procedure and step gets a header |

The report also lists per-file metrics and throughput, and flags files where the analyzer probably missed structure (for example "PROCEDURE DIVISION present but no paragraphs found"). An inventory-gap list shows referenced copybooks, PROCs and programs that were not supplied. The command exits non-zero if a gate fails, so it can run in CI.

## 4. SME accuracy review

`validation/review_sheet.csv` holds a random sample of generated comments, stratified by kind (summary, rule, logic, I/O, data, dependency, risk), with the code next to each one. Give it to one or two people who know the system. For each row, set **verdict** to `correct`, `partly`, `wrong` or `unclear`, and optionally fill `corrected_text` and `notes`.

```bash
python tools/validate.py --score validation/review_sheet.csv
```

`validation/ACCURACY.md` reports strict and lenient accuracy overall, per comment kind and per language, with 95% confidence intervals. It also lists every comment judged wrong. That list is the work queue for rule fixes: add the failing snippet (anonymised) to `tests/fixtures/` with a test, fix the analyzer, and re-run.

**Suggested acceptance bar** (agree it with the client up front): strict accuracy ≥ 85% for *rule* and *summary* comments, ≥ 90% for *I/O* and *dependency* comments, and every gate passing. With 60 rated comments the confidence interval is about ±10 points, so rate more if the decision is close.

## 5. Report back

Share `VALIDATION_REPORT.md`, `ACCURACY.md` and the anonymised examples of wrong comments. Never share the key file or the original code.
