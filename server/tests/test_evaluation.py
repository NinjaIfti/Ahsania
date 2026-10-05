import json
from datetime import date

import httpx
import yaml
from typer.testing import CliRunner

from capture.cli import app as cli
from capture.evaluation import report, run_eval, score
from capture.extraction.stub import STUB_VALUES, stub_transport
from capture.extraction.vlm import VlmClient
from capture.formschema.model import TemplateDef
from capture.formschema.validate import validate_values
from constants import PHOTO, REPO_DIR, TEMPLATES_DIR

GOLDEN = REPO_DIR / "eval" / "golden"
runner = CliRunner()


def template(key: str) -> TemplateDef:
    return TemplateDef.model_validate(yaml.safe_load((TEMPLATES_DIR / f"{key}.yaml").read_text(encoding="utf-8")))


def model(transport=None) -> VlmClient:
    return VlmClient("http://vlm.test/v1", "test-model", timeout=5, max_image_side=1600, transport=transport or stub_transport())


def write_case(root, template_key: str, name: str, values: dict, ignore=()) -> None:
    folder = root / template_key / name
    folder.mkdir(parents=True)
    (folder / "page-1.jpg").write_bytes(PHOTO)
    (folder / "expected.json").write_text(json.dumps({"style": "typed", "values": values, "ignore": list(ignore)}))


def test_scoring_counts_right_wrong_and_invented_values():
    expected = {
        "modality": "CT",
        "study_date": "2026-09-01",
        "contrast": None,
        "lesions": [{"lobe": "RUL", "long_axis_cm": 2.3}],
        "impression": "Suspicious for primary lung malignancy.",
    }
    actual = {
        "modality": "CT",
        "study_date": "2026-09-02",
        "contrast": True,
        "lesions": [{"lobe": "RUL", "long_axis_cm": 2.30}],
        "impression": "suspicious for primary lung malignancy",
    }
    assert score(template("radiology_report"), expected, actual, set()) == (4, 5, 1, ["study_date"])


def test_ignored_fields_are_not_scored():
    expected = {"study_date": "2026-09-01", "capture_source": None}
    actual = {"study_date": "2026-09-01", "capture_source": "monitor screen"}
    assert score(template("xray_film_photo"), expected, actual, {"capture_source"}) == (1, 1, 0, [])


def test_a_run_scores_each_case_and_reports_against_the_s3_target(tmp_path):
    write_case(tmp_path, "radiology_report", "case-01", STUB_VALUES["radiology_report"])
    write_case(tmp_path, "radiology_report", "case-02", {**STUB_VALUES["radiology_report"], "modality": "MRI"})
    results = run_eval(tmp_path, TEMPLATES_DIR, model())
    assert [(r.case, r.correct, r.total, r.wrong) for r in results] == [("case-01", 7, 7, []), ("case-02", 6, 7, ["modality"])]
    text = report(results)
    assert "radiology_report" in text
    assert "S3: typed accuracy 92.9% meets the 90% target" in text
    assert "radiology_report/case-02: wrong modality" in text


def test_a_model_error_counts_every_field_as_wrong(tmp_path):
    write_case(tmp_path, "radiology_report", "case-01", STUB_VALUES["radiology_report"])
    [result] = run_eval(tmp_path, TEMPLATES_DIR, model(httpx.MockTransport(lambda request: httpx.Response(500))))
    assert (result.correct, result.total, result.error) == (0, 7, "model server answered 500")


def test_the_cli_runs_a_golden_set_with_the_stub(tmp_path):
    write_case(tmp_path, "radiology_report", "case-01", STUB_VALUES["radiology_report"])
    r = runner.invoke(cli, ["eval", "--golden", str(tmp_path), "--stub"])
    assert r.exit_code == 0, r.output
    assert "S3: typed accuracy 100.0% meets the 90% target" in r.output


def test_the_cli_fails_on_a_folder_without_cases(tmp_path):
    r = runner.invoke(cli, ["eval", "--golden", str(tmp_path), "--stub"])
    assert r.exit_code == 1
    assert "no golden documents found" in r.output


def test_the_committed_golden_set_is_valid_for_its_templates():
    cases = sorted(GOLDEN.glob("*/*/expected.json"))
    assert len(cases) == 20
    for expected_file in cases:
        tpl = template(expected_file.parent.parent.name)
        spec = json.loads(expected_file.read_text(encoding="utf-8"))
        assert (expected_file.parent / "page-1.jpg").is_file()
        values = {key: value for key, value in spec["values"].items() if value is not None}
        errors = [e for e in validate_values(tpl, values, date(2026, 10, 5)) if e["path"] not in spec["ignore"]]
        assert errors == [], expected_file
