# Two Panels Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task (the user chose inline execution; no subagents). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The capture app becomes two panels. Doctors capture and approve records; admins approve them and manage accounts. The device key, the blur step and quarantine are removed.

**Architecture:** The server changes first: roles, states, rules and the migration (Task 1), then the account endpoints (Task 2). Then the web app (Tasks 3–4), and finally the end-to-end story (Task 5). Every task leaves the server suite, the web suite and tsc green and ends in a commit.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, PostgreSQL (pgserver), React 19, react-router 8, TanStack Query, vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-05-two-panels-design.md`

**Plan style:** this plan is short by the user's request ("keep it simple"). Steps name exact files, behaviours and test cases. Full code is given only where a detail is easy to get wrong.

## Global Constraints

- **Commit trailer:** every commit ends with exactly `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Execution:** work inline, with no subagents. After each task, commit and update `.superpowers/HANDOFF.md` under "Where things stand".
- **Commands:**
  - Server tests: `cd server && uv run pytest -q`. Paddle test: `uv run --extra ocr pytest -m paddle`. There is no system `python`.
  - Web: `cd web && npm test`, `npm run typecheck`, `npm run e2e`.
- **Roles:** exactly `doctor` and `admin`.
- **Statuses:** exactly `processing`, `draft`, `pending_admin`, `approved`.
- **Username:** `strip().lower()`. On create it must match `^[a-z0-9._-]{3,64}$`. Login looks it up case-insensitively.
- **Password:** at least 10 characters, the same rule as the CLI.
- **reg_no:** remove all whitespace, then uppercase. It must be 1–64 characters after that. It is never used in a file path.
- **Actions:** the doctor's approve keeps the action name `submit` (button "Approve and send to admin"). The admin's send-back keeps `return`.
- **Style:** match the surrounding code, with sparse comments and no new layers.

## Review Focus

1. **A reg. no. with `/` or `..` (e.g. `AMH/12/2024`)** must store the pages inside the storage directory. Pages go to `records/<record_id>/page-N.jpg`, so the reg. no. never reaches a path. Tested in Task 1.
2. **Reg. no. formatting:** `" amh 123 "` and `"AMH123"` are the same patient. An all-whitespace or 65-character reg. no. gets a 422, not a 500. Tested in Task 1.
3. **An outbox replay of a by-hand upload** (same `client_upload_id`) returns the same record and queues no job. Tested in Task 1.
4. **Admin deactivating themself** is refused. Deactivating someone else ends their sessions at once. Tested in Task 2.
5. **Old outbox items** in a browser's IndexedDB still carry `study_code`/`key_fingerprint` meta. They must be refused with a message and a Discard button, never retried forever. The server answers 422, which already counts as "fail" in `classifyStatus`. Tested in Task 3.

---

### Task 1: Server: two roles, new states, reg. no., no key and no quarantine

**Files:**
- Modify: `server/capture/db/models.py`, `workflow/rules.py`, `auth/login.py`, `api/schemas.py`, `api/convert.py`, `api/routes_auth.py`, `api/routes_records.py`, `api/routes_files.py`, `api/routes_admin.py`, `api/app.py`, `records/service.py`, `jobqueue.py`, `worker/process.py`, `worker/loop.py`, `storage.py`, `cli.py`, `devserver.py`
- Create: `server/migrations/versions/0004_two_panels.py`
- Delete: `server/capture/api/routes_device.py`, `server/capture/extraction/phi.py`, `server/tests/test_phi.py`, `server/tests/test_quarantine_api.py`
- Tests: update `tests/conftest.py`, `constants.py`, `test_rules.py`, `test_auth.py`, `test_route_auth.py`, `test_records_create.py`, `test_records_review.py`, `test_worker.py`, `test_jobqueue.py`, `test_settings_routes.py`, `test_schema.py`, `test_cli.py`, `test_devserver.py`, `test_storage.py`

