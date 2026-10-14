import os
from pathlib import Path
import subprocess

import pytest

from filepilot.planner import classification_plan
from filepilot.safety import SafetyError
from filepilot.scanner import scan_folder

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows filesystem integration")


def create_junction(link: Path, target: Path) -> None:
    # Creation only, with literal PowerShell quoting of generated fixture paths.
    def literal(value):
        return "'" + str(value).replace("'", "''") + "'"
    script = f"New-Item -ItemType Junction -Path {literal(link)} -Target {literal(target)} -ErrorAction Stop | Out-Null"
    # Cold .NET / PowerShell startup on a hosted runner can exceed 15 seconds.
    # Keep a bound and let timeouts fail, rather than skipping the protection test.
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                            capture_output=True, timeout=45)
    if result.returncode:
        pytest.skip("Execution environment cannot create Windows junction fixtures")


def test_real_windows_junction_loop_is_skipped(folder):
    (folder / "normal.txt").write_text("one")
    loop = folder / "loop"
    create_junction(loop, folder)
    result = scan_folder(folder)
    assert len(result.files) == 1
    assert any(issue.path == loop and "联接点" in issue.reason for issue in result.issues)
    with pytest.raises(SafetyError, match="联接点"):
        scan_folder(loop)


def test_target_parent_changed_to_junction_after_preview_blocks_move(folder, operator, tmp_path):
    (folder / "normal.txt").write_text("one")
    outside = tmp_path / "separate-folder"
    outside.mkdir()
    result = scan_folder(folder)
    target = folder / "custom-output"
    plan = classification_plan(result, {file.path for file in result.files}, target)
    create_junction(target, outside)
    with pytest.raises(SafetyError, match="联接点"):
        operator.execute(plan, confirmed=True)
    assert (folder / "normal.txt").read_text() == "one"
    assert list(outside.iterdir()) == []


def test_windows_rename_race_never_overwrites_an_existing_target(folder, operator, monkeypatch):
    file = folder / "normal.txt"
    file.write_text("one")
    result = scan_folder(folder)
    plan = classification_plan(result, {file}, folder / "FilePilot_整理")
    original = os.rename
    def occupy_then_rename(source, destination):
        Path(destination).write_text("foreign content")
        original(source, destination)
    monkeypatch.setattr(os, "rename", occupy_then_rename)
    moved = operator.execute(plan, confirmed=True)
    assert moved.completed == 0
    assert file.read_text() == "one"
    assert plan.items[0].destination.read_text() == "foreign content"


def test_ntfs_alternate_stream_is_preserved_by_move_and_undo(folder, operator):
    file = folder / "normal.txt"
    file.write_text("one")
    stream_path = str(file) + ":filepilot-test"
    try:
        with open(stream_path, "wb") as stream:
            stream.write(b"private metadata")
    except OSError:
        pytest.skip("Execution environment or filesystem does not allow NTFS alternate stream fixtures")
    result = scan_folder(folder)
    plan = classification_plan(result, {file}, folder / "FilePilot_整理")
    moved = operator.execute(plan, confirmed=True)
    with open(str(plan.items[0].destination) + ":filepilot-test", "rb") as stream:
        assert stream.read() == b"private metadata"
    operator.undo(moved.batch_id, confirmed=True)
    with open(stream_path, "rb") as stream:
        assert stream.read() == b"private metadata"
