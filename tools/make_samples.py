"""Generate the synthetic legacy sample codebase used for demos, tests and evaluation.

All programs are invented for this project (no client code). Fixed-format COBOL is produced from
a compact notation so column rules hold exactly:
    "A text"  -> Area A (column 8)      "B text" -> Area B (column 12)
    "* text"  -> comment (indicator column 7)
Sequence numbers fill columns 1-6, and every line is checked to end by column 72.
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "samples")


def fixed(src: str) -> str:
    out, seq = [], 100
    for raw in src.strip("\n").split("\n"):
        if not raw.strip():
            out.append(f"{seq:06d}")
        else:
            tag, _, text = raw.partition(" ")
            if tag == "*":
                line = f"{seq:06d}*{text}"
            elif tag == "A":
                line = f"{seq:06d} {text}"
            elif tag == "B":
                line = f"{seq:06d}     {text}"
            else:
                raise ValueError(raw)
            if len(line) > 72:
                raise ValueError(f"line exceeds column 72: {line!r}")
            out.append(line)
        seq += 100
    return "\n".join(out) + "\n"


PAYROLL = r"""
A IDENTIFICATION DIVISION.
A PROGRAM-ID. PAYROLL.
A AUTHOR. LEGACY-TEAM.
* PAYROLL CALC - DO NOT CHANGE W/O APPROVAL
A ENVIRONMENT DIVISION.
A INPUT-OUTPUT SECTION.
A FILE-CONTROL.
B SELECT EMP-FILE ASSIGN TO EMPIN
B     ORGANIZATION IS SEQUENTIAL
B     FILE STATUS IS WS-EMP-FS.
B SELECT PAY-FILE ASSIGN TO PAYOUT
B     FILE STATUS IS WS-PAY-FS.
B SELECT RPT-FILE ASSIGN TO RPTOUT.
A DATA DIVISION.
A FILE SECTION.
A FD  EMP-FILE
B     RECORDING MODE IS F.
B COPY EMPREC.
A FD  PAY-FILE.
A 01  PAY-REC.
B     05 PAY-EMP-ID          PIC X(6).
B     05 PAY-GROSS           PIC S9(7)V99 COMP-3.
B     05 PAY-FED-TAX         PIC S9(7)V99 COMP-3.
B     05 PAY-ST-TAX          PIC S9(7)V99 COMP-3.
B     05 PAY-DEDS            PIC S9(7)V99 COMP-3.
B     05 PAY-NET             PIC S9(7)V99 COMP-3.
B     05 FILLER              PIC X(33).
A FD  RPT-FILE.
A 01  RPT-LINE               PIC X(132).
A WORKING-STORAGE SECTION.
A 01  WS-SWITCHES.
B     05 WS-EOF-SW           PIC X VALUE 'N'.
B        88 END-OF-EMP-FILE        VALUE 'Y'.
B     05 WS-EMP-FS           PIC XX.
B     05 WS-PAY-FS           PIC XX.
A 01  WS-CALC-FIELDS.
B     05 WS-REG-HRS          PIC S9(3)V9 COMP-3.
B     05 WS-OT-HRS           PIC S9(3)V9 COMP-3.
B     05 WS-GROSS-PAY        PIC S9(7)V99 COMP-3.
B     05 WS-OT-PAY           PIC S9(7)V99 COMP-3.
B     05 WS-TAXABLE          PIC S9(7)V99 COMP-3.
B     05 WS-FED-TAX          PIC S9(7)V99 COMP-3.
B     05 WS-ST-TAX           PIC S9(7)V99 COMP-3.
B     05 WS-TOT-DEDS         PIC S9(7)V99 COMP-3.
B     05 WS-NET-PAY          PIC S9(7)V99 COMP-3.
* CONSTANTS
A 01  WS-CONSTANTS.
B     05 WS-STD-HRS          PIC 9(3)V9  VALUE 40.0.
B     05 WS-OT-RATE          PIC 9V99    VALUE 1.50.
B     05 WS-ST-TAX-RATE      PIC V999    VALUE .045.
B     05 WS-401K-MAX         PIC 9(5)V99 VALUE 23000.00.
A 01  WS-COUNTERS.
B     05 WS-REC-CNT          PIC 9(7) COMP VALUE ZERO.
B     05 WS-ERR-CNT          PIC 9(7) COMP VALUE ZERO.
B     05 WS-TOT-GROSS        PIC S9(11)V99 COMP-3 VALUE ZERO.
A 01  WS-TAX-PARMS.
B     05 TP-TAXABLE          PIC S9(7)V99 COMP-3.
B     05 TP-FILING-STATUS    PIC X.
B     05 TP-FED-TAX          PIC S9(7)V99 COMP-3.
B     05 TP-RETURN-CD        PIC XX.
A 01  WS-DEPT-TABLE.
B     05 WS-DEPT-ENTRY OCCURS 20 TIMES INDEXED BY DEPT-IDX.
B        10 WS-DEPT-CD        PIC X(4).
B        10 WS-DEPT-BONUS-PCT PIC V99.
A 01  WS-RPT-DETAIL.
B     05 RD-EMP-ID           PIC X(6).
B     05 FILLER              PIC X(2) VALUE SPACES.
B     05 RD-EMP-NAME         PIC X(30).
B     05 RD-GROSS            PIC Z,ZZZ,ZZ9.99.
B     05 FILLER              PIC X(2) VALUE SPACES.
B     05 RD-NET              PIC Z,ZZZ,ZZ9.99.
A 01  WS-RPT-ALT REDEFINES WS-RPT-DETAIL.
B     05 RA-TEXT             PIC X(64).
A PROCEDURE DIVISION.
A 0000-MAINLINE.
B     PERFORM 1000-INITIALIZE
B     PERFORM 2000-PROCESS-EMPLOYEE
B         UNTIL END-OF-EMP-FILE
B     PERFORM 9000-TERMINATE
B     STOP RUN.
A 1000-INITIALIZE.
B     OPEN INPUT  EMP-FILE
B          OUTPUT PAY-FILE RPT-FILE
B     IF WS-EMP-FS NOT = '00'
B         DISPLAY 'EMPIN OPEN ERROR ' WS-EMP-FS
B         MOVE 16 TO RETURN-CODE
B         GO TO 9999-ABEND
B     END-IF
B     PERFORM 1100-READ-EMPLOYEE.
A 1100-READ-EMPLOYEE.
B     READ EMP-FILE
B         AT END SET END-OF-EMP-FILE TO TRUE
B     END-READ.
A 2000-PROCESS-EMPLOYEE.
B     ADD 1 TO WS-REC-CNT
B     PERFORM 2100-VALIDATE-EMPLOYEE
B     IF EMP-VALID
B         PERFORM 2200-CALC-GROSS-PAY
B         PERFORM 2300-CALC-DEDUCTIONS
B         PERFORM 2400-CALC-TAXES
B         PERFORM 2500-WRITE-PAY-RECORD
B     ELSE
B         ADD 1 TO WS-ERR-CNT
B     END-IF
B     PERFORM 1100-READ-EMPLOYEE.
A 2100-VALIDATE-EMPLOYEE.
B     SET EMP-VALID TO TRUE
B     IF EMP-HOURS NOT NUMERIC OR EMP-RATE NOT NUMERIC
B         SET EMP-INVALID TO TRUE
B     END-IF
B     IF EMP-TERMINATED
B         SET EMP-INVALID TO TRUE
B     END-IF.
* GROSS
A 2200-CALC-GROSS-PAY.
B     EVALUATE TRUE
B         WHEN EMP-SALARIED
B             COMPUTE WS-GROSS-PAY ROUNDED =
B                 EMP-ANNUAL-SAL / 26
B         WHEN EMP-HOURLY
B             IF EMP-HOURS > WS-STD-HRS
B                 MOVE WS-STD-HRS TO WS-REG-HRS
B                 COMPUTE WS-OT-HRS = EMP-HOURS - WS-STD-HRS
B             ELSE
B                 MOVE EMP-HOURS TO WS-REG-HRS
B                 MOVE ZERO TO WS-OT-HRS
B             END-IF
B             COMPUTE WS-OT-PAY =
B                 WS-OT-HRS * EMP-RATE * WS-OT-RATE
B             COMPUTE WS-GROSS-PAY =
B                 (WS-REG-HRS * EMP-RATE) + WS-OT-PAY
B         WHEN OTHER
B             MOVE ZERO TO WS-GROSS-PAY
B             ADD 1 TO WS-ERR-CNT
B     END-EVALUATE
B     SET DEPT-IDX TO 1
B     SEARCH WS-DEPT-ENTRY
B         AT END CONTINUE
B         WHEN WS-DEPT-CD (DEPT-IDX) = EMP-DEPT
B             COMPUTE WS-GROSS-PAY ROUNDED = WS-GROSS-PAY *
B                 (1 + WS-DEPT-BONUS-PCT (DEPT-IDX))
B     END-SEARCH
B     ADD WS-GROSS-PAY TO WS-TOT-GROSS.
A 2300-CALC-DEDUCTIONS.
B     COMPUTE WS-TOT-DEDS = EMP-401K-PCT * WS-GROSS-PAY
B     IF EMP-YTD-401K + WS-TOT-DEDS > WS-401K-MAX
B         COMPUTE WS-TOT-DEDS = WS-401K-MAX - EMP-YTD-401K
B     END-IF
B     ADD EMP-HEALTH-PREM TO WS-TOT-DEDS
B     COMPUTE WS-TAXABLE = WS-GROSS-PAY - WS-TOT-DEDS.
A 2400-CALC-TAXES.
B     MOVE WS-TAXABLE       TO TP-TAXABLE
B     MOVE EMP-FILING-STAT  TO TP-FILING-STATUS
B     CALL 'TAXCALC' USING WS-TAX-PARMS
B     IF TP-RETURN-CD NOT = '00'
B         DISPLAY 'TAXCALC FAILED FOR ' EMP-ID
B         MOVE ZERO TO WS-FED-TAX
B     ELSE
B         MOVE TP-FED-TAX TO WS-FED-TAX
B     END-IF
B     COMPUTE WS-ST-TAX ROUNDED = WS-TAXABLE * WS-ST-TAX-RATE
B     COMPUTE WS-NET-PAY = WS-GROSS-PAY - WS-TOT-DEDS
B                        - WS-FED-TAX - WS-ST-TAX.
A 2500-WRITE-PAY-RECORD.
B     MOVE EMP-ID       TO PAY-EMP-ID
B     MOVE WS-GROSS-PAY TO PAY-GROSS
B     MOVE WS-FED-TAX   TO PAY-FED-TAX
B     MOVE WS-ST-TAX    TO PAY-ST-TAX
B     MOVE WS-TOT-DEDS  TO PAY-DEDS
B     MOVE WS-NET-PAY   TO PAY-NET
B     WRITE PAY-REC
B     MOVE EMP-ID       TO RD-EMP-ID
B     MOVE EMP-NAME     TO RD-EMP-NAME
B     MOVE WS-GROSS-PAY TO RD-GROSS
B     MOVE WS-NET-PAY   TO RD-NET
B     WRITE RPT-LINE FROM WS-RPT-DETAIL AFTER ADVANCING 1 LINE.
A 9000-TERMINATE.
B     CLOSE EMP-FILE PAY-FILE RPT-FILE
B     DISPLAY 'RECORDS READ:    ' WS-REC-CNT
B     DISPLAY 'RECORDS IN ERROR:' WS-ERR-CNT
B     IF WS-ERR-CNT > 0
B         MOVE 4 TO RETURN-CODE
B     END-IF.
A 9999-ABEND.
B     DISPLAY 'PAYROLL ABENDING'
B     STOP RUN.
"""

EMPREC = r"""
* EMPLOYEE MASTER RECORD - 80 BYTES
A 01  EMP-REC.
B     05 EMP-ID              PIC X(6).
B     05 EMP-NAME            PIC X(30).
B     05 EMP-DEPT            PIC X(4).
B     05 EMP-TYPE            PIC X.
B        88 EMP-SALARIED          VALUE 'S'.
B        88 EMP-HOURLY            VALUE 'H' 'P'.
B     05 EMP-STATUS          PIC X.
B        88 EMP-ACTIVE            VALUE 'A'.
B        88 EMP-TERMINATED        VALUE 'T'.
B     05 EMP-HOURS           PIC 9(3)V9.
B     05 EMP-RATE            PIC 9(3)V99.
B     05 EMP-ANNUAL-SAL      PIC 9(7)V99 COMP-3.
B     05 EMP-FILING-STAT     PIC X.
B     05 EMP-401K-PCT        PIC V999.
B     05 EMP-YTD-401K        PIC 9(5)V99 COMP-3.
B     05 EMP-HEALTH-PREM     PIC 9(4)V99 COMP-3.
B     05 EMP-VALID-SW        PIC X.
B        88 EMP-VALID             VALUE 'Y'.
B        88 EMP-INVALID           VALUE 'N'.
B     05 FILLER              PIC X(11).
"""

CUSTRPT = """\
>>SOURCE FORMAT FREE
*> Customer credit utilisation scoring (synthetic sample)
IDENTIFICATION DIVISION.
PROGRAM-ID. CUSTRISK.
DATA DIVISION.
WORKING-STORAGE SECTION.
EXEC SQL INCLUDE SQLCA END-EXEC.
01 WS-CUST.
   05 WS-CUST-ID      PIC 9(9) COMP.
   05 WS-CUST-NAME    PIC X(40).
   05 WS-CREDIT-LMT   PIC S9(9)V99 COMP-3.
   05 WS-BALANCE      PIC S9(9)V99 COMP-3.
   05 WS-RISK-CD      PIC X.
      88 HIGH-RISK    VALUE 'H'.