**Interfaces:**
- Produces: `Role.DOCTOR`, `Role.ADMIN`, `Status.PENDING_ADMIN`, `User.username`, `Record.reg_no`, `Patient.reg_no`, `next_status(*, action, role, status, comment, has_errors) -> Status`, `can_edit(role, status) -> bool`, `normalize_reg_no(raw: str) -> str` (in `api/schemas.py`), `create_record(..., reg_no, template_key, client_upload_id, fill_by_hand, pages)`, `save_page(storage_dir, record_id, page_no, data)`. `UserOut` has `{id, name, username, role}`. `RecordSummary.reg_no` replaces `study_code`. `RecordDetail` loses `quarantine`.

- [ ] **Step 1: Rules first (TDD).** Rewrite `tests/test_rules.py` for the new table:
  - a doctor submits a valid draft → `pending_admin`; submitting with errors → 422;
  - an admin submitting → 403;
  - an admin approves `pending_admin` → `approved`; a doctor approving → 403;
  - an admin returns `pending_admin` with a comment → `draft`; without a comment → 422; a doctor returning → 403;
  - an admin reopens `approved` with a reason → `draft`;
  - a doctor's `fill_by_hand` on `processing` → `draft`, and from `draft` → 409;
  - `can_edit("doctor","draft")` is True; `can_edit` is False for `pending_admin`, and for admin on any status;
  - `release` → 422 "Unknown action". The `Action` enum drops `RELEASE`, so pydantic refuses it at the API.

  Run `uv run pytest tests/test_rules.py -q`. Expected: FAIL.
- [ ] **Step 2: Implement `rules.py`.** Remove `can_view`, `NSU_VISIBLE` and the four-eyes check.

```python
class Action(enum.StrEnum):
    SUBMIT = "submit"
    APPROVE = "approve"
    RETURN = "return"
    REOPEN = "reopen"
    FILL_BY_HAND = "fill_by_hand"


def can_edit(role: str, status: str) -> bool:
    return role == Role.DOCTOR and status == Status.DRAFT


def next_status(*, action: str, role: str, status: str, comment: str | None, has_errors: bool) -> Status:
    has_comment = bool(comment and comment.strip())
    if action == Action.SUBMIT:
        if role != Role.DOCTOR:
            raise TransitionError("Only a doctor can approve a draft", 403)
        if status != Status.DRAFT:
            raise TransitionError("Only drafts can be sent to the admin")
        if has_errors:
            raise TransitionError("Fix the highlighted fields before approving", 422)
        return Status.PENDING_ADMIN
    if action == Action.APPROVE:
        if role != Role.ADMIN:
            raise TransitionError("Only an admin can give the final approval", 403)
        if status != Status.PENDING_ADMIN:
            raise TransitionError("This record is not waiting for the admin")
        return Status.APPROVED
    if action == Action.RETURN:
        if role != Role.ADMIN:
            raise TransitionError("Only an admin can send a record back", 403)
        if status != Status.PENDING_ADMIN:
            raise TransitionError("This record is not waiting for the admin")
        if not has_comment:
            raise TransitionError("A comment is required when sending a record back", 422)
        return Status.DRAFT
    if action == Action.REOPEN:
        if role != Role.ADMIN:
            raise TransitionError("Only an admin can reopen records", 403)
        if status != Status.APPROVED:
            raise TransitionError("Only approved records can be reopened")
        if not has_comment:
            raise TransitionError("A reason is required to reopen a record", 422)
        return Status.DRAFT
    if action == Action.FILL_BY_HAND:
        if role != Role.DOCTOR:
            raise TransitionError("Only a doctor can fill in records", 403)
        if status != Status.PROCESSING:
            raise TransitionError("This record is not waiting for the AI")
        return Status.DRAFT
    raise TransitionError(f"Unknown action: {action}", 422)
```

  Run `uv run pytest tests/test_rules.py -q`. Expected: PASS.

