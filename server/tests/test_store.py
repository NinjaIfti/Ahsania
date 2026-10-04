import pytest
from sqlalchemy import func, select

from capture.db.models import Template
from capture.formschema.store import TemplateConflict, active_templates, get_active, load_templates
from constants import TEMPLATES_DIR

MINIMAL = """\
key: demo_form
version: {version}
phase: 1
kind: document
title: Demo form
fields:
  - {{key: seen_on, type: date, required: true, document_date: true}}
  - {{key: note, type: text, label: "{label}"}}
"""


def write(directory, version=1, label="Note"):
    (directory / "demo_form.yaml").write_text(MINIMAL.format(version=version, label=label), encoding="utf-8")


def test_load_creates_then_reports_unchanged(db, tmp_path):
    write(tmp_path)
    with db.begin() as s:
        assert load_templates(s, tmp_path) == ["demo_form v1: created"]
    with db.begin() as s:
        assert load_templates(s, tmp_path) == ["demo_form v1: unchanged"]


def test_empty_template_folder_is_an_error(db, tmp_path):
    with pytest.raises(TemplateConflict, match=r"no \*.yaml templates found in"):
        with db.begin() as s:
            load_templates(s, tmp_path)


def test_changing_a_template_without_bumping_version_fails(db, tmp_path):
    write(tmp_path)
    with db.begin() as s:
        load_templates(s, tmp_path)
    write(tmp_path, label="Comment")
    with pytest.raises(TemplateConflict, match="without bumping"):
        with db.begin() as s:
            load_templates(s, tmp_path)


def test_new_version_becomes_active_and_old_is_kept(db, tmp_path):
    write(tmp_path)
    with db.begin() as s:
        load_templates(s, tmp_path)
    write(tmp_path, version=2, label="Comment")
    with db.begin() as s:
        load_templates(s, tmp_path)
        assert get_active(s, "demo_form").version == 2
        assert [t.version for t in active_templates(s)] == [2]
        assert s.scalar(select(func.count()).select_from(Template)) == 2


def test_repository_templates_are_valid(db):
    with db.begin() as s:
        load_templates(s, TEMPLATES_DIR)
        found = {(t.key, t.phase, t.kind) for t in active_templates(s)}
    assert found == {
        ("radiology_report", 1, "document"),
        ("xray_film_photo", 1, "film_photo"),
        ("ct_mri_film_photo", 1, "film_photo"),
        ("dicom_series", 1, "dicom"),
        ("pathology_molecular_report", 3, "document"),
        ("lab_report", 3, "document"),
        ("treatment_sheet", 3, "document"),
        ("clinical_summary", 3, "document"),
        ("outcome_followup", 3, "document"),
    }
