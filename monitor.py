"""Simulate 14 days of production traffic and measure drift against the training data.

For every day we compare the incoming applicants with the training data (the reference) using the
Population Stability Index (PSI) per feature, and we track the share of applicants the champion
model flags as likely defaulters. From day 8 a simulated economic shock lowers incomes and raises
loan amounts, which is the drift we want the alerts to catch.

Usage:  MLFLOW_TRACKING_URI=http://127.0.0.1:5000 python monitor.py
Writes: drift_chart.png and drift_report.csv
"""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mlflow.sklearn
import numpy as np
import pandas as pd

from train import FEATURES, make_data

MODEL_URI = os.getenv("MODEL_URI", "models:/loan-default@champion")
DAYS, PER_DAY, SHOCK_DAY = 14, 400, 8
PSI_WARN, PSI_ALERT = 0.10, 0.25          # thresholds chosen from the chart (see the report)
FLAG_RATE_ALERT_POINTS = 10               # alert if the flagged share moves 10+ points from the reference


def psi(reference: pd.Series, current: pd.Series, bins: int = 10) -> float:
    """Population Stability Index with bins taken from the reference deciles."""
    edges = np.unique(np.quantile(reference, np.linspace(0, 1, bins + 1)))
    edges[0], edges[-1] = -np.inf, np.inf
    ref = np.histogram(reference, edges)[0] / len(reference)
    cur = np.histogram(current, edges)[0] / len(current)
    ref, cur = np.clip(ref, 1e-4, None), np.clip(cur, 1e-4, None)
    return float(np.sum((cur - ref) * np.log(cur / ref)))


def production_day(day: int) -> pd.DataFrame:
    """One day of applicants. Before the shock they look like the training data; after it, incomes
    fall and loan amounts rise a little more every day."""
    df = make_data(n=PER_DAY, seed=1000 + day)[FEATURES].copy()
    if day >= SHOCK_DAY:
        strength = (day - SHOCK_DAY + 1) / (DAYS - SHOCK_DAY + 1)   # grows from ~0.14 to 1.0
        df["monthly_income_usd"] = (df["monthly_income_usd"] * (1 - 0.35 * strength)).clip(80).round()
        df["amount_usd"] = (df["amount_usd"] * (1 + 0.40 * strength)).clip(upper=5000).round().astype(int)
    return df


def main():
    model = mlflow.sklearn.load_model(MODEL_URI)
    reference = make_data()[FEATURES]
    ref_flag_rate = float((model.predict_proba(reference)[:, 1] >= 0.5).mean())

    rows = []
    for day in range(1, DAYS + 1):
        cur = production_day(day)
        row = {"day": day, **{f"psi_{f}": psi(reference[f], cur[f]) for f in ["amount_usd", "monthly_income_usd"]}}
        row["flag_rate"] = float((model.predict_proba(cur)[:, 1] >= 0.5).mean())
        row["max_psi"] = max(row["psi_amount_usd"], row["psi_monthly_income_usd"])
        status = "ALERT" if row["max_psi"] >= PSI_ALERT else "WARN" if row["max_psi"] >= PSI_WARN else "ok"
        if abs(row["flag_rate"] - ref_flag_rate) * 100 >= FLAG_RATE_ALERT_POINTS:
            status = "ALERT"
        row["status"] = status
        rows.append(row)

    report = pd.DataFrame(rows)
    report.round(3).to_csv("drift_report.csv", index=False)
    print(f"Reference flagged share: {ref_flag_rate:.1%}")
    print(report.round(3).to_string(index=False))

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    ax1.plot(report.day, report.psi_monthly_income_usd, "o-", label="PSI monthly_income_usd", color="#1F4E79")
    ax1.plot(report.day, report.psi_amount_usd, "s-", label="PSI amount_usd", color="#E07B39")
    ax1.axhline(PSI_WARN, color="#E0B000", ls="--", label=f"warning {PSI_WARN}")
    ax1.axhline(PSI_ALERT, color="#C00000", ls="--", label=f"alert {PSI_ALERT}")
    ax1.axvspan(SHOCK_DAY - 0.5, DAYS + 0.5, color="#C00000", alpha=0.06)
    ax1.text(SHOCK_DAY - 0.3, ax1.get_ylim()[1] * 0.9, "simulated shock starts", fontsize=8, color="#C00000")
    ax1.set_ylabel("PSI vs training data")
    ax1.set_title("Fourteen-day drift run - loan-default@champion")
    ax1.legend(fontsize=8, loc="upper left")

    ax2.plot(report.day, report.flag_rate * 100, "o-", color="#5B9E5B", label="applicants flagged as likely defaulters")
    ax2.axhline(ref_flag_rate * 100, color="grey", ls=":", label=f"reference {ref_flag_rate:.0%}")
    ax2.axhspan(ref_flag_rate * 100 + FLAG_RATE_ALERT_POINTS, 100, color="#C00000", alpha=0.06)
    ax2.axhline(ref_flag_rate * 100 + FLAG_RATE_ALERT_POINTS, color="#C00000", ls="--",
                label=f"alert: +{FLAG_RATE_ALERT_POINTS} points")
    ax2.set_ylim(0, max(60, report.flag_rate.max() * 110))
    ax2.set_ylabel("% flagged (P(default) >= 0.5)")
    ax2.set_xlabel("Day")
    ax2.set_xticks(range(1, DAYS + 1))
    ax2.legend(fontsize=8, loc="upper left")
    fig.tight_layout()
    fig.savefig("drift_chart.png", dpi=150)
    print("Saved drift_chart.png and drift_report.csv")


if __name__ == "__main__":
    main()
