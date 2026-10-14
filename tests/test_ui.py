import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QEventLoop, QPoint, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from filepilot.journal import Journal
from filepilot.ui import MainWindow, PreviewDialog


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    app.setQuitOnLastWindowClosed(False)
    return app


def wait_for(window, timeout=8):
    if window._thread is not None:
        loop = QEventLoop()
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        window._thread.finished.connect(loop.quit)
        timer.start(int(timeout * 1000))
        loop.exec()
        timer.stop()
    assert window._thread is None, "Background worker did not finish"


@pytest.fixture
def window(qapp, folder, tmp_path, monkeypatch):
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda parent, title, message: warnings.append(message))
    widget = MainWindow(Journal(tmp_path / "ui-state" / "history.sqlite3"), root=folder)
    widget.show()
    QTest.qWait(20)
    yield widget
    widget.close()
    wait_for(widget)
    qapp.processEvents()
    assert not warnings, warnings


def test_preview_requires_checkbox_and_cancel_does_not_move(qapp, folder):
    file = folder / "a.txt"
    file.write_text("one")
    dialog = PreviewDialog([(str(file), str(folder / "target" / "a.txt"), "test")], "预览", "确认移动")
    dialog.show()
    QTest.qWait(20)
    assert not dialog.confirm.isEnabled()
    QTest.mouseClick(dialog.acknowledge, Qt.MouseButton.LeftButton, pos=QPoint(8, dialog.acknowledge.height() // 2))
    assert dialog.confirm.isEnabled()
    dialog.reject()
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert file.read_text() == "one"


def test_gui_scan_and_real_checkbox_interaction(window, folder):
    (folder / "a.txt").write_text("one")
    (folder / "b.py").write_text("print(1)")
    QTest.mouseClick(window.scan_button, Qt.MouseButton.LeftButton)
    wait_for(window)
    assert len(window.result.files) == 2
    assert not window.preview_button.isEnabled()
    index = window.file_proxy.index(0, 0)
    QTest.mouseClick(window.file_table.viewport(), Qt.MouseButton.LeftButton, pos=window.file_table.visualRect(index).center())
    assert len(window.file_model.checked) == 1
    assert window.preview_button.isEnabled()


def test_gui_full_scan_preview_move_history_undo_flow(window, folder, monkeypatch):
    original = {"a.txt": b"one", "b.py": b"print(1)"}
    for name, content in original.items():
        (folder / name).write_bytes(content)
    window.start_scan()
    wait_for(window)
    window.select_visible(False)
    seen = []
    def approve(dialog):
        assert not dialog.confirm.isEnabled()
        dialog.acknowledge.setChecked(True)
        assert dialog.confirm.isEnabled()
        seen.append(dialog.table.rowCount())
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(PreviewDialog, "exec", approve)
    window.preview_classification()
    wait_for(window)
    assert window.stack.currentIndex() == 2
    assert window.journal.recent()[0]["state"] == "completed"
    assert window.result is None  # No stale scan can execute again.
    assert all(not (folder / name).exists() for name in original)
    window.preview_undo()
    wait_for(window)
    assert seen == [2, 2]
    assert window.journal.recent()[0]["state"] == "undone"
    assert all((folder / name).read_bytes() == content for name, content in original.items())


def test_cancelled_dialog_keeps_files_unchanged(window, folder, monkeypatch):
    (folder / "a.txt").write_text("one")
    window.start_scan()
    wait_for(window)
    window.select_visible(False)
    monkeypatch.setattr(PreviewDialog, "exec", lambda dialog: QDialog.DialogCode.Rejected)
    window.preview_classification()
    assert window._thread is None
    assert window.journal.recent() == []
    assert (folder / "a.txt").read_text() == "one"


def test_filter_selection_only_selects_visible_files(window, folder):
    (folder / "a.txt").write_text("one")
    (folder / "b.py").write_text("print(1)")
    window.start_scan()
    wait_for(window)
    window.file_proxy.setFilterFixedString(".py")
    window.select_visible(False)
    assert window.file_model.checked == {folder / "b.py"}


def test_changing_root_invalidates_scan(window, folder, tmp_path):
    (folder / "a.txt").write_text("one")
    window.start_scan()
    wait_for(window)
    window.select_visible(False)
    other = tmp_path / "other"
    other.mkdir()
    window.root_input.setText(str(other))
    assert window.result is None
    assert not window.preview_button.isEnabled()


def test_close_requests_cancellation_and_waits_for_worker(window):
    def working(progress):
        while not window._cancel.is_set():
            time.sleep(0.01)
        return []
    window.start_job(working, lambda result: None)
    window.close()
    wait_for(window)
    assert not window.isVisible()
