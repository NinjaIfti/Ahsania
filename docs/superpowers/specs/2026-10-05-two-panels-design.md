# Two Panels (Doctor + Admin) — Design

**Date:** 2026-10-05
**Status:** Approved in chat, for written review
**Changes:** `2026-10-04-data-capture-design.md` (M1–M3, merged at 82f882d). Where the two disagree, this document wins.

## Why

Doctors have no time for device setup, key custody or blurring names. The app becomes two panels: doctors capture and check records, and admins (the NSU team) approve them and manage accounts.

## Decisions

| Topic | Decision |
|---|---|
| Roles | `doctor` and `admin` only. `uploader`, `hospital_doctor` and `nsu_reviewer` are removed. |
| Login | Short ID (`username`, e.g. `dr.rahman`) + password. No email. |
| Accounts | Admins create accounts in the Admin panel. The first admin is created with `capture users create`. |
| Patient | The hospital patient ID, `RC` followed by digits (e.g. `RC12345`), is stored as typed: uppercased, whitespace removed. Anything else is refused ("Patient ID must be RC followed by numbers"). No device key, no study-code hash. |
| Photos | Accepted as taken. No blur step, no held-back (quarantine) check. NSU strips identifiers on its side. |
| Review | Doctor approves → admin approves. Admin can send back (comment required). |

**Ethics note:** storing real registration numbers and unblurred photos on the NSU server departs from the original spec (§1, S2, §4.1–4.2) and the MoU's de-identification rule. AMCGH and the ethics committee need to agree to this before real patient data is captured.

## Record states

```
processing ──▶ draft ──doctor approves──▶ pending_admin ──admin approves──▶ approved
                 ▲                              │                              │
                 └────── admin sends back ──────┘                              │
                 └──────────────── admin reopens (reason) ─────────────────────┘
```

- `processing`: the AI is reading the photos. When it finishes, the record becomes `draft` with pre-filled fields. If the AI fails, the record still becomes `draft`, as now.
- `quarantined`, `pending_doctor` and `pending_nsu` are removed.
- A doctor may approve a record they uploaded themselves.

| Action | Who | Rule |
|---|---|---|
| Create record | doctor | at least one photo |
| Edit fields | doctor | `draft` only |
| Approve (draft → pending_admin) | doctor | required fields filled, no red fields |
| Approve (pending_admin → approved) | admin | — |
| Send back (pending_admin → draft) | admin | comment required |
| Reopen (approved → draft) | admin | reason required (exists today) |
| Fill by hand now (processing → draft) | doctor | allowed at any time; no 2-minute wait |

Doctors see every record. Admins see every record and every value; the NSU-only hiding of values and AI answers is removed.

## Doctor panel

1. **Patient:** type the patient ID (`RC` + numbers).
2. **Form:** pick the template.
3. **Photos:** take or choose photos, optional crop.
4. **Upload:** two buttons, **Let the AI fill it** (record starts in `processing`) and **I'll fill it myself** (record is created directly as `draft`, `extraction_status = skipped`, no job queued).
5. **Record page:** photos beside the form, with the AI colours and source boxes as now. **Approve and send to admin** submits. A sent-back record shows the admin's comment at the top.

Home: **New capture**, my drafts, sent back to me, being read by the AI, waiting for admin.

## Admin panel

- **Waiting for admin:** the `pending_admin` queue. Open a record, then **Approve** or **Send back**.
- **All records:** a list with a status filter. Approved records can be reopened.
- **Accounts:** a list of name, ID, role and active flag. Create an account (name, ID, password, role). Deactivate or reactivate it, and set a new password. An admin cannot deactivate themself.

## Removed

- **Web:** the device key, Device setup page, `crypto/` (study code, fingerprint, key store), the Hide-names step, the Tesseract assets and their `postinstall` copy, the Re-upload page, held-back banners and the NSU queue.
- **Server:**
  - `routes_device`;
  - the `settings.expected_key_fingerprint` column and the clear-fingerprint endpoint;
  - `key_fingerprint` in the upload meta;
  - quarantine (the PHI net in the worker, release, reupload and housekeeping expiry);
  - the four-eyes check;
  - the NSU value-hiding in record detail and events.
- **Kept:** the AI worker, the eval golden set, `fill_by_hand`, the Phase 3 switch (API only) and reopen.

## Data

One new Alembic migration:
- `users.email` → `username` (String 64, unique), keeping existing rows. `users.institution` is dropped. Roles are mapped `uploader`/`hospital_doctor` → `doctor` and `nsu_reviewer` → `admin`.
- `patients.study_code` → `reg_no` (String 64), and likewise `records.study_code` → `reg_no`.
- `records.quarantine` and `settings.expected_key_fingerprint` are dropped. Records whose status is `quarantined` or `pending_doctor` become `draft`, and `pending_nsu` becomes `pending_admin`.

Dev server demo users (password `demo-pass-123`): `doctor` "Demo Doctor", `doctor2` "Demo Doctor Two", `admin` "Demo Admin".

## API changes

- `POST /auth/login` takes `username` instead of `email`.
- `POST /records` meta: `reg_no`, `template_key`, `client_upload_id`, and `fill_by_hand: bool` (true creates the record as `draft` and skips the AI).
- `GET /admin/users`, `POST /admin/users`, and `PATCH /admin/users/{id}` (`active`, `password`).
- Statuses and actions follow the tables above.

## Testing

- Delete the tests for removed features and update the rest to the new roles and states.
- New unit tests cover the state rules, the account endpoints (admin only, unique ID, password at least 10 characters as in the CLI, an admin cannot deactivate themself) and `fill_by_hand` on create.
- The Playwright story is rewritten as follows. Admin creates a doctor. That doctor uploads one AI-filled record and one by-hand record, and approves both. Admin sends one back. The doctor fixes and re-approves it. Admin approves both.
