"""Read every run of the loan-default experiment from MLflow and save a table and a comparison chart.

Usage:  MLFLOW_TRACKING_URI=http://127.0.0.1:5000 python compare_runs.py
Writes: experiment_results.md (table with run links) and experiment_comparison.png
"""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mlflow

TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://127.0.0.1:5000")
mlflow.set_tracking_uri(TRACKING_URI)
exp = mlflow.get_experiment_by_name("loan-default")
runs = mlflow.search_runs([exp.experiment_id], order_by=["metrics.recall DESC", "metrics.auc DESC"])

cols = ["tags.mlflow.runName", "tags.model_type", "metrics.recall", "metrics.precision", "metrics.auc", "metrics.f1", "run_id"]
table = runs[cols].rename(columns=lambda c: c.split(".")[-1]).rename(columns={"runName": "run"})

lines = ["| Run | Model type | Recall | Precision | AUC | F1 | Link |", "|---|---|---|---|---|---|---|"]
for r in table.itertuples():
    url = f"{TRACKING_URI}/#/experiments/{exp.experiment_id}/runs/{r.run_id}"
    lines.append(f"| {r.run} | {r.model_type} | {r.recall:.3f} | {r.precision:.3f} | {r.auc:.3f} | {r.f1:.3f} | [run]({url}) |")
open("experiment_results.md", "w").write("\n".join(lines) + "\n")
print("\n".join(lines))

fig, ax = plt.subplots(figsize=(11, 5))
x = range(len(table))
w = 0.27
for i, (metric, color) in enumerate([("recall", "#1F4E79"), ("precision", "#E07B39"), ("auc", "#5B9E5B")]):
    bars = ax.bar([p + (i - 1) * w for p in x], table[metric], w, label=metric.upper() if metric == "auc" else metric.capitalize(), color=color)
    ax.bar_label(bars, fmt="%.2f", fontsize=7, padding=1)
ax.set_xticks(list(x), [f"{r}\n({t.replace('_', ' ')})" for r, t in zip(table.run, table.model_type)], fontsize=8)
ax.set_ylim(0.5, 1.0)
ax.axhline(0.70, color="grey", ls="--", lw=0.8, label="precision floor 0.70")
ax.set_ylabel("Score on the same 1,000-applicant test set")
ax.set_title("loan-default experiment: 8 runs, 3 model types (threshold 0.5)")
ax.legend(loc="lower left", ncol=4, fontsize=8)
fig.tight_layout()
fig.savefig("experiment_comparison.png", dpi=150)
print("Saved experiment_comparison.png")
