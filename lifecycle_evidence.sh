#!/usr/bin/env bash
# Evidence for deliverables 4-7. Needs: tracking server (5000), scoring server (5001), FastAPI (8000).
# Run from the loan-api folder with the venv active:
#   bash lifecycle_evidence.sh 2>&1 | tee lifecycle_evidence.txt
export MLFLOW_TRACKING_URI=${MLFLOW_TRACKING_URI:-http://127.0.0.1:5000}
export MLFLOW_DISABLE_AGENT_HINT=1 PYTHONWARNINGS=ignore
APPLICANT='{"amount_usd":1500,"term_months":12,"monthly_income_usd":350.0,"previous_loans":1,"late_payments":0}'
run() { echo; echo "\$ $*"; eval "$@"; echo; }
wait_api() { for i in $(seq 1 60); do curl -s localhost:8000/health >/dev/null && return; sleep 1; done; echo "FastAPI not reachable on :8000"; }

echo "=============== 4. MLflow scoring server (port 5001) ==============="
run "curl -s -w '\nHTTP %{http_code}\n' http://127.0.0.1:5001/ping"
run "curl -s -w '\nHTTP %{http_code}\n' -X POST http://127.0.0.1:5001/invocations -H 'Content-Type: application/json' -d '{\"dataframe_records\":[$APPLICANT]}'"
echo "--- signature rejection 1: text where an integer is expected"
run "curl -s -w '\nHTTP %{http_code}\n' -X POST http://127.0.0.1:5001/invocations -H 'Content-Type: application/json' -d '{\"dataframe_records\":[{\"amount_usd\":\"lots\",\"term_months\":12,\"monthly_income_usd\":350.0,\"previous_loans\":1,\"late_payments\":0}]}'"
echo "--- signature rejection 2: a required column is missing"
run "curl -s -w '\nHTTP %{http_code}\n' -X POST http://127.0.0.1:5001/invocations -H 'Content-Type: application/json' -d '{\"dataframe_records\":[{\"amount_usd\":1500,\"term_months\":12,\"previous_loans\":1,\"late_payments\":0}]}'"

echo "=============== 5. FastAPI loads @champion; same probability as MLflow ==============="
run "grep -n 'MODEL_URI' main.py"
run "curl -s http://127.0.0.1:8000/health"
run "curl -s -X POST http://127.0.0.1:8000/api/v1/predictions -H 'Content-Type: application/json' -d '$APPLICANT'"
echo "--- comparison (same applicant):"
MLF=$(curl -s -X POST http://127.0.0.1:5001/invocations -H 'Content-Type: application/json' -d "{\"dataframe_records\":[$APPLICANT]}" | python -c 'import sys,json; print(round(json.load(sys.stdin)["predictions"][0][1], 3))')
API=$(curl -s -X POST http://127.0.0.1:8000/api/v1/predictions -H 'Content-Type: application/json' -d "$APPLICANT" | python -c 'import sys,json; print(json.load(sys.stdin)["default_probability"])')
echo "MLflow scoring server P(default) = $MLF"
echo "FastAPI default_probability     = $API"
[ "$MLF" = "$API" ] && echo "MATCH" || echo "DIFFERENT"

echo; echo "=============== 6. Fourteen-day drift run ==============="
run "python monitor.py"

echo "=============== 7. Rollback ==============="
echo "--- BEFORE"
run "curl -s http://127.0.0.1:8000/health"
run "python set_champion.py 2"
read -r -p ">>> Now restart FastAPI (Ctrl+C in its terminal, then run it again), then press Enter here... " _ </dev/tty
wait_api
echo "--- AFTER ROLLBACK (champion -> version 2)"
run "curl -s http://127.0.0.1:8000/health"
run "curl -s -X POST http://127.0.0.1:8000/api/v1/predictions -H 'Content-Type: application/json' -d '$APPLICANT'"
run "python set_champion.py 1"
read -r -p ">>> Restart FastAPI again, then press Enter here... " _ </dev/tty
wait_api
echo "--- RESTORED (champion -> version 1)"
run "curl -s http://127.0.0.1:8000/health"
run "curl -s -X POST http://127.0.0.1:8000/api/v1/predictions -H 'Content-Type: application/json' -d '$APPLICANT'"
echo "Done."
