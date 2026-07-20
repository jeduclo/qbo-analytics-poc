"""
ml_train.py
Weekly ML model training script.

Trains three models:
  1. XGBoost invoice overdue classifier
  2. Prophet + XGBoost revenue forecaster
  3. Isolation Forest GL anomaly detector

Saves model files to models/ and logs accuracy metrics to qbo.ml_model_metadata.

Run from project root:
    python etl/ml_train.py

Designed for unattended weekly execution via GitHub Actions (Sunday 04:00 UTC).
Requires at least 50 resolved invoices in staging for meaningful classifier training.
"""

import os
import sys
import logging
import joblib
import numpy as np
import pandas as pd
import xgboost as xgb
import shap
from datetime import date, timedelta
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score, accuracy_score
from sklearn.ensemble import IsolationForest
from prophet import Prophet
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "ml"))
from db_connection import get_engine, verify_connection
from features import (
    INVOICE_FEATURES, ANOMALY_FEATURES,
    build_invoice_features, build_anomaly_features, build_revenue_series
)
from explain import build_explanations_column
from evaluate import log_model_metadata, update_model_registry

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

MODELS_DIR      = os.path.join(os.path.dirname(__file__), "..", "models")
TRAINING_CUTOFF = date.today() - timedelta(days=90)   # Business Rule 6
MIN_TRAINING_ROWS = 50

def train_overdue_classifier(engine) -> bool:
    """
    Train XGBoost binary classifier to predict invoice overdue probability.

    Training data: invoices older than 90 days (outcome is certain).
    Label: 1 = Overdue, 0 = Paid. Open invoices excluded.

    Returns True on success, False if insufficient training data.
    """
    log.info("[Model 1] Training Invoice Overdue Classifier...")

    # ── Load training data ────────────────────────────────────────────────────
    query = f"""
        SELECT *
        FROM qbo.vw_ml_invoice_features
        WHERE invoice_date < '{TRAINING_CUTOFF}'
          AND status IN ('Paid', 'Overdue')
    """
    df = pd.read_sql(query, engine)
    log.info(f"  Training rows loaded: {len(df):,}")

    if len(df) < MIN_TRAINING_ROWS:
        log.warning(
            f"  Insufficient training data: {len(df)} rows "
            f"(minimum {MIN_TRAINING_ROWS}). Skipping classifier training.\n"
            f"  The synthetic dataset should have ~360 resolved invoices — "
            f"check that synthetic data is loaded in staging."
        )
        return False

    # ── Engineer features and labels ──────────────────────────────────────────
    X = build_invoice_features(df)
    y = (df["status"] == "Overdue").astype(int)

    log.info(f"  Class distribution — Overdue: {y.sum()} | Paid: {(y==0).sum()}")

    # ── Train / test split ────────────────────────────────────────────────────
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.20, random_state=42, stratify=y
    )
    log.info(f"  Train: {len(X_train)} rows | Test: {len(X_test)} rows")

    # ── XGBoost model ─────────────────────────────────────────────────────────
    model = xgb.XGBClassifier(
        n_estimators=200,
        max_depth=4,              # Shallow trees — prevents overfitting on small datasets
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        eval_metric="auc",
        use_label_encoder=False,
        random_state=42,
        verbosity=0,
    )

    model.fit(
        X_train, y_train,
        eval_set=[(X_test, y_test)],
        verbose=False,
    )

    # ── Evaluate ──────────────────────────────────────────────────────────────
    y_prob = model.predict_proba(X_test)[:, 1]
    y_pred = model.predict(X_test)
    auc    = roc_auc_score(y_test, y_prob)
    acc    = accuracy_score(y_test, y_pred)

    log.info(f"  AUC-ROC: {auc:.4f}")
    log.info(f"  Accuracy: {acc:.4f}")

    if auc < 0.55:
        log.warning(
            f"  AUC-ROC {auc:.4f} is close to random (0.50). "
            f"Model may not have enough signal — check feature quality "
            f"and that the synthetic data narrative is loaded correctly."
        )

    # ── SHAP explainer ────────────────────────────────────────────────────────
    log.info("  Building SHAP TreeExplainer...")
    explainer = shap.TreeExplainer(model)

    # Verify SHAP works on a sample before saving
    sample_shap = explainer.shap_values(X_test.iloc[:5])
    log.info(f"  SHAP verified on 5-row sample. Shape: {sample_shap.shape}")

    # ── Save model files ──────────────────────────────────────────────────────
    classifier_path = os.path.join(MODELS_DIR, "overdue_classifier.pkl")
    explainer_path  = os.path.join(MODELS_DIR, "overdue_explainer.pkl")

    joblib.dump(model,     classifier_path)
    joblib.dump(explainer, explainer_path)
    log.info(f"  Saved: {classifier_path}")
    log.info(f"  Saved: {explainer_path}")

    # ── Log metadata to Azure SQL ─────────────────────────────────────────────
    log_model_metadata(
        engine,
        model_name="overdue_classifier",
        accuracy=acc,
        auc_roc=auc,
        training_rows=len(X_train),
        feature_count=len(INVOICE_FEATURES),
    )

    update_model_registry("overdue_classifier", {
        "auc_roc": auc,
        "accuracy": acc,
        "training_rows": len(X_train),
        "features": INVOICE_FEATURES,
    })

    log.info(f"  [Model 1] Complete. AUC: {auc:.4f}")
    return True


