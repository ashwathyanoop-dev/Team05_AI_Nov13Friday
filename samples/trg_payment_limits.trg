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
