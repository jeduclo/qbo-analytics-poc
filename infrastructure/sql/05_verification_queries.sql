-- Run after Workshop 4 data generation to verify all tables and views.
-- Expected results documented in docs/data_verification.md.

-- Row counts (run after Workshop 4)
SELECT 'stg_customers'         AS table_name, COUNT(*) AS row_count FROM qbo.stg_customers
UNION ALL
SELECT 'stg_invoices',                         COUNT(*) FROM qbo.stg_invoices
UNION ALL
SELECT 'stg_payments',                         COUNT(*) FROM qbo.stg_payments
UNION ALL
SELECT 'coa_mapping',                          COUNT(*) FROM qbo.coa_mapping
UNION ALL
SELECT 'macro_indicators',                     COUNT(*) FROM qbo.macro_indicators;

-- NULL checks on key columns
SELECT 'Customers missing display_name' AS check_name, COUNT(*) AS failures
FROM qbo.stg_customers WHERE display_name IS NULL
UNION ALL
SELECT 'Invoices missing customer_id',    COUNT(*) FROM qbo.stg_invoices WHERE customer_id IS NULL
UNION ALL
SELECT 'Invoices missing status',         COUNT(*) FROM qbo.stg_invoices WHERE status IS NULL
UNION ALL
SELECT 'Payments missing amount',         COUNT(*) FROM qbo.stg_payments WHERE amount IS NULL;

-- Date range check
SELECT
    MIN(invoice_date) AS earliest_invoice,
    MAX(invoice_date) AS latest_invoice
FROM qbo.stg_invoices;

-- Status distribution
SELECT status, COUNT(*) AS count
FROM qbo.stg_invoices
GROUP BY status;

-- View smoke tests
SELECT TOP 5 * FROM qbo.vw_sales_summary ORDER BY revenue_month;
SELECT TOP 5 * FROM qbo.vw_ar_aging ORDER BY days_past_due DESC;
SELECT TOP 5 * FROM qbo.vw_invoice_detail;
SELECT TOP 5 * FROM qbo.vw_ml_invoice_features;

-- CoA mapping coverage check
SELECT statement, COUNT(*) AS account_count
FROM qbo.coa_mapping
GROUP BY statement;