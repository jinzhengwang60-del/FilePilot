from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from threading import Event
from typing import Callable

from .journal import Journal, record_from_item
from .models import FileRecord, MovePlan, OperationResult
from .safety import CancelledError, SafetyError, SafetyPolicy, exists_any, path_key, signature, within
from .scanner import hash_file

OperationProgress = Callable[[str, int, int, str], None]


def existing_parent(path: Path) -> Path:
    parent = path.parent
    while not parent.exists() and parent.parent != parent:
        parent = parent.parent
    return parent


class FileOperator:
    def __init__(self, journal: Journal, policy: SafetyPolicy | None = None):
        self.journal = journal
        self.policy = policy or SafetyPolicy()

    def _verify(self, file: FileRecord, cancel: Event | None = None) -> str:
        digest = hash_file(file.path, self.policy, file.signature, cancel)
        if file.digest is not None and digest != file.digest:
            raise SafetyError(f"文件内容在扫描后发生变化，请重新扫描：{file.path}")
        return digest

    def _target(self, source: Path, destination: Path) -> None:
        self.policy.check_path(destination)
        if path_key(source) == path_key(destination):
            raise SafetyError("来源和目标不能相同。")
        if exists_any(destination):
            raise SafetyError(f"目标已存在，不能覆盖；请重新生成预览：{destination}")
        if source.lstat().st_dev != existing_parent(destination).stat().st_dev:
            raise SafetyError("首版仅支持同一磁盘内移动，请选择与来源相同磁盘的目标目录。")

    def _move(self, file: FileRecord, destination: Path, digest: str) -> None:
        self._target(file.path, destination)
        self.policy.make_parents(destination.parent)
        # Revalidate immediately before the namespace operation. Windows rename refuses replacement.
        self.policy.regular_file(file.path, file.signature)
        self.policy.check_path(destination)
        if os.name == "nt":
            os.rename(file.path, destination)
        else:
            # POSIX rename replaces existing names; link() reserves a name exclusively instead.
            os.link(file.path, destination, follow_symlinks=False)
            if signature(file.path.lstat()) != file.signature:
                raise SafetyError("来源在移动时发生变化；两份路径均保留，请检查历史记录。")
            os.unlink(file.path)
        # Content stays on the same filesystem, including NTFS alternate streams on Windows.
        actual = hash_file(destination, self.policy, file.signature)
        if actual != digest:
            raise SafetyError("移动后的文件发生变化；文件仍在目标位置，请检查历史记录。")

    def execute(self, plan: MovePlan, *, confirmed: bool = False, cancel: Event | None = None,
                progress: OperationProgress | None = None) -> OperationResult:
        if confirmed is not True:
            raise SafetyError("移动前必须明确确认本次预览。")
        if not plan.items or plan.kind not in {"classify", "quarantine"}:
            raise SafetyError("移动计划为空或类型不受支持。")
        root = self.policy.scan_root(plan.root)
        target = self.policy.check_path(plan.destination_root)
        if path_key(root) == path_key(target):
            raise SafetyError("目标必须是独立的整理目录。")
        with self.journal.operation_lock():
            sources: set[str] = set()
            destinations: set[str] = set()
            digests: dict[str, str] = {}
            # Preflight the whole batch. A changed file or a new collision prevents every move.
            for index, item in enumerate(plan.items):
                source_key, target_key = path_key(item.file.path), path_key(item.destination)
                if not within(item.file.path, root) or not within(item.destination, target):
                    raise SafetyError("移动计划超出扫描或目标目录范围。")
                if source_key in sources or target_key in destinations:
                    raise SafetyError("移动计划中存在重复来源或重复目标。")
                sources.add(source_key)
                destinations.add(target_key)
                self._target(item.file.path, item.destination)
                digests[source_key] = self._verify(item.file, cancel)
                if progress:
                    progress("移动前核对", index + 1, len(plan.items), item.file.relative)
            if sources & destinations:
                raise SafetyError("目标与本次操作的来源重叠，请选择其他目录。")
            if plan.kind == "quarantine":
                keeper_digests = {keeper.digest for keeper in plan.keepers}
                if not plan.keepers or None in keeper_digests or any(item.file.digest not in keeper_digests for item in plan.items):
                    raise SafetyError("隔离计划必须为每组内容相同的文件保留一份。")
                if any(path_key(keeper.path) in sources or not within(keeper.path, root) for keeper in plan.keepers):
                    raise SafetyError("保留的文件不能在移动列表中，且必须属于扫描目录。")
            for keeper in plan.keepers:
                self._verify(keeper, cancel)
            batch_id = self.journal.begin(plan, digests)
            completed = 0
            message = ""
            for index, item in enumerate(plan.items):
                if cancel is not None and cancel.is_set():
                    message = "操作已停止；已移动的文件可以在历史记录中撤销。"
                    break
                digest = digests[path_key(item.file.path)]
                try:
                    checked = replace(item.file, digest=digest)
                    self._verify(checked, cancel)
                    self.journal.item_state(batch_id, index, "moving")
                    self._move(checked, item.destination, digest)
                except (OSError, SafetyError, CancelledError) as exc:
                    message = str(exc)
                    state = "review" if exists_any(item.destination) else "failed"
                    self.journal.item_state(batch_id, index, state, message)
                    break
                # If this durable checkpoint fails, leave 'moving' for explicit recovery.
                self.journal.item_state(batch_id, index, "moved")
                completed += 1
                if progress:
                    progress("正在移动", completed, len(plan.items), item.file.relative)
            state = "completed" if completed == len(plan.items) else "partial" if completed else "stopped"
            self.journal.batch_state(batch_id, state, message)
            return OperationResult(batch_id, state, completed, len(plan.items), message)

    def undo(self, batch_id: str, *, confirmed: bool = False, cancel: Event | None = None,
             progress: OperationProgress | None = None) -> OperationResult:
        if confirmed is not True:
            raise SafetyError("撤销前必须明确确认。")
        with self.journal.operation_lock():
            batch = self.journal.batch(batch_id)
            self.policy.scan_root(batch["root"])
            target = self.policy.check_path(batch["destination_root"])
            items = [item for item in reversed(self.journal.items(batch_id)) if item["state"] == "moved"]
            if not items:
                raise SafetyError("此记录没有可撤销的已移动文件。")
            for index, item in enumerate(items):
                file = record_from_item(item, at_destination=True)
                original = Path(item["source"])
                if not within(original, Path(batch["root"])) or not within(file.path, target):
                    raise SafetyError("历史路径超出原操作范围，撤销已阻止。")
                self._target(file.path, original)
                self._verify(file, cancel)
                if progress:
                    progress("撤销前核对", index + 1, len(items), file.path.name)
            self.journal.batch_state(batch_id, "undoing")
            completed = 0
            message = ""
            for item in items:
                if cancel is not None and cancel.is_set():
                    message = "撤销已停止；剩余文件可稍后继续撤销。"
                    break
                file = record_from_item(item, at_destination=True)
                try:
                    self._verify(file, cancel)
                    self.journal.item_state(batch_id, item["position"], "undoing")
                    self._move(file, Path(item["source"]), item["digest"])
                except (OSError, SafetyError, CancelledError) as exc:
                    message = str(exc)
                    self.journal.item_state(batch_id, item["position"], "undoing", message)
                    break
                self.journal.item_state(batch_id, item["position"], "undone")
                completed += 1
                if progress:
                    progress("正在撤销", completed, len(items), file.path.name)
            has_review = any(item["state"] in {"review", "review_undo"} for item in self.journal.items(batch_id))
            state = "needs_review" if has_review else "undone" if completed == len(items) else "partial_undo"
            self.journal.batch_state(batch_id, state, message)
            return OperationResult(batch_id, state, completed, len(items), message)

    def recover(self) -> list[str]:
        """Reconcile interrupted records. Never move, unlink, or overwrite any file."""
        recovered = []
        with self.journal.operation_lock():
            for batch in self.journal.recent(limit=10000):
                items = self.journal.items(batch["id"])
                if batch["state"] not in {"executing", "undoing", "partial_undo"} and not any(item["state"] in {"moving", "undoing", "review", "review_undo"} for item in items):
                    continue
                for item in items:
                    if item["state"] not in {"moving", "undoing", "review", "review_undo"}:
                        continue
                    source, destination = Path(item["source"]), Path(item["destination"])
                    undoing = item["state"] in {"undoing", "review_undo"}
                    present = source if undoing else destination
                    absent = destination if undoing else source
                    state = "review_undo" if undoing else "review"
                    message = "路径或文件内容存在歧义，需人工检查；文件未被改动。"
                    try:
                        file = record_from_item(item, at_destination=not undoing)
                        if exists_any(present) and not exists_any(absent):
                            self._verify(file)
                            state = "undone" if undoing else "moved"
                            message = "已核对中断后的文件位置和内容。"
                        elif not exists_any(present) and exists_any(absent):
                            file = record_from_item(item, at_destination=undoing)
                            self._verify(file)
                            state = "moved" if undoing else "failed"
                            message = "操作尚未移动文件。"
                    except (OSError, SafetyError) as exc:
                        message = str(exc)
                    self.journal.item_state(batch["id"], item["position"], state, message)
                current = self.journal.items(batch["id"])
                states = {item["state"] for item in current}
                state = ("needs_review" if states & {"review", "review_undo"} else "undone" if states == {"undone"}
                         else "completed" if states == {"moved"} else "partial" if "moved" in states else "stopped")
                self.journal.batch_state(batch["id"], state, "中断记录已核对；未自动移动或删除文件。")
                recovered.append(batch["id"])
        return recovered
