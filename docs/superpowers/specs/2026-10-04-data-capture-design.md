# Photo-to-Form Data Capture — Design

**Project:** NSU Big-Matrix Lab × Ahsania Mission Cancer & General Hospital (AMCGH) — phased multimodal AI for lung cancer
**Date:** 2026-10-04
**Status:** Draft for review

---

## 1. Purpose

AMCGH staff must supply NSU with de-identified clinical data for the lung cancer project (see the MoU and research proposal). Typing reports into spreadsheets is slow and error-prone, and photos of paper documents carry patient identifiers that the MoU forbids sharing.

This system lets hospital staff **photograph a document or imaging film, have AI fill a structured form, review it, and submit it**. The result is a clean, de-identified, doubly verified dataset that NSU can export for model training.

### Success criteria

| # | Criterion | How measured |
|---|---|---|
| S1 | Uploader captures, reviews and submits a 1–2 page radiology report in **≤ 2 minutes** (median) | Pilot timing from `review_events` |
| S2 | **No patient identifier is ever visible to an NSU user** | Count of identifiers found by NSU reviewers during pilot = 0; quarantine hits are counted separately as "caught" |
| S3 | AI field accuracy on the golden set: **≥ 90 % for typed reports**; handwritten accuracy measured and reported | `extractor eval` against golden set |
| S4 | Every approved record has been confirmed by **one AMCGH doctor and one NSU reviewer** | Enforced by state machine; tested |
| S5 | Exports are reproducible | Manifest SHA-256 hashes match exported files |

### Non-goals

- Training or running the lung cancer models themselves.
- Integration with the hospital information system (HIS/PACS).
- A native iOS app (the web app works in iOS Safari; no wrapper is built).
- A web-based template editor (templates are YAML in the repo).
- Bangla-language UI in v1 (English UI; Bangla text in documents is still captured).

---

## 2. Decisions taken during brainstorming

| Topic | Decision |
|---|---|
| Inputs | Radiology reports, pathology/lab reports, handwritten treatment sheets, photos of X-ray/CT/MRI films, **and DICOM file upload** |
| Platform | One React web app (installable PWA) + a **Flutter WebView shell** for Android |
| OCR / extraction | **Self-hosted open model on the Big-Matrix Lab GPU**; no third-party AI service |
| Pipeline | **Hybrid**: vision-language model fills fields; PaddleOCR cross-checks and supplies source boxes |
| Patient linking | Hospital registration number → **keyed hash computed on the device**; NSU never sees the reg. no. or the key |
| Scope | All templates built now; **Phase 3 templates locked** behind an admin switch until the hospital approves Phase 3 |
| Review | **Uploader submits → AMCGH doctor approves → NSU reviewer approves** |
| Stack | **Python (FastAPI) + React**, PostgreSQL, files on NSU disk |
| Dates | Real imaging/document dates are **kept** (needed for scan pairing intervals); per-patient date shifting is available as a later option if the ethics committee requires it |

---

## 3. Architecture

```
 Hospital phone / PC                        NSU server(s)
┌──────────────────────────┐   HTTPS   ┌───────────────────────────┐
│ web/  React PWA          │──────────▶│ server/  API process      │
│  • camera capture        │  only     │  (FastAPI)                │
│  • redaction canvas      │  redacted │  • auth, roles            │
│    (Tesseract.js hints)  │  images + │  • records, templates     │
│  • reg-no → study code   │  study    │  • review workflow        │
│    (HMAC, WebCrypto)     │  code     │  • export                 │
│  • DICOM header scrub    │           │  PostgreSQL + file store  │
│    (dcmjs)               │           └────────────┬──────────────┘
│  • review / correct form │                        │ jobs table + shared storage
└──────────────────────────┘           ┌────────────▼──────────────┐
 android/  Flutter WebView shell       │ server/  worker process   │
  (camera + file permissions)          │  • PHI safety net         │
                                       │  • PaddleOCR (CPU)        │
                                       │  • calls vLLM (Qwen-VL)   │
                                       │  • cross-check + validate │
                                       └────────────┬──────────────┘
                                                    │ HTTP (OpenAI-compatible)
                                       ┌────────────▼──────────────┐
                                       │ vLLM server on GPU        │
                                       └───────────────────────────┘
```

### Units

