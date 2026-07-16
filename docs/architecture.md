# Architecture — QBO Financial Intelligence Platform

## Six-Layer Stack

| Layer | Name | Technology | Description |
|-------|------|------------|-------------|
| 1 | Source | QuickBooks Online API | REST API, JSON responses, OAuth 2.0 authentication. Three entities: Customer, Invoice, Payment. Sandbox environment used during development. |
| 2 | Extraction | Python ETL Script (qbo_etl.py) | Python script that authenticates, paginates through all records, transforms fields, and loads into Azure SQL. Runs daily via GitHub Actions. |
| 3 | Storage | Azure SQL Database | Single database, single schema (qbo). Contains staging tables, warehouse views, ML output tables, CoA mapping table, and macro indicators table. |
| 4 | Intelligence | Python ML Pipeline | XGBoost classifier for invoice overdue prediction. Prophet + XGBoost hybrid for 12-month revenue forecasting. Isolation Forest for GL anomaly detection. SHAP for plain-language risk explanations. |
| 5 | Visualization | Power BI Desktop → Power BI Service | PBIX format. Semantic model authored via Claude Desktop connected through PowerBI Modeling MCP Server. Published to Power BI Service for daily refresh. |
| 6 | Delivery | Company Website (iframe embed) | Power BI "Publish to Web" iframe embedded in /demos/quickbooks page. Publicly accessible. No login required. |

## Data Flow

## Automation

| Job | Schedule | Tool |
|-----|----------|------|
| ETL + ML scoring | Daily at 05:00 UTC | GitHub Actions |
| ML retraining | Sunday at 04:00 UTC | GitHub Actions |
| Power BI refresh | Daily at 07:00 UTC | Power BI Service |

> ⚠️ QBO OAuth refresh token expires every 100 days — set a 90-day calendar reminder to renew.