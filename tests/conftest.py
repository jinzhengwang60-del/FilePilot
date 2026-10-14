import os
from pathlib import Path
from uuid import uuid4

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def pytest_configure(config):
    # Keep generated test files inside the checkout, away from protected AppData.
    if config.option.basetemp is None:
        root = (Path(__file__).resolve().parents[1] / "artifacts" / "test-work").resolve()
        target = (root / uuid4().hex).resolve()
        if target.parent != root:
            raise RuntimeError("Unsafe test directory")
        root.mkdir(parents=True, exist_ok=True)
        config.option.basetemp = str(target)


@pytest.fixture
def folder(tmp_path):
    root = tmp_path / "inbox"
    root.mkdir()
    return root


@pytest.fixture
def operator(tmp_path):
    from filepilot.journal import Journal
    from filepilot.operations import FileOperator
    return FileOperator(Journal(tmp_path / "state" / "history.sqlite3"))
