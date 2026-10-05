import hashlib
import uuid
from pathlib import Path


def resolve_in_storage(storage_dir: Path, relative: str) -> Path:
    root = Path(storage_dir).resolve()
    target = (root / relative).resolve()
    if not target.is_relative_to(root):
        raise ValueError(f"path escapes storage: {relative}")
    return target


def save_page(storage_dir: Path, record_id: uuid.UUID, page_no: int, data: bytes) -> tuple[str, str]:
    """Store one page under its record's ID: the patient ID never becomes part of a path."""
    relative = f"records/{record_id}/page-{page_no}.jpg"
    target = resolve_in_storage(storage_dir, relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return relative, hashlib.sha256(data).hexdigest()