- [ ] **Step 3: Models and migration.**
  - **`models.py`:**
    - `Role` becomes `DOCTOR = "doctor"`, `ADMIN = "admin"`.
    - `Status` drops `QUARANTINED`, `PENDING_DOCTOR` and `PENDING_NSU`, and adds `PENDING_ADMIN = "pending_admin"`.
    - Delete `HOSPITAL_ROLES` and `NSU_ROLES`.
    - `User`: `username: Mapped[str] = mapped_column(String(64), unique=True)`; `email` and `institution` are removed.
    - `AppSettings` loses `expected_key_fingerprint`.
    - `Patient.reg_no: String(64)`, the primary key.
    - `Record.reg_no` is an FK to `patients.reg_no`, with an index. `Record.quarantine` is removed.
    - `Job.skip_safety_net` is removed.
  - **`0004_two_panels.py`** (revision `"0004"`, down `"0003"`). Upgrade, in order:

```python
op.execute("UPDATE users SET role = 'doctor' WHERE role IN ('uploader', 'hospital_doctor')")
op.execute("UPDATE users SET role = 'admin' WHERE role = 'nsu_reviewer'")
op.alter_column("users", "email", new_column_name="username", type_=sa.String(64))
op.drop_column("users", "institution")
op.alter_column("patients", "study_code", new_column_name="reg_no", type_=sa.String(64))
op.alter_column("records", "study_code", new_column_name="reg_no", type_=sa.String(64))
op.execute("ALTER INDEX IF EXISTS ix_records_study_code RENAME TO ix_records_reg_no")
op.execute("UPDATE records SET status = 'draft' WHERE status IN ('quarantined', 'pending_doctor')")
op.execute("UPDATE records SET status = 'pending_admin' WHERE status = 'pending_nsu'")
op.drop_column("records", "quarantine")
op.drop_column("settings", "expected_key_fingerprint")
op.drop_column("jobs", "skip_safety_net")
```

  Downgrade reverses the column changes: rename back; re-add `institution` (server default `'AMCGH'`), `quarantine`, `expected_key_fingerprint` and `skip_safety_net` (server default false). It maps `doctor` → `hospital_doctor` and `pending_admin` → `pending_nsu`.
  - **`test_schema.py`:** assert `users.username` exists and `email` doesn't, `records.reg_no` exists, and `records.quarantine` and `settings.expected_key_fingerprint` are gone.
- [ ] **Step 4: Auth by username.**
  - `authenticate(db, username, password, now)` looks up `func.lower(User.username) == username.strip().lower()`. Its docstring says "unknown IDs".
  - `LoginIn.username`.
  - `UserOut {id, name, username, role}`.
  - The 401 detail becomes "Invalid ID or password".
  - Update `test_auth.py` and `test_route_auth.py`, adding a test that `" Dr.Test "` logs in as `dr.test`.
- [ ] **Step 5: Records.**
  - **`schemas.py`:**
    - Remove `FingerprintIn`/`Out`, `ReuploadMeta`, `STUDY_CODE_PATTERN`, `SettingsOut.expected_key_fingerprint` and `RecordDetail.quarantine`. `RecordSummary.study_code` becomes `reg_no`.
    - Add:

