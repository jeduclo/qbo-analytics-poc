-- Run after 03_create_warehouse_views.sql
-- Creates ML output tables. These are empty at this stage — populated by ml_score.py and ml_train.py.

IF OBJECT_ID('qbo.ml_invoice_predictions', 'U') IS NOT NULL DROP TABLE qbo.ml_invoice_predictions;
CREATE TABLE qbo.ml_invoice_predictions (
    invoice_id                      VARCHAR(50)    NOT NULL,
    customer_id                     VARCHAR(50)    NOT NULL,
    overdue_probability             DECIMAL(5,4)   NOT NULL,
    risk_tier                       VARCHAR(10)    NOT NULL,
    top_risk_factor                 VARCHAR(200)   NULL,
    estimated_delay_days            INT            NULL,
    implicit_cost_at_current_rate   DECIMAL(10,2)  NULL,
    scored_at                       DATETIME       NOT NULL DEFAULT GETDATE(),
    CONSTRAINT pk_ml_invoice_predictions PRIMARY KEY (invoice_id)
);

IF OBJECT_ID('qbo.ml_revenue_forecast', 'U') IS NOT NULL DROP TABLE qbo.ml_revenue_forecast;
CREATE TABLE qbo.ml_revenue_forecast (
    forecast_month      DATE           NOT NULL,
    forecast_revenue    DECIMAL(18,2)  NOT NULL,
    lower_bound         DECIMAL(18,2)  NOT NULL,
    upper_bound         DECIMAL(18,2)  NOT NULL,
    scenario            VARCHAR(20)    NOT NULL,
    generated_at        DATETIME       NOT NULL DEFAULT GETDATE(),
    CONSTRAINT pk_ml_revenue_forecast PRIMARY KEY (forecast_month, scenario)
);

IF OBJECT_ID('qbo.ml_anomaly_flags', 'U') IS NOT NULL DROP TABLE qbo.ml_anomaly_flags;
CREATE TABLE qbo.ml_anomaly_flags (
    invoice_id      VARCHAR(50)    NOT NULL,
    anomaly_score   DECIMAL(8,4)   NOT NULL,
    is_anomaly      BIT            NOT NULL DEFAULT 0,
    anomaly_reason  VARCHAR(500)   NULL,
    flagged_at      DATETIME       NOT NULL DEFAULT GETDATE(),
    CONSTRAINT pk_ml_anomaly_flags PRIMARY KEY (invoice_id)
);

IF OBJECT_ID('qbo.ml_model_metadata', 'U') IS NOT NULL DROP TABLE qbo.ml_model_metadata;
CREATE TABLE qbo.ml_model_metadata (
    model_name       VARCHAR(100)   NOT NULL,
    trained_at       DATETIME       NOT NULL,
    accuracy         DECIMAL(5,4)   NULL,
    auc_roc          DECIMAL(5,4)   NULL,
    training_rows    INT            NULL,
    feature_count    INT            NULL,
    xgboost_version  VARCHAR(20)    NULL,
    CONSTRAINT pk_ml_model_metadata PRIMARY KEY (model_name)
);

PRINT 'All ML output tables created successfully.';