from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from .models import FileRecord, MoveItem, MovePlan, ScanResult
from .safety import SafetyError, SafetyPolicy, exists_any, path_key, within


def _choose_name(destination: Path, reserved: set[str]) -> Path:
    original = destination
    counter = 2
    while exists_any(destination) or path_key(destination) in reserved:
        if counter > 10000:
            raise SafetyError("同名文件过多，请选择其他目标目录。")
        destination = original.with_name(f"{original.stem} ({counter}){original.suffix}")
        counter += 1
    reserved.add(path_key(destination))
    return destination


def _select(result: ScanResult, paths: set[Path]) -> tuple[FileRecord, ...]:
    if result.cancelled:
        raise SafetyError("本次扫描未完成，请重新扫描后再整理。")
    keys = {path_key(path) for path in paths}
    files = tuple(record for record in result.files if path_key(record.path) in keys)
    if len(files) != len(keys):
        raise SafetyError("选择中包含不属于本次扫描的文件。")
    if not files:
        raise SafetyError("请先勾选要处理的文件。")
    return files


def classification_plan(result: ScanResult, selected: set[Path], destination: Path | str,
                        policy: SafetyPolicy | None = None) -> MovePlan:
    policy = policy or SafetyPolicy()
    target = policy.check_path(destination)
    if path_key(target) == path_key(result.root):
        raise SafetyError("请选择一个独立的整理目录，不能直接使用扫描目录。")
    reserved: set[str] = set()
    items = []
    for record in _select(result, selected):
        if within(target, result.root) and within(record.path, target):
            continue
        if path_key(target / record.category / record.path.name) == path_key(record.path):
            continue
        path = _choose_name(target / record.category / record.path.name, reserved)
        policy.check_path(path)
        items.append(MoveItem(record, path, f"按扩展名建议归入「{record.category}」"))
    if not items:
        raise SafetyError("勾选文件已在整理目录中，无需移动。")
    return MovePlan(result.root, target, "classify", tuple(items))


def quarantine_plan(result: ScanResult, selected: set[Path], policy: SafetyPolicy | None = None) -> MovePlan:
    policy = policy or SafetyPolicy()
    files = _select(result, selected)
    keys = {path_key(file.path) for file in files}
    duplicate_keys = {path_key(file.path) for group in result.duplicates for file in group.files}
    if not keys <= duplicate_keys:
        raise SafetyError("隔离操作只能选择已确认内容相同的重复文件。")
    keepers = []
    for group in result.duplicates:
        if any(path_key(file.path) in keys for file in group.files):
            remaining = [file for file in group.files if path_key(file.path) not in keys]
            if not remaining:
                raise SafetyError("每组重复文件必须至少保留一份，请减少勾选。")
            keepers.append(remaining[0])
    target = policy.check_path(result.root / ".filepilot-quarantine" / uuid4().hex[:12])
    reserved: set[str] = set()
    items = tuple(MoveItem(file, _choose_name(target / file.relative, reserved), "内容相同；移入隔离区，保留文件并可撤销") for file in files)
    return MovePlan(result.root, target, "quarantine", items, tuple(keepers))
