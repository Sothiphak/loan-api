# Production Image Checklist — `loan-api:1.0.0`

Evidence for the seven production-image practices from Lesson 4.6, for the image built from
`Dockerfile.prod` (`compose.yaml` → `build: { context: ., dockerfile: Dockerfile.prod }`).
All commands were run on 11 Nov 2026 against the running Compose stack.

| # | Requirement | Status | Key evidence |
|---|---|---|---|
| 1 | Slim base image | ✅ | `python:3.12-slim`, final image **584 MB** (dev image 764 MB) |
| 2 | Multi-stage build | ✅ | `builder` stage + runtime stage; no `train.py`, no `tests/` in the image |
| 3 | Separate dev dependencies | ✅ | `pytest` only in `requirements-dev.txt`; not installed in the production image |
| 4 | Run as a non-root user | ✅ | `USER app`, `uid=999(app)` |
| 5 | Pin versions | ✅ | `python:3.12-slim` + every package pinned with `==` |
| 6 | HEALTHCHECK | ✅ | Calls `/health` every 30 s; container reports `healthy` |
| 7 | Scan regularly | ✅ | Trivy: **0 CRITICAL**, 47 HIGH in Debian base packages with no fix yet (2 fixed by rebuilding) |

---

## 1. Slim base image

Both stages start from the official slim Python image.

```console
$ grep -n '^FROM' Dockerfile.prod
4:FROM python:3.12-slim AS builder
17:FROM python:3.12-slim

$ docker images loan-api:1.0.0 --format 'table {{.Repository}}:{{.Tag}}\t{{.Size}}'
REPOSITORY:TAG   SIZE
loan-api:1.0.0   584MB

$ docker images loan-api-dev --format 'table {{.Repository}}:{{.Tag}}\t{{.Size}}'
REPOSITORY:TAG        SIZE
loan-api-dev:latest   764MB
```

The production image is **180 MB smaller** than the development image. A first version was 774 MB;
deleting the unused `tests/` folders and `__pycache__` that pandas, SciPy and scikit-learn ship
(in the builder stage) brought it down to 584 MB. Most of the remaining size is NumPy, SciPy,
pandas and scikit-learn, which the model needs.

## 2. Multi-stage build

Stage `builder` installs the packages into `/opt/venv` and trains the model. The runtime stage
copies only the virtual environment, the model file and the two files the API needs.

```console
$ grep -n -E '^FROM|COPY --from' Dockerfile.prod
4:FROM python:3.12-slim AS builder
17:FROM python:3.12-slim
28:COPY --from=builder /opt/venv /opt/venv
29:COPY --from=builder /build/models/model.joblib /app/models/model.joblib

$ docker run --rm loan-api:1.0.0 ls -la /app /app/models
/app:
-rw-r--r-- 1 root root 2143 Nov  9 08:29 main.py
drwxr-xr-x 2 root root 4096 Nov 11 15:14 models
-rw-r--r-- 1 root root  837 Nov 11 14:52 schemas.py

/app/models:
-rw-r--r-- 1 root root 1940 Nov 11 15:14 model.joblib

$ docker run --rm loan-api:1.0.0 sh -c 'ls /app/train.py /app/tests 2>&1 || true'
ls: cannot access '/app/train.py': No such file or directory
ls: cannot access '/app/tests': No such file or directory
```

The training code and the tests stay in the first stage; only what runs ships.

## 3. Separate dev dependencies

```console
$ cat requirements.txt
fastapi[standard]==0.150.0
scikit-learn==1.9.1
pandas==3.0.6
numpy==2.5.4
joblib==1.6.0

$ cat requirements-dev.txt
-r requirements.txt
pytest==9.1.1

$ docker run --rm loan-api:1.0.0 sh -c 'pip list 2>/dev/null | grep -i "^pytest" || echo "pytest: not installed in the production image"'
pytest: not installed in the production image

$ docker run --rm loan-api-dev sh -c 'pip list 2>/dev/null | grep -i "^pytest"'
pytest                                   9.1.1
```

`Dockerfile.prod` installs only `requirements.txt`; the development `Dockerfile` installs
`requirements-dev.txt`, so the tests still run there (`docker run --rm loan-api-dev pytest -q` → 5 passed).

