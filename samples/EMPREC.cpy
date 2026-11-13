000100*EMPLOYEE MASTER RECORD - 80 BYTES
000200 01  EMP-REC.
000300         05 EMP-ID              PIC X(6).
000400         05 EMP-NAME            PIC X(30).
000500         05 EMP-DEPT            PIC X(4).
000600         05 EMP-TYPE            PIC X.
000700            88 EMP-SALARIED          VALUE 'S'.
000800            88 EMP-HOURLY            VALUE 'H' 'P'.
000900         05 EMP-STATUS          PIC X.
001000            88 EMP-ACTIVE            VALUE 'A'.
001100            88 EMP-TERMINATED        VALUE 'T'.
001200         05 EMP-HOURS           PIC 9(3)V9.
001300         05 EMP-RATE            PIC 9(3)V99.
001400         05 EMP-ANNUAL-SAL      PIC 9(7)V99 COMP-3.
001500         05 EMP-FILING-STAT     PIC X.
001600         05 EMP-401K-PCT        PIC V999.
001700         05 EMP-YTD-401K        PIC 9(5)V99 COMP-3.
001800         05 EMP-HEALTH-PREM     PIC 9(4)V99 COMP-3.
001900         05 EMP-VALID-SW        PIC X.
002000            88 EMP-VALID             VALUE 'Y'.
002100            88 EMP-INVALID           VALUE 'N'.
002200         05 FILLER              PIC X(11).
