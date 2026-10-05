import pytest

from capture.extraction.ocr import OcrLine
from capture.extraction.read_id import IdReader, OcrUnavailable, find_reg_no
from constants import JPEG
from fakes import FakeOcr


def lines(*texts: str) -> list[OcrLine]:
    return [OcrLine(1, t, (0, 0, 1, 1)) for t in texts]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Reg No: RC12345", "RC12345"),
        ("rc 00123", "RC00123"),
        ("Reg. No.: RC-778", "RC778"),
        ("R C:4501 Age 52", "RC4501"),
    ],
)
def test_finds_the_rc_number(text, expected):
    assert find_reg_no(lines("CT CHEST REPORT", text)) == expected


@pytest.mark.parametrize("text", ["CT CHEST REPORT", "Source 1234", "RC123abc", "RCC 12", "Cell 01712345678"])
def test_ignores_text_without_an_id(text):
    assert find_reg_no(lines(text)) is None


@pytest.fixture
def doctor(templates, make_user, login_as):
    return login_as(make_user("doctor"))


def test_doctor_gets_the_id_read_from_a_page(app, settings, doctor):
    app.state.id_reader = IdReader(settings, engine=FakeOcr("AMCGH", "Patient ID: RC 98765"))
    r = doctor.post("/api/read-id", files={"page": ("p.jpg", JPEG, "image/jpeg")})
    assert r.status_code == 200, r.text
    assert r.json() == {"reg_no": "RC98765"}


def test_no_id_on_the_page_returns_null(app, settings, doctor):
    app.state.id_reader = IdReader(settings, engine=FakeOcr("CT CHEST REPORT"))
    r = doctor.post("/api/read-id", files={"page": ("p.jpg", JPEG, "image/jpeg")})
    assert r.json() == {"reg_no": None}


def test_non_jpeg_is_refused(doctor):
    r = doctor.post("/api/read-id", files={"page": ("p.png", b"\x89PNG", "image/png")})
    assert r.status_code == 415


def test_server_without_ocr_says_so(app, settings, doctor):
    class NoOcr:
        def read(self, page, image):
            raise ImportError("paddleocr")

    app.state.id_reader = IdReader(settings, engine=NoOcr())
    r = doctor.post("/api/read-id", files={"page": ("p.jpg", JPEG, "image/jpeg")})
    assert r.status_code == 503


def test_admin_cannot_use_it(make_user, login_as):
    admin = login_as(make_user("admin"))
    assert admin.post("/api/read-id", files={"page": ("p.jpg", JPEG, "image/jpeg")}).status_code == 403


def test_reader_reports_missing_ocr(settings):
    class NoOcr:
        def read(self, page, image):
            raise ImportError

    with pytest.raises(OcrUnavailable):
        IdReader(settings, engine=NoOcr()).read(JPEG)