## 4. Run as a non-root user

```console
$ grep -n -E 'useradd|^USER' Dockerfile.prod
26:RUN groupadd --system app && useradd --system --gid app --no-create-home app
31:USER app

$ docker inspect --format 'User: {{.Config.User}}' loan-api:1.0.0
User: app

$ docker run --rm loan-api:1.0.0 id
uid=999(app) gid=999(app) groups=999(app)
```

The application files are owned by `root` and only readable by `app`, so a compromised process
cannot modify the code, the model or system files.

## 5. Pin versions

```console
$ grep -n '^FROM' Dockerfile.prod
4:FROM python:3.12-slim AS builder
17:FROM python:3.12-slim

$ grep -n '==' requirements.txt requirements-dev.txt
requirements.txt:1:fastapi[standard]==0.150.0
requirements.txt:2:scikit-learn==1.9.1
requirements.txt:3:pandas==3.0.6
requirements.txt:4:numpy==2.5.4
requirements.txt:5:joblib==1.6.0
requirements-dev.txt:2:pytest==9.1.1

$ docker run --rm loan-api:1.0.0 python --version
Python 3.12.16
```

The published image is also tagged with a fixed version, `1.0.0`, besides `latest`.

## 6. HEALTHCHECK

```console
$ grep -n -A1 HEALTHCHECK Dockerfile.prod
33:HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
34-  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)" || exit 1

$ docker inspect --format '{{json .Config.Healthcheck}}' loan-api:1.0.0
{"Test":["CMD-SHELL","python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)\" || exit 1"],"Interval":30000000000,"Timeout":3000000000,"StartPeriod":15000000000,"Retries":3}

$ docker inspect --format 'Health: {{.State.Health.Status}}' loan-api-api-1
Health: healthy

$ docker compose ps
NAME             IMAGE                COMMAND                  SERVICE   STATUS                    PORTS
loan-api-api-1   loan-api:1.0.0       "uvicorn main:app --…"   api       Up 29 seconds (healthy)   0.0.0.0:8000->8000/tcp
loan-api-db-1    postgres:17-alpine   "docker-entrypoint.s…"   db        Up 5 minutes (healthy)    5432/tcp

$ curl -s http://localhost:8000/health
{"status":"ok","model_version":"1.0.0"}
```

The check uses Python's standard library, so no extra tool (such as `curl`) is installed in the image.

## 7. Scan regularly

```console
$ docker run --rm -v /var/run/docker.sock:/var/run/docker.sock aquasec/trivy:latest image --quiet --severity HIGH,CRITICAL loan-api:1.0.0

loan-api:1.0.0 (debian 13.7)
============================
Total: 47 (HIGH: 47, CRITICAL: 0)
```

- **Python packages:** all 63 scanned packages in `/opt/venv` (FastAPI, scikit-learn, pandas, NumPy, SciPy, …) — **0 vulnerabilities**.
- **CRITICAL:** **0**.
- **HIGH:** 47, all in Debian system packages that come with the `python:3.12-slim` base image.

### Notes on the HIGH findings

**Rebuilt and fixed (2 findings).** The first scan reported 49 HIGH. `zlib1g` had a fixed version
available (`1:1.3.dfsg+really1.3.1-1+deb13u1`) for **CVE-2026-76844** and **CVE-2026-85091**.
I added `apt-get update && apt-get upgrade -y` to the runtime stage, rebuilt, and rescanned: both are gone.

**Cannot be fixed yet (47 findings).** For every remaining finding Trivy shows **no fixed version**
(status `affected`, or `fix_deferred` for Perl): Debian has not released a patched package, so neither
upgrading nor rebuilding can remove them today. They are grouped by CVE below.