```python
def normalize_reg_no(raw: str) -> str:
    """Spec: stored as typed, uppercased, whitespace removed."""
    value = "".join(raw.split()).upper()
    if not 1 <= len(value) <= 64:
        raise ValueError("Registration number must be 1 to 64 characters")
    return value


class CreateMeta(BaseModel):
    reg_no: Annotated[str, AfterValidator(normalize_reg_no)]
    template_key: str
    client_upload_id: uuid.UUID
    fill_by_hand: bool = False
```

  - **`service.py`:**
    - Delete `_check_device_key`, `replace_pages` and the `can_view` filter in `duplicates_of`.
    - `create_record` takes `reg_no` and `fill_by_hand`. With `fill_by_hand`, set `status=DRAFT, extraction_status=SKIPPED` and queue no job; otherwise call `queue_extraction`.
    - `detail_for(db, record)` loses its `viewer_role` parameter.
  - **`convert.py`:** drop `hide_values`, `hide_change_values` and `_visible_changes`. Rename `study_code` to `reg_no` and drop `quarantine`.
  - **`routes_records.py`:**
    - `create` requires `Role.DOCTOR`, and `_load_visible` becomes `_load` (404 only when missing).
    - `list_records`: rename the `study_code` param to `reg_no` and remove the NSU filter.
    - `transition` loses the release, files-expired and 2-minute branches. `FILL_BY_HAND_AFTER` and the `reupload` route are removed.
  - **`routes_files.py`:** drop `can_view`.
  - **`routes_admin.py`:** drop `clear_fingerprint`.
  - **`app.py`:** drop `routes_device`.
  - **`storage.save_page(storage_dir, record_id, page_no, data)`** writes to `records/{record_id}/page-{page_no}.jpg`. The `suffix` parameter goes away.
  - **Tests:**
    - `conftest`: `make_user(role="doctor", username=None, ...)` and `login_as` posts `username`. Drop the `hospital_key` fixture. `upload(client, reg_no=REG_NO, fill_by_hand=False, ...)`. The `db` fixture's settings reset drops the fingerprint. `ai_uploader` becomes `ai_doctor`.
    - `constants`: `REG_NO = "AMH-00123"`; drop `FINGERPRINT` and `STUDY_CODE`.
    - Update `test_records_create.py` and `test_records_review.py` to the new roles and states, and add:
      - `" amh 123 "` and `"AMH123"` land on the same `patients` row;
      - an empty or 65-character reg. no. gets a 422;
      - reg. no. `"AMH/../x"` stores the page under `records/<record id>/`;
      - a `fill_by_hand=True` upload on the AI app is `draft`/`skipped` with no `jobs` row, and its replay returns 200 with the same id and still no job;
      - an admin cannot create a record (403);
      - an admin sees and approves a record a doctor submitted;
      - a doctor can submit their own upload.
    - `test_storage.py`: the new `save_page` signature.
- [ ] **Step 6: Worker.**
  - `process_job` drops the PHI check and `_quarantine`; its outcomes are `done|dropped|retry|failed`.
  - `ClaimedJob` and `queue_extraction` drop `skip_safety_net`.
  - `loop.py`: delete `expire_quarantined_files` and `QUARANTINE_KEEP`. `housekeeping` keeps only `fail_abandoned`, so drop its `settings` argument and update the caller.
  - Delete `extraction/phi.py` and `tests/test_phi.py`, and drop the quarantine cases from `test_worker.py` and `test_jobqueue.py`.
- [ ] **Step 7: CLI and dev server.**
  - `capture users create <username> <name> <role>` checks the username pattern and the 10-character password. `users deactivate <username>`.
  - `DEMO_USERS = [("doctor", "Demo Doctor", "doctor"), ("doctor2", "Demo Doctor Two", "doctor"), ("admin", "Demo Admin", "admin")]`.
  - Update `test_cli.py` and `test_devserver.py`.
- [ ] **Step 8: Run everything.** Run `cd server && uv run pytest -q`, then `uv run --extra ocr pytest -m paddle`. Expected: all pass. Then `grep -rn "study_code\|hospital_doctor\|nsu_reviewer\|uploader\|quarantin\|fingerprint\|PENDING_NSU" capture migrations/versions/0004_two_panels.py tests`. Expected: matches only inside the 0004 migration's SQL strings.
- [ ] **Step 9: Commit.** `feat(server): two roles (doctor, admin), reg. no. as-is, no device key or quarantine`

### Task 2: Server: admin account endpoints

**Files:**
- Modify: `server/capture/api/routes_admin.py`, `server/capture/api/schemas.py`
- Test: create `server/tests/test_admin_users.py`

**Interfaces:**
- Consumes: `Role`, `User.username`, `hash_password`, `revoke_all_for_user(db, user_id)`, `require_roles(Role.ADMIN)`.
- Produces:
  - `GET /api/admin/users` returns `list[AccountOut]`.
  - `POST /api/admin/users` returns 201 with an `AccountOut`.
  - `PATCH /api/admin/users/{id}` returns an `AccountOut`.
  - `AccountOut {id, name, username, role, active}`.
  - `AccountIn {name, username, password, role}`.
  - `AccountPatch {active: bool | None, password: str | None}`.

