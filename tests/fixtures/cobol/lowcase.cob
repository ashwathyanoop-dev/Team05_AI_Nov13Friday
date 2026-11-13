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
