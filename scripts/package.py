"""Package already validated local builds without traversing links or test fixtures."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import zipfile

PROJECT = Path(__file__).resolve().parents[1]
RELEASE = PROJECT / "release"
SKIP = {".git", ".venv", ".build-tools", ".pytest_cache", "__pycache__", "build", "dist", "release", "demo-files", "artifacts"}


def is_reparse(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def regular_files(root: Path, *, source: bool = False):
    if is_reparse(root):
        raise RuntimeError("Do not package linked directories")
    for current, directories, files in os.walk(root, followlinks=False):
        folder = Path(current)
        directories[:] = sorted(name for name in directories if not is_reparse(folder / name)
                                 and (not source or name not in SKIP and not name.endswith(".egg-info")))
        for name in sorted(files):
            path = folder / name
            if source and (name == ".env" or name.startswith(".env.") or ".sqlite" in name.lower()
                           or name.lower().endswith((".db", ".lock", ".pyc"))):
                continue
            if not is_reparse(path) and stat.S_ISREG(path.lstat().st_mode):
                yield path


def package():
    if RELEASE.resolve().parent != PROJECT.resolve():
        raise RuntimeError("Release directory must stay inside the project")
    RELEASE.mkdir(exist_ok=True)
    binary_root = PROJECT / "dist" / "FilePilot"
    if not (binary_root / "FilePilot.exe").is_file():
        raise RuntimeError("Build FilePilot first")
    for report in ("frozen-smoke.json", "ui-verification.json"):
        payload = json.loads((PROJECT / "artifacts" / report).read_text(encoding="utf-8-sig"))
        if not payload.get("ok"):
            raise RuntimeError("Verify FilePilot before packaging")
    windows = RELEASE / "FilePilot-v0.1.0-windows-x64.zip"
    source = RELEASE / "FilePilot-v0.1.0-source.zip"
    with zipfile.ZipFile(windows, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in regular_files(binary_root):
            archive.write(path, "FilePilot/" + path.relative_to(binary_root).as_posix())
        archive.write(PROJECT / "README.md", "FilePilot/README.md")
        archive.write(PROJECT / "THIRD_PARTY.md", "FilePilot/THIRD_PARTY.md")
        for path in regular_files(PROJECT / "docs"):
            archive.write(path, "FilePilot/docs/" + path.relative_to(PROJECT / "docs").as_posix())
    with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in regular_files(PROJECT, source=True):
            archive.write(path, "FilePilot/" + path.relative_to(PROJECT).as_posix())
    manifest = {}
    for path in (windows, source):
        with path.open("rb") as stream:
            manifest[path.name] = {"size": path.stat().st_size, "sha256": hashlib.file_digest(stream, "sha256").hexdigest()}
    (RELEASE / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (RELEASE / "SHA256SUMS.txt").write_text("\n".join(f"{data['sha256']}  {name}" for name, data in manifest.items()) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    package()
