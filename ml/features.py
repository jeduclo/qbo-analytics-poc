"""
ml/features.py
Shared feature engineering for invoice overdue classification.

CRITICAL: Both ml_train.py and ml_score.py import and call build_invoice_features()
from this module. Never duplicate feature logic in individual scripts —
any divergence between training and scoring transformations causes silent,
hard-to-diagnose prediction errors in production.

If you add a feature, add it here first, then verify both train and score
still run correctly before committing.
"""

import numpy as np
import pandas as pd

# ── Feature list ──────────────────────────────────────────────────────────────
# This is the single source of truth for which columns are model inputs.
# Order matters — XGBoost feature importance indices correspond to this list.
INVOICE_FEATURES = [
    "amount",
    "payment_terms_days",
    "customer_avg_days_to_pay",
    "customer_historical_overdue_rate",
    "customer_invoice_count",
    "invoice_month",
    "invoice_quarter",
    "bank_rate",
    "cpi",
    "sector_index",
    "customer_current_balance",
    "days_since_last_payment",
]

ANOMALY_FEATURES = [
    "amount",
    "payment_terms_days",
    "customer_avg_days_to_pay",
    "customer_historical_overdue_rate",
    "invoice_month",
]


def build_invoice_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Engineer all features from the raw ML feature view DataFrame.
    Returns a DataFrame containing only the INVOICE_FEATURES columns,
    in the correct order, with types cast to float.

    Called by both ml_train.py (on historical invoices) and ml_score.py
    (on open invoices). Must produce identical output for identical input.

    Args:
        df: DataFrame from qbo.vw_ml_invoice_features. Must contain all
            source columns needed to derive INVOICE_FEATURES.

    Returns:
        DataFrame with exactly the columns in INVOICE_FEATURES, cast to float.

    Raises:
        KeyError if a required source column is missing from df.
        ValueError if the resulting feature DataFrame contains NaN values.
    """
    # All features are pulled directly from the view — no derivation needed here
    # because the view handles all joins and calculations.
    # This function's job is to select, order, and type-cast.

    missing_cols = [c for c in INVOICE_FEATURES if c not in df.columns]
    if missing_cols:
        raise KeyError(
            f"Feature view is missing columns required for model input: "
            f"{missing_cols}\n"
            f"Check qbo.vw_ml_invoice_features definition."
        )

    features = df[INVOICE_FEATURES].copy()

    # Cast all features to float — XGBoost requires numeric input
    for col in INVOICE_FEATURES:
        features[col] = pd.to_numeric(features[col], errors="coerce")

    # Check for NaN values — these would silently corrupt predictions
    null_counts = features.isnull().sum()
    cols_with_nulls = null_counts[null_counts > 0]
    if not cols_with_nulls.empty:
        raise ValueError(
            f"Feature matrix contains NaN values after engineering:\n"
            f"{cols_with_nulls.to_string()}\n"
            f"Check the ML feature view — COALESCE defaults may be missing."
        )

    return features


def build_anomaly_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Engineer features for the Isolation Forest anomaly detector.
    Subset of INVOICE_FEATURES — anomaly detection uses fewer features
    to avoid the curse of dimensionality on small datasets.
    """
    missing_cols = [c for c in ANOMALY_FEATURES if c not in df.columns]
    if missing_cols:
        raise KeyError(
            f"Anomaly feature view is missing columns: {missing_cols}"
        )

    features = df[ANOMALY_FEATURES].copy()
    for col in ANOMALY_FEATURES:
        features[col] = pd.to_numeric(features[col], errors="coerce").fillna(0)

    return features


def build_revenue_series(engine) -> pd.DataFrame:
    """
    Build the monthly revenue time series for Prophet training.
    Prophet requires columns named 'ds' (datetime) and 'y' (value).

    Joins monthly revenue from vw_sales_summary to macro indicators
    for the XGBoost adjustment layer.

    Returns:
        DataFrame with columns: ds, y, bank_rate, cpi, sector_index
    """
    query = """
        SELECT
            s.revenue_month                     AS ds,
            SUM(s.total_revenue)                AS y,
            m.bank_rate,
            m.cpi,
            m.sector_index
        FROM qbo.vw_sales_summary s
        LEFT JOIN qbo.macro_indicators m
            ON m.indicator_date = s.revenue_month
        GROUP BY s.revenue_month, m.bank_rate, m.cpi, m.sector_index
        ORDER BY s.revenue_month
    """
    df = pd.read_sql(query, engine)
    df["ds"] = pd.to_datetime(df["ds"])
    df["y"]  = df["y"].astype(float)
    return df