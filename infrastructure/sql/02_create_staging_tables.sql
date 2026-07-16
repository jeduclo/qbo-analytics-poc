-- Run after 01_create_schema.sql
-- Creates all staging tables, CoA mapping table, and macro indicators table.
-- DROP and recreate if tables already exist (development mode).

-- Customers
IF OBJECT_ID('qbo.stg_customers', 'U') IS NOT NULL DROP TABLE qbo.stg_customers;
CREATE TABLE qbo.stg_customers (
    customer_id   VARCHAR(50)    NOT NULL,
    display_name  VARCHAR(200)   NOT NULL,
    email         VARCHAR(200)   NULL,
    city          VARCHAR(100)   NULL,
    country       VARCHAR(100)   NULL,
    balance       DECIMAL(18,2)  NOT NULL DEFAULT 0,
    created_date  DATE           NULL,
    loaded_at     DATETIME       NOT NULL DEFAULT GETDATE(),
    CONSTRAINT pk_stg_customers PRIMARY KEY (customer_id)
);

-- Invoices
IF OBJECT_ID('qbo.stg_invoices', 'U') IS NOT NULL DROP TABLE qbo.stg_invoices;
CREATE TABLE qbo.stg_invoices (
    invoice_id    VARCHAR(50)    NOT NULL,
    customer_id   VARCHAR(50)    NOT NULL,
    invoice_date  DATE           NOT NULL,
    due_date      DATE           NULL,
    amount        DECIMAL(18,2)  NOT NULL,
    balance       DECIMAL(18,2)  NOT NULL DEFAULT 0,
    status        VARCHAR(20)    NOT NULL,
    loaded_at     DATETIME       NOT NULL DEFAULT GETDATE(),
    CONSTRAINT pk_stg_invoices PRIMARY KEY (invoice_id)
);

-- Payments
IF OBJECT_ID('qbo.stg_payments', 'U') IS NOT NULL DROP TABLE qbo.stg_payments;
CREATE TABLE qbo.stg_payments (
    payment_id      VARCHAR(50)    NOT NULL,
    customer_id     VARCHAR(50)    NOT NULL,
    payment_date    DATE           NOT NULL,
    amount          DECIMAL(18,2)  NOT NULL,
    payment_method  VARCHAR(50)    NULL,
    loaded_at       DATETIME       NOT NULL DEFAULT GETDATE(),
    CONSTRAINT pk_stg_payments PRIMARY KEY (payment_id)
);

-- Chart of Accounts Mapping
IF OBJECT_ID('qbo.coa_mapping', 'U') IS NOT NULL DROP TABLE qbo.coa_mapping;
CREATE TABLE qbo.coa_mapping (
    gl_account          VARCHAR(20)    NOT NULL,
    account_name        VARCHAR(200)   NOT NULL,
    fs_line_item        VARCHAR(100)   NOT NULL,
    statement           VARCHAR(50)    NOT NULL,
    section             VARCHAR(100)   NOT NULL,
    subsection          VARCHAR(100)   NULL,
    display_order       INT            NOT NULL,
    sign                VARCHAR(10)    NOT NULL,
    is_working_capital  BIT            NOT NULL DEFAULT 0,
    is_non_cash         BIT            NOT NULL DEFAULT 0,
    cash_flow_category  VARCHAR(50)    NOT NULL DEFAULT 'N/A',
    is_kpi_numerator    BIT            NOT NULL DEFAULT 0,
    is_kpi_denominator  BIT            NOT NULL DEFAULT 0,
    benchmark_sector    VARCHAR(100)   NULL,
    CONSTRAINT pk_coa_mapping PRIMARY KEY (gl_account)
);

-- Macro Indicators
IF OBJECT_ID('qbo.macro_indicators', 'U') IS NOT NULL DROP TABLE qbo.macro_indicators;
CREATE TABLE qbo.macro_indicators (
    indicator_date      DATE           NOT NULL,
    bank_rate           DECIMAL(5,4)   NULL,
    cpi                 DECIMAL(6,2)   NULL,
    gdp_growth          DECIMAL(6,4)   NULL,
    usd_cad             DECIMAL(8,4)   NULL,
    sector_index        DECIMAL(8,2)   NULL,
    consumer_confidence DECIMAL(6,2)   NULL,
    loaded_at           DATETIME       NOT NULL DEFAULT GETDATE(),
    CONSTRAINT pk_macro_indicators PRIMARY KEY (indicator_date)
);

PRINT 'All staging tables created successfully.';