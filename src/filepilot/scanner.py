from __future__ import annotations

import hashlib
import os
import stat
import time
from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from threading import Event
from typing import Callable

from .categories import classify
from .models import DuplicateGroup, FileRecord, ScanIssue, ScanResult
from .safety import CancelledError, SafetyError, SafetyPolicy, is_link_or_reparse, signature

CHUNK_SIZE = 1024 * 1024
IGNORED_NAMES = frozenset({".git", ".venv", "__pycache__", "node_modules", ".filepilot-quarantine", "filepilot_整理"})
Progress = Callable[[str, int, int, str], None]


def hash_file(path: Path, policy: SafetyPolicy, expected: tuple[int, int, int, int] | None = None,
              cancel: Event | None = None) -> str:
    before = policy.regular_file(path, expected)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    digest = hashlib.sha256()
    with os.fdopen(os.open(path, flags), "rb") as stream:
        if signature(os.fstat(stream.fileno())) != signature(before):
            raise SafetyError(f"文件在读取前发生变化：{path}")
        while True:
            if cancel is not None and cancel.is_set():
                raise CancelledError("操作已取消。")
            chunk = stream.read(CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
        if signature(os.fstat(stream.fileno())) != signature(before):
            raise SafetyError(f"文件在读取时发生变化：{path}")
    policy.regular_file(path, signature(before))
    return digest.hexdigest()


def scan_folder(root: Path | str, *, recursive: bool = True, include_hidden: bool = False,
                policy: SafetyPolicy | None = None, cancel: Event | None = None,
                progress: Progress | None = None) -> ScanResult:
    policy = policy or SafetyPolicy()
    root = policy.scan_root(root)
    start = time.monotonic()
    records: list[FileRecord] = []
    issues: list[ScanIssue] = []
    stack = [root]
    seen: set[tuple[int, int]] = set()
    cancelled = False
    last_report = 0.0
    while stack:
        if cancel is not None and cancel.is_set():
            cancelled = True
            break
        folder = stack.pop()
        try:
            policy.check_path(folder)
            info = folder.lstat()
            identity = info.st_dev, info.st_ino
            if identity in seen:
                issues.append(ScanIssue(folder, "重复目录标识，已跳过以避免循环"))
                continue
            seen.add(identity)
            with os.scandir(folder) as iterator:
                for entry in iterator:
                    if cancel is not None and cancel.is_set():
                        cancelled = True
                        break
                    path = Path(entry.path)
                    try:
                        # Windows DirEntry's cached stat may report dev/ino/nlink as zero.
                        # lstat obtains the actual identity used by open/fstat and move checks.
                        info = path.lstat()
                        if is_link_or_reparse(info):
                            issues.append(ScanIssue(path, "符号链接、联接点或重解析点"))
                            continue
                        if policy.protected(path):
                            issues.append(ScanIssue(path, "系统或敏感目录"))
                            continue
                        if entry.name.casefold() in IGNORED_NAMES:
                            issues.append(ScanIssue(path, "应用输出目录或开发缓存"))
                            continue
                        if not include_hidden and (entry.name.startswith(".") or getattr(info, "st_file_attributes", 0) & 0x2):
                            issues.append(ScanIssue(path, "隐藏文件或文件夹"))
                            continue
                        if stat.S_ISDIR(info.st_mode):
                            if recursive:
                                stack.append(path)
                        elif stat.S_ISREG(info.st_mode):
                            if info.st_nlink > 1:
                                issues.append(ScanIssue(path, "硬链接文件不参与整理"))
                                continue
                            records.append(FileRecord(path, str(path.relative_to(root)), info.st_size,
                                                      info.st_mtime_ns, info.st_dev, info.st_ino, classify(path)))
                        else:
                            issues.append(ScanIssue(path, "不是普通文件或文件夹"))
                        if progress and time.monotonic() - last_report > 0.1:
                            progress("扫描文件", len(records), 0, str(path))
                            last_report = time.monotonic()
                    except (OSError, SafetyError) as exc:
                        issues.append(ScanIssue(path, str(exc)))
        except (OSError, SafetyError) as exc:
            issues.append(ScanIssue(folder, str(exc)))

    by_size: dict[int, list[int]] = defaultdict(list)
    for index, record in enumerate(records):
        by_size[record.size].append(index)
    candidates = [index for indices in by_size.values() if len(indices) > 1 for index in indices]
    by_hash: dict[str, list[FileRecord]] = defaultdict(list)
    hashed = 0
    if not cancelled:
        for index in candidates:
            record = records[index]
            try:
                digest = hash_file(record.path, policy, record.signature, cancel)
                records[index] = replace(record, digest=digest)
                by_hash[digest].append(records[index])
                hashed += 1
                if progress:
                    progress("核对重复文件", hashed, len(candidates), record.relative)
            except CancelledError:
                cancelled = True
                break
            except (OSError, SafetyError) as exc:
                issues.append(ScanIssue(record.path, str(exc)))
    # Cancelled scans are inspection-only. Never offer actions from a partial result.
    groups = [] if cancelled else [DuplicateGroup(digest, tuple(sorted(files, key=lambda f: (f.mtime_ns, f.relative.casefold()))))
                                  for digest, files in by_hash.items() if len(files) > 1]
    return ScanResult(root, tuple(sorted(records, key=lambda f: f.relative.casefold())),
                      tuple(sorted(groups, key=lambda g: (-g.extra_bytes, g.digest))), tuple(issues),
                      time.monotonic() - start, hashed, cancelled)