| Unit | Responsibility | Depends on |
|---|---|---|
| `web/` | All UI; all privacy-critical client work (study code, redaction, DICOM scrub) | API only |
| `server/` API process | Single source of truth: users, sessions, templates, records, files, state machine, audit log, export | PostgreSQL, storage dir |
| `server/` worker process | Claims extraction jobs, runs PHI check, OCR, VLM call, cross-check, validation; writes results | PostgreSQL, storage dir, vLLM URL |
| vLLM | Serves the vision-language model over an OpenAI-compatible HTTP API | GPU |
| `android/` | Loads the web app URL; grants camera and file-chooser permissions | Web app URL |
| `templates/` | YAML form definitions | — |

The API and worker are **one Python package with two entry points** (`uvicorn server.api:app`, `python -m server.worker`). They share the form-schema and DB models but never call each other: they communicate only through the `jobs` table and shared storage. The API never loads a model; the worker never talks to browsers.

### Repository layout

```
web/                React + Vite + TypeScript
server/             Python package
  api/              FastAPI routers
  worker/           job loop, extraction pipeline
  formschema/       template YAML parsing + validation (shared)
  db/               SQLAlchemy models, Alembic migrations
  cli.py            `server templates load`, `server eval`, user bootstrap
templates/          *.yaml form templates
android/            Flutter WebView shell
deploy/             docker-compose.yml, Caddyfile, .env.example
eval/               golden-set documents (synthetic) + expected values
docs/
```

### Technology choices

- **Server:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 + Alembic, PostgreSQL 16, argon2-cffi, PaddleOCR (CPU by default), rapidfuzz, python-dateutil, pydicom (server-side DICOM metadata read), stream-zip.
- **Model serving:** vLLM, OpenAI-compatible API, structured (JSON-schema-guided) output, logprobs enabled. Default model: a Qwen-VL 7–8B instruct model; 4-bit AWQ variant if the GPU has < 24 GB. Configured via `VLM_URL` and `VLM_MODEL`.
- **Web:** React 18, Vite, TypeScript, React Router, TanStack Query, Tailwind CSS, react-konva (redaction boxes), Tesseract.js v5 (self-hosted worker + `eng` traineddata), dcmjs, vite-plugin-pwa.
- **Android:** Flutter + `flutter_inappwebview` (file chooser with camera capture, permission requests).
- **Deploy:** docker-compose with `postgres`, `api`, `worker`, `vllm`, `caddy` (TLS + serves the built web app + reverse-proxies `/api`). API and worker share one storage volume (same host; NFS if split later).

---

## 4. Capture flow (client side)

### 4.1 Device key setup (once per device, hospital only)

Only users with role `hospital_doctor` can open **Device setup**.

1. **First device ever:** "Generate key" creates a 256-bit random key and displays it as a Crockford base32 string (52 chars) for printing. The device posts the key **fingerprint** to the API; the API stores it as `settings.expected_key_fingerprint` **only if it is empty**.
2. **Other devices:** "Enter key" — the custodian types the printed key.
3. The key is imported with WebCrypto as a **non-extractable HMAC-SHA256 CryptoKey** and stored in IndexedDB. It is never sent to the server.
4. **Fingerprint** = `K-` + first 4 hex chars of `SHA-256("amcgh-fingerprint:" + key)`, e.g. `K-4F2A`. Shown on screen and sent with every upload. 16 bits reveal nothing about the key but catch typos.
5. Capture is blocked on a device with no key.

**Key custody procedure** (included in the deployment guide): the key is printed, sealed, and held by two named AMCGH custodians. If it is lost, new uploads can no longer be linked to existing patients. Clearing the expected fingerprint is an NSU admin action, logged, and only done at the hospital's written request.

### 4.2 Study code

```
normalized = uppercase(regno) with whitespace, '-', '/', '.' removed
study_code = "AMH-" + first 10 chars of CrockfordBase32( HMAC-SHA256(key, normalized) )
```

- `AMH-00123` and `amh 00123` → same code. Leading zeros are **kept** (they may be significant).
- 10 base32 chars = 50 bits, so collisions are negligible at this cohort size.
- The reg. no. is held only in component state and cleared after the code is computed. It is never persisted or transmitted.

### 4.3 Document capture wizard

