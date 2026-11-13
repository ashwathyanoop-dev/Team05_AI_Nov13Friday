# Evaluation: does the generated commentary improve code comprehension?

_Generated 2026-11-13 13:35 by `python tools/evaluate.py` on the synthetic sample codebase._

## Method

Each sample has questions a developer new to the code must answer during migration analysis (business rules, data flow, dependencies, risks). Each question has evidence phrases that a correct answer must contain. A question is **answerable** when all its evidence appears in the file's comment lines. *Before* uses only the original comments. *After* adds the generated comments at the default **Essential** level, with no human review or edits and no LLM, so this is the rule engine's floor.

## Results

| File | Language | Questions answerable before | after | Comment density before → after | Units with header comment before → after | Rules surfaced | Risks surfaced |
|---|---|---|---|---|---|---|---|
| PAYROLL.cbl | COBOL | 0/11 | **11/11** | 2% → 112% | 1/11 → 11/11 | 7 | 2 |
| loan_servicing.pkb | PL/SQL | 0/10 | **10/10** | 1% → 54% | 0/4 → 4/4 | 7 | 4 |
| trg_payment_limits.trg | PL/SQL | 0/2 | **2/2** | 0% → 56% | 0/1 → 1/1 | 1 | 0 |
| NIGHTPAY.jcl | JCL | 0/6 | **6/6** | 9% → 128% | 0/4 → 4/4 | 1 | 0 |
| CUSTRISK.cob | COBOL | 0/3 | **3/3** | 2% → 64% | 0/2 → 2/2 | 3 | 0 |
| EMPREC.cpy | COBOL | 1/2 | **2/2** | 5% → 119% | 0/0 → 0/0 | 4 | 0 |

**Overall: 1/34 questions answerable from the original comments, 34/34 (100%) with the generated comments.**

## Question detail

| File | Question | Before | After |
|---|---|---|---|
| PAYROLL.cbl | Which external dataset (DD name) supplies the employee input? | ✗ | ✓ |
| PAYROLL.cbl | When is an hourly employee paid overtime? | ✗ | ✓ |
| PAYROLL.cbl | How is gross pay computed for salaried staff? | ✗ | ✓ |
| PAYROLL.cbl | Which employee types count as hourly? | ✗ | ✓ |
| PAYROLL.cbl | What happens when the TAXCALC call fails? | ✗ | ✓ |
| PAYROLL.cbl | Is the 401(k) deduction capped, and by what? | ✗ | ✓ |
| PAYROLL.cbl | Is overtime pay rounded or truncated? | ✗ | ✓ |
| PAYROLL.cbl | Which return code signals records in error? | ✗ | ✓ |
| PAYROLL.cbl | Which paragraphs run for every employee record? | ✗ | ✓ |
| PAYROLL.cbl | Which constructs are risky to migrate? | ✗ | ✓ |
| PAYROLL.cbl | Which fields must not become floating point in Java? | ✗ | ✓ |
| loan_servicing.pkb | What happens to a payment on a closed loan? | ✗ | ✓ |
| loan_servicing.pkb | Is interest settled before principal? | ✗ | ✓ |
| loan_servicing.pkb | When is a late fee charged? | ✗ | ✓ |
| loan_servicing.pkb | When does a loan move to DEFAULT? | ✗ | ✓ |
| loan_servicing.pkb | Which error rejects non-positive payments? | ✗ | ✓ |
| loan_servicing.pkb | Which tables does apply_payment change? | ✗ | ✓ |
| loan_servicing.pkb | Are any errors silently swallowed? | ✗ | ✓ |
| loan_servicing.pkb | Is there a transaction-boundary risk in the monthly accrual? | ✗ | ✓ |
| loan_servicing.pkb | How is the risk grade decided? | ✗ | ✓ |
| loan_servicing.pkb | Is there an SQL-injection risk? | ✗ | ✓ |
| trg_payment_limits.trg | When does the trigger fire? | ✗ | ✓ |
| trg_payment_limits.trg | What is the daily payment limit and what happens above it? | ✗ | ✓ |
| NIGHTPAY.jcl | How is the employee file sorted before payroll runs? | ✗ | ✓ |
| NIGHTPAY.jcl | Which records are kept by the sort? | ✗ | ✓ |
| NIGHTPAY.jcl | When is the PAYROLL step skipped? | ✗ | ✓ |
| NIGHTPAY.jcl | Where does the payroll output go? | ✗ | ✓ |
| NIGHTPAY.jcl | When is the error log printed? | ✗ | ✓ |
| NIGHTPAY.jcl | What does the GL posting step read? | ✗ | ✓ |
| CUSTRISK.cob | What utilisation makes a customer high risk? | ✗ | ✓ |
| CUSTRISK.cob | Which tables are read and which are updated? | ✗ | ✓ |
| CUSTRISK.cob | How is utilisation calculated? | ✗ | ✓ |
| EMPREC.cpy | How long is an employee record? | ✓ | ✓ |
| EMPREC.cpy | What does EMP-STATUS 'T' mean? | ✗ | ✓ |

## Limitations

- This is an automated proxy. It shows the information is *present* in the comments, not that a reader understands it faster. The questions were written by the tool's authors for synthetic code, so treat the after-score as an upper bound for real client code.
- Comment density over 100% means more comment lines than code lines. Reviewers normally reject or trim some suggestions, and the *Essential* level already hides field-by-field data notes.

## Recommended human study (for a client pilot)

1. Pick two comparable modules from the anonymised client codebase and two developers with no prior exposure.
2. Each developer gets one module raw and the other annotated (counterbalanced), plus the same 8–10 questions.
3. Record time to answer, correctness (scored by an SME), and confidence (1–5).
4. Report the per-module deltas, and log which generated comments the SME marked wrong. Those logs feed rule improvements.
