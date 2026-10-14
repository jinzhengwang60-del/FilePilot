"""Capture the actual read-only demo UI using a public, relative directory name."""
from __future__ import annotations

import os
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from filepilot.demo import create_demo
from filepilot.journal import Journal
from filepilot.scanner import scan_folder
from filepilot.ui import MainWindow


def main() -> None:
    os.chdir(PROJECT)
    demo = create_demo(Path("demo-files"))
    output = PROJECT / "docs" / "screenshots"
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    app.setStyle("Fusion")
    window = MainWindow(Journal(PROJECT / "artifacts" / "qa-state" / "screenshots.sqlite3"),
                        root=Path("demo-files"))
    window.show()
    window.display_scan(scan_folder(demo))
    # Relative paths are valid user inputs. The core still works with checked absolute paths.
    window.destination_input.setText(str(Path("demo-files") / "FilePilot_整理"))
    window.file_model.select_paths({demo / name for name in
                                    ("旅行计划.txt", "照片/封面.png", "代码/hello.py")})
    app.processEvents()
    if not window.grab().save(str(output / "files.png")):
        raise RuntimeError("Could not save the files screenshot")
    window.navigate(1)
    window.select_visible(True)
    app.processEvents()
    if not window.grab().save(str(output / "duplicates.png")):
        raise RuntimeError("Could not save the duplicates screenshot")
    window.close()
    print("Captured two actual demo pages without moving files.")


if __name__ == "__main__":
    main()
