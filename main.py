"""Loan Application Service: stores loan applications and scores their default risk."""
import os
from contextlib import asynccontextmanager

import joblib
import pandas as pd
from fastapi import FastAPI, HTTPException

from schemas import Application, ApplicationCreate, LoanFeatures, Prediction

# The model is loaded from the MLflow Model Registry BY ALIAS, so promoting or rolling back a model
# only means moving the alias and restarting - no code change, no file path, no version number.
MODEL_URI = os.getenv("MODEL_URI", "models:/loan-default@champion")
MODEL_PATH = os.getenv("MODEL_PATH")  # optional: load a local joblib file instead (Docker image from Module 4, tests)
FEATURES = ["amount_usd", "term_months", "monthly_income_usd", "previous_loans", "late_payments"]
ml = {}            # filled at start-up: {"model": ..., "version": ..., "features": [...], "source": ...}
APPLICATIONS = {}  # in-memory store; resets when the server restarts


def load_from_registry(uri: str) -> dict:
    """Load models:/<name>@<alias> and look up which registry version the alias points to."""
    import mlflow  # imported here so the Module 4 Docker image (MODEL_PATH) does not need MLflow
    import mlflow.sklearn

    name, alias = uri.removeprefix("models:/").split("@")
    version = mlflow.MlflowClient().get_model_version_by_alias(name, alias)
    return {"model": mlflow.sklearn.load_model(uri), "features": FEATURES,
            "version": f"{name} v{version.version} (@{alias})", "registry_version": version.version,
            "source": uri}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # load the model once, when the server starts
    if MODEL_PATH:
        ml.update(joblib.load(MODEL_PATH), source=MODEL_PATH)
    else:
        ml.update(load_from_registry(MODEL_URI))
    yield
    ml.clear()


app = FastAPI(title="Loan Application Service", version="1.0.0", lifespan=lifespan)


def score(features: LoanFeatures) -> Prediction:
    X = pd.DataFrame([features.model_dump()])[ml["features"]]
    probability = float(ml["model"].predict_proba(X)[0, 1])
    band = "low" if probability < 0.2 else "medium" if probability < 0.5 else "high"
    return Prediction(default_probability=round(probability, 3), risk_band=band, model_version=ml["version"])


@app.get("/health")
def health():
    body = {"status": "ok", "model_version": ml.get("version")}
    if ml.get("registry_version"):  # loaded from the registry: show which version the alias points to
        body.update(registry_version=ml["registry_version"], model_source=ml["source"])
    return body


@app.post("/api/v1/predictions", response_model=Prediction)
def predict(features: LoanFeatures):
    return score(features)


@app.post("/api/v1/applications", response_model=Application, status_code=201)
def create_application(body: ApplicationCreate):
    new = Application(id=7781 + len(APPLICATIONS), status="pending",
                      prediction=score(body), **body.model_dump())
    APPLICATIONS[new.id] = new
    return new


@app.get("/api/v1/applications", response_model=list[Application])
def list_applications():
    return list(APPLICATIONS.values())


@app.get("/api/v1/applications/{application_id}", response_model=Application)
def get_application(application_id: int):
    if application_id not in APPLICATIONS:
        raise HTTPException(status_code=404, detail=f"Application {application_id} not found")
    return APPLICATIONS[application_id]
