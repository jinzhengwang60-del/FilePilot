import os
from dataclasses import replace
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from filepilot.journal import record_from_item
from filepilot.models import MoveItem, MovePlan
from filepilot.planner import classification_plan, quarantine_plan
from filepilot.safety import CancelledError, SafetyError, path_key
from filepilot.scanner import scan_folder


def plan_for(folder, selected=None):
    result = scan_folder(folder)
    return classification_plan(result, selected or {file.path for file in result.files}, folder / "FilePilot_整理")


def test_preview_does_not_create_targets_and_collision_names_are_visible(folder):
    (folder / "first").mkdir()
    (folder / "second").mkdir()
    for child in ("first", "second"):
        (folder / child / "same.txt").write_text(child)
    target = folder / "FilePilot_整理" / "文档"
    target.mkdir(parents=True)
    (target / "same.txt").write_text("existing")
    before = set(folder.rglob("*"))
    plan = plan_for(folder)
    assert {item.destination.name for item in plan.items} == {"same (2).txt", "same (3).txt"}
    assert set(folder.rglob("*")) == before


def test_confirmation_required_for_move_and_undo(folder, operator):
    file = folder / "a.txt"
    file.write_text("keep")
    plan = plan_for(folder)
    with pytest.raises(SafetyError, match="确认"):
        operator.execute(plan)
    assert file.read_text() == "keep"
    assert operator.journal.recent() == []
    result = operator.execute(plan, confirmed=True)
    with pytest.raises(SafetyError, match="确认"):
        operator.undo(result.batch_id)
    assert plan.items[0].destination.is_file()


def test_move_persists_history_and_undo_restores_content_and_timestamp(folder, operator):
    file = folder / "中文名称.txt"
    content = "FilePilot 保留内容。".encode("utf-8")
    file.write_bytes(content)
    timestamp = file.stat().st_mtime_ns
    plan = plan_for(folder)
    result = operator.execute(plan, confirmed=True)
    assert result.state == "completed"
    assert not file.exists()
    assert plan.items[0].destination.read_bytes() == content
    assert plan.items[0].destination.stat().st_mtime_ns == timestamp
    # Reopen the database to prove the history isn't only held in memory.
    from filepilot.journal import Journal
    from filepilot.operations import FileOperator
    reopened = FileOperator(Journal(operator.journal.path))
    assert reopened.journal.items(result.batch_id)[0]["state"] == "moved"
    undone = reopened.undo(result.batch_id, confirmed=True)
    assert undone.state == "undone"
    assert file.read_bytes() == content
    assert file.stat().st_mtime_ns == timestamp
    assert not plan.items[0].destination.exists()


def test_changed_file_prevents_entire_batch(folder, operator):
    (folder / "a.txt").write_text("one")
    (folder / "b.txt").write_text("two")
    plan = plan_for(folder)
    (folder / "b.txt").write_text("a changed file")
    with pytest.raises(SafetyError, match="变化"):
        operator.execute(plan, confirmed=True)
    assert (folder / "a.txt").is_file()
    assert not plan.destination_root.exists()
    assert operator.journal.recent() == []


def test_duplicate_content_change_is_detected_even_if_size_and_mtime_are_restored(folder, operator):
    first, second = folder / "one.txt", folder / "two.txt"
    first.write_bytes(b"abc")
    second.write_bytes(b"abc")
    result = scan_folder(folder)
    plan = quarantine_plan(result, {second})
    stamp = second.stat().st_mtime_ns
    second.write_bytes(b"xyz")
    os.utime(second, ns=(stamp, stamp))
    with pytest.raises(SafetyError, match="内容"):
        operator.execute(plan, confirmed=True)
    assert first.read_bytes() == b"abc" and second.read_bytes() == b"xyz"


def test_collision_created_after_preview_blocks_all_moves(folder, operator):
    (folder / "a.txt").write_text("original")
    plan = plan_for(folder)
    destination = plan.items[0].destination
    destination.parent.mkdir(parents=True)
    destination.write_text("someone else's file")
    with pytest.raises(SafetyError, match="覆盖"):
        operator.execute(plan, confirmed=True)
    assert destination.read_text() == "someone else's file"
    assert (folder / "a.txt").read_text() == "original"


