from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = REPO_DIR / "templates"
FINGERPRINT = "K-B9FF"
STUDY_CODE = "AMH-N0ZDG4KM8V"
# SOI, a JFIF APP0 segment, SOS, EOI: the smallest header the metadata walker accepts.
JPEG = (
    b"\xff\xd8"
    + b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    + b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00"
    + b"\xff\xd9"
)
