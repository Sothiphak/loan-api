"""Train several loan-default models and track every run in MLflow.

Usage (tracking server running on port 5000):
    export MLFLOW_TRACKING_URI=http://127.0.0.1:5000
    python train_tracked.py

Each run logs its parameters, recall / precision / AUC / F1 on the same test set,
and the model with a signature, so it can be registered and served later.
"""
import mlflow
import mlflow.sklearn
import pandas as pd
from mlflow.models import infer_signature
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score, precision_score, recall_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from train import FEATURES, make_data

EXPERIMENT = "loan-default"
THRESHOLD = 0.5  # a probability at or above this is treated as "will default"

# (run name, model type, parameters) - 8 runs across 3 model types
CANDIDATES = [
    ("logreg-C0.01", "logistic_regression", {"C": 0.01}),
    ("logreg-C0.1", "logistic_regression", {"C": 0.1}),
    ("logreg-C1.0", "logistic_regression", {"C": 1.0}),
    ("rf-100-d4", "random_forest", {"n_estimators": 100, "max_depth": 4}),
    ("rf-200-d6", "random_forest", {"n_estimators": 200, "max_depth": 6}),
    ("rf-300-d10", "random_forest", {"n_estimators": 300, "max_depth": 10}),
    ("gb-100-lr0.05", "gradient_boosting", {"n_estimators": 100, "learning_rate": 0.05, "max_depth": 2}),
    ("gb-200-lr0.1", "gradient_boosting", {"n_estimators": 200, "learning_rate": 0.1, "max_depth": 3}),
]


def build(model_type: str, params: dict):
    """Every model handles class imbalance, so recall is comparable across types."""
    if model_type == "logistic_regression":
        return make_pipeline(StandardScaler(), LogisticRegression(class_weight="balanced", max_iter=1000, **params))
    if model_type == "random_forest":
        return RandomForestClassifier(class_weight="balanced", random_state=42, n_jobs=-1, **params)
    if model_type == "gradient_boosting":
        return GradientBoostingClassifier(random_state=42, **params)
    raise ValueError(model_type)


def main():
    mlflow.set_experiment(EXPERIMENT)

    df = make_data()
    X = df[FEATURES].astype({"amount_usd": "int64", "term_months": "int64", "monthly_income_usd": "float64",
                             "previous_loans": "int64", "late_payments": "int64"})
    y = df.defaulted.astype(int)
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)

    # Gradient boosting has no class_weight option, so it gets balanced sample weights instead
    pos_weight = (y_train == 0).sum() / (y_train == 1).sum()
    sample_weight = y_train.map({0: 1.0, 1: pos_weight})

    rows = []
    for run_name, model_type, params in CANDIDATES:
        with mlflow.start_run(run_name=run_name) as run:
            model = build(model_type, params)
            if model_type == "gradient_boosting":
                model.fit(X_train, y_train, sample_weight=sample_weight)
            else:
                model.fit(X_train, y_train)

            proba = model.predict_proba(X_test)[:, 1]
            pred = (proba >= THRESHOLD).astype(int)
            metrics = {
                "recall": recall_score(y_test, pred),
                "precision": precision_score(y_test, pred, zero_division=0),
                "auc": roc_auc_score(y_test, proba),
                "f1": f1_score(y_test, pred),
            }

            mlflow.set_tag("model_type", model_type)
            mlflow.log_params({"model_type": model_type, "threshold": THRESHOLD, **params})
            mlflow.log_metrics(metrics)

            # The served model returns predict_proba, so the scoring server gives probabilities
            signature = infer_signature(X_test.head(5), model.predict_proba(X_test.head(5)))
            # MLflow saves sklearn models with skops; tree models need their Tree type marked as trusted
            trusted = ["sklearn.tree._tree.Tree"] if model_type != "logistic_regression" else None
            mlflow.sklearn.log_model(model, name="model", signature=signature, input_example=X_test.head(2),
                                     pyfunc_predict_fn="predict_proba", skops_trusted_types=trusted)

            rows.append({"run": run_name, "model_type": model_type, "run_id": run.info.run_id,
                         **{k: round(v, 3) for k, v in metrics.items()}})
            print(f"{run_name:15s} recall={metrics['recall']:.3f} precision={metrics['precision']:.3f} "
                  f"auc={metrics['auc']:.3f}")

    table = pd.DataFrame(rows).sort_values(["recall", "auc"], ascending=False)
    table.to_csv("experiment_results.csv", index=False)
    print("\n" + table.to_string(index=False))


if __name__ == "__main__":
    main()
