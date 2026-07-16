-- Run after 02_create_staging_tables.sql
-- Creates all seven warehouse views.

-- 1. Sales Summary
CREATE OR ALTER VIEW qbo.vw_sales_summary AS
SELECT
    i.customer_id,
    c.display_name        AS customer_name,
    c.country,
    DATEFROMPARTS(YEAR(i.invoice_date), MONTH(i.invoice_date), 1) AS revenue_month,
    SUM(i.amount)         AS total_revenue,
    COUNT(i.invoice_id)   AS invoice_count
FROM qbo.stg_invoices i
JOIN qbo.stg_customers c ON i.customer_id = c.customer_id
GROUP BY
    i.customer_id,
    c.display_name,
    c.country,
    DATEFROMPARTS(YEAR(i.invoice_date), MONTH(i.invoice_date), 1);
GO

-- 2. AR Aging
CREATE OR ALTER VIEW qbo.vw_ar_aging AS
SELECT
    i.invoice_id,
    i.customer_id,
    c.display_name        AS customer_name,
    c.country,
    i.invoice_date,
    i.due_date,
    i.amount,
    i.balance,
    DATEDIFF(day, i.due_date, GETDATE()) AS days_past_due,
    CASE
        WHEN DATEDIFF(day, i.due_date, GETDATE()) <= 0  THEN 'Current'
        WHEN DATEDIFF(day, i.due_date, GETDATE()) <= 30 THEN '1-30 Days'
        WHEN DATEDIFF(day, i.due_date, GETDATE()) <= 60 THEN '31-60 Days'
        WHEN DATEDIFF(day, i.due_date, GETDATE()) <= 90 THEN '61-90 Days'
        ELSE '90+ Days'
    END AS aging_bucket
FROM qbo.stg_invoices i
JOIN qbo.stg_customers c ON i.customer_id = c.customer_id
WHERE i.balance > 0;
GO

-- 3. Cash Received
CREATE OR ALTER VIEW qbo.vw_cash_received AS
SELECT
    DATEFROMPARTS(YEAR(payment_date), MONTH(payment_date), 1) AS payment_month,
    payment_method,
    SUM(amount)       AS total_received,
    COUNT(payment_id) AS payment_count
FROM qbo.stg_payments
GROUP BY
    DATEFROMPARTS(YEAR(payment_date), MONTH(payment_date), 1),
    payment_method;
GO

-- 4. Invoice Detail
CREATE OR ALTER VIEW qbo.vw_invoice_detail AS
SELECT
    i.invoice_id,
    i.customer_id,
    c.display_name                                          AS customer_name,
    c.country,
    i.invoice_date,
    i.due_date,
    i.amount,
    i.balance,
    i.status,
    DATEDIFF(day, i.due_date, GETDATE())                   AS days_past_due,
    CASE
        WHEN i.balance = 0                                   THEN 'Current'
        WHEN DATEDIFF(day, i.due_date, GETDATE()) <= 0      THEN 'Current'
        WHEN DATEDIFF(day, i.due_date, GETDATE()) <= 30     THEN '1-30 Days'
        WHEN DATEDIFF(day, i.due_date, GETDATE()) <= 60     THEN '31-60 Days'
        WHEN DATEDIFF(day, i.due_date, GETDATE()) <= 90     THEN '61-90 Days'
        ELSE '90+ Days'
    END AS aging_bucket
FROM qbo.stg_invoices i
JOIN qbo.stg_customers c ON i.customer_id = c.customer_id;
GO

-- 5. P&L Structure
CREATE OR ALTER VIEW qbo.vw_pl_structure AS
SELECT
    m.gl_account,
    m.account_name,
    m.fs_line_item,
    m.section,
    m.subsection,
    m.display_order,
    m.sign,
    m.is_kpi_numerator,
    m.is_kpi_denominator
FROM qbo.coa_mapping m
WHERE m.statement = 'P&L'
-- In production: join to GL transactions table here
-- In PoC: amounts are derived in Power BI DAX from invoice/payment staging tables
ORDER BY m.display_order
OFFSET 0 ROWS;
GO

-- 6. Balance Sheet Structure
CREATE OR ALTER VIEW qbo.vw_bs_structure AS
SELECT
    m.gl_account,
    m.account_name,
    m.fs_line_item,
    m.section,
    m.subsection,
    m.display_order,
    m.sign,
    m.is_working_capital,
    m.is_kpi_numerator,
    m.is_kpi_denominator
FROM qbo.coa_mapping m
WHERE m.statement = 'Balance Sheet'
ORDER BY m.display_order
OFFSET 0 ROWS;
GO

-- 7. ML Invoice Features
CREATE OR ALTER VIEW qbo.vw_ml_invoice_features AS
SELECT
    i.invoice_id,
    i.customer_id,
    i.invoice_date,
    i.due_date,
    i.amount,
    i.balance,
    i.status,
    DATEDIFF(day, i.invoice_date, i.due_date)             AS payment_terms_days,
    MONTH(i.invoice_date)                                  AS invoice_month,
    DATEPART(quarter, i.invoice_date)                      AS invoice_quarter,
    COALESCE(ch.avg_days_to_pay, 0)                        AS customer_avg_days_to_pay,
    COALESCE(ch.historical_overdue_rate, 0.0)              AS customer_historical_overdue_rate,
    COALESCE(ch.invoice_count, 0)                          AS customer_invoice_count,
    COALESCE(ch.current_balance, 0)                        AS customer_current_balance,
    COALESCE(ch.days_since_last_payment, 999)              AS days_since_last_payment,
    COALESCE(mac.bank_rate, 0)                             AS bank_rate,
    COALESCE(mac.cpi, 0)                                   AS cpi,
    COALESCE(mac.sector_index, 0)                          AS sector_index
FROM qbo.stg_invoices i
-- Customer payment history subquery
LEFT JOIN (
    SELECT
        i2.customer_id,
        AVG(CAST(DATEDIFF(day, i2.invoice_date,
            (SELECT MIN(p.payment_date)
             FROM qbo.stg_payments p
             WHERE p.customer_id = i2.customer_id
               AND p.payment_date >= i2.invoice_date)
        ) AS FLOAT))                                       AS avg_days_to_pay,
        AVG(CAST(CASE WHEN i2.status = 'Overdue' THEN 1.0 ELSE 0.0 END AS FLOAT))
                                                           AS historical_overdue_rate,
        COUNT(i2.invoice_id)                               AS invoice_count,
        SUM(i2.balance)                                    AS current_balance,
        DATEDIFF(day,
            MAX(p2.payment_date),
            GETDATE())                                     AS days_since_last_payment
    FROM qbo.stg_invoices i2
    LEFT JOIN qbo.stg_payments p2 ON i2.customer_id = p2.customer_id
    GROUP BY i2.customer_id
) ch ON i.customer_id = ch.customer_id
-- Macro indicators join on invoice month
LEFT JOIN qbo.macro_indicators mac
    ON mac.indicator_date = DATEFROMPARTS(YEAR(i.invoice_date), MONTH(i.invoice_date), 1);
GO

PRINT 'All warehouse views created successfully.';