def train_revenue_forecaster(engine) -> bool:
    """
    Train Prophet + XGBoost hybrid revenue forecaster.

    Step 1: Prophet fits trend and seasonality on monthly revenue.
    Step 2: XGBoost fits on Prophet residuals with macro indicators as features.
    Final forecast: Prophet base + XGBoost macro adjustment.

    Saves two model files: revenue_forecaster_prophet.pkl and
    revenue_forecaster_xgb.pkl.
    """
    log.info("[Model 2] Training Revenue Forecaster...")

    # ── Load monthly revenue + macro data ─────────────────────────────────────
    df = build_revenue_series(engine)
    log.info(f"  Revenue series loaded: {len(df)} months")

    if len(df) < 6:
        log.warning(
            f"  Only {len(df)} months of revenue history. "
            f"Prophet requires at least 6 months. Skipping forecaster training."
        )
        return False

    # ── Step 1: Prophet base model ────────────────────────────────────────────
    log.info("  Fitting Prophet model...")
    prophet_df = df[["ds", "y"]].copy()

    prophet_model = Prophet(
        yearly_seasonality=True,
        weekly_seasonality=False,
        daily_seasonality=False,
        seasonality_mode="multiplicative",
        interval_width=0.80,              # 80% confidence interval for forecast bands
        changepoint_prior_scale=0.10,     # Moderate flexibility for trend changes
    )
    prophet_model.fit(prophet_df)

    # In-sample predictions to compute residuals
    prophet_pred = prophet_model.predict(prophet_df[["ds"]])
    df["prophet_yhat"]    = prophet_pred["yhat"].values
    df["residual"]        = df["y"] - df["prophet_yhat"]

    log.info(f"  Prophet fitted. Mean residual: {df['residual'].mean():.0f}")

    # ── Step 2: XGBoost macro adjustment on residuals ─────────────────────────
    macro_cols = ["bank_rate", "cpi", "sector_index"]
    df_macro   = df[macro_cols + ["residual"]].dropna()

    if len(df_macro) >= 6:
        log.info(f"  Training XGBoost residual model on {len(df_macro)} rows...")
        X_macro = df_macro[macro_cols].fillna(0)
        y_res   = df_macro["residual"]

        macro_model = xgb.XGBRegressor(
            n_estimators=100,
            max_depth=3,
            learning_rate=0.05,
            random_state=42,
            verbosity=0,
        )
        macro_model.fit(X_macro, y_res)
        log.info("  XGBoost macro model fitted.")
    else:
        log.warning(
            f"  Insufficient macro data ({len(df_macro)} rows with macro cols). "
            f"Using Prophet-only forecast (no macro adjustment)."
        )
        macro_model = None

    # ── Save model files ──────────────────────────────────────────────────────
    prophet_path = os.path.join(MODELS_DIR, "revenue_forecaster_prophet.pkl")
    xgb_path     = os.path.join(MODELS_DIR, "revenue_forecaster_xgb.pkl")

    joblib.dump(prophet_model, prophet_path)
    joblib.dump(macro_model,   xgb_path)
    log.info(f"  Saved: {prophet_path}")
    log.info(f"  Saved: {xgb_path}")

    # Log as a regression model — use R² as accuracy proxy
    from sklearn.metrics import r2_score
    r2 = r2_score(df_macro["residual"], macro_model.predict(X_macro)) if macro_model else 0.0

    log_model_metadata(
        engine,
        model_name="revenue_forecaster",
        accuracy=max(r2, 0.0),
        auc_roc=0.0,              # Not applicable for regression
        training_rows=len(df),
        feature_count=len(macro_cols),
    )

    update_model_registry("revenue_forecaster", {
        "prophet_months_trained": len(df),
        "macro_adjustment": macro_model is not None,
    })

    log.info("[Model 2] Complete.")
    return True


