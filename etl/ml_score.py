"""
ml_score.py
Daily ML scoring script.

Loads trained model files and scores:
  1. All open invoices → qbo.ml_invoice_predictions
  2. Next 12 months of revenue → qbo.ml_revenue_forecast (3 scenarios)
  3. Last 30 days of invoices for anomalies → qbo.ml_anomaly_flags

Run from project root:
    python etl/ml_score.py

Designed for unattended daily execution via GitHub Actions.
Must be run after qbo_etl.py on the same day.
Model files must exist in models/ (written by ml_train.py).
"""

import os
import sys
import logging
import joblib
import numpy as np
import pandas as pd
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv
from sqlalchemy import text

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "ml"))
from db_connection import get_engine, verify_connection
from features import (
    INVOICE_FEATURES, ANOMALY_FEATURES,
    build_invoice_features, build_anomaly_features
)
from explain import build_explanations_column

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

MODELS_DIR = os.path.join(os.path.dirname(__file__), "..", "models")


def get_current_bank_rate(engine) -> float:
    """Retrieve the most recent bank rate from macro_indicators."""
    query = """
        SELECT TOP 1 bank_rate
        FROM qbo.macro_indicators
        WHERE bank_rate IS NOT NULL
        ORDER BY indicator_date DESC
    """
    result = pd.read_sql(query, engine)
    return float(result.iloc[0]["bank_rate"]) if not result.empty else 0.05


def score_open_invoices(engine) -> int:
    """
    Score all open invoices with the overdue classifier.
    Writes results to qbo.ml_invoice_predictions (full replace).

    Returns number of invoices scored.
    """
    log.info("[1/3] Scoring open invoices...")

    # ── Load open invoices from feature view ──────────────────────────────────
    query = """
        SELECT *
        FROM qbo.vw_ml_invoice_features
        WHERE status IN ('Open', 'Overdue')
    """
    df = pd.read_sql(query, engine)
    log.info(f"  Open/Overdue invoices to score: {len(df):,}")

    if df.empty:
        log.warning("  No open invoices to score. Skipping.")
        return 0

    # ── Load models ───────────────────────────────────────────────────────────
    classifier_path = os.path.join(MODELS_DIR, "overdue_classifier.pkl")
    explainer_path  = os.path.join(MODELS_DIR, "overdue_explainer.pkl")

    if not os.path.exists(classifier_path):
        raise FileNotFoundError(
            f"Model file not found: {classifier_path}\n"
            f"Run ml_train.py before ml_score.py."
        )

    model     = joblib.load(classifier_path)
    explainer = joblib.load(explainer_path)
    log.info("  Models loaded.")

    # ── Build features and score ──────────────────────────────────────────────
    X = build_invoice_features(df)
    df["overdue_probability"] = model.predict_proba(X)[:, 1]

    # ── Risk tier assignment (Business Rule 4) ────────────────────────────────
    df["risk_tier"] = pd.cut(
        df["overdue_probability"],
        bins=[0, 0.30, 0.60, 1.01],
        labels=["Low", "Medium", "High"],
        right=False,
    ).astype(str)

    # ── SHAP explanations ─────────────────────────────────────────────────────
    log.info("  Computing SHAP values...")
    shap_values             = explainer.shap_values(X)
    df["top_risk_factor"]   = build_explanations_column(shap_values, INVOICE_FEATURES)

    # ── Estimated delay days (simple heuristic) ───────────────────────────────
    # High-risk invoices estimated 30+ days late; Medium 10–30; Low 0
    df["estimated_delay_days"] = df["overdue_probability"].apply(
        lambda p: int(p * 60) if p > 0.30 else 0
    )

    # ── Implicit financing cost (Business Rule 5) ─────────────────────────────
    bank_rate = get_current_bank_rate(engine)
    df["implicit_cost_at_current_rate"] = (
        df["balance"] * bank_rate / 365
    ).round(2)

    log.info(
        f"  Risk tier distribution: "
        f"High={( df['risk_tier']=='High').sum()} | "
        f"Medium={(df['risk_tier']=='Medium').sum()} | "
        f"Low={(   df['risk_tier']=='Low').sum()}"
    )

    # ── Write to Azure SQL ────────────────────────────────────────────────────
    output_cols = [
        "invoice_id", "customer_id", "overdue_probability",
        "risk_tier", "top_risk_factor", "estimated_delay_days",
        "implicit_cost_at_current_rate",
    ]
    output_df = df[output_cols].copy()
    output_df["scored_at"] = pd.Timestamp.now()

    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE qbo.ml_invoice_predictions"))

    output_df.to_sql(
        "ml_invoice_predictions", engine, schema="qbo",
        if_exists="append", index=False, chunksize=500, method="multi",
    )
    log.info(f"  Written {len(output_df):,} rows → qbo.ml_invoice_predictions")
    return len(output_df)


