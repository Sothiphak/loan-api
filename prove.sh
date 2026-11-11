#!/usr/bin/env bash
# Collects the evidence for CHECKLIST.md (Lesson 4.6 checklist). Run from the loan-api folder:
#   bash prove.sh 2>&1 | tee evidence.txt
IMAGE=loan-api:1.0.0
run() { echo; echo "\$ $*"; eval "$@"; }

echo "=============== 1. Slim base image ==============="
run "grep -n '^FROM' Dockerfile.prod"
run "docker images $IMAGE --format 'table {{.Repository}}:{{.Tag}}\t{{.Size}}'"
run "docker images loan-api-dev --format 'table {{.Repository}}:{{.Tag}}\t{{.Size}}'"

echo; echo "=============== 2. Multi-stage build ==============="
run "grep -n -E '^FROM|COPY --from' Dockerfile.prod"
run "docker run --rm $IMAGE ls -la /app /app/models"
run "docker run --rm $IMAGE sh -c 'ls /app/train.py /app/tests 2>&1 || true'"

echo; echo "=============== 3. Separate dev dependencies ==============="
run "cat requirements.txt"
run "cat requirements-dev.txt"
run "docker run --rm $IMAGE sh -c 'pip list 2>/dev/null | grep -i \"^pytest\" || echo \"pytest: not installed in the production image\"'"
run "docker run --rm loan-api-dev sh -c 'pip list 2>/dev/null | grep -i \"^pytest\"'"

echo; echo "=============== 4. Run as a non-root user ==============="
run "grep -n -E 'useradd|^USER' Dockerfile.prod"
run "docker inspect --format 'User: {{.Config.User}}' $IMAGE"
run "docker run --rm $IMAGE id"

echo; echo "=============== 5. Pin versions ==============="
run "grep -n '^FROM' Dockerfile.prod"
run "grep -n '==' requirements.txt requirements-dev.txt"
run "docker run --rm $IMAGE python --version"

echo; echo "=============== 6. HEALTHCHECK ==============="
run "grep -n -A1 HEALTHCHECK Dockerfile.prod"
run "docker inspect --format '{{json .Config.Healthcheck}}' $IMAGE"
run "docker inspect --format 'Health: {{.State.Health.Status}}' loan-api-api-1"
run "docker compose ps"
run "curl -s http://localhost:8000/health"

echo; echo "=============== 7. Scan regularly (Trivy, HIGH and CRITICAL) ==============="
run "docker run --rm -v /var/run/docker.sock:/var/run/docker.sock aquasec/trivy:latest image --quiet --severity HIGH,CRITICAL $IMAGE"

echo; echo "=============== Extra: configurable MODEL_PATH ==============="
run "grep -n MODEL_PATH main.py Dockerfile.prod compose.yaml"
run "docker run --rm $IMAGE printenv MODEL_PATH"

echo; echo "=============== Extra: no secrets in the image or repository ==============="
run "docker history --no-trunc $IMAGE --format '{{.CreatedBy}}' | grep -i -E 'password|secret|token|api_key' || echo 'No secrets in image layers'"
run "docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' $IMAGE"
run "git grep -n -i -E 'password|secret|token|api_key' -- . ':!prove.sh' ':!CHECKLIST.md' || echo 'No matches'"

echo; echo "=============== Extra: prediction through Compose ==============="
run "curl -s -X POST http://localhost:8000/api/v1/predictions -H 'Content-Type: application/json' -d '{\"amount_usd\":1500,\"term_months\":12,\"monthly_income_usd\":350,\"previous_loans\":1,\"late_payments\":0}'"
echo
