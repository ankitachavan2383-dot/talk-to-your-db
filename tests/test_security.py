import re
from pathlib import Path

import pytest

from app.core.security import SecretBox
from app.data.loader import LoadError, save_original


def test_no_exec_or_eval_in_source():
    pat = re.compile(r"(?<![\w.])(exec|eval)\s*\(")
    offenders = [str(p) for p in Path("app").rglob("*.py") if pat.search(p.read_text())]
    assert not offenders, offenders


def test_secretbox_roundtrip():
    from cryptography.fernet import Fernet
    box = SecretBox(Fernet.generate_key().decode())
    assert box.decrypt(box.encrypt("pw")) == "pw"


def test_upload_is_read_only_and_validated(tmp_path):
    path, kind = save_original(b"a,b\n1,2\n", "../../evil name.csv", tmp_path, 1)
    assert kind == "csv" and path.parent.parent == tmp_path and ".." not in path.name
    assert not (path.stat().st_mode & 0o222)  # no write bits
    with pytest.raises(LoadError):
        save_original(b"x", "script.exe", tmp_path, 1)
