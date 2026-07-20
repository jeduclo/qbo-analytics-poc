"""
ml/evaluate.py
Model evaluation utilities. Logs performance metrics to qbo.ml_model_metadata
so Power BI can display model accuracy as a KPI card.
"""

import json
import xgboost as xgb
import pandas as pd
from datetime import datetime
from sqlalchemy import text


def log_model_metadata(engine, model_name: str, accuracy: float,
                        auc_roc: float, training_rows: int,
                        feature_count: int) -> None:
    """
    Write or update a row in qbo.ml_model_metadata.
    Called at the end of each training run.
    Power BI reads this table to populate the Model Accuracy % KPI card.

    Uses MERGE so re-running the training script updates rather than duplicates.
    """
    merge_sql = text("""
        MERGE qbo.ml_model_metadata AS target
        USING (SELECT
            :model_name     AS model_name,
            :trained_at     AS trained_at,
            :accuracy       AS accuracy,
            :auc_roc        AS auc_roc,
            :training_rows  AS training_rows,
            :feature_count  AS feature_count,
            :xgb_version    AS xgboost_version
        ) AS source
        ON target.model_name = source.model_name
        WHEN MATCHED THEN UPDATE SET
            trained_at      = source.trained_at,
            accuracy        = source.accuracy,
            auc_roc         = source.auc_roc,
            training_rows   = source.training_rows,
            feature_count   = source.feature_count,
            xgboost_version = source.xgboost_version
        WHEN NOT MATCHED THEN INSERT
            (model_name, trained_at, accuracy, auc_roc,
             training_rows, feature_count, xgboost_version)
        VALUES
            (source.model_name, source.trained_at, source.accuracy,
             source.auc_roc, source.training_rows, source.feature_count,
             source.xgboost_version);
    """)

    with engine.begin() as conn:
        conn.execute(merge_sql, {
            "model_name":    model_name,
            "trained_at":    datetime.now(),
            "accuracy":      round(accuracy, 4),
            "auc_roc":       round(auc_roc, 4),
            "training_rows": training_rows,
            "feature_count": feature_count,
            "xgb_version":   xgb.__version__,
        })


def update_model_registry(model_name: str, metadata: dict,
                           registry_path: str = "models/model_registry.json") -> None:
    """
    Update the local model registry JSON file with training metadata.
    Provides a human-readable record of what is currently deployed.

    Args:
        model_name: Model identifier string
        metadata: Dict of metadata to record (trained_at, auc_roc, etc.)
        registry_path: Path to the JSON registry file
    """
    import os

    registry = {}
    if os.path.exists(registry_path):
        with open(registry_path) as f:
            registry = json.load(f)

    registry[model_name] = {
        **metadata,
        "updated_at": datetime.now().isoformat(),
    }

    with open(registry_path, "w") as f:
        json.dump(registry, f, indent=2, default=str)