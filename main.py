"""Loan Application Service: stores loan applications and scores their default risk."""
import os
from contextlib import asynccontextmanager

import joblib
import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.security import APIKeyHeader

from schemas import Application, ApplicationCreate, LoanFeatures, Prediction

# The model is loaded from the MLflow Model Registry BY ALIAS, so promoting or rolling back a model
# only means moving the alias and restarting - no code change, no file path, no version number.
MODEL_URI = os.getenv("MODEL_URI", "models:/loan-default@champion")
MODEL_PATH = os.getenv("MODEL_PATH")  # optional: load a local joblib file instead (Docker image from Module 4, tests)
FEATURES = ["amount_usd", "term_months", "monthly_income_usd", "previous_loans", "late_payments"]
ml = {}            # filled at start-up: {"model": ..., "version": ..., "features": [...], "source": ...}
APPLICATIONS = {}  # in-memory store; resets when the server restarts
GIT_SHA = os.getenv("GIT_SHA", "dev")  # stamped into the image at build time by the pipeline

# --- API key (Lesson 6.6): the key lives only in an environment variable (Render / GitHub secret) ---
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(key: str | None = Security(api_key_header)) -> None:
    expected = os.getenv("API_KEY")
    if not expected:  # fail closed: never run unprotected because a variable is missing
        raise HTTPException(status_code=503, detail="API key not configured")
    if key is None:
        raise HTTPException(status_code=401, detail="Missing API key")
    if key != expected:
        raise HTTPException(status_code=403, detail="Invalid API key")


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

# Error responses documented in /openapi.json, matching the Module 2 contract
AUTH_ERRORS = {401: {"description": "Missing API key"}, 403: {"description": "Invalid API key"}}
NOT_FOUND = {404: {"description": "Resource not found"}}


def score(features: LoanFeatures) -> Prediction:
    X = pd.DataFrame([features.model_dump()])[ml["features"]]
    probability = float(ml["model"].predict_proba(X)[0, 1])
    band = "low" if probability < 0.2 else "medium" if probability < 0.5 else "high"
    return Prediction(default_probability=round(1 - probability, 3), risk_band=band, model_version=ml["version"])


@app.get("/health")
def health():
    body = {"status": "ok", "model_version": ml.get("version"), "git_sha": GIT_SHA}
    if ml.get("registry_version"):  # loaded from the registry: show which version the alias points to
        body.update(registry_version=ml["registry_version"], model_source=ml["source"])
    return body


@app.post("/api/v1/predictions", response_model=Prediction, dependencies=[Depends(require_api_key)], responses=AUTH_ERRORS)
def predict(features: LoanFeatures):
    return score(features)


@app.post("/api/v1/applications", response_model=Application, status_code=201, dependencies=[Depends(require_api_key)], responses=AUTH_ERRORS)
def create_application(body: ApplicationCreate):
    new = Application(id=7781 + len(APPLICATIONS), status="pending",
                      prediction=score(body), **body.model_dump())
    APPLICATIONS[new.id] = new
    return new


@app.get("/api/v1/applications", response_model=list[Application], dependencies=[Depends(require_api_key)], responses=AUTH_ERRORS)
def list_applications():
    return list(APPLICATIONS.values())


@app.get("/api/v1/applications/{application_id}", response_model=Application, dependencies=[Depends(require_api_key)],
         responses={**AUTH_ERRORS, **NOT_FOUND})
def get_application(application_id: int):
    if application_id not in APPLICATIONS:
        raise HTTPException(status_code=404, detail=f"Application {application_id} not found")
    return APPLICATIONS[application_id]


@app.get("/api/v1/borrowers/{borrower_id}/applications", response_model=list[Application],
         dependencies=[Depends(require_api_key)], responses=AUTH_ERRORS)
def list_borrower_applications(borrower_id: int):
    """All applications that belong to one borrower (the nested list from the Module 2 contract)."""
    return [a for a in APPLICATIONS.values() if a.borrower_id == borrower_id]