def generate_revenue_forecast(engine) -> int:
    """
    Generate 12-month revenue forecast in three scenarios.
    Writes 36 rows to qbo.ml_revenue_forecast.

    Scenarios:
      Base:   Current macro conditions unchanged
      Stress: Rate +75bps, CPI +5%, sector index -8%
      Upside: Rate -25bps, CPI -2%, sector index +5%
    """
    log.info("[2/3] Generating revenue forecast...")

    prophet_path = os.path.join(MODELS_DIR, "revenue_forecaster_prophet.pkl")
    xgb_path     = os.path.join(MODELS_DIR, "revenue_forecaster_xgb.pkl")

    if not os.path.exists(prophet_path):
        log.warning("  Revenue forecaster not found. Skipping forecast generation.")
        return 0

    prophet_model = joblib.load(prophet_path)
    macro_model   = joblib.load(xgb_path)

    # ── Build future dates (12 months forward) ────────────────────────────────
    today         = date.today()
    future_months = [
        (today.replace(day=1) + relativedelta(months=i))
        for i in range(1, 13)
    ]
    future_df = pd.DataFrame({"ds": pd.to_datetime(future_months)})

    # ── Prophet base forecast ─────────────────────────────────────────────────
    prophet_forecast = prophet_model.predict(future_df)

    # ── Current macro values for scenario construction ────────────────────────
    current_macro_query = """
        SELECT TOP 1 bank_rate, cpi, sector_index
        FROM qbo.macro_indicators
        WHERE bank_rate IS NOT NULL
        ORDER BY indicator_date DESC
    """
    current = pd.read_sql(current_macro_query, engine)
    base_rate   = float(current.iloc[0]["bank_rate"])   if not current.empty else 0.05
    base_cpi    = float(current.iloc[0]["cpi"])          if not current.empty else 150.0
    base_sector = float(current.iloc[0]["sector_index"]) if not current.empty else 100.0

    scenarios = {
        "Base":   {"bank_rate": base_rate,          "cpi": base_cpi,           "sector_index": base_sector},
        "Stress": {"bank_rate": base_rate + 0.0075, "cpi": base_cpi * 1.05,    "sector_index": base_sector * 0.92},
        "Upside": {"bank_rate": base_rate - 0.0025, "cpi": base_cpi * 0.98,    "sector_index": base_sector * 1.05},
    }

    rows = []
    for scenario_name, macro_vals in scenarios.items():
        for i, row in prophet_forecast.iterrows():
            prophet_base = row["yhat"]
            lower        = row["yhat_lower"]
            upper        = row["yhat_upper"]

            # XGBoost macro adjustment
            if macro_model is not None:
                macro_input = pd.DataFrame([macro_vals])
                adjustment  = float(macro_model.predict(macro_input)[0])
            else:
                adjustment = 0.0

            forecast_rev = max(prophet_base + adjustment, 0)
            width        = (upper - lower) / 2

            rows.append({
                "forecast_month":   future_months[i],
                "forecast_revenue": round(forecast_rev, 2),
                "lower_bound":      round(max(forecast_rev - width, 0), 2),
                "upper_bound":      round(forecast_rev + width, 2),
                "scenario":         scenario_name,
                "generated_at":     pd.Timestamp.now(),
            })

    forecast_df = pd.DataFrame(rows)

    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE qbo.ml_revenue_forecast"))

    forecast_df.to_sql(
        "ml_revenue_forecast", engine, schema="qbo",
        if_exists="append", index=False, chunksize=500, method="multi",
    )
    log.info(f"  Written {len(forecast_df)} rows → qbo.ml_revenue_forecast "
             f"(12 months × 3 scenarios)")
    return len(forecast_df)


