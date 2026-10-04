import pytest
from sqlalchemy import func, select

from capture.db.models import Record
from capture.jpeg import check_jpeg
from constants import JPEG


def segment(marker: int, payload: bytes) -> bytes:
    return bytes([0xFF, marker]) + (len(payload) + 2).to_bytes(2, "big") + payload


SOI = b"\xff\xd8"
SOS = segment(0xDA, b"\x01\x01\x00\x00\x3f\x00")
EXIF = segment(0xE1, b"Exif\x00\x00" + b"II*\x00" + b"\x00" * 8)
XMP = segment(0xE1, b"http://ns.adobe.com/xap/1.0/\x00<x:xmpmeta/>")
IRB = segment(0xED, b"Photoshop 3.0\x00")
JFIF = segment(0xE0, b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00")


def kind(data: bytes) -> str | None:
    try:
        check_jpeg(data)
    except ValueError as e:
        return str(e)
    return None


def test_accepts_the_minimal_jfif():
    assert kind(JPEG) is None


def test_accepts_other_segments_fill_bytes_and_standalone_markers():
    other_app1 = segment(0xE1, b"something else")
    comment = segment(0xFE, b"hi")
    dqt = segment(0xDB, b"\x00" * 65)
    data = SOI + b"\xff\xff" + b"\xff\x01" + b"\xff\xd3" + JFIF + other_app1 + comment + dqt + SOS
    assert kind(data + b"\x00\xff\xd9") is None


@pytest.mark.parametrize("meta", [EXIF, XMP, IRB], ids=["exif", "xmp", "app13"])
def test_rejects_photo_metadata(meta):
    assert kind(SOI + JFIF + meta + SOS) == "has_metadata"


@pytest.mark.parametrize(
    "data",
    [
        SOI + JFIF[:-3],
        SOI + b"\xff\xe0\x00\x01" + SOS,
        SOI + b"\xff\xe0",
        b"\x89PNG\r\n\x1a\n" + b"\x00" * 16,
        b"",
        JFIF + SOS,
        SOI + JFIF,
        SOI + JFIF + b"\xff\xd9",
        SOI + JFIF + b"\x00\x00",
    ],
    ids=["truncated", "short-length", "no-length", "no-soi", "empty", "soi-missing", "no-sos", "eoi-before-sos", "garbage"],
)
def test_rejects_malformed_files(data):
    assert kind(data) == "not_jpeg"


def test_upload_with_exif_is_refused_and_nothing_is_stored(db, settings, templates, hospital_key, make_user, login_as, upload):
    client = login_as(make_user("uploader"))
    r = upload(client, pages=(SOI + JFIF + EXIF + SOS,))
    assert r.status_code == 422
    assert r.json()["detail"] == "Pages must not contain photo metadata (EXIF/XMP) — re-capture the photo in the app"
    with db() as s:
        assert s.scalar(select(func.count()).select_from(Record)) == 0
    assert not (settings.storage_dir / "records").exists()
