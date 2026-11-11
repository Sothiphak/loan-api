-- Runs once, the first time the database volume is created.
CREATE TABLE IF NOT EXISTS applications (
    id                  INTEGER PRIMARY KEY,
    borrower_name       TEXT,
    amount_usd          INTEGER NOT NULL,
    term_months         INTEGER NOT NULL,
    monthly_income_usd  NUMERIC NOT NULL,
    previous_loans      INTEGER NOT NULL DEFAULT 0,
    late_payments       INTEGER NOT NULL DEFAULT 0,
    status              TEXT NOT NULL DEFAULT 'pending',
    default_probability NUMERIC,
    risk_band           TEXT,
    model_version       TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
