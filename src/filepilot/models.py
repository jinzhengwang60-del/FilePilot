from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FileRecord:
    path: Path
    relative: str
    size: int
    mtime_ns: int
    device: int
    inode: int
    category: str
    digest: str | None = None

    @property
    def signature(self) -> tuple[int, int, int, int]:
        return self.size, self.mtime_ns, self.device, self.inode


@dataclass(frozen=True)
class ScanIssue:
    path: Path
    reason: str


@dataclass(frozen=True)
class DuplicateGroup:
    digest: str
    files: tuple[FileRecord, ...]

    @property
    def extra_bytes(self) -> int:
        return self.files[0].size * (len(self.files) - 1)


@dataclass(frozen=True)
class ScanResult:
    root: Path
    files: tuple[FileRecord, ...]
    duplicates: tuple[DuplicateGroup, ...]
    issues: tuple[ScanIssue, ...]
    elapsed: float
    hashed_count: int
    cancelled: bool = False

    @property
    def total_bytes(self) -> int:
        return sum(file.size for file in self.files)

    @property
    def extra_bytes(self) -> int:
        return sum(group.extra_bytes for group in self.duplicates)


@dataclass(frozen=True)
class MoveItem:
    file: FileRecord
    destination: Path
    reason: str


@dataclass(frozen=True)
class MovePlan:
    root: Path
    destination_root: Path
    kind: str
    items: tuple[MoveItem, ...]
    keepers: tuple[FileRecord, ...] = ()


@dataclass(frozen=True)
class OperationResult:
    batch_id: str
    state: str
    completed: int
    total: int
    message: str = ""


def format_bytes(value: int) -> str:
    amount = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if amount < 1024 or unit == "TB":
            return f"{amount:.0f} {unit}" if unit == "B" else f"{amount:.1f} {unit}"
        amount /= 1024
    return str(value)
