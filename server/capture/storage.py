import hashlib
import uuid
from pathlib import Path


def resolve_in_storage(storage_dir: Path, relative: str) -> Path:
    root = Path(storage_dir).resolve()
    target = (root / relative).resolve()
    if not target.is_relative_to(root):
        raise ValueError(f"path escapes storage: {relative}")
    return target


def save_page(storage_dir: Path, study_code: str, record_id: uuid.UUID, page_no: int, data: bytes) -> tuple[str, str]:
    relative = f"records/{study_code}/{record_id}/page-{page_no}.jpg"
    target = resolve_in_storage(storage_dir, relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return relative, hashlib.sha256(data).hexdigest()


def remove_stored(storage_dir: Path, relatives: list[str]) -> None:
    """Delete stored files once the database no longer points at them; a file that is already gone is fine."""
    for relative in relatives:
        resolve_in_storage(storage_dir, relative).unlink(missing_ok=True)