def flag_anomalies(engine) -> int:
    """
    Score invoices from the last 30 days for anomalies.
    Writes results to qbo.ml_anomaly_flags.
    """
    log.info("[3/3] Running anomaly detection...")

    cutoff = date.today() - timedelta(days=600)
    query  = f"""
        SELECT *
        FROM qbo.vw_ml_invoice_features
        WHERE invoice_date >= '{cutoff}'
    """
    df = pd.read_sql(query, engine)
    log.info(f"  Invoices in last 30 days: {len(df):,}")

    if df.empty:
        log.warning("  No recent invoices. Skipping anomaly detection.")
        return 0

    path = os.path.join(MODELS_DIR, "anomaly_detector.pkl")
    if not os.path.exists(path):
        log.warning("  Anomaly detector not found. Skipping.")
        return 0

    model = joblib.load(path)
    X     = build_anomaly_features(df)

    scores     = model.score_samples(X)              # More negative = more anomalous
    flags      = model.predict(X)                    # -1 = anomaly, 1 = normal
    df["anomaly_score"] = scores
    df["is_anomaly"]    = (flags == -1).astype(int)

    # Simple anomaly reason based on which feature is most extreme
    def anomaly_reason(row):
        if row["is_anomaly"] == 0:
            return None
        if row.get("amount", 0) > 20000:
            return "Invoice amount significantly above customer average"
        if row.get("customer_historical_overdue_rate", 0) > 0.5:
            return "Customer overdue rate exceeds 50%"
        if row.get("payment_terms_days", 30) > 60:
            return "Unusually extended payment terms"
        return "Statistical outlier across multiple dimensions"

    df["anomaly_reason"] = df.apply(anomaly_reason, axis=1)

    output_df = df[["invoice_id", "anomaly_score", "is_anomaly", "anomaly_reason"]].copy()
    output_df["flagged_at"] = pd.Timestamp.now()

    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE qbo.ml_anomaly_flags"))

    output_df.to_sql(
        "ml_anomaly_flags", engine, schema="qbo",
        if_exists="append", index=False, chunksize=500, method="multi",
    )

    n_flagged = df["is_anomaly"].sum()
    log.info(
        f"  Written {len(output_df):,} rows → qbo.ml_anomaly_flags "
        f"({n_flagged} flagged as anomalies)"
    )
    return len(output_df)


# ── Main ──────────────────────────────────────────────────────────────────────
def run_scoring() -> int:
    from datetime import datetime
    start = datetime.now()
    log.info("=" * 60)
    log.info("ML Scoring Pipeline — START")
    log.info("=" * 60)

    try:
        engine = get_engine()
        verify_connection(engine)
    except Exception as e:
        log.error(f"Database connection failed: {e}")
        return 1

    try:
        n_scored    = score_open_invoices(engine)
        n_forecast  = generate_revenue_forecast(engine)
        n_anomalies = flag_anomalies(engine)
    except Exception as e:
        log.error(f"Scoring failed: {e}")
        return 1

    elapsed = (datetime.now() - start).total_seconds()
    log.info("=" * 60)
    log.info("ML Scoring Pipeline — COMPLETE")
    log.info(f"  Invoices scored:     {n_scored:>6,}")
    log.info(f"  Forecast rows:       {n_forecast:>6,}")
    log.info(f"  Anomaly rows:        {n_anomalies:>6,}")
    log.info(f"  Elapsed:             {elapsed:.1f}s")
    log.info("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(run_scoring())