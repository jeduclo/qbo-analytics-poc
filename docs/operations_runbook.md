# Operations Runbook
## QBO Financial Intelligence Platform
Last updated: 2026-07-22

---

## Platform Overview

The platform runs on a fully automated daily pipeline:

| Time (UTC) | What happens |
|------------|-------------|
| 04:00 Sunday | Weekly ML model retraining (GitHub Actions) |
| 05:00 daily  | ETL + ML scoring pipeline (GitHub Actions) |
| 07:00 daily  | Power BI dataset refresh (Power BI Service) |

All components run unattended. Failures trigger an email notification to
the repository owner. The platform requires no manual intervention
under normal operating conditions.

---

## Monitoring

### Check if the pipeline ran successfully
1. Go to github.com/jeduclo/qbo-analytics-poc → Actions tab
2. Look for "Daily Analytics Pipeline" — most recent run should be today
   at approximately 05:00 UTC with a green ✓ status
3. If the run is red ✗, click it to read the step-by-step log

### Check if Power BI refreshed successfully
1. Go to app.powerbi.com → Portfolio Demos workspace → Datasets
2. Click three-dot menu next to QBO_Dashboard → Settings → Refresh history
3. Most recent refresh should be today at approximately 07:00 UTC with status: Completed

### Check if data is current in Azure SQL
Run this query in the Azure Portal Query Editor:
```sql
SELECT
    'stg_invoices'             AS table_name,
    MAX(loaded_at)             AS last_loaded,
    COUNT(*)                   AS row_count
FROM qbo.stg_invoices
UNION ALL
SELECT
    'ml_invoice_predictions',
    MAX(scored_at),
    COUNT(*)
FROM qbo.ml_invoice_predictions
UNION ALL
SELECT
    'ml_revenue_forecast',
    MAX(generated_at),
    COUNT(*)
FROM qbo.ml_revenue_forecast;
```
Both `loaded_at` and `scored_at` should be from today.

---

## Scheduled Maintenance

### QBO OAuth Refresh Token Renewal (every 90 days)

**When:** A 90-day calendar reminder was set in Workshop 5.
When it fires, do this immediately — do not wait.
The token expires after 100 days with no warning.

**How to renew:**
1. Go to developer.intuit.com and sign in
2. Navigate to the Intuit OAuth 2.0 Playground
3. Enter your Client ID and Client Secret
4. Complete the OAuth handshake (Steps 5.4.2 through 5.4.5 in Workshop 5)
5. Copy the new refresh_token value
6. Update GitHub Secret: go to repository → Settings → Secrets → Actions →
   click QBO_REFRESH_TOKEN → Update secret → paste new value → Save
7. Manually trigger the daily pipeline to confirm the new token works:
   Actions tab → Daily Analytics Pipeline → Run workflow
8. Set a new 90-day calendar reminder immediately

**What happens if you miss it:**
The daily pipeline fails at the ETL step with a 401 or invalid_grant error.
No data is loaded. The existing data remains in Azure SQL and Power BI
continues to show the last successful load. Renew the token and re-trigger
the pipeline to resume.

**Next renewal due:** 2026-10-20

---

## Failure Recovery Procedures

### Scenario 1: Daily pipeline fails at ETL step

**Symptoms:** GitHub Actions run fails at "Run QBO ETL Pipeline".
Staging tables contain yesterday's data.

**Common causes and fixes:**

| Error message | Cause | Fix |
|---------------|-------|-----|
| `invalid_grant` or `401` | Refresh token expired | Renew token (see above) |
| `OperationalError: Login failed` | Azure SQL password changed | Update AZURE_SQL_PASSWORD GitHub Secret |
| `TCP connection failed` | Azure SQL firewall blocked GitHub IP | In Azure Portal → SQL server → Networking → confirm "Allow Azure services" is ON |
| `ModuleNotFoundError` | requirements.txt out of date | Run pip freeze > requirements.txt locally and push |

After fixing, go to Actions → Daily Analytics Pipeline → Run workflow.

### Scenario 2: Daily pipeline fails at ML scoring step

**Symptoms:** ETL succeeded but scoring failed.
ml_invoice_predictions shows yesterday's scored_at timestamp.

**Common causes and fixes:**

