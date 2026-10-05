import hashlib
import uuid

import pytest

from capture.storage import resolve_in_storage, save_page


def test_save_page_writes_file_and_returns_hash(tmp_path):
    record_id = uuid.uuid4()
    relative, digest = save_page(tmp_path, record_id, 2, b"abc")
    assert relative == f"records/{record_id}/page-2.jpg"
    assert (tmp_path / relative).read_bytes() == b"abc"
    assert digest == hashlib.sha256(b"abc").hexdigest()


def test_resolve_rejects_paths_outside_storage(tmp_path):
    with pytest.raises(ValueError):
        resolve_in_storage(tmp_path, "../secret.txt")
