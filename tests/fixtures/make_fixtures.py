"""Regression fixtures for COBOL edge cases. Run to (re)write the files next to this script."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
from tools.make_samples import fixed  # noqa: E402  (column-checked fixed-format generator)

FIXTURES = {
    "cobol/OLDSTYLE.cbl": fixed(r"""
A IDENTIFICATION DIVISION.
A PROGRAM-ID. OLDSTYLE.
A DATA DIVISION.
A WORKING-STORAGE SECTION.
A 77  WS-CODE        PIC 9.
A 77  WS-AMT         PIC S9(5)V99.
A PROCEDURE DIVISION.
A A000-START.
B     PERFORM B000-CALC THRU B999-EXIT.
B     GO TO C100-ONE C200-TWO DEPENDING ON WS-CODE.
B     STOP RUN.
A B000-CALC.
B     IF WS-AMT > 100
B         MULTIPLY 2 BY WS-AMT
B     ELSE
B         DIVIDE 2 INTO WS-AMT.
B     ALTER D000-SWITCH TO PROCEED TO C100-ONE.
A B999-EXIT.
B     EXIT.
A C100-ONE.
B     DISPLAY 'ONE'.
A C200-TWO.
B     DISPLAY 'TWO'
B     DISPLAY 'DONE'.
A D000-SWITCH.
B     GO TO.
"""),
    "cobol/lowcase.cob": """\
identification division.
program-id. lowcase.
data division.
working-storage section.
01 ws-i        pic 9(3) value 0.
01 ws-total    pic 9(7)v99 comp-3 value 0.
01 ws-name     pic x(20).
01 ws-table.
   05 ws-amt   pic 9(5)v99 occurs 10 times.
procedure division.
main-section section.
start-here.
    perform varying ws-i from 1 by 1 until ws-i > 10
        add ws-amt (ws-i) to ws-total
    end-perform
    string 'Total=' delimited by size ws-total delimited by size into ws-name
    display ws-name
    goback.
""",
    "cobol/NESTED.cbl": fixed(r"""
A IDENTIFICATION DIVISION.
A PROGRAM-ID. ORDERS.
A DATA DIVISION.
A WORKING-STORAGE SECTION.
A 01  WS-ORDER-STATUS    PIC X GLOBAL.
B     88 ORDER-OPEN          VALUE 'O'.
B     88 ORDER-SHIPPED       VALUE 'S'.
A 01  WS-TOTAL           PIC S9(7)V99 COMP-3.
A PROCEDURE DIVISION.
A MAIN-PARA.
B     CALL 'PRICING' USING WS-TOTAL
B     CALL 'AUDITLOG'
B     STOP RUN.
A IDENTIFICATION DIVISION.
A PROGRAM-ID. PRICING.
A DATA DIVISION.
A LINKAGE SECTION.
A 01  LS-TOTAL           PIC S9(7)V99 COMP-3.
A PROCEDURE DIVISION USING LS-TOTAL.
A MAIN-PARA.
B     IF ORDER-SHIPPED
B         COMPUTE LS-TOTAL ROUNDED = LS-TOTAL * 1.08
B     END-IF
B     GOBACK.
A END PROGRAM PRICING.
A END PROGRAM ORDERS.
"""),
    "cobol/REPLDEMO.cbl": fixed(r"""
A IDENTIFICATION DIVISION.
A PROGRAM-ID. REPLDEMO.
A DATA DIVISION.
A WORKING-STORAGE SECTION.
B REPLACE ==:PFX:== BY ==WS==.
A 01  :PFX:-LIMIT        PIC 9(5) VALUE 5000.
A 01  :PFX:-BALANCE      PIC S9(7)V99 COMP-3.
B REPLACE OFF.
B COPY CUSTREC REPLACING ==:TAG:== BY ==IN==.
A PROCEDURE DIVISION.
A MAIN-PARA.
B     IF IN-PREMIUM
B         COMPUTE WS-BALANCE = IN-AMOUNT * 2
B     END-IF
B     IF WS-BALANCE > WS-LIMIT
B         DISPLAY 'OVER LIMIT'
B     END-IF
B     GOBACK.
"""),
    "cobol/CUSTREC.cpy": fixed(r"""
A 01  :TAG:-CUSTOMER.
B     05 :TAG:-ID            PIC X(8).
B     05 :TAG:-TIER          PIC X.
B        88 :TAG:-PREMIUM         VALUE 'P'.
B        88 :TAG:-STANDARD        VALUE 'S'.
B     05 :TAG:-AMOUNT        PIC S9(7)V99 COMP-3.
"""),
}


def main():
    for rel, text in FIXTURES.items():
        path = os.path.join(HERE, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        print("wrote", rel)


if __name__ == "__main__":
    main()