01 WS-UTIL-PCT        PIC 9(3)V99.
01 WS-ROW-CNT         PIC 9(7) VALUE 0.
PROCEDURE DIVISION.
MAIN-PARA.
    EXEC SQL
        DECLARE CUST-CUR CURSOR FOR
        SELECT C.CUST_ID, C.CUST_NAME, A.CREDIT_LIMIT, A.BALANCE
          FROM CUSTOMER C JOIN ACCOUNT A ON A.CUST_ID = C.CUST_ID
         WHERE C.STATUS = 'A'
    END-EXEC
    EXEC SQL OPEN CUST-CUR END-EXEC
    PERFORM FETCH-AND-SCORE UNTIL SQLCODE NOT = 0
    EXEC SQL CLOSE CUST-CUR END-EXEC
    EXEC SQL COMMIT END-EXEC
    GOBACK.
FETCH-AND-SCORE.
    EXEC SQL
        FETCH CUST-CUR INTO :WS-CUST-ID, :WS-CUST-NAME,
                            :WS-CREDIT-LMT, :WS-BALANCE
    END-EXEC
    IF SQLCODE = 0
       ADD 1 TO WS-ROW-CNT
       COMPUTE WS-UTIL-PCT ROUNDED = WS-BALANCE / WS-CREDIT-LMT * 100
       EVALUATE TRUE
          WHEN WS-UTIL-PCT > 90
             MOVE 'H' TO WS-RISK-CD
          WHEN WS-UTIL-PCT > 60
             MOVE 'M' TO WS-RISK-CD
          WHEN OTHER
             MOVE 'L' TO WS-RISK-CD
       END-EVALUATE
       IF HIGH-RISK
          EXEC SQL
             UPDATE ACCOUNT
                SET REVIEW_FLAG = 'Y', RISK_CODE = :WS-RISK-CD
              WHERE CUST_ID = :WS-CUST-ID
          END-EXEC
       END-IF
    END-IF.
