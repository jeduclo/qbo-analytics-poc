"""
ml/explain.py
SHAP-based explanations for the invoice overdue classifier.

Converts numeric SHAP values into plain-language risk factor descriptions
that appear in the Power BI Collections Priority table.
The explanations are written for a non-technical audience (CFO, AR manager).
"""

import numpy as np
import pandas as pd

# Plain-language descriptions for each feature.
# These are the labels a collections manager sees in the Power BI table.
FEATURE_EXPLANATIONS = {
    "amount":                           "Invoice amount above risk threshold",
    "payment_terms_days":               "Extended payment terms increase risk",
    "customer_avg_days_to_pay":         "Customer historically pays late",
    "customer_historical_overdue_rate": "Customer has prior overdue history",
    "customer_invoice_count":           "Low invoice history for this customer",
    "invoice_month":                    "Seasonal payment pattern",
    "invoice_quarter":                  "Seasonal payment pattern",
    "bank_rate":                        "Rising interest rate environment",
    "cpi":                              "Elevated inflation environment",
    "sector_index":                     "Sector economic conditions",
    "customer_current_balance":         "High outstanding balance for this customer",
    "days_since_last_payment":          "No recent payment activity from customer",
}


def get_top_shap_features(shap_values: np.ndarray,
                           feature_names: list[str],
                           n: int = 1) -> list[str]:
    """
    Return the top n most influential feature names for each prediction.
    Uses absolute SHAP values — both strongly positive and strongly negative
    influences are considered important.

    Args:
        shap_values: 2D array of shape (n_samples, n_features)
        feature_names: List of feature names matching INVOICE_FEATURES order
        n: Number of top features to return per sample (default 1)

    Returns:
        List of feature name strings, one per sample (or comma-joined if n > 1)
    """
    top_indices = np.abs(shap_values).argsort(axis=1)[:, -n:][:, ::-1]
    results = []
    for row_indices in top_indices:
        top_names = [feature_names[i] for i in row_indices]
        results.append(top_names[0] if n == 1 else ", ".join(top_names))
    return results


def get_plain_language_explanation(feature_name: str) -> str:
    """
    Convert a feature name into a plain-language explanation string.
    Falls back to the feature name itself if no mapping is defined.

    Args:
        feature_name: Raw feature name from INVOICE_FEATURES

    Returns:
        Human-readable explanation string for display in Power BI
    """
    return FEATURE_EXPLANATIONS.get(feature_name, feature_name.replace("_", " ").title())


def build_explanations_column(shap_values: np.ndarray,
                               feature_names: list[str]) -> list[str]:
    """
    Build the full top_risk_factor column for ml_invoice_predictions.
    Combines get_top_shap_features and get_plain_language_explanation.

    Args:
        shap_values: 2D SHAP value array from TreeExplainer
        feature_names: INVOICE_FEATURES list

    Returns:
        List of plain-language explanation strings, one per invoice row
    """
    top_features = get_top_shap_features(shap_values, feature_names, n=1)
    return [get_plain_language_explanation(f) for f in top_features]