- [ ] **Step 1: Failing tests** in `test_admin_users.py`:
  - a doctor gets 403 on all three endpoints;
  - an admin lists users ordered by name;
  - creating `{"name":"Dr. Rahman","username":" Dr.Rahman ","password":"long-enough-1","role":"doctor"}` returns 201 with `username == "dr.rahman"`, and the new user can log in;
  - a duplicate username in any case → 409 "That ID is already taken";
  - username `"a b"` or `"x"` → 422;
  - a password of 9 characters → 422;
  - role `"uploader"` → 422;
  - PATCH `active=false` on another user → their existing client gets 401 on `/api/me`;
  - PATCH `active=false` on self → 422 "You cannot deactivate your own account";
  - PATCH `password` → the old password fails, the new one works, and the account is unlocked (`failed_logins == 0`, `locked_until is None`);
  - PATCH on an unknown id → 404.

  Run `uv run pytest tests/test_admin_users.py -q`. Expected: FAIL (404s).
- [ ] **Step 2: Implement.** Use pydantic validators:
  - `username`: strip, lower, then the pattern;
  - `password`: `min_length=10`;
  - `role: Role`.

  The routes use `admin_only`, as the existing settings routes do. Create catches the duplicate with a `func.lower(User.username)` lookup before insert. Deactivation calls `revoke_all_for_user`. Log changes to the `capture.audit` logger as `update_settings` does, without passwords. Run the test file. Expected: PASS. Then run the full `uv run pytest -q`. Expected: PASS.
- [ ] **Step 3: Commit.** `feat(server): admins create, deactivate and reset accounts`

### Task 3: Web: login by ID, two roles, capture without key or blur

**Files:**
- Modify:
  - `web/src/api/types.ts`, `api/hooks.ts`, `auth/roles.ts`, `auth/LoginPage.tsx`;
  - `capture/CapturePage.tsx`, `capture/PatientStep.tsx`, `capture/PhotosStep.tsx`, `capture/types.ts`;
  - `storage/idb.ts`, `home/HomePage.tsx`, `layout/Layout.tsx`;
  - `records/RecordPage.tsx`, `records/permissions.ts`, `records/RecordList.tsx`, `ui/StatusBadge.tsx`, `App.tsx`;
  - `package.json`.
- Delete:
  - `web/src/crypto/` and `web/src/device/`;
  - `capture/RedactStep.tsx`, `capture/RedactStep.test.tsx`, `capture/RedactionCanvas.tsx`, `capture/ReuploadPage.tsx`;
  - `web/src/redaction/`, `web/src/queues/`;
  - `burnRedactions` in `imaging/render.ts`, if nothing else uses it;
  - `web/scripts/copy-tesseract.mjs` and `web/public/tesseract/`.
- Tests: update `records/permissions.test.ts`, `home/HomePage.test.tsx`, `outbox/outbox.test.ts` and `auth/RequireAuth.test.tsx`. Delete the tests of deleted modules.

**Interfaces:**
- Consumes the Task 1 API:
  - `POST /auth/login {username, password}`;
  - `RecordSummary.reg_no`;
  - statuses `processing|draft|pending_admin|approved`;
  - create meta `{reg_no, template_key, client_upload_id, fill_by_hand}`.
- Produces:
  - `Role = "doctor" | "admin"`;
  - `Me {id, name, username, role}`;
  - `OutboxMeta {reg_no, template_key, fill_by_hand}`;
  - `availableActions(role, status): UiAction[]`, where `UiAction = "submit" | "approve" | "return" | "reopen" | "fill_by_hand"`;
  - `canEdit(role, status)`.