1. **Patient** — enter reg. no. → study code shown (staff can read it back against the patient file).
2. **Form type** — choose a template. Phase 3 templates are shown greyed out with "Locked until Phase 3" while `phase3_enabled = false`.
3. **Photos** — `<input type="file" accept="image/*" capture="environment">` opens the native camera (best image quality; works in the WebView). Multiple pages allowed. Each page gets:
   - manual crop and 90° rotate;
   - **blur check**: variance of Laplacian on a downscaled greyscale copy; below threshold → warning "Photo looks blurry — retake?" (warning only, never a block).
4. **Redaction** — Tesseract.js runs **on the device** and proposes black boxes over any OCR line whose text starts with a label in the configurable list: `Name, Patient, Pt, Mobile, Mob, Phone, Cell, Contact, Address, Addr, Father, Husband, Guardian, S/O, D/O, W/O, Reg, Registration, ID, MRN, UHID, NID`. Staff can move, resize, add and delete boxes. Continue requires ticking **"All names and numbers are covered."** Redaction is burned in by drawing solid black rectangles on a canvas and re-encoding to JPEG (quality 0.85, long side ≤ 3000 px). Re-encoding strips EXIF, including GPS. The unredacted original exists only in memory and is discarded when the wizard closes.
5. **Upload** — sends the redacted JPEGs, study code, template key and key fingerprint. If the request fails, the **redacted** payload is stored in an IndexedDB outbox and retried with backoff; the home screen shows "N waiting to upload". Unredacted images are never written to the outbox.

The document date is **not** entered in the wizard: each template marks one date field as `document_date`. The AI pre-fills it, and it is required before submit (see §6).

### 4.4 DICOM upload (hospital PC)

1. Staff enter the reg. no. (study code computed as above), choose "DICOM series", and select a folder.
2. dcmjs parses each file and applies de-identification in the browser, following the DICOM PS3.15 Basic Application Confidentiality Profile with the *Retain Longitudinal Temporal Information* option:
   - `PatientName`, `PatientID` → study code;
   - `PatientBirthDate`, `InstitutionName`, `InstitutionAddress`, `ReferringPhysicianName`, `PerformingPhysicianName`, `OperatorsName`, `AccessionNumber`, `OtherPatientIDs` and all private tags → removed;
   - `PatientAge`, `PatientSex`, study/series dates → kept;
   - Study/Series/SOP Instance UIDs → `2.25.` + decimal of the first 128 bits of `HMAC(key, original UID)`. This is consistent across uploads, so series stay linked, and NSU cannot reverse it;
   - geometry tags kept untouched: `PixelSpacing`, `ImagerPixelSpacing`, `SliceThickness`, `ImagePositionPatient`, `ImageOrientationPatient`, `Rows`, `Columns`.
3. A thumbnail of each series (middle image) is shown for a visual check of burned-in text. Files with `BurnedInAnnotation = YES`, or modality `US`/`SC`/`OT`, are **held back** and listed for manual handling; they are not uploaded.
4. Files are grouped by (remapped) `SeriesInstanceUID`; each series becomes one record. Upload is one file per request with 3 retries, then `finalize`.

---

## 5. Extraction pipeline (worker)

Triggered when a document or film record is created. DICOM records never go through the worker: their fields are read from the headers by pydicom at finalize time, and `extraction_status = not_applicable`.

### 5.1 Job handling

- `jobs` rows are claimed with `SELECT … FOR UPDATE SKIP LOCKED`. A job locked for more than 10 minutes is reclaimable.
- Up to **3 attempts**. After the final failure, `record.extraction_status = failed`, `record.status = draft`, and the uploader fills the form by hand. The AI is a shortcut, never a blocker.

### 5.2 Steps

1. **PHI safety net.** PaddleOCR reads every page, and the text is checked for:
   - Bangladeshi mobile numbers: `(?:\+?88)?01[3-9]\d{8}` after collapsing spaces and dashes inside digit runs;
   - NID-length digit runs (10, 13 or 17 digits) not part of a decimal number;
   - email addresses;
   - a line matching the redaction label list followed by ≥ 3 alphabetic characters. Redacted areas are black, so text OCR'd after a label means it was left uncovered.

   On any hit: `record.status = quarantined`, the hit reasons and boxes are stored, and processing stops (see §7.4). This is a backstop; on-device redaction is the primary control.

2. **VLM extraction.** All pages go in one request to vLLM. The prompt contains the template's fields (key, label, type, unit, allowed options and synonyms, hint) and instructs: *return `null` for anything not present; do not infer*. `response_format` is a JSON schema generated from the template, so output always parses. `logprobs` is requested.

