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