| CVE | Packages (findings) | Why it cannot be fixed yet / risk for this API |
|---|---|---|
| CVE-2026-76642, CVE-2026-78408, CVE-2026-78409, CVE-2026-78410 (util-linux) | bsdutils, libblkid1, liblastlog2-2, libmount1, libsmartcols1, libuuid1, login, mount, util-linux (36) | No Debian fix yet. The bugs are in `mount` / `nsenter` and need mount privileges; the API runs as the non-root user `app` and never calls these tools. These packages are essential to the base image and cannot be removed. |
| CVE-2025-69720 (ncurses) | libncursesw6, libtinfo6, ncurses-base, ncurses-bin (4) | No Debian fix yet. Terminal-drawing library; the API serves HTTP only and never draws to a terminal. |
| CVE-2026-119373, CVE-2026-119374, CVE-2026-119379 (SQLite) | libsqlite3-0 (3) | No Debian fix yet. Requires a crafted FTS5 index or session changeset; the API does not use SQLite (data is kept in memory / PostgreSQL). |
| CVE-2026-16742 (systemd-homed) | libsystemd0, libudev1 (2) | No Debian fix yet. Affects the `systemd-homed` service, which does not run inside the container. |
| CVE-2026-54369 (acl) | libacl1 (1) | No Debian fix yet. Local privilege escalation through symlinks; the container user cannot write to the application or system directories. |
| CVE-2026-9538 (Perl Archive::Tar) | perl-base (1) | Debian marked it `fix_deferred`. Needs a crafted tar file processed by Perl; the API never runs Perl or opens tar files. |

**Plan:** rescan with Trivy on every release (and at least weekly), and rebuild with
`docker compose build --pull` as soon as Debian publishes fixes, then push a new patch version.

---

## Extra: configurable `MODEL_PATH`

```console
$ grep -n MODEL_PATH main.py Dockerfile.prod compose.yaml
main.py:11:MODEL_PATH = os.getenv("MODEL_PATH", "model.joblib")  # where the trained model file lives
main.py:18:    ml.update(joblib.load(MODEL_PATH))  # load the model once, when the server starts
Dockerfile.prod:21:    MODEL_PATH=/app/models/model.joblib
compose.yaml:10:      MODEL_PATH: /app/models/model.joblib

$ docker run --rm loan-api:1.0.0 printenv MODEL_PATH
/app/models/model.joblib
```

The model is trained during the build and stored inside the image, so the published image runs
without any local files.

## Extra: no secrets in the image or the repository

```console
$ docker history --no-trunc loan-api:1.0.0 --format '{{.CreatedBy}}' | grep -i -E 'password|secret|token|api_key' || echo 'No secrets in image layers'
No secrets in image layers

$ docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' loan-api:1.0.0
PATH=/opt/venv/bin:/usr/local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
LANG=C.UTF-8
GPG_KEY=7169605F62C751356D054A26A821E680E5FA6305
PYTHON_VERSION=3.12.16
PYTHON_SHA256=b5796915dc45ff745cfb4e990a7e7c93d6f546328a102ce31448d69ebc37575c
PYTHONDONTWRITEBYTECODE=1
PYTHONUNBUFFERED=1
MODEL_PATH=/app/models/model.joblib

$ git grep -n -i -E 'password|secret|token|api_key' -- . ':!prove.sh' ':!CHECKLIST.md' || echo 'No matches'
.dockerignore:1:# Keep the build context small and free of secrets
compose.yaml:11:      DATABASE_URL: postgresql://loan:loan_dev_password@db:5432/loans
compose.yaml:21:      POSTGRES_PASSWORD: loan_dev_password   # development only, never used in production
```

- The image contains no secrets. `GPG_KEY` is the **public** key ID that the official Python
  image uses to verify the Python download; it is not a secret.
- The only password in the repository is the **development-only** PostgreSQL password in
  `compose.yaml` (the allowed exception). It is not baked into the image: the `DATABASE_URL`
  is passed at run time by Compose.
- `.dockerignore` keeps `.git`, `.env` files, the virtual environment and local model files out of the build context.

## Extra: a prediction through Compose

```console
$ curl -s -X POST http://localhost:8000/api/v1/predictions -H 'Content-Type: application/json' \
    -d '{"amount_usd":1500,"term_months":12,"monthly_income_usd":350,"previous_loans":1,"late_payments":0}'
{"default_probability":0.095,"risk_band":"low","model_version":"1.0.0"}
```

The full raw output of every command is in `evidence.txt`, produced by `bash prove.sh 2>&1 | tee evidence.txt`.
