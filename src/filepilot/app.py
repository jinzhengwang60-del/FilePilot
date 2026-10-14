from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FilePilot · 预览优先的本地文件整理")
    parser.add_argument("--root", type=Path, help="预填扫描目录；不会自动扫描或移动")
    parser.add_argument("--data-dir", type=Path, help="历史数据库目录，默认使用用户本地应用数据目录")
    parser.add_argument("--demo", action="store_true", help="在当前目录创建或加载专用演示文件夹")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--smoke-test", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    # Keep the CLI and core importable without Qt installed.
    from PySide6 import __version__ as pyside_version
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox
    from .demo import create_demo
    from .journal import Journal, default_data_dir
    from .ui import MainWindow

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("FilePilot")
    app.setOrganizationName("FilePilot")
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    try:
        root = create_demo(Path.cwd() / "demo-files") if args.demo else args.root
        data_dir = args.data_dir or default_data_dir()
        window = MainWindow(Journal(data_dir / "history.sqlite3"), root=root)
    except Exception as exc:
        if args.smoke_test:
            args.smoke_test.parent.mkdir(parents=True, exist_ok=True)
            args.smoke_test.write_text(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), encoding="utf-8")
        else:
            QMessageBox.critical(None, "FilePilot 无法启动", str(exc))
        return 1
    window.show()
    if args.smoke_test:
        def report_and_exit() -> None:
            args.smoke_test.parent.mkdir(parents=True, exist_ok=True)
            screenshot = args.smoke_test.with_suffix(".png")
            image_saved = window.grab().save(str(screenshot))
            payload = {"ok": bool(image_saved), "filepilot": __version__, "python": sys.version.split()[0],
                       "pyside6": pyside_version, "pages": window.stack.count(), "screenshot": str(screenshot),
                       "database_created": window.journal.path.is_file(), "frozen": bool(getattr(sys, "frozen", False))}
            args.smoke_test.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            app.exit(0 if image_saved else 1)
        QTimer.singleShot(700, report_and_exit)
    return app.exec()
