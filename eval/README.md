# Extractor golden set

Synthetic documents with known values, used to measure the model's per-field accuracy (spec §1 S3, §11.3).
Every document is made up; no real patient appears.

    cd server
    uv run capture eval            # the model at CAPTURE_VLM_URL (needs the GPU server)
    uv run capture eval --stub     # checks the harness only (fixed answers, not a model)

Run it after every model or prompt change. S3 asks for at least 90 % field accuracy on typed documents.

## Layout

    golden/<template_key>/case-NN/page-1.jpg (more pages: page-2.jpg, ...)
    golden/<template_key>/case-NN/expected.json   {"style": "typed" | "handwritten", "values": {...}, "ignore": [...]}

`values` uses the form's value format (see `templates/<template_key>.yaml`). Fields listed in `ignore`
(for example `capture_source`, which can only be judged from the photo itself) are not scored.

## Adding cases

- Typed: extend `make_golden.py` and re-run it (`uv run --no-project --with pillow python eval/make_golden.py`).
- Handwritten (still to collect): staff write made-up values on blank AMCGH forms, black out nothing real,
  photograph them with the app's capture settings, and add a case folder with `"style": "handwritten"`.
