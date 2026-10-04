# Capture server

FastAPI + PostgreSQL API for the AMCGH × NSU lung cancer data capture app.
Design: `../docs/superpowers/specs/2026-10-04-data-capture-design.md`.

## Develop

```bash
uv sync                                        # Python 3.12 + dependencies
uv run pytest                                  # tests (start their own PostgreSQL)
uv run python -m capture.devserver --reset     # API on http://127.0.0.1:8000, demo users
```

Demo users (password `demo-pass-123`): `uploader@amcgh.test`, `doctor@amcgh.test`,
`doctor2@amcgh.test`, `reviewer@nsu.test`, `admin@nsu.test`.

## Operate

Configuration comes from `CAPTURE_*` environment variables (see `capture/config.py`):
`CAPTURE_DATABASE_URL`, `CAPTURE_STORAGE_DIR`, `CAPTURE_COOKIE_SECURE` (keep `true` behind HTTPS),
`CAPTURE_EXTRACTION_ENABLED` (stays `false` until the M3 worker exists).

```bash
uv run alembic upgrade head                    # migrate
uv run capture templates load                  # add new templates / versions from ../templates
uv run capture users create EMAIL "Full Name" hospital_doctor
uv run capture users deactivate EMAIL
uv run uvicorn capture.api.app:create_app --factory --host 127.0.0.1 --port 8000
```