3. **Per-field confidence.** For each leaf value, the character span in the output is mapped to its tokens. Confidence = geometric mean of those tokens' probabilities.

4. **Cross-check against OCR.** Each non-null value is normalized and searched in the PaddleOCR lines:
   - *numbers:* numeric equality after unit conversion for length (`mm` ↔ `cm`) and tolerant formatting (`2.3`, `2.30`, `2·3`);
   - *dates:* OCR dates parsed with `dayfirst=True` (Bangladesh uses DD/MM/YYYY);
   - *enum:* the option value or any of its template synonyms;
   - *text:* `rapidfuzz.partial_ratio ≥ 85`.

   On a match, the page number and bounding box(es) are stored.

5. **Template validation.** Required fields, `min`/`max`, enum membership, and dates not in the future.

6. **Field colour**, stored with the result:

| Colour | Rule |
|---|---|
| 🔴 red | fails validation |
| 🟡 amber | confidence < `CONFIDENCE_THRESHOLD` (default 0.85) **or** no OCR match |
| 🟢 green | matched and confident |
| ⚪ grey | empty |

7. Write `record.extraction` and pre-fill `record.values`; set `status = draft`, `extraction_status = done`.

### 5.3 Film photos

The VLM reads only the text burned into the film (date, view, side marker). The image itself is the training asset. The same safety net applies, because films carry printed names.

### 5.4 Performance target

Filled fields are shown **within ~30 s** of upload for a 1–2 page report on a single GPU. The browser polls `GET /api/records/{id}` every 3 s while `status = processing`.

---

## 6. Form templates

### 6.1 Format

```yaml
key: radiology_report
version: 1
phase: 1
kind: document            # document | film_photo | dicom
title: Radiology report (CT / MRI / X-ray / PET-CT)
fields:
  - {key: modality, type: enum, required: true, options: [CT, MRI, X-ray, PET-CT]}
  - {key: study_date, type: date, required: true, document_date: true}
  - key: lesions
    type: group
    repeat: true
    fields:
      - key: lobe
        type: enum
        options:
          - {value: RUL, synonyms: ["right upper lobe", "rt upper lobe"]}
          - {value: RML, synonyms: ["right middle lobe", "rt middle lobe"]}
          - {value: RLL, synonyms: ["right lower lobe", "rt lower lobe"]}
          - {value: LUL, synonyms: ["left upper lobe", "lt upper lobe"]}
          - {value: LLL, synonyms: ["left lower lobe", "lt lower lobe"]}
          - {value: other}
      - {key: long_axis_cm, type: number, unit: cm, min: 0.1, max: 20}
      - {key: short_axis_cm, type: number, unit: cm, min: 0.1, max: 20}
      - {key: description, type: text, hint: "e.g. spiculated, cavitating, ground-glass"}
```

- **Field types:** `text`, `number` (with optional `unit`, `min`, `max`), `date`, `enum` (options with optional `synonyms`), `boolean`, `group` (optionally `repeat: true`). `source: dicom` marks read-only fields filled from DICOM headers.
- Exactly one field per template has `document_date: true`. It is required before submit and orders the patient timeline.
- `server templates load` upserts templates from `templates/*.yaml`. Changing a template's fields requires bumping `version`; the loader refuses a changed definition with an unchanged version. Records keep the template version they were created with.

### 6.2 Initial templates (draft field lists — to be reviewed by AMCGH clinicians, see §12)

**Phase 1–2 (enabled)**

| Template | kind | Fields |
|---|---|---|
| `radiology_report` | document | modality; study_date*; contrast (bool); lesions[] {lobe, long_axis_cm, short_axis_cm, description}; lymph_nodes (text); metastasis_sites (text); pleural_effusion {none, left, right, bilateral}; reported_change {new, increased, decreased, stable, not stated}; impression (text) |
| `xray_film_photo` | film_photo | study_date*; view {PA, AP, lateral, other}; side_marker {L, R, none visible}; capture_source {lightbox film, monitor screen, printout} |
| `ct_mri_film_photo` | film_photo | modality {CT, MRI}; study_date*; window {lung, mediastinal, other, unknown}; slice_label (text); capture_source |
| `dicom_series` | dicom | modality, study_date*, body_part, series_description, pixel_spacing, slice_thickness, image_count, rows, columns — all `source: dicom` |

