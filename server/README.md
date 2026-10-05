# Capture server

FastAPI + PostgreSQL API for the AMCGH × NSU lung cancer data capture app.
Design: `../docs/superpowers/specs/2026-10-04-data-capture-design.md`, changed by `2026-10-05-two-panels-design.md`
(two roles, doctor and admin).

## Develop

```bash
uv sync                                        # Python 3.12 + dependencies
uv run pytest                                  # tests (start their own PostgreSQL)
uv run python -m capture.devserver --reset     # API on http://127.0.0.1:8000, demo users
```

Demo logins (password `demo-pass-123`): `doctor`, `doctor2`, `admin`.

## Operate

Configuration comes from `CAPTURE_*` environment variables (see `capture/config.py`):
`CAPTURE_DATABASE_URL`, `CAPTURE_STORAGE_DIR`, `CAPTURE_COOKIE_SECURE` (keep `true` behind HTTPS),
`CAPTURE_EXTRACTION_ENABLED` (`true` once a worker runs, see below).

```bash
uv run alembic upgrade head                    # migrate
uv run capture templates load                  # add new templates / versions from ../templates
uv run capture users create ID "Full Name" admin       # the first admin; admins add the rest under Accounts
uv run capture users deactivate ID
uv run capture eval                            # model accuracy on ../eval/golden (needs CAPTURE_VLM_URL)
uv run uvicorn capture.api.app:create_app --factory --host 127.0.0.1 --port 8000
```

## AI worker

The worker reads each upload with PaddleOCR (CPU) and asks the self-hosted model (vLLM, OpenAI-compatible) to fill the form. Uploads made with "I'll fill it myself" skip it.

```bash
uv sync --extra ocr                                                    # PaddleOCR + PaddlePaddle; models download on first use
uv run --extra ocr python -m capture.devserver --reset --worker stub   # API + worker with a fixed-answer model
uv run --extra ocr pytest -m paddle                                    # the real-OCR test (left out of plain `uv run pytest`)
uv run --extra ocr python -m capture.worker                            # the worker process (API needs CAPTURE_EXTRACTION_ENABLED=true)
```

A plain `uv sync` removes the OCR extra again; `uv run` leaves it installed.

Use `--worker vlm` to send pages to the model at `CAPTURE_VLM_URL` (model name: `CAPTURE_VLM_MODEL`) instead of the stub. Fields below `CAPTURE_CONFIDENCE_THRESHOLD` (default 0.85) are shown amber. Keep `CAPTURE_OCR_ENABLE_MKLDNN=false` on Windows.