"""

LOAN_PKG = """\
CREATE OR REPLACE PACKAGE loan_servicing AS
  PROCEDURE apply_payment(p_loan_id IN NUMBER, p_amount IN NUMBER, p_status OUT VARCHAR2);
  PROCEDURE accrue_monthly_interest;
  FUNCTION get_risk_grade(p_loan_id IN NUMBER) RETURN VARCHAR2;
END loan_servicing;
/

CREATE OR REPLACE PACKAGE BODY loan_servicing AS

  c_late_fee      CONSTANT NUMBER := 25;
  e_loan_closed   EXCEPTION;

  CURSOR c_active_loans IS
    SELECT l.loan_id, l.principal_bal, l.annual_rate, l.days_past_due
      FROM loans l
     WHERE l.status = 'ACTIVE';

  PROCEDURE log_event(p_loan_id NUMBER, p_msg VARCHAR2) IS
    PRAGMA AUTONOMOUS_TRANSACTION;
  BEGIN
    INSERT INTO loan_audit (loan_id, event_ts, message)
    VALUES (p_loan_id, SYSTIMESTAMP, p_msg);
    COMMIT;
  END log_event;

  PROCEDURE apply_payment(p_loan_id IN NUMBER, p_amount IN NUMBER, p_status OUT VARCHAR2) IS
    v_balance   loans.principal_bal%TYPE;
    v_status    loans.status%TYPE;
    v_dpd       loans.days_past_due%TYPE;
    v_interest  NUMBER(12,2);
  BEGIN
    SELECT principal_bal, status, days_past_due, accrued_interest
      INTO v_balance, v_status, v_dpd, v_interest
      FROM loans
     WHERE loan_id = p_loan_id
       FOR UPDATE;

    IF v_status = 'CLOSED' THEN
      RAISE e_loan_closed;
    END IF;

    IF p_amount <= 0 THEN
      RAISE_APPLICATION_ERROR(-20010, 'Payment amount must be positive');
    END IF;

    -- late fee
    IF v_dpd > 30 THEN
      v_interest := v_interest + c_late_fee;
    END IF;

    IF p_amount >= v_interest THEN
      v_balance := v_balance - (p_amount - v_interest);
      v_interest := 0;
    ELSE
      v_interest := v_interest - p_amount;
    END IF;

    UPDATE loans
       SET principal_bal    = GREATEST(v_balance, 0),
           accrued_interest = v_interest,
           days_past_due    = 0,
           status = CASE WHEN v_balance <= 0 THEN 'PAID_OFF' ELSE status END
     WHERE loan_id = p_loan_id;

    INSERT INTO payments (loan_id, amount, paid_on)
    VALUES (p_loan_id, p_amount, SYSDATE);

    p_status := CASE
                  WHEN v_balance <= 0 THEN 'PAID_OFF'
                  WHEN v_dpd > 30 THEN 'CURED_WITH_FEE'
                  ELSE 'APPLIED'
                END;
    log_event(p_loan_id, 'Payment applied: ' || p_amount);
    COMMIT;
  EXCEPTION
    WHEN e_loan_closed THEN
      p_status := 'REJECTED_CLOSED';
      log_event(p_loan_id, 'Payment on closed loan');
    WHEN NO_DATA_FOUND THEN
      p_status := 'UNKNOWN_LOAN';
  END apply_payment;

  PROCEDURE accrue_monthly_interest IS
    v_monthly NUMBER(12,2);
  BEGIN
    FOR r IN c_active_loans LOOP
      v_monthly := ROUND(r.principal_bal * r.annual_rate / 12, 2);
      UPDATE loans
         SET accrued_interest = accrued_interest + v_monthly
       WHERE loan_id = r.loan_id;
      IF r.days_past_due > 90 THEN
        UPDATE loans SET status = 'DEFAULT' WHERE loan_id = r.loan_id;
        log_event(r.loan_id, 'Moved to default');
      END IF;
      COMMIT;
    END LOOP;
  EXCEPTION
    WHEN OTHERS THEN
      NULL;
  END accrue_monthly_interest;

  FUNCTION get_risk_grade(p_loan_id IN NUMBER) RETURN VARCHAR2 IS
    v_dpd   NUMBER;
    v_ltv   NUMBER;
    v_sql   VARCHAR2(400);
  BEGIN
    v_sql := 'SELECT days_past_due, loan_to_value FROM loans WHERE loan_id = ' || p_loan_id;
    EXECUTE IMMEDIATE v_sql INTO v_dpd, v_ltv;
    CASE
      WHEN v_dpd > 60 OR v_ltv > 0.95 THEN RETURN 'D';
      WHEN v_dpd > 30 THEN RETURN 'C';
      WHEN v_ltv > 0.80 THEN RETURN 'B';
      ELSE RETURN 'A';
    END CASE;
  END get_risk_grade;