**Phase 3 (locked until `phase3_enabled = true`)**

| Template | kind | Fields |
|---|---|---|
| `pathology_molecular_report` | document | report_date*; specimen {biopsy, resection, cytology, other}; histological_subtype {adenocarcinoma, squamous cell, small cell, large cell, NSCLC-NOS, other}; grade {G1, G2, G3, G4, not stated}; egfr {mutated, wild-type, not tested} + egfr_variant; alk {rearranged, not rearranged, not tested}; ros1 (same); kras {mutated, wild-type, not tested} + kras_variant (e.g. G12C); pdl1_tps_percent (0–100); pdl1_assay (text) |
| `lab_report` | document | report_date*; results[] {analyte {CEA, LDH, Albumin, Hemoglobin, WBC, Platelets, Neutrophils, Lymphocytes, Other}, other_name, value, unit_as_printed, reference_range} |
| `treatment_sheet` | document | sheet_date*; treatments[] {modality {chemotherapy, immunotherapy, targeted, radiotherapy, surgery}, regimen_drugs, cycle_number, dose, dose_modified (bool), dose_modification_reason, start_date}; response {CR, PR, SD, PD, not assessed}; adverse_events[] {event, ctcae_grade {1–5}} |
| `clinical_summary` | document | summary_date*; age_years; sex {male, female}; smoking_status {never, former, current, unknown}; pack_years; ecog {0–4}; comorbidities; presenting_symptoms |
| `outcome_followup` | document | followup_date*; vital_status {alive, dead, lost to follow-up}; progression (bool) + progression_date; recurrence (bool) + recurrence_date; date_of_death |

`*` = the `document_date` field. **No date of birth anywhere; age only.**

---

## 7. Data model (PostgreSQL)

| Table | Columns (key ones) |
|---|---|
| `users` | id, name, email (unique), password_hash (argon2), role `uploader / hospital_doctor / nsu_reviewer / admin`, institution `AMCGH / NSU`, active, failed_logins, locked_until |
| `sessions` | id (random 256-bit), user_id, created_at, expires_at, revoked |
| `settings` | singleton: expected_key_fingerprint, phase3_enabled |
| `patients` | study_code (PK), first_seen_at |
| `templates` | id, key, version, phase, kind, title, definition (JSONB), loaded_at; unique (key, version) |
| `records` | id, study_code (FK), template_id (FK), status, extraction_status `pending / done / failed / not_applicable`, values (JSONB), extraction (JSONB: per-field value, confidence, colour, source boxes), document_date (denormalized from values), quarantine (JSONB: reasons, boxes), row_version (int, optimistic locking), created_by, created_at, updated_at |
| `record_files` | id, record_id, kind `page / dicom`, path, sha256, size, page_no, dicom_meta (JSONB) |
| `jobs` | id, kind `extract`, record_id, status `queued / running / done / failed`, attempts, last_error, locked_at, locked_by |
| `review_events` | id, record_id, actor_id, action `upload / submit / edit / approve / return / reopen / quarantine / release / reupload`, comment, field_changes (JSONB: path, old, new), field_flags (JSONB), created_at — **append-only** |

**Storage layout**

```
storage/records/<study_code>/<record_id>/page-<n>.jpg
storage/records/<study_code>/<record_id>/dicom/<sop_uid>.dcm
storage/quarantine/<record_id>/page-<n>.jpg
```

Files are stored outside any web-served directory and are served only through the API.

---

## 8. Review workflow

### 8.1 State machine

```
processing ──▶ quarantined ──(re-redact + re-upload)──▶ processing
    │               └──(hospital_doctor "release": false alarm)──▶ processing (skips safety net)
    ▼
  draft ──submit──▶ pending_doctor ──approve──▶ pending_nsu ──approve──▶ approved
    ▲                    │                           │                     │
    └──── return ────────┴───────── return ──────────┘                     │
    └──────────────────────────── reopen (admin, reason) ──────────────────┘
```

| Transition | Who | Rule |
|---|---|---|
| submit | uploader, hospital_doctor | all `required` fields filled; no 🔴 fields |
| approve (doctor) | hospital_doctor | **not the record's creator** (four-eyes) |
| approve (NSU) | nsu_reviewer | — |
| return | hospital_doctor from `pending_doctor`; nsu_reviewer from `pending_nsu` | comment required; optional per-field flags; goes back to `draft`. After an NSU return the record must pass the doctor again |
| reopen | admin | reason required; record leaves exports until re-approved |
| release quarantine | hospital_doctor | comment required; re-runs extraction without the safety net |
| re-upload after quarantine | uploader, hospital_doctor | new redacted pages replace the old ones; quarantined files are deleted |