def test_mid_batch_collision_keeps_previous_moves_undoable(folder, operator, monkeypatch):
    (folder / "a.txt").write_text("one")
    (folder / "b.txt").write_text("two")
    plan = plan_for(folder)
    original = operator._move
    calls = 0
    def collide(file, destination, digest):
        nonlocal calls
        calls += 1
        if calls == 2:
            destination.write_text("foreign")
        original(file, destination, digest)
    monkeypatch.setattr(operator, "_move", collide)
    result = operator.execute(plan, confirmed=True)
    assert result.state == "partial" and result.completed == 1
    assert plan.items[1].destination.read_text() == "foreign"
    assert plan.items[1].file.path.read_text() == "two"
    monkeypatch.setattr(operator, "_move", original)
    operator.undo(result.batch_id, confirmed=True)
    assert (folder / "a.txt").read_text() == "one"
    assert plan.items[1].destination.read_text() == "foreign"


def test_undo_does_not_overwrite_a_new_file_at_original_path(folder, operator):
    file = folder / "a.txt"
    file.write_text("original")
    plan = plan_for(folder)
    result = operator.execute(plan, confirmed=True)
    file.write_text("new occupant")
    with pytest.raises(SafetyError, match="覆盖"):
        operator.undo(result.batch_id, confirmed=True)
    assert file.read_text() == "new occupant"
    assert plan.items[0].destination.read_text() == "original"


def test_undo_rejects_modified_destination_content(folder, operator):
    (folder / "a.txt").write_bytes(b"abc")
    plan = plan_for(folder)
    result = operator.execute(plan, confirmed=True)
    destination = plan.items[0].destination
    stamp = destination.stat().st_mtime_ns
    destination.write_bytes(b"xyz")
    os.utime(destination, ns=(stamp, stamp))
    with pytest.raises(SafetyError, match="内容"):
        operator.undo(result.batch_id, confirmed=True)
    assert not (folder / "a.txt").exists()
    assert destination.read_bytes() == b"xyz"


def test_quarantine_preserves_files_and_requires_a_keeper(folder, operator):
    first, second = folder / "one.txt", folder / "two.txt"
    first.write_bytes(b"same")
    second.write_bytes(b"same")
    result = scan_folder(folder)
    with pytest.raises(SafetyError, match="保留"):
        quarantine_plan(result, {first, second})
    plan = quarantine_plan(result, {second})
    moved = operator.execute(plan, confirmed=True)
    assert first.read_bytes() == b"same"
    assert plan.items[0].destination.read_bytes() == b"same"
    assert ".filepilot-quarantine" in plan.items[0].destination.parts
    assert scan_folder(folder).duplicates == ()
    operator.undo(moved.batch_id, confirmed=True)
    assert second.read_bytes() == b"same"


def test_missing_keeper_blocks_quarantine(folder, operator):
    first, second = folder / "one.txt", folder / "two.txt"
    first.write_bytes(b"same")
    second.write_bytes(b"same")
    plan = quarantine_plan(scan_folder(folder), {second})
    first.unlink()  # Test fixture mutation, never a user file.
    with pytest.raises(OSError):
        operator.execute(plan, confirmed=True)
    assert second.exists()


def test_cancel_before_preflight_creates_no_history_or_moves(folder, operator):
    (folder / "a.txt").write_text("one")
    plan = plan_for(folder)
    cancel = Event()
    cancel.set()
    with pytest.raises(CancelledError):
        operator.execute(plan, confirmed=True, cancel=cancel)
    assert operator.journal.recent() == []
    assert (folder / "a.txt").exists()


def test_cancel_between_files_keeps_partial_batch_undoable(folder, operator):
    for name in ("a.txt", "b.txt", "c.txt"):
        (folder / name).write_text(name)
    cancel = Event()
    def stop(phase, done, total, current):
        if phase == "正在移动" and done == 1:
            cancel.set()
    result = operator.execute(plan_for(folder), confirmed=True, cancel=cancel, progress=stop)
    assert result.completed == 1 and result.state == "partial"
    operator.undo(result.batch_id, confirmed=True)
    assert all((folder / name).exists() for name in ("a.txt", "b.txt", "c.txt"))


def test_plan_cannot_escape_the_scanned_root(folder, operator, tmp_path):
    (folder / "a.txt").write_text("one")
    outside = tmp_path / "other.txt"
    outside.write_text("outside")
    record = scan_folder(tmp_path, recursive=False).files[0]
    forged = MovePlan(folder, folder / "output", "classify", (MoveItem(record, folder / "output" / "other.txt", "forged"),))
    with pytest.raises(SafetyError, match="范围"):
        operator.execute(forged, confirmed=True)
    assert outside.exists()


