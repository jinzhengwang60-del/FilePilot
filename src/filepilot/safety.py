from __future__ import annotations

import os
import stat
from dataclasses import dataclass, field
from pathlib import Path


class SafetyError(ValueError):
    """An actionable safety check prevented a filesystem operation."""


class CancelledError(Exception):
    pass


def absolute(path: Path | str) -> Path:
    # Do not resolve links before checking them: resolve() hides the linked path.
    return Path(os.path.abspath(os.path.expanduser(os.fspath(path))))


def path_key(path: Path | str) -> str:
    return os.path.normcase(os.fspath(absolute(path)))


def within(path: Path, parent: Path) -> bool:
    try:
        return os.path.commonpath((path_key(path), path_key(parent))) == path_key(parent)
    except ValueError:
        return False


def is_link_or_reparse(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def signature(info: os.stat_result) -> tuple[int, int, int, int]:
    return info.st_size, info.st_mtime_ns, info.st_dev, info.st_ino


def default_protected_roots() -> tuple[Path, ...]:
    if os.name == "nt":
        drive = os.environ.get("SystemDrive", "C:")
        candidates = [os.environ.get(name) for name in ("WINDIR", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMDATA")]
        candidates.extend([f"{drive}/Windows", f"{drive}/Program Files", f"{drive}/Program Files (x86)",
                           f"{drive}/ProgramData", str(Path.home() / "AppData")])
    else:
        candidates = ["/etc", "/proc", "/sys", "/dev", "/boot", "/usr", "/bin", "/sbin", "/var"]
    candidates.extend(str(Path.home() / name) for name in (".ssh", ".aws", ".gnupg"))
    return tuple(absolute(path) for path in candidates if path)


@dataclass(frozen=True)
class SafetyPolicy:
    protected_roots: tuple[Path, ...] = field(default_factory=default_protected_roots)

    def protected(self, path: Path) -> bool:
        if any(within(path, root) for root in self.protected_roots):
            return True
        return any(part.casefold() in {"system volume information", "$recycle.bin", "recovery", "appdata", ".ssh", ".aws", ".gnupg"} for part in path.parts)

    def check_path(self, path: Path | str) -> Path:
        raw = os.fspath(path)
        if os.name == "nt" and (raw.startswith("\\\\") or ":" in raw[2:]):
            raise SafetyError("仅支持本地普通路径；不支持网络路径、设备路径或 NTFS 数据流。")
        result = absolute(path)
        if self.protected(result):
            raise SafetyError(f"系统或敏感目录已受保护：{result}")
        self.check_ancestors(result)
        return result

    def check_ancestors(self, path: Path) -> None:
        for node in reversed((path, *path.parents)):
            try:
                info = node.lstat()
            except FileNotFoundError:
                continue
            if is_link_or_reparse(info):
                raise SafetyError(f"已跳过符号链接、联接点或重解析点：{node}")
            if node != path and not stat.S_ISDIR(info.st_mode):
                raise SafetyError(f"路径的父级不是文件夹：{node}")

    def scan_root(self, path: Path | str) -> Path:
        root = self.check_path(path)
        if root.parent == root:
            raise SafetyError("请选择一个具体文件夹，不能扫描整个磁盘根目录。")
        if not root.is_dir():
            raise SafetyError(f"文件夹不存在：{root}")
        return root

    def regular_file(self, path: Path, expected: tuple[int, int, int, int] | None = None) -> os.stat_result:
        checked = self.check_path(path)
        info = checked.lstat()
        if not stat.S_ISREG(info.st_mode) or is_link_or_reparse(info):
            raise SafetyError(f"不是普通文件：{path}")
        if info.st_nlink > 1:
            raise SafetyError(f"硬链接文件不参与整理：{path}")
        if expected is not None and signature(info) != expected:
            raise SafetyError(f"文件在扫描后发生了变化，请重新扫描：{path}")
        return info

    def make_parents(self, directory: Path) -> None:
        self.check_path(directory)
        missing = []
        node = directory
        while not exists_any(node):
            missing.append(node)
            node = node.parent
        for node in reversed(missing):
            self.check_ancestors(node.parent)
            try:
                node.mkdir()
            except FileExistsError:
                pass
            self.check_ancestors(node)
        self.check_path(directory)
        if not directory.is_dir():
            raise SafetyError(f"目标不是文件夹：{directory}")


def exists_any(path: Path) -> bool:
    # lexists includes dangling symlinks, which must also reserve a name.
    return os.path.lexists(path)
