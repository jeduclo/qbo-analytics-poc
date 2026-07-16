# Scope — QBO Financial Intelligence Platform

## Business Objective

### Who is this for?
Accounting firm partners and senior staff who manage a portfolio of SMB clients using QuickBooks Online.

### What will they see?
A Power BI dashboard with three pages: Financial Overview, Financial Statements, and Scenario Forecast — enriched with ML-powered invoice overdue predictions, 12-month revenue forecasts (Base / Stress / Upside), GL anomaly alerts, and macroeconomic context (Bank of Canada rate, CPI, GDP, USD/CAD).

### What action do we want them to take?
Proactively reach out to at-risk clients before cash flow crises occur, and present the dashboard as a premium advisory service offering to prospects.

---

## In Scope

### Infrastructure
- One Azure SQL database
- One schema: `qbo`
- GitHub repository with GitHub Actions for automation

### Data Sources
- QuickBooks Online API: Customer, Invoice, Payment entities
- Chart of Accounts mapping table (manually curated, reusable)
- Macro indicators: Bank of Canada overnight rate, CPI, GDP growth, USD/CAD rate, sector index, consumer confidence
- Statistics Canada API and Bank of Canada API for macro data

### Machine Learning
- XGBoost invoice overdue prediction classifier
- Prophet + XGBoost hybrid 12-month revenue forecast (Base, Stress, Upside scenarios)
- Isolation Forest GL anomaly detection
- SHAP-based plain-language risk factor explanations
- Weekly automated model retraining

### Visualization
- One Power BI report in PBIX format
- Three pages: Financial Overview, Financial Statements, Scenario Forecast
- Semantic model authored via Claude Desktop + PowerBI Modeling MCP Server
- Published to Power BI Service with daily scheduled refresh

### Delivery
- One website page: `/demos/quickbooks`
- One demos landing page: `/demos` (QuickBooks active, Odoo and Dynamics 365 coming soon)
- Power BI "Publish to Web" iframe embed (public, no login required)

### Development Data
- 24 months of synthetic data (Jan 2023 – Dec 2024)
- 70 customers, ~600 invoices, ~400 payments
- Engineered narrative: baseline → dip → recovery → growth

### Automation
- Daily ETL + ML scoring: GitHub Actions
- Weekly ML retraining: GitHub Actions
- Daily Power BI refresh: Power BI Service scheduled refresh

---

## Out of Scope (This Phase)

| Item | Reason |
|------|--------|
| Real client QuickBooks data | PoC uses synthetic data only |
| Row-level security | Not required for public demo embed |
| Mobile-optimised Power BI layout | Single desktop layout for this phase |
| QuickBooks Desktop | REST API only; QuickBooks Desktop uses a different SDK |
| Multi-page reports beyond three pages | Defined scope; additional pages in a future engagement |
| Deep learning or neural network models | XGBoost is appropriate for SMB data volumes and explainability requirements |
| Real-time streaming data | Daily batch is sufficient for financial reporting use case |
| Multi-tenant architecture | Single client PoC |
| Odoo integration | Planned for next workshop series |
| Dynamics 365 integration | Planned for workshop series after Odoo |

---

## Assumptions

- Power BI Pro licence or trial is available
- Azure account is available with budget for a serverless SQL database (~$5–15/month)
- GitHub account is available (free tier sufficient)
- Anthropic account is available for Claude Desktop
- QuickBooks Online developer sandbox is available (free at developer.intuit.com)

---

## Delivery Timeline

| Workshop | Focus | Target Week | Hard Dependency |
|----------|-------|-------------|-----------------|
| 1 | Vision & Scope | Week 1 | None |
| 2 | Infrastructure Setup | Week 1 | Workshop 1 complete |
| 3 | Data Modelling | Week 2 | Workshop 2 complete |
| 4 | Synthetic Data Generation | Week 2 | Workshop 3 complete |
| 5 | QBO API & Authentication | Week 3 | Workshop 2 complete |
| 6 | ETL Pipeline | Week 3 | Workshops 4 and 5 complete |
| 7 | ML Pipeline | Week 4 | Workshop 6 complete |
| 8 | Power BI Dashboard | Week 4–5 | Workshop 4 minimum |
| 9 | Website Integration | Week 5 | Workshop 8 complete |
| 10 | Scheduling & Automation | Week 6 | Workshops 6 and 7 complete |
| 11 | QA, Polish & Demo Prep | Week 6–7 | All prior workshops complete |

> **Note:** Workshop 8 can begin on synthetic data while Workshops 5, 6, and 7 are still in progress — saves ~1 week of calendar time.