def train_anomaly_detector(engine) -> bool:
    """
    Train Isolation Forest anomaly detector on all invoices.
    Unsupervised — no labels required.
    """
    log.info("[Model 3] Training GL Anomaly Detector...")

    query = "SELECT * FROM qbo.vw_ml_invoice_features"
    df    = pd.read_sql(query, engine)
    log.info(f"  Rows loaded for anomaly training: {len(df):,}")

    X = build_anomaly_features(df)

    anomaly_model = IsolationForest(
        n_estimators=100,
        contamination=0.05,       # Expect ~5% anomalies
        random_state=42,
        n_jobs=-1,                # Use all available CPU cores
    )
    anomaly_model.fit(X)

    # Quick sanity check: what fraction is flagged on training data?
    flags  = anomaly_model.predict(X)
    pct    = (flags == -1).mean()
    log.info(f"  Anomaly rate on training data: {pct:.1%} (target: ~5%)")

    path = os.path.join(MODELS_DIR, "anomaly_detector.pkl")
    joblib.dump(anomaly_model, path)
    log.info(f"  Saved: {path}")

    log_model_metadata(
        engine,
        model_name="anomaly_detector",
        accuracy=pct,             # Fraction flagged — not a true accuracy metric
        auc_roc=0.0,
        training_rows=len(X),
        feature_count=len(ANOMALY_FEATURES),
    )

    log.info("[Model 3] Complete.")
    return True


# ── Main ──────────────────────────────────────────────────────────────────────
def run_training() -> int:
    from datetime import datetime
    start = datetime.now()
    log.info("=" * 60)
    log.info("ML Training Pipeline — START")
    log.info(f"Training cutoff: invoices before {TRAINING_CUTOFF}")
    log.info("=" * 60)

    try:
        engine = get_engine()
        verify_connection(engine)
    except Exception as e:
        log.error(f"Database connection failed: {e}")
        return 1

    results = {
        "overdue_classifier":  train_overdue_classifier(engine),
        "revenue_forecaster":  train_revenue_forecaster(engine),
        "anomaly_detector":    train_anomaly_detector(engine),
    }

    elapsed = (datetime.now() - start).total_seconds()
    log.info("=" * 60)
    log.info("ML Training Pipeline — COMPLETE")
    for name, success in results.items():
        status = "SUCCESS" if success else "SKIPPED"
        log.info(f"  {name:<30} {status}")
    log.info(f"  Elapsed: {elapsed:.1f}s")
    log.info("=" * 60)

    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(run_training())
    
    