END loan_servicing;
/
"""

TRIGGER = """\
CREATE OR REPLACE TRIGGER trg_payment_limits
BEFORE INSERT OR UPDATE ON payments
FOR EACH ROW
WHEN (NEW.amount > 0)
DECLARE
  v_daily_total NUMBER;
BEGIN
  SELECT NVL(SUM(amount), 0)
    INTO v_daily_total
    FROM payments
   WHERE loan_id = :NEW.loan_id
     AND TRUNC(paid_on) = TRUNC(SYSDATE);

  IF v_daily_total + :NEW.amount > 50000 THEN
    RAISE_APPLICATION_ERROR(-20020, 'Daily payment limit exceeded for loan ' || :NEW.loan_id);
  END IF;

  :NEW.paid_on := NVL(:NEW.paid_on, SYSDATE);
END;
/
"""

JCL = """\
//NIGHTPAY JOB (ACCT01),'PAYROLL BATCH',CLASS=A,MSGCLASS=X,
//             NOTIFY=&SYSUID
//*
//* NIGHTLY PAYROLL
//*
//JOBLIB   DD DSN=PROD.PAYROLL.LOADLIB,DISP=SHR
//STEP010  EXEC PGM=SORT
//SORTIN   DD DSN=PROD.EMP.MASTER,DISP=SHR
//SORTOUT  DD DSN=&&EMPSORT,DISP=(NEW,PASS),
//            SPACE=(CYL,(5,5)),DCB=(RECFM=FB,LRECL=80)
//SYSOUT   DD SYSOUT=*
//SYSIN    DD *
  SORT FIELDS=(37,4,CH,A,1,6,CH,A)
  INCLUDE COND=(42,1,CH,EQ,C'A')
