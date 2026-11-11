"""The unit tests use the local model file from `python train.py`, not the MLflow registry."""
import os

os.environ.setdefault("MODEL_PATH", "model.joblib")