def test_plan_cannot_escape_destination_or_repeat_source(folder, operator):
    (folder / "a.txt").write_text("one")
    plan = plan_for(folder)
    outside = replace(plan, items=(replace(plan.items[0], destination=folder.parent / "outside.txt"),))
    with pytest.raises(SafetyError, match="范围"):
        operator.execute(outside, confirmed=True)
    repeated = replace(plan, items=(plan.items[0], plan.items[0]))
    with pytest.raises(SafetyError, match="重复"):
        operator.execute(repeated, confirmed=True)


def test_cross_volume_moves_are_refused(folder, operator, monkeypatch):
    (folder / "a.txt").write_text("one")
    plan = plan_for(folder)
    fake_parent = SimpleNamespace(stat=lambda: SimpleNamespace(st_dev=plan.items[0].file.device + 1))
    monkeypatch.setattr("filepilot.operations.existing_parent", lambda path: fake_parent)
    with pytest.raises(SafetyError, match="同一磁盘"):
        operator.execute(plan, confirmed=True)
    assert (folder / "a.txt").exists()


def test_recovery_handles_crash_after_move_before_database_checkpoint(folder, operator):
    (folder / "a.txt").write_text("one")
    plan = plan_for(folder)
    digest = operator._verify(plan.items[0].file)
    batch_id = operator.journal.begin(plan, {path_key(plan.items[0].file.path): digest})
    operator.journal.item_state(batch_id, 0, "moving")
    operator._move(plan.items[0].file, plan.items[0].destination, digest)
    before = plan.items[0].destination.read_bytes()
    assert operator.recover() == [batch_id]
    assert operator.journal.items(batch_id)[0]["state"] == "moved"
    assert plan.items[0].destination.read_bytes() == before  # Recovery itself never moves files.
    operator.undo(batch_id, confirmed=True)
    assert (folder / "a.txt").read_text() == "one"


def test_recovery_handles_crash_after_undo_before_checkpoint(folder, operator):
    (folder / "a.txt").write_text("one")
    result = operator.execute(plan_for(folder), confirmed=True)
    item = operator.journal.items(result.batch_id)[0]
    operator.journal.batch_state(result.batch_id, "undoing")
    operator.journal.item_state(result.batch_id, 0, "undoing")
    operator._move(record_from_item(item, at_destination=True), Path(item["source"]), item["digest"])
    operator.recover()
    assert operator.journal.batch(result.batch_id)["state"] == "undone"
    assert (folder / "a.txt").read_text() == "one"


def test_ambiguous_recovery_never_deletes_either_file(folder, operator):
    (folder / "a.txt").write_text("one")
    plan = plan_for(folder)
    digest = operator._verify(plan.items[0].file)
    batch_id = operator.journal.begin(plan, {path_key(plan.items[0].file.path): digest})
    operator.journal.item_state(batch_id, 0, "moving")
    plan.items[0].destination.parent.mkdir(parents=True)
    plan.items[0].destination.write_text("one")
    operator.recover()
    assert operator.journal.batch(batch_id)["state"] == "needs_review"
    assert plan.items[0].file.path.exists() and plan.items[0].destination.exists()


def test_os_lock_blocks_concurrent_operations_and_releases_after_exception(operator):
    with operator.journal.operation_lock():
        with pytest.raises(SafetyError, match="正在进行"):
            with operator.journal.operation_lock():
                pass
    with pytest.raises(RuntimeError):
        with operator.journal.operation_lock():
            raise RuntimeError("simulated failure")
    with operator.journal.operation_lock():
        pass


def test_cancelled_scan_cannot_generate_plan(folder):
    (folder / "a.txt").write_text("one")
    result = replace(scan_folder(folder), cancelled=True)
    with pytest.raises(SafetyError, match="未完成"):
        classification_plan(result, {folder / "a.txt"}, folder / "target")


def test_ancestor_target_is_valid_and_not_mistaken_for_already_organized(folder, operator):
    file = folder / "a.txt"
    file.write_text("one")
    result = scan_folder(folder)
    plan = classification_plan(result, {file}, folder.parent)
    assert len(plan.items) == 1
    moved = operator.execute(plan, confirmed=True)
    assert plan.items[0].destination.read_text() == "one"
    operator.undo(moved.batch_id, confirmed=True)
    assert file.read_text() == "one"


def test_forged_quarantine_without_keeper_is_rejected(folder, operator):
    (folder / "a.txt").write_text("same")
    (folder / "b.txt").write_text("same")
    result = scan_folder(folder)
    plan = quarantine_plan(result, {folder / "b.txt"})
    with pytest.raises(SafetyError, match="保留"):
        operator.execute(replace(plan, keepers=()), confirmed=True)
    assert (folder / "b.txt").exists()