- [ ] **Step 1: Permissions (TDD).** Rewrite `permissions.test.ts`:
  - doctor + draft → `["submit"]`;
  - doctor + processing → `["fill_by_hand"]`;
  - admin + pending_admin → `["approve","return"]`;
  - admin + approved → `["reopen"]`;
  - doctor + pending_admin → `[]`;
  - `canEdit` is true only for doctor + draft.

  Run `npm test -- permissions`. Expected: FAIL. Then implement `permissions.ts`; `fillByHandOffered` and `FILL_BY_HAND_AFTER_MS` go away. Expected: PASS.
- [ ] **Step 2: Types, roles and login.**
  - `types.ts`: the new `Role`, `Status` and `Me`; drop `Quarantine` and `QuarantineHit`; `reg_no` replaces `study_code`.
  - `roles.ts`: `ROLE_LABEL = { doctor: "Doctor", admin: "Admin" }`; drop `isHospital`.
  - `LoginPage`: the field is labelled "ID", is `type="text"` with `autoComplete="username"`, and posts `{ username, password }`.
  - `StatusBadge`: `processing` "Being read by AI", `draft` "Draft", `pending_admin` "Waiting for admin", `approved` "Approved".
  - `RecordList`: shows `r.reg_no`, and the badge reads "Sent back".
  - `hooks.ts`: drop `useExpectedFingerprint`; `RecordFilter.reg_no`.
- [ ] **Step 3: Capture.**
  - `PatientStep` becomes one input, "Hospital registration number", and a Continue button. It calls `onDone(regNo.trim())` and needs no crypto.
  - `PhotosStep` replaces `onNext` with `onUpload(fillByHand: boolean): Promise<void>` and two buttons, **Let the AI fill it** and **I'll fill it myself**. Both are disabled with no pages or while uploading, and an error from `onUpload` shows in `role="alert"`.
  - `CapturePage` has three steps (Patient, Form, Photos) and uploads `pages.map((p) => p.blob)`. `preparePage` already re-encodes the photo, so EXIF is gone. The meta is `{ reg_no, template_key, fill_by_hand }`. The key and role guards are gone.
  - `PageDraft` drops `boxes` and `ocrDone`.
  - `idb.ts`: DB version 2. The upgrade creates `outbox` when `oldVersion < 1` and deletes the `device` store if present. The doc comment says "An upload waiting to be sent".
  - `outbox.test.ts`: update the meta, and add a test that an item whose send gets a 422 is marked `failed` and not retried. This covers old-meta items.
  - `package.json`: remove `postinstall`, `tesseract.js` and `@tesseract.js-data/eng` with `npm uninstall tesseract.js @tesseract.js-data/eng`, after deleting the `postinstall` line.
- [ ] **Step 4: Home, layout and record page.**
  - **Doctor home:**
    - **New capture**, and the outbox waiting/refused blocks, kept;
    - **Being read by the AI** (mine, processing);
    - **Sent back to me** (my drafts whose `last_event.action` is `return` or `reopen`);
    - **My drafts** (the other drafts);
    - the link "N waiting for admin" (`/records?status=pending_admin`).
  - **Admin home:** the heading **Waiting for admin**, with a `RecordList` of `pending_admin`, oldest first.
  - **Layout nav:** "Home", "All records" (`/records`), and "Accounts" (`/accounts`) for admins.
  - **`App.tsx`:** remove the `setup`, `reupload` and `queue/:stage` routes. Add `records` and `accounts` with placeholder `<p>` elements; Task 4 replaces them.
  - **`RecordPage`:**
    - remove the quarantine block, the reupload link, release, the "another doctor" note and `useNow`;
    - the button labels are `submit` → "Approve and send to admin", `approve` → "Approve", `return` → "Send back…", `reopen` → "Reopen…";
    - "Fill by hand now" shows for `fill_by_hand` with no wait;
    - "Study code" becomes "Registration no.";
    - the return banner reads "Sent back by {actor}: {comment}";
    - the `DONE` messages: submit "Sent to the admin", approve "Approved", return "Sent back to the doctor", reopen "Reopened", fill_by_hand "The AI was stopped — fill the form in by hand";
    - the `EVENT_LABEL` entries for `quarantine`, `release` and `reupload` stay, because old events can still show.
  - `HomePage.test.tsx`: doctor home shows a returned draft under "Sent back to me"; admin home lists `pending_admin` records.