| Error message | Cause | Fix |
|---------------|-------|-----|
| `FileNotFoundError: overdue_classifier.pkl` | Model artifact download failed | Manually trigger weekly_retrain.yml, then re-trigger daily pipeline |
| `ValueError: NaN values in feature matrix` | Missing macro indicator month | Add row to qbo.macro_indicators for missing month |
| `KeyError` in feature engineering | Feature view schema changed | Re-run 03_create_warehouse_views.sql |

### Scenario 3: Power BI refresh fails

**Steps:**
1. Go to Power BI Service → Dataset settings → Data source credentials
2. Click Edit credentials → re-enter Azure SQL username and password → save
3. Click Refresh now to test immediately
4. If refresh succeeds, scheduled refresh will resume automatically tomorrow

### Scenario 4: Weekly retraining produces worse model accuracy

**Steps:**
1. Check training data count:
```sql
SELECT COUNT(*) FROM qbo.stg_invoices
WHERE invoice_date < DATEADD(day, -90, GETDATE())
AND status IN ('Paid', 'Overdue');
```
Should be at least 50 rows.
2. If on live QBO sandbox, reload synthetic data:
   python synthetic_data/generate_qbo_data.py
   Then manually trigger weekly_retrain.yml.

---

## Adding a New Client

1. Create a new Azure SQL database or schema
2. Run all five DDL scripts from infrastructure/sql/
3. Register a new QBO application in the client's Intuit developer account
4. Complete the OAuth handshake and obtain a new refresh token
5. Add a new set of GitHub Secrets with a client-specific prefix
6. Create a new workflow file copying daily_pipeline.yml with client secrets
7. Generate synthetic data or connect to live QBO and verify the pipeline
8. Publish a new Power BI report using the Workshop 8 prompt sequence
9. Add a new card to the /demos landing page

---

## GitHub Secrets Reference

| Secret Name | Description | Renewal frequency |
|-------------|-------------|------------------|
| `AZURE_SQL_SERVER` | Azure SQL server hostname | Only if database recreated |
| `AZURE_SQL_DATABASE` | Database name | Static |
| `AZURE_SQL_USERNAME` | SQL admin username | Only if rotated |
| `AZURE_SQL_PASSWORD` | SQL admin password | Rotate annually |
| `QBO_CLIENT_ID` | Intuit app Client ID | Only if app recreated |
| `QBO_CLIENT_SECRET` | Intuit app Client Secret | Only if regenerated |
| `QBO_REALM_ID` | QBO company Realm ID | Static per company |
| `QBO_REFRESH_TOKEN` | QBO OAuth refresh token | Every 90 days — CRITICAL |
| `QBO_ENVIRONMENT` | sandbox or production | Changes when going live |

---

## File Reference

| File | Purpose |
|------|---------|
| `etl/qbo_etl.py` | Daily ETL — QBO API to Azure SQL |
| `etl/ml_score.py` | Daily ML scoring |
| `etl/ml_train.py` | Weekly model retraining |
| `etl/db_connection.py` | Shared database connection |
| `etl/qbo_auth.py` | QBO OAuth token refresh |
| `ml/features.py` | Shared feature engineering |
| `ml/explain.py` | SHAP plain-language explanations |
| `ml/evaluate.py` | Model accuracy logging |
| `synthetic_data/generate_qbo_data.py` | Regenerate synthetic data |
| `.github/workflows/daily_pipeline.yml` | GitHub Actions daily workflow |
| `.github/workflows/weekly_retrain.yml` | GitHub Actions weekly workflow |
| `infrastructure/sql/*.sql` | Database DDL scripts |
| `powerbi/QBO_Dashboard.pbix` | Power BI report file |
| `docs/demos/quickbooks/index.html` | Demo website page |

---

## Emergency Resources

- **Azure Portal:** portal.azure.com
- **Intuit Developer Portal:** developer.intuit.com
- **Power BI Service:** app.powerbi.com
- **GitHub Actions:** github.com/jeduclo/qbo-analytics-poc/actions
- **QBO API Docs:** developer.intuit.com/app/developer/qbo/docs

---

*Operations Runbook — QBO Financial Intelligence Platform*
*Last reviewed: 2026-07-22*