Quarantined files not resolved within **14 days** are deleted automatically, and the record is marked `quarantined` with "files expired" so the upload can be repeated.

### 8.2 Permissions

| Action | uploader | hospital_doctor | nsu_reviewer | admin |
|---|---|---|---|---|
| Create records / capture | ✔ | ✔ | — | — |
| Device key setup | — | ✔ | — | — |
| See `processing`, `draft`, `pending_doctor` | ✔ | ✔ | — | — |
| See `quarantined` records and files | ✔ | ✔ | — | — |
| See `pending_nsu`, `approved` | ✔ | ✔ | ✔ | ✔ |
| Edit field values | `draft` only | `draft`, `pending_doctor` | — | — |
| Patient timeline | ✔ | ✔ | ✔ (non-quarantined) | ✔ (non-quarantined) |
| Export | — | — | ✔ | ✔ |
| Users, settings, Phase 3 switch, reopen | — | — | — | ✔ |

Every edit is written to `review_events.field_changes` (old → new). Edits use `row_version`, and a stale version returns 409.

### 8.3 Screens

1. **Login.**
2. **Home** — "New capture" (large), outbox count, my drafts, returned records (badge).
3. **Capture wizard** — §4.3 / §4.4.
4. **Record review** — page images (zoom and pan) beside the form; on phones, images above the form and collapsible. Tapping a field highlights its source box. Colours from §5.2. Return comments and flagged fields are shown at the top. Action buttons depend on role and status.
5. **Queues** — doctor queue (`pending_doctor`), NSU queue (`pending_nsu`). Columns: study code, template, document date, uploaded by, 🟡/🔴 counts, age in queue.
6. **Patient timeline** — all records for a study code ordered by document date, with a pairing indicator: has baseline CT/MRI ✔/✘, number of follow-up X-rays, days between.
7. **Admin** — users, Phase 3 switch, expected key fingerprint (view / clear), extraction queue length and failures, export.

---

## 9. API (outline)

```
POST   /api/auth/login              POST /api/auth/logout          GET /api/me
GET    /api/templates               (active versions; `locked` flag for Phase 3)
POST   /api/records                 multipart: meta + redacted pages → record (processing)
POST   /api/records/dicom           create DICOM series record (study code, series meta)
POST   /api/records/{id}/files      add one de-identified DICOM file
POST   /api/records/{id}/finalize   close DICOM upload, read headers, → draft
GET    /api/records?status=&study_code=&template=
GET    /api/records/{id}
PATCH  /api/records/{id}/values     {row_version, values}
POST   /api/records/{id}/transition {action, comment?, field_flags?}
POST   /api/records/{id}/reupload   multipart: replacement redacted pages (quarantine only)
GET    /api/files/{file_id}         role- and status-checked file stream
GET    /api/patients/{study_code}/timeline
POST   /api/device/fingerprint      first-time set of expected fingerprint (hospital_doctor)
GET/PUT /api/admin/settings         GET/POST/PATCH /api/admin/users
GET    /api/export                  streams ZIP of approved records
```

Every upload carries the key fingerprint. A mismatch with `settings.expected_key_fingerprint` returns 409 *"This device's key doesn't match — ask your hospital admin."* Creating a record from a locked Phase 3 template returns 403. Switching Phase 3 off again only blocks new Phase 3 records; existing ones are unaffected.

---

## 10. Export

`GET /api/export` (nsu_reviewer, admin) streams a ZIP containing **approved records only**:

```
export-<timestamp>/
  manifest.json            template versions, record count, SHA-256 of every file below
  <template_key>.csv       one row per record (flattened scalar fields)
  <template_key>__<group>.csv   one row per repeat-group item, keyed by record_id
  records.json             all records, full nested values
  pairing_report.csv       study_code, baseline CT/MRI date, follow-up X-ray dates, interval days
  files/<study_code>/<record_id>/...   pages and DICOM files
```

---

## 11. Security, errors, testing

### 11.1 Security

- HTTPS only via Caddy; HSTS on.
- Passwords stored with argon2id. Login is rate-limited; 5 failures lock the account for 15 minutes. Sessions are server-side; the cookie is `HttpOnly`, `Secure`, `SameSite=Strict`, with a 12-hour expiry. Deactivating a user revokes their sessions.
- Every route is deny-by-default with an explicit role and status check; tests cover every route (§11.3).
- The app's DB role has **no UPDATE/DELETE grant on `review_events`**.
- **No third-party scripts, fonts or CDNs** in the web app. Tesseract.js, its worker and its traineddata are served from our origin. A strict Content-Security-Policy (`default-src 'self'`) is set.
- Recommended for operations: full-disk encryption on the storage volume, plus nightly encrypted backups (pg_dump + storage) to a second disk.

### 11.2 Error handling

| Situation | Behaviour |
|---|---|
| Network failure during upload | Redacted payload kept in the IndexedDB outbox, retried with backoff; home shows count |
| Worker or vLLM down | Records stay `processing`; after 2 minutes the UI offers "Fill by hand now"; admin sees queue length |
| Extraction fails 3× | `extraction_status = failed`, record → `draft` for manual entry |
| Duplicate photo | Same SHA-256 already exists for this study code → warning with link to the existing record (upload still allowed) |
| Key fingerprint mismatch | 409 with a clear message; nothing stored |
| Concurrent edits | `row_version` mismatch → 409 "Someone else changed this record — reload" |
| Locked template | 403 "Locked until Phase 3" |

### 11.3 Testing

- **Server (pytest):**
  - every state transition × every role (allowed and forbidden);
  - the four-eyes rule;
  - a quarantined record and its files return 404 to NSU roles;
  - export contains only approved records, and manifest hashes match;
  - template version immutability;
  - fingerprint mismatch;
  - optimistic locking;
  - PHI safety-net patterns (phone, NID, email, label + text) with positive and negative cases;
  - cross-check matching (units, day-first dates, synonyms).
- **Web (Vitest):**
  - study-code HMAC against fixed test vectors, including normalization cases;
  - fingerprint derivation;
  - DICOM scrub on a sample file: listed tags removed, geometry tags kept, UIDs remapped consistently;
  - redaction re-encode produces no EXIF.
- **End-to-end (Playwright):** capture → submit → doctor approve → NSU approve → export, with a **stub extractor** returning fixed fields; plus quarantine → re-upload.
- **Extractor golden set (`server eval`):** 20–30 **synthetic** documents (typed and handwritten, made-up patients) with expected values, reporting per-field accuracy for each template. Run on every model change.
- **Android shell:** manual checklist on 2–3 real phones covering camera capture, multi-page, file chooser, upload, and back-button behaviour.
- **Pilot:** 1–2 weeks at AMCGH with about 20 patients before full rollout, measuring S1–S3.

---

## 12. Open items (owner)

1. **Clinical review of the §6.2 field lists** — AMCGH (Dr. Nusrat / Prof. Alam's team) — before the pilot.
2. **GPU specification** of the Big-Matrix Lab server, which decides between full and 4-bit model — NSU.
3. **Ethics committee confirmation** of (a) keeping real dates and (b) the on-device redaction + quarantine approach — AMCGH Ethics Review Committee.
4. **Public HTTPS hostname** for the NSU server — NSU IT.
5. **Sample registration-number formats**, to confirm the normalization rules in §4.2 — AMCGH.

---

## 13. Build order (input to the implementation plan)

Each milestone leaves a working system.

| M | Deliverable | Usable result |
|---|---|---|
| M1 | Server skeleton: auth, roles, sessions, templates loader, records, files, state machine, audit log, tests | API-complete workflow, tested |
| M2 | Web: login, device setup, study code, capture wizard (photo, crop, blur, redaction, outbox), review screen with **manual** entry, queues | Full capture-and-approve flow **without AI** |
| M3 | Worker: job loop, PHI safety net, PaddleOCR, vLLM extraction, cross-check, colours, golden-set eval | AI pre-fill and source highlighting |
| M4 | Patient timeline, admin screens, export | NSU can pull a dataset |
| M5 | DICOM path (browser scrub, upload, header fields) | CT/X-ray DICOM collection for Phases 1–2 |
| M6 | Flutter WebView shell, deployment (docker-compose, Caddy), key custody guide, pilot | Pilot at AMCGH |

The implementation plan should cover **M1–M2 first**, with later milestones planned once those are reviewed.