- [ ] **Step 5: Run everything.** `cd web && npm test && npm run typecheck && npm run build`. Expected: all pass. The build is smaller without Tesseract.
- [ ] **Step 6: Commit.** `feat(web): login by ID, doctor and admin panels, capture without device key or blur step`

### Task 4: Web: admin pages (All records, Accounts)

**Files:**
- Create: `web/src/records/AllRecordsPage.tsx`, `web/src/admin/AccountsPage.tsx`, `web/src/admin/AccountsPage.test.tsx`
- Modify: `web/src/App.tsx`, `web/src/api/hooks.ts`, `web/src/api/types.ts`

**Interfaces:**
- Consumes the Task 2 endpoints, plus `GET /records?status=`.
- Produces `Account {id, name, username, role, active}` and `useAccounts()` (query key `["accounts"]`).

- [ ] **Step 1: Failing test.** `AccountsPage.test.tsx` (jsdom, mocked `fetch` in the style of `HomePage.test.tsx`):
  - it lists two accounts;
  - the signed-in admin's own row has no Deactivate button;
  - submitting the create form posts `{name, username, password, role}` to `/api/admin/users` and shows the new row after refetch;
  - a 409 reply shows "That ID is already taken".

  Run `npm test -- AccountsPage`. Expected: FAIL.
- [ ] **Step 2: Implement `AccountsPage`.**
  - Admin only; others see "Only an admin can manage accounts."
  - A table of name, ID, role and status, with per-row **Deactivate**/**Reactivate** and **Set password…** (an inline input plus Save).
  - A create form (Name, ID, Password, Role select defaulting to Doctor), using `card`/`inputClass`/`primaryButton` from `ui/styles`.

  Expected: PASS.
- [ ] **Step 3: Implement `AllRecordsPage`.** A status `<select>` (All, Being read by AI, Draft, Waiting for admin, Approved) backed by the `?status=` URL param, so the home link works, over a `RecordList`. Wire both routes in `App.tsx`. Run `npm test && npm run typecheck`. Expected: PASS.
- [ ] **Step 4: Commit.** `feat(web): admin Accounts page and All records list`

### Task 5: End-to-end story and wrap-up

**Files:**
- Modify: `web/e2e/flow.spec.ts`, `.superpowers/HANDOFF.md`, `docs/superpowers/specs/2026-10-04-data-capture-design.md` (a one-line pointer at the top to the two-panel spec)

- [ ] **Step 1: Rewrite `flow.spec.ts`** (serial, keeping its helpers and the `report.jpg` fixture):
  1. A wrong password is refused. `admin` signs in and out.
  2. Admin creates the doctor "Dr. Test" with ID `dr.test` on Accounts.
  3. `dr.test` signs in and captures reg. no. `amh 555` with a cropped `report.jpg`, choosing **Let the AI fill it**. The record shows "AMH555", is read by the stub AI, has the amber field checked and a mistake fixed, then goes through **Approve and send to admin**.
  4. Second capture: **I'll fill it myself** opens a draft at once. The doctor fills the required fields and approves.
  5. Admin sends the first record back with a comment. The doctor sees it under "Sent back to me", fixes it and approves again.
  6. Admin approves both, and both show "Approved" in All records.
  7. The offline outbox test, kept and adapted: the upload waits while the API route is blocked, then goes up on **Try now**.
- [ ] **Step 2: Run the full gate.**
  - Server: `cd server && uv run pytest -q` and `uv run --extra ocr pytest -m paddle`.
  - Web: `cd web && npm test && npm run typecheck && npm run e2e`.

  Expected: all green.
- [ ] **Step 3: Update `HANDOFF.md` and memory.** Done, with the demo logins `doctor`/`doctor2`/`admin`. Do not push; ask first.
- [ ] **Step 4: Commit.** `test(e2e): two-panel story; docs: point the old spec at the two-panel design`
