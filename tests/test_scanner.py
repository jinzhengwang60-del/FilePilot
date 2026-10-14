import hashlib
import os
from pathlib import Path
from threading import Event

import pytest

from filepilot.categories import classify
from filepilot.safety import SafetyError, SafetyPolicy
from filepilot.scanner import hash_file, scan_folder


def test_duplicate_detection_uses_content_and_scan_is_read_only(folder):
    (folder / "one.txt").write_bytes(b"abc")
    (folder / "copy.bin").write_bytes(b"abc")
    (folder / "different.txt").write_bytes(b"xyz")
    (folder / "unique.md").write_bytes(b"a longer note")
    before = {file.name: (file.read_bytes(), file.stat().st_mtime_ns) for file in folder.iterdir()}
    result = scan_folder(folder)
    assert len(result.files) == 4
    assert result.hashed_count == 3
    assert len(result.duplicates) == 1
    assert result.duplicates[0].digest == hashlib.sha256(b"abc").hexdigest()
    assert {file.path.name for file in result.duplicates[0].files} == {"one.txt", "copy.bin"}
    assert result.extra_bytes == 3
    assert before == {file.name: (file.read_bytes(), file.stat().st_mtime_ns) for file in folder.iterdir()}


def test_recursion_hidden_and_output_directories(folder):
    (folder / "visible.txt").write_text("visible")
    (folder / ".secret").write_text("secret")
    for name in ("nested", "FilePilot_整理", ".filepilot-quarantine", "node_modules"):
        (folder / name).mkdir()
        (folder / name / "child.txt").write_text(name)
    result = scan_folder(folder)
    assert {file.relative for file in result.files} == {"visible.txt", str(Path("nested") / "child.txt")}
    flat = scan_folder(folder, recursive=False, include_hidden=True)
    assert {file.path.name for file in flat.files} == {"visible.txt", ".secret"}


def test_protected_child_is_skipped_and_protected_root_rejected(folder):
    protected = folder / "private"
    protected.mkdir()
    (protected / "key.txt").write_text("private")
    (folder / "normal.txt").write_text("normal")
    policy = SafetyPolicy((protected,))
    assert [file.path.name for file in scan_folder(folder, policy=policy).files] == ["normal.txt"]
    with pytest.raises(SafetyError, match="敏感"):
        scan_folder(protected, policy=policy)


def test_sensitive_directory_names_are_protected_even_outside_current_profile(folder):
    for name in ("AppData", ".ssh", ".aws", ".gnupg"):
        child = folder / name
        child.mkdir()
        (child / "secret.txt").write_text("private")
    (folder / "normal.txt").write_text("normal")
    result = scan_folder(folder, include_hidden=True)
    assert [file.path.name for file in result.files] == ["normal.txt"]
    assert len(result.issues) == 4


def test_disk_root_is_refused(folder):
    with pytest.raises(SafetyError, match="根目录"):
        scan_folder(Path(folder.anchor))


def test_symlink_loop_and_linked_scan_root_are_refused(folder):
    (folder / "normal.txt").write_text("normal")
    link = folder / "loop"
    try:
        link.symlink_to(folder, target_is_directory=True)
    except OSError:
        pytest.skip("This Windows account cannot create symbolic links")
    result = scan_folder(folder)
    assert len(result.files) == 1
    assert any(issue.path == link for issue in result.issues)
    with pytest.raises(SafetyError, match="链接"):
        scan_folder(link)


def test_hardlinks_are_not_counted_as_reclaimable_copies(folder):
    (folder / "normal.txt").write_bytes(b"same inode")
    try:
        os.link(folder / "normal.txt", folder / "alias.txt")
    except OSError:
        pytest.skip("This execution environment does not allow creating hardlinks")
    result = scan_folder(folder)
    assert result.files == ()
    assert len(result.issues) == 2


def test_access_denied_is_reported_without_aborting_other_files(folder, monkeypatch):
    denied = folder / "denied"
    denied.mkdir()
    (folder / "normal.txt").write_text("normal")
    original = os.scandir
    def guarded(path):
        if Path(path) == denied:
            raise PermissionError("test access denied")
        return original(path)
    monkeypatch.setattr(os, "scandir", guarded)
    result = scan_folder(folder)
    assert len(result.files) == 1
    assert any("access denied" in issue.reason for issue in result.issues)


def test_metadata_change_is_rejected_by_hash_reader(folder):
    file = folder / "note.txt"
    file.write_bytes(b"before")
    record = scan_folder(folder).files[0]
    file.write_bytes(b"after with a different size")
    with pytest.raises(SafetyError, match="变化"):
        hash_file(file, SafetyPolicy(), record.signature)


def test_cancelled_scan_has_no_actionable_duplicate_groups(folder):
    (folder / "one.txt").write_bytes(b"abc")
    event = Event()
    event.set()
    result = scan_folder(folder, cancel=event)
    assert result.cancelled
    assert result.duplicates == ()


def test_empty_files_are_duplicates_with_zero_extra_bytes(folder):
    (folder / "one.txt").touch()
    (folder / "two.txt").touch()
    result = scan_folder(folder)
    assert len(result.duplicates) == 1
    assert result.extra_bytes == 0


@pytest.mark.parametrize("name,category", [("PHOTO.JPG", "图片"), ("backup.tar.gz", "压缩包"),
    ("README.md", "文档"), ("notes.csv", "文档"), ("main.py", "代码"), ("sample.flac", "音频"),
    ("film.mp4", "视频"), ("setup.msi", "安装包"), ("no_extension", "其他")])
def test_extension_categories(name, category):
    assert classify(Path(name)) == category


@pytest.mark.skipif(os.name != "nt", reason="Windows path validation")
@pytest.mark.parametrize("path", [r"\\server\share\folder", r"\\?\C:\Windows", r"C:\data\file.txt:secret"])
def test_network_device_paths_and_alternate_stream_paths_are_refused(path):
    with pytest.raises(SafetyError):
        SafetyPolicy().check_path(path)
