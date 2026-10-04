from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = REPO_DIR / "templates"
FINGERPRINT = "K-B9FF"
STUDY_CODE = "AMH-N0ZDG4KM8V"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64 + b"\xff\xd9"
