import uuid

import pytest
from fastapi.routing import APIRoute

from capture.api.app import create_app
from capture.api.deps import current_user
from capture.db.models import Record, Status

PUBLIC = {"/api/health", "/api/auth/login", "/api/auth/logout"}


def all_routes(app):
    """(full path, APIRoute) pairs, flattening routers included via include_router (FastAPI 0.14x wraps them)."""
    pairs = []
    for route in app.routes:
        if isinstance(route, APIRoute):
            pairs.append((route.path, route))
        elif hasattr(route, "original_router"):
            prefix = route.include_context.prefix
            pairs.extend((prefix + r.path, r) for r in route.original_router.routes if isinstance(r, APIRoute))
    return pairs


def protected_routes(app):
    return [(path, r) for path, r in all_routes(app) if path not in PUBLIC]


def depends_on_current_user(dependant) -> bool:
    for dep in dependant.dependencies:
        if dep.call is current_user or depends_on_current_user(dep):
            return True
    return False


def test_the_route_inventory_is_not_empty(app):
    assert len(protected_routes(app)) >= 10
    assert PUBLIC <= {path for path, _ in all_routes(app)}


def test_every_non_public_route_requires_a_logged_in_user(settings, db):
    app = create_app(settings, session_factory=db)
    unprotected = [path for path, r in protected_routes(app) if not depends_on_current_user(r.dependant)]
    assert unprotected == []


def test_every_non_public_route_answers_401_without_a_cookie(app, client):
    sample = str(uuid.uuid4())
    for full_path, route in protected_routes(app):
        path = full_path
        for name in route.param_convertors:
            path = path.replace("{" + name + "}", sample)
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            kwargs = {"json": {}} if method in {"POST", "PUT", "PATCH"} else {}
            r = client.request(method, path, **kwargs)
            assert r.status_code == 401, f"{method} {full_path} returned {r.status_code}"


def test_quarantined_records_and_files_are_hidden_from_nsu(app, db, templates, hospital_key, make_user, login_as, upload):
    uploader = login_as(make_user("uploader"))
    reviewer = login_as(make_user("nsu_reviewer"))
    record = upload(uploader).json()
    with db.begin() as s:
        s.get(Record, uuid.UUID(record["id"])).status = Status.QUARANTINED
    file_id = record["files"][0]["id"]

    assert uploader.get(f"/api/records/{record['id']}").status_code == 200
    assert uploader.get(f"/api/files/{file_id}").status_code == 200
    assert reviewer.get(f"/api/records/{record['id']}").status_code == 404
    assert reviewer.get(f"/api/files/{file_id}").status_code == 404
