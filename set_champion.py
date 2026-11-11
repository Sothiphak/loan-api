"""Point the `champion` alias at another registered version (promotion or rollback).

Usage:  MLFLOW_TRACKING_URI=http://127.0.0.1:5000 python set_champion.py 2
Then restart FastAPI (it loads models:/loan-default@champion at start-up) and check /health.
"""
import os
import sys

import mlflow
from mlflow import MlflowClient

mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "http://127.0.0.1:5000"))
client = MlflowClient()
version = sys.argv[1]
before = client.get_model_version_by_alias("loan-default", "champion").version
client.set_registered_model_alias("loan-default", "champion", version)
print(f"@champion: version {before} -> version {version}")
