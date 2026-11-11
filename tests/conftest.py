"""The unit tests use the local model file from `python train.py` (not the MLflow registry)
and a throw-away API key that exists only inside the test run."""
import os

os.environ.setdefault("MODEL_PATH", "model.joblib")
os.environ.setdefault("API_KEY", "test-key-not-a-secret")
