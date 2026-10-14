"""Render the actual Qt application and exercise a complete disposable file workflow."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

project = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
from filepilot.demo import create_demo
from filepilot.journal import Journal
from filepilot.planner import classification_plan
from filepilot.scanner import scan_folder
from filepilot.ui import MainWindow, PreviewDialog


def wait(window):
    if window._thread is not None:
        loop = QEventLoop()
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        window._thread.finished.connect(loop.quit)
        timer.start(30000)
        loop.exec()
        timer.stop()
    assert window._thread is None


def main():
    output = project / "artifacts"
    output.mkdir(exist_ok=True)
    demo = create_demo(project / "demo-files")
    app = QApplication([])
    app.setStyle("Fusion")
    app.setQuitOnLastWindowClosed(False)
    window = MainWindow(Journal(output / "qa-state" / "history.sqlite3"), root=demo)
    window.show()
    window.start_scan()
    wait(window)
    assert window.result is not None and len(window.result.files) == 15
    selected = {demo / name for name in ("旅行计划.txt", "照片/封面.png", "代码/hello.py")}
    window.file_model.select_paths(selected)
    app.processEvents()
    assert window.grab().save(str(output / "filepilot-files.png"))
    window.navigate(1)
    window.select_visible(True)
    app.processEvents()
    assert window.grab().save(str(output / "filepilot-duplicates.png"))
    plan = classification_plan(window.result, selected, demo / "FilePilot_整理")
    preview = PreviewDialog.for_plan(plan, window)
    preview.show()
    app.processEvents()
    assert preview.grab().save(str(output / "filepilot-preview.png"))
    preview.reject()
    # Only disposable generated demo files are moved; the selected preview is reused exactly.
    moved = window.operator.execute(plan, confirmed=True)
    window.navigate(2)
    app.processEvents()
    assert window.grab().save(str(output / "filepilot-history.png"))
    undone = window.operator.undo(moved.batch_id, confirmed=True)
    checked = scan_folder(demo)
    assert len(checked.files) == 15 and len(checked.duplicates) == 3
    report = {"ok": True, "files": len(checked.files), "duplicate_groups": len(checked.duplicates),
              "moved": moved.completed, "undone": undone.completed, "restored": all(path.is_file() for path in selected),
              "screenshots": ["filepilot-files.png", "filepilot-duplicates.png", "filepilot-preview.png", "filepilot-history.png"]}
    (output / "ui-verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    window.close()
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