/*
//STEP020  EXEC PGM=PAYROLL,COND=(4,LT)
//EMPIN    DD DSN=&&EMPSORT,DISP=(OLD,DELETE)
//PAYOUT   DD DSN=PROD.PAYROLL.PAYFILE(+1),
//            DISP=(NEW,CATLG,DELETE),
//            SPACE=(CYL,(10,5),RLSE),
//            DCB=(RECFM=FB,LRECL=64)
//RPTOUT   DD SYSOUT=A
//SYSOUT   DD SYSOUT=*
//         IF (STEP020.RC = 4) THEN
//STEP025  EXEC PGM=IEBGENER
//SYSUT1   DD DSN=PROD.PAYROLL.ERRLOG,DISP=SHR
//SYSUT2   DD SYSOUT=*
//SYSPRINT DD SYSOUT=*
//SYSIN    DD DUMMY
//         ENDIF
//STEP030  EXEC PGM=GLPOST,COND=((4,LT,STEP010),(8,LT,STEP020))
//PAYIN    DD DSN=PROD.PAYROLL.PAYFILE(0),DISP=SHR
//GLOUT    DD DSN=PROD.GL.INTERFACE,DISP=MOD
//SYSOUT   DD SYSOUT=*
//
"""

PAYPROC = """\
//PAYPROC  PROC HLQ=PROD,CYCLE=MONTHLY,OUTCLS=A
//*
//PS010    EXEC PGM=PAYROLL,PARM='&CYCLE'
//EMPIN    DD DSN=&HLQ..EMP.MASTER,DISP=SHR
//PAYOUT   DD DSN=&HLQ..PAYROLL.&CYCLE..PAYFILE(+1),
//            DISP=(NEW,CATLG,DELETE),SPACE=(CYL,(10,5),RLSE)
//RPTOUT   DD SYSOUT=&OUTCLS
//PS020    EXEC PGM=GLPOST,COND=(4,LT,PS010)
//PAYIN    DD DSN=&HLQ..PAYROLL.&CYCLE..PAYFILE(+1),DISP=SHR
//GLOUT    DD DSN=&HLQ..GL.&ENV..INTERFACE,DISP=MOD
"""

MONTHEND = """\
//MONTHEND JOB (ACCT01),'MONTH END',CLASS=A,MSGCLASS=X
//         SET ENV=QA
//         JCLLIB ORDER=PROD.PROCLIB
//*
//CLEANUP  PROC DSNAME=
//CL010    EXEC PGM=IEFBR14
//OLD      DD DSN=&DSNAME,DISP=(MOD,DELETE,DELETE),SPACE=(TRK,1)
//         PEND
//*
//STEP005  EXEC CLEANUP,DSNAME=&ENV..PAYROLL.WORK
//STEP010  EXEC PAYPROC,HLQ=TEST,CYCLE=EOM
//PS010.EMPIN DD DSN=TEST.EMP.SNAPSHOT,DISP=SHR
//PS020.GLOUT DD DUMMY
//STEP020  EXEC ARCHPROC
//
"""


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    files = {
        "PAYROLL.cbl": fixed(PAYROLL),
        "EMPREC.cpy": fixed(EMPREC),
        "CUSTRISK.cob": CUSTRPT,
        "loan_servicing.pkb": LOAN_PKG,
        "trg_payment_limits.trg": TRIGGER,
        "NIGHTPAY.jcl": JCL,
        "PAYPROC.proc": PAYPROC,
        "MONTHEND.jcl": MONTHEND,
    }
    for name, text in files.items():
        with open(os.path.join(OUT, name), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        print(f"wrote samples/{name} ({text.count(chr(10))} lines)")


if __name__ == "__main__":
    sys.exit(main())
