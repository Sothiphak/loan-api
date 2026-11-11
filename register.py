"""Register the two best runs under `loan-default` and set the champion and challenger aliases.

Selection rule (business view): a missed defaulter (false negative) costs the lender the loan,
so recall comes first; but rejecting too many good borrowers loses business, so precision must
stay at or above 0.70. AUC breaks ties.
  champion   = highest recall among runs with precision >= 0.70
  challenger = highest recall among the other model types (a different approach to compare against)

Usage:  MLFLOW_TRACKING_URI=http://127.0.0.1:5000 python register.py
"""
import os

import mlflow
from mlflow import MlflowClient

MODEL_NAME = "loan-default"
PRECISION_FLOOR = 0.70

mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "http://127.0.0.1:5000"))
client = MlflowClient()
exp = mlflow.get_experiment_by_name("loan-default")
runs = mlflow.search_runs([exp.experiment_id], order_by=["metrics.recall DESC", "metrics.auc DESC"])

eligible = runs[runs["metrics.precision"] >= PRECISION_FLOOR]
champion = eligible.iloc[0]
others = runs[runs["tags.model_type"] != champion["tags.model_type"]]
challenger = others.iloc[0]


def describe(r, role):
    return (f"{role}: {r['tags.mlflow.runName']} ({r['tags.model_type'].replace('_', ' ')}). "
            f"Test set: recall {r['metrics.recall']:.3f}, precision {r['metrics.precision']:.3f}, "
            f"AUC {r['metrics.auc']:.3f}. Run {r['run_id']}.")


try:
    client.create_registered_model(MODEL_NAME, description=(
        "Predicts the probability that a loan applicant defaults. Input: amount_usd, term_months, "
        "monthly_income_usd, previous_loans, late_payments. Output: [P(repay), P(default)]."))
except mlflow.exceptions.MlflowException:
    pass  # already exists

for alias, r, role in [("champion", champion, "Champion - best recall that keeps precision >= 0.70"),
                       ("challenger", challenger, "Challenger - highest recall overall, different model type")]:
    mv = mlflow.register_model(f"runs:/{r['run_id']}/model", MODEL_NAME)
    client.update_model_version(MODEL_NAME, mv.version, description=describe(r, role))
    client.set_registered_model_alias(MODEL_NAME, alias, mv.version)
    client.set_model_version_tag(MODEL_NAME, mv.version, "run_name", r["tags.mlflow.runName"])
    print(f"@{alias:10s} -> version {mv.version}  ({r['tags.mlflow.runName']})")
