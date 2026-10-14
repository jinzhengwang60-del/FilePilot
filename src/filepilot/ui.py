from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
from threading import Event
from typing import Callable

from PySide6.QtCore import QObject, QSortFilterProxyModel, QThread, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QDesktopServices, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QDialog, QFileDialog, QFrame,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressBar,
    QPushButton, QStackedWidget, QTableView, QTableWidget, QTableWidgetItem, QTextEdit,
    QVBoxLayout, QWidget,
)

from . import __version__
from .journal import Journal
from .models import MovePlan, OperationResult, ScanResult, format_bytes
from .operations import FileOperator
from .planner import classification_plan, quarantine_plan
from .safety import CancelledError, SafetyError, absolute, path_key
from .scanner import scan_folder
from .ui_models import FileTableModel

STYLE = """
QWidget { font-family: 'Microsoft YaHei UI', 'Segoe UI', sans-serif; font-size: 13px; color: #1d2b40; }
QMainWindow, QWidget#Content { background: #f4f6fa; }
QFrame#Sidebar { background: #152339; }
QFrame#Sidebar QLabel { color: #a6b4c8; background: transparent; }
QFrame#Sidebar QLabel#Brand { color: white; font-size: 23px; font-weight: 700; }
QFrame#Sidebar QLabel#Mark { background: #5b83ee; color: white; border-radius: 12px; font-size: 24px; font-weight: 700; }
QPushButton#Nav { background: transparent; color: #b8c6d9; border: none; text-align: left; padding: 14px 16px; border-radius: 9px; font-size: 14px; }
QPushButton#Nav:checked { background: #293b57; color: white; font-weight: 600; }
QPushButton#Nav:hover { background: #223550; }
QLabel#Title { font-size: 27px; font-weight: 700; color: #172a45; }
QLabel#Subtle { color: #718097; }
QLabel#Section { font-size: 15px; font-weight: 600; }
QLabel#StatValue { font-size: 25px; font-weight: 650; color: #243d61; }
QFrame#Card { background: white; border: 1px solid #e2e7ef; border-radius: 12px; }
QPushButton { background: white; border: 1px solid #d8dfe9; border-radius: 7px; padding: 8px 14px; min-height: 18px; }
QPushButton:hover { background: #edf2ff; border-color: #b7c8f4; }
QPushButton:disabled { color: #a6afbd; background: #f1f3f7; border-color: #e0e5ee; }
QPushButton#Primary { background: #4f75de; color: white; border: 1px solid #4f75de; font-weight: 600; }
QPushButton#Primary:hover { background: #4065cf; }
QPushButton#Primary:disabled { background: #b5c5e9; border-color: #b5c5e9; color: #f8faff; }
QLineEdit { background: #fafbfd; border: 1px solid #dde4ed; padding: 9px 11px; border-radius: 7px; selection-background-color: #4f75de; }
QLineEdit:focus { border-color: #7494ed; }
QTableView, QTableWidget { background: white; border: none; gridline-color: #eef1f6; selection-background-color: #e9effc; selection-color: #1d2b40; outline: none; }
QTableView::item, QTableWidget::item { padding: 6px 8px; border-bottom: 1px solid #eef1f6; }
QHeaderView::section { background: #f8f9fc; color: #728199; border: none; border-bottom: 1px solid #e3e8f0; padding: 10px 8px; font-weight: 600; }
QTextEdit { background: #fafbfd; border: 1px solid #e1e7ef; border-radius: 8px; padding: 10px; }
QCheckBox { spacing: 7px; }
QCheckBox::indicator { width: 16px; height: 16px; }
QProgressBar { border: none; background: #e5eaf4; border-radius: 3px; max-height: 6px; text-align: center; }
QProgressBar::chunk { background: #4f75de; border-radius: 3px; }
QScrollBar:vertical { background: #f5f7fb; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #c7d2e3; border-radius: 4px; min-height: 25px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QDialog { background: #f4f6fa; }
"""

STATE_NAMES = {"completed": "已完成", "partial": "部分完成", "stopped": "已停止", "executing": "待核对中断",
               "undoing": "待核对撤销", "undone": "已撤销", "partial_undo": "部分撤销", "needs_review": "需要检查"}
ITEM_NAMES = {"planned": "未执行", "moving": "待核对", "moved": "已移动", "undone": "已撤销", "failed": "未移动",
              "review": "需要检查", "review_undo": "撤销需要检查", "undoing": "撤销待核对"}


def label(text: str, name: str = "") -> QLabel:
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    if name:
        widget.setObjectName(name)
    return widget


def configure_fonts() -> None:
    # The Windows offscreen QPA can have an empty font database. Use an installed
    # Windows font when available; never redistribute the operating system's fonts.
    if os.name == "nt" and not QFontDatabase.families():
        font_dir = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        for filename in ("msyh.ttc", "segoeui.ttf"):
            path = font_dir / filename
            if path.is_file():
                QFontDatabase.addApplicationFont(str(path))
    if "Microsoft YaHei UI" in QFontDatabase.families():
        QApplication.instance().setFont(QFont("Microsoft YaHei UI", 10))


def configure_palette() -> None:
    # A fixed light stylesheet must use a matching palette, including native
    # checkbox indicators. Windows can otherwise supply a dark system palette.
    palette = QPalette()
    for role, color in {
        QPalette.ColorRole.Window: "#f4f6fa", QPalette.ColorRole.WindowText: "#1d2b40",
        QPalette.ColorRole.Base: "#ffffff", QPalette.ColorRole.AlternateBase: "#f8f9fc",
        QPalette.ColorRole.ToolTipBase: "#ffffff", QPalette.ColorRole.ToolTipText: "#1d2b40",
        QPalette.ColorRole.Text: "#1d2b40", QPalette.ColorRole.Button: "#ffffff",
        QPalette.ColorRole.ButtonText: "#1d2b40", QPalette.ColorRole.Highlight: "#4f75de",
        QPalette.ColorRole.HighlightedText: "#ffffff", QPalette.ColorRole.Link: "#4f75de",
    }.items():
        palette.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor("#a6afbd"))
    QApplication.instance().setPalette(palette)


def button(text: str, callback: Callable | None = None, *, primary: bool = False) -> QPushButton:
    widget = QPushButton(text)
    if primary:
        widget.setObjectName("Primary")
    if callback:
        widget.clicked.connect(callback)
    return widget


class Worker(QObject):
    result = Signal(object)
    error = Signal(str)
    progress = Signal(str, int, int, str)
    done = Signal()

    def __init__(self, function: Callable):
        super().__init__()
        self.function = function

    @Slot()
    def run(self) -> None:
        try:
            self.result.emit(self.function(self.progress.emit))
        except CancelledError:
            self.error.emit("操作已取消，尚未开始的文件保持原位。")
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self.done.emit()


class PreviewDialog(QDialog):
    def __init__(self, rows: list[tuple[str, str, str]], title: str, action: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(1030, 590)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(14)
        layout.addWidget(label(title, "Title"))
        layout.addWidget(label(f"共 {len(rows)} 个文件 · 同名文件不会被覆盖 · 操作完成后可以撤销", "Subtle"))
        source_root = destination_root = None
        if rows:
            source_root = Path(os.path.commonpath([str(Path(row[0]).parent) for row in rows]))
            destination_root = Path(os.path.commonpath([str(Path(row[1]).parent) for row in rows]))
            for name, root in (("来源", source_root), ("目标", destination_root)):
                description = label(f"{name}：{root}", "Subtle")
                description.setWordWrap(True)
                description.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                layout.addWidget(description)
        self.table = QTableWidget(len(rows), 3)
        self.table.setHorizontalHeaderLabels(["来源内相对路径", "目标内相对路径", "原因"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                shown = str(Path(value).relative_to(source_root if column == 0 else destination_root)) if column < 2 else value
                item = QTableWidgetItem(shown)
                item.setToolTip(value)
                self.table.setItem(row, column, item)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)
        self.acknowledge = QCheckBox("我已核对来源与目标，同意执行这次操作")
        layout.addWidget(self.acknowledge)
        footer = QHBoxLayout()
        footer.addStretch()
        footer.addWidget(button("返回检查", self.reject))
        self.confirm = button(action, self.accept, primary=True)
        self.confirm.setEnabled(False)
        self.acknowledge.toggled.connect(self.confirm.setEnabled)
        footer.addWidget(self.confirm)
        layout.addLayout(footer)

    @classmethod
    def for_plan(cls, plan: MovePlan, parent=None) -> "PreviewDialog":
        title = "确认分类整理" if plan.kind == "classify" else "确认移入隔离区"
        return cls([(str(item.file.path), str(item.destination), item.reason) for item in plan.items],
                   title, f"确认移动 {len(plan.items)} 个文件", parent)


class MainWindow(QMainWindow):
    def __init__(self, journal: Journal, *, root: Path | None = None):
        super().__init__()
        configure_fonts()
        configure_palette()
        self.journal = journal
        self.operator = FileOperator(journal)
        self.result: ScanResult | None = None
        self._thread: QThread | None = None
        self._worker: Worker | None = None
        self._cancel = Event()
        self._closing = False
        self._history_rows: list[dict] = []
        self.setWindowTitle(f"FilePilot · 本地文件整理  {__version__}")
        self.resize(1280, 860)
        self.setMinimumSize(1040, 720)
        self._build_ui()
        if root is not None:
            self.root_input.setText(str(root))
        self.refresh_history()
        self._update_actions()

    def _build_ui(self) -> None:
        container = QWidget()
        main = QHBoxLayout(container)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(208)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(18, 28, 18, 24)
        side.setSpacing(12)
        brand = QHBoxLayout()
        mark = label("F", "Mark")
        mark.setFixedSize(42, 42)
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand.addWidget(mark)
        brand.addWidget(label("FilePilot", "Brand"))
        side.addLayout(brand)
        side.addWidget(label("给文件一个好位置"))
        side.addSpacing(28)
        side.addWidget(label("工作空间"))
        self.nav_group = QButtonGroup(self)
        self.nav_buttons = []
        for index, text in enumerate(("01   文件整理", "02   重复检查", "03   操作历史")):
            nav = button(text)
            nav.setObjectName("Nav")
            nav.setCheckable(True)
            nav.clicked.connect(lambda checked=False, page=index: self.navigate(page))
            self.nav_group.addButton(nav, index)
            self.nav_buttons.append(nav)
            side.addWidget(nav)
        self.nav_buttons[0].setChecked(True)
        side.addStretch()
        side.addWidget(label("●  仅在本地处理"))
        foot = label("扫描只读 · 移动可撤销\n\nv" + __version__)
        foot.setWordWrap(True)
        side.addWidget(foot)
        main.addWidget(sidebar)
        content = QWidget()
        content.setObjectName("Content")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 23, 28, 22)
        layout.setSpacing(15)
        heading = QHBoxLayout()
        title_box = QVBoxLayout()
        self.breadcrumb = label("工作空间  /  文件整理", "Subtle")
        self.title_label = label("让文件，各归其位。", "Title")
        title_box.addWidget(self.breadcrumb)
        title_box.addWidget(self.title_label)
        title_box.addWidget(label("先看清文件，再决定如何整理。每一步由你确认。", "Subtle"))
        heading.addLayout(title_box)
        heading.addStretch()
        heading.addWidget(button("使用说明", self.show_help))
        layout.addLayout(heading)
        scan_card = QFrame()
        scan_card.setObjectName("Card")
        scan_layout = QVBoxLayout(scan_card)
        scan_layout.setContentsMargins(18, 14, 18, 14)
        scan_layout.addWidget(label("要整理的文件夹", "Section"))
        path_bar = QHBoxLayout()
        self.root_input = QLineEdit()
        self.root_input.setPlaceholderText("选择一个具体文件夹，例如下载或项目素材文件夹")
        self.root_input.textChanged.connect(self._root_changed)
        self.browse_button = button("选择文件夹", self.choose_root)
        self.scan_button = button("只读扫描", self.start_scan, primary=True)
        path_bar.addWidget(self.root_input, 1)
        path_bar.addWidget(self.browse_button)
        path_bar.addWidget(self.scan_button)
        scan_layout.addLayout(path_bar)
        options = QHBoxLayout()
        self.recursive = QCheckBox("包含子文件夹")
        self.recursive.setChecked(True)
        self.hidden = QCheckBox("包含隐藏文件")
        options.addWidget(self.recursive)
        options.addWidget(self.hidden)
        self.issues_button = button("查看跳过项", self.show_issues)
        self.issues_button.setEnabled(False)
        options.addWidget(self.issues_button)
        options.addStretch()
        self.cancel_button = button("停止", self.cancel_job)
        self.cancel_button.setEnabled(False)
        options.addWidget(self.cancel_button)
        scan_layout.addLayout(options)
        self.scan_summary = label("尚未扫描 · 文件保持原位", "Subtle")
        self.scan_summary.setWordWrap(True)
        scan_layout.addWidget(self.scan_summary)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()
        scan_layout.addWidget(self.progress_bar)
        layout.addWidget(scan_card)
        stats = QHBoxLayout()
        self.stat_labels = []
        for name, hint in (("文件数量", "当前扫描范围"), ("文件总大小", "不含跳过项"), ("重复副本大小", "隔离后仍保留文件"), ("已跳过", "保护目录 / 无法访问")):
            card = QFrame()
            card.setObjectName("Card")
            box = QVBoxLayout(card)
            box.setContentsMargins(16, 12, 16, 12)
            box.addWidget(label(name, "Subtle"))
            number = label("—", "StatValue")
            self.stat_labels.append(number)
            box.addWidget(number)
            box.addWidget(label(hint, "Subtle"))
            stats.addWidget(card, 1)
        layout.addLayout(stats)
        self.stack = QStackedWidget()
        self.file_model = FileTableModel(parent=self)
        self.duplicate_model = FileTableModel(duplicates=True, parent=self)
        self.file_model.selection_changed.connect(self._update_actions)
        self.duplicate_model.selection_changed.connect(self._update_actions)
        self.stack.addWidget(self._file_page(False))
        self.stack.addWidget(self._file_page(True))
        self.stack.addWidget(self._history_page())
        layout.addWidget(self.stack, 1)
        main.addWidget(content, 1)
        self.setCentralWidget(container)
        self.setStyleSheet(STYLE)

    def _file_page(self, duplicates: bool) -> QWidget:
        page = QFrame()
        page.setObjectName("Card")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)
        toolbar = QHBoxLayout()
        toolbar.addWidget(label("内容相同的文件" if duplicates else "文件与分类建议", "Section"))
        toolbar.addStretch()
        search = QLineEdit()
        search.setPlaceholderText("搜索文件名、类型或路径")
        search.setMaximumWidth(240)
        toolbar.addWidget(search)
        select = button("勾选建议副本" if duplicates else "勾选筛选结果",
                        lambda: self.select_visible(duplicates))
        clear = button("清空勾选", lambda: (self.duplicate_model if duplicates else self.file_model).select_paths(set()))
        toolbar.addWidget(select)
        toolbar.addWidget(clear)
        layout.addLayout(toolbar)
        table = QTableView()
        model = self.duplicate_model if duplicates else self.file_model
        proxy = QSortFilterProxyModel(self)
        proxy.setSourceModel(model)
        proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        proxy.setFilterKeyColumn(-1)
        proxy.setSortRole(Qt.ItemDataRole.UserRole)
        table.setModel(proxy)
        search.textChanged.connect(proxy.setFilterFixedString)
        table.setSortingEnabled(True)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.verticalHeader().hide()
        table.verticalHeader().setDefaultSectionSize(42)
        table.setShowGrid(False)
        widths = (45, 185, 70, 95, 230, 180)
        for column, width in enumerate(widths):
            table.setColumnWidth(column, width)
        table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        table.doubleClicked.connect(lambda index: self.open_parent(model.files[proxy.mapToSource(index).row()].path))
        layout.addWidget(table, 1)
        if duplicates:
            self.duplicate_table, self.duplicate_proxy = table, proxy
            self.duplicate_selection = label("每组至少保留一份；建议保留较早修改的文件。", "Subtle")
            footer = QHBoxLayout()
            footer.addWidget(self.duplicate_selection, 1)
            self.quarantine_button = button("预览隔离副本", self.preview_quarantine, primary=True)
            footer.addWidget(self.quarantine_button)
            layout.addLayout(footer)
        else:
            self.file_table, self.file_proxy = table, proxy
            output = QHBoxLayout()
            output.addWidget(label("整理到"))
            self.destination_input = QLineEdit()
            self.destination_input.setPlaceholderText("扫描后默认使用来源文件夹中的 FilePilot_整理")
            output.addWidget(self.destination_input, 1)
            self.target_button = button("更改目录", self.choose_target)
            output.addWidget(self.target_button)
            layout.addLayout(output)
            footer = QHBoxLayout()
            self.file_selection = label("先选择文件夹并扫描，再勾选需要整理的文件。", "Subtle")
            footer.addWidget(self.file_selection, 1)
            self.preview_button = button("预览分类整理", self.preview_classification, primary=True)
            footer.addWidget(self.preview_button)
            layout.addLayout(footer)
        return page

    def _history_page(self) -> QWidget:
        page = QFrame()
        page.setObjectName("Card")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 14, 16, 14)
        toolbar = QHBoxLayout()
        toolbar.addWidget(label("操作历史", "Section"))
        toolbar.addStretch()
        toolbar.addWidget(button("刷新记录", self.refresh_history))
        self.recover_button = button("检查中断记录", self.recover_history)
        toolbar.addWidget(self.recover_button)
        layout.addLayout(toolbar)
        self.history_table = QTableWidget(0, 5)
        self.history_table.setHorizontalHeaderLabels(["时间", "操作", "已移动 / 总数", "状态", "扫描目录"])
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.history_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.history_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.history_table.verticalHeader().hide()
        self.history_table.verticalHeader().setDefaultSectionSize(38)
        self.history_table.setColumnWidth(0, 155)
        self.history_table.setColumnWidth(1, 100)
        self.history_table.setColumnWidth(2, 115)
        self.history_table.setColumnWidth(3, 100)
        self.history_table.horizontalHeader().setStretchLastSection(True)
        self.history_table.itemSelectionChanged.connect(self._history_selected)
        layout.addWidget(self.history_table, 2)
        self.history_details = QTextEdit()
        self.history_details.setReadOnly(True)
        self.history_details.setPlaceholderText("选择一条记录，查看每个文件的来源、去向和处理状态。")
        layout.addWidget(self.history_details, 1)
        footer = QHBoxLayout()
        footer.addWidget(label("撤销前会再次检查文件内容和原位置，避免覆盖。", "Subtle"), 1)
        self.undo_button = button("撤销选中操作", self.preview_undo, primary=True)
        self.undo_button.setEnabled(False)
        footer.addWidget(self.undo_button)
        layout.addLayout(footer)
        return page

    def navigate(self, page: int) -> None:
        self.stack.setCurrentIndex(page)
        self.nav_buttons[page].setChecked(True)
        self.breadcrumb.setText("工作空间  /  " + ("文件整理", "重复检查", "操作历史")[page])
        self.title_label.setText(("让文件，各归其位。", "重复的内容，看清再处理。", "每一步，都有来路。")[page])
        if page == 2:
            self.refresh_history()

    def _root_changed(self, value: str) -> None:
        if self.result is not None and path_key(value or ".") != path_key(self.result.root):
            self.invalidate_scan()
            self.destination_input.clear()
            self.scan_summary.setText("扫描目录已改变，请重新扫描。")
        if hasattr(self, "scan_button"):
            self._update_actions()

    def choose_root(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "选择要扫描的文件夹", self.root_input.text() or str(Path.home()))
        if chosen:
            self.root_input.setText(chosen)

    def choose_target(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "选择同一磁盘上的整理目录", self.root_input.text())
        if chosen:
            self.destination_input.setText(chosen)

    def _update_actions(self) -> None:
        busy = self._thread is not None
        ready = self.result is not None and not self.result.cancelled and not busy
        if hasattr(self, "scan_button"):
            self.scan_button.setEnabled(bool(self.root_input.text().strip()) and not busy)
        if hasattr(self, "preview_button"):
            self.preview_button.setEnabled(ready and bool(self.file_model.checked))
            self.file_selection.setText(f"已勾选 {len(self.file_model.checked)} 个文件 · 双击可打开所在文件夹" if self.result else "先选择文件夹并扫描，再勾选需要整理的文件。")
        if hasattr(self, "quarantine_button"):
            self.quarantine_button.setEnabled(ready and bool(self.duplicate_model.checked))
            self.duplicate_selection.setText(f"已勾选 {len(self.duplicate_model.checked)} 个副本 · 每组至少保留一份")
        if hasattr(self, "issues_button"):
            self.issues_button.setEnabled(self.result is not None and bool(self.result.issues) and not busy)
        if hasattr(self, "undo_button"):
            self._history_selected()

    def select_visible(self, duplicates: bool) -> None:
        model = self.duplicate_model if duplicates else self.file_model
        proxy = self.duplicate_proxy if duplicates else self.file_proxy
        paths = {model.files[proxy.mapToSource(proxy.index(row, 0)).row()].path for row in range(proxy.rowCount())}
        model.select_paths(model.checked | (paths & model.suggested_copies if duplicates else paths))

    def start_scan(self) -> None:
        root = self.root_input.text().strip()
        recursive, hidden = self.recursive.isChecked(), self.hidden.isChecked()
        self.invalidate_scan()
        self.start_job(lambda progress: scan_folder(root, recursive=recursive, include_hidden=hidden,
                                                    cancel=self._cancel, progress=progress), self.display_scan)

    def start_job(self, function: Callable, callback: Callable) -> None:
        if self._thread is not None:
            return
        self._cancel = Event()
        self._thread = QThread(self)
        self._worker = Worker(function)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.result.connect(callback)
        self._worker.error.connect(self._job_error)
        self._worker.progress.connect(self._progress)
        self._worker.done.connect(self._thread.quit)
        self._worker.done.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._job_finished)
        self._thread.finished.connect(self._thread.deleteLater)
        for widget in (self.root_input, self.browse_button, self.recursive, self.hidden, self.destination_input, self.target_button, self.recover_button):
            widget.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.show()
        self.scan_summary.setText("正在核对文件，请稍候……")
        self._update_actions()
        self._thread.start()

    @Slot(str, int, int, str)
    def _progress(self, phase: str, done: int, total: int, current: str) -> None:
        self.progress_bar.setRange(0, total)
        if total:
            self.progress_bar.setValue(done)
        short = current if len(current) < 100 else "…" + current[-99:]
        self.scan_summary.setText(f"{phase} · {done}{' / ' + str(total) if total else ''} · {short}")

    @Slot(str)
    def _job_error(self, message: str) -> None:
        self.scan_summary.setText("操作已停止 · " + message)
        self.refresh_history()
        if not self._closing:
            QMessageBox.warning(self, "操作未完成", message)

    @Slot()
    def _job_finished(self) -> None:
        self._thread = None
        self._worker = None
        self.cancel_button.setEnabled(False)
        self.progress_bar.hide()
        for widget in (self.root_input, self.browse_button, self.recursive, self.hidden, self.destination_input, self.target_button, self.recover_button):
            widget.setEnabled(True)
        self._update_actions()
        if self._closing:
            self.close()

    def cancel_job(self) -> None:
        self._cancel.set()
        self.cancel_button.setEnabled(False)
        self.scan_summary.setText("正在停止，等待当前文件安全处理完毕……")

    def invalidate_scan(self) -> None:
        self.result = None
        self.file_model.set_result(None)
        self.duplicate_model.set_result(None)
        for stat_label in self.stat_labels:
            stat_label.setText("—")

    @Slot(object)
    def display_scan(self, result: ScanResult) -> None:
        self.result = result
        self.file_model.set_result(result)
        self.duplicate_model.set_result(result)
        values = (str(len(result.files)), format_bytes(result.total_bytes), format_bytes(result.extra_bytes), str(len(result.issues)))
        for stat_label, text in zip(self.stat_labels, values):
            stat_label.setText(text)
        if not self.destination_input.text().strip():
            self.destination_input.setText(str(result.root / "FilePilot_整理"))
        self.scan_summary.setText(f"{'扫描已停止，仅供查看' if result.cancelled else '只读扫描完成'} · {len(result.files)} 个文件 · {len(result.duplicates)} 组重复 · 用时 {result.elapsed:.1f} 秒")
        self.scan_summary.setToolTip("\n".join(f"{issue.path}：{issue.reason}" for issue in result.issues[:100]))
        self._update_actions()

    def _preview(self, plan: MovePlan) -> None:
        if PreviewDialog.for_plan(plan, self).exec() == QDialog.DialogCode.Accepted:
            self.start_job(lambda progress: self.operator.execute(plan, confirmed=True, cancel=self._cancel, progress=progress),
                           self.operation_finished)

    def preview_classification(self) -> None:
        if self.result is None:
            return
        try:
            if not self.destination_input.text().strip():
                raise SafetyError("请先填写或选择整理目标目录。")
            self._preview(classification_plan(self.result, self.file_model.checked, self.destination_input.text()))
        except (OSError, SafetyError) as exc:
            QMessageBox.warning(self, "无法生成预览", str(exc))

    def preview_quarantine(self) -> None:
        if self.result is None:
            return
        try:
            self._preview(quarantine_plan(self.result, self.duplicate_model.checked))
        except (OSError, SafetyError) as exc:
            QMessageBox.warning(self, "无法生成预览", str(exc))

    @Slot(object)
    def operation_finished(self, result: OperationResult) -> None:
        self.invalidate_scan()
        self.navigate(2)
        self.scan_summary.setText(f"{STATE_NAMES.get(result.state, result.state)} · 已处理 {result.completed} / {result.total} 个文件 · 继续整理前请重新扫描")
        if result.message and not self._closing:
            QMessageBox.warning(self, "操作结果", result.message)

    def refresh_history(self) -> None:
        if not hasattr(self, "history_table"):
            return
        self._history_rows = self.journal.recent()
        self.history_table.setRowCount(len(self._history_rows))
        for row, batch in enumerate(self._history_rows):
            stamp = datetime.fromisoformat(batch["created"]).astimezone().strftime("%m-%d %H:%M:%S")
            values = (stamp, "分类整理" if batch["kind"] == "classify" else "隔离副本",
                      f"{batch['moved']} / {batch['total']}", STATE_NAMES.get(batch["state"], batch["state"]), batch["root"])
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.history_table.setItem(row, column, item)
        self.history_details.clear()
        if self._history_rows:
            self.history_table.selectRow(0)
        self._history_selected()

    def _history_selected(self) -> None:
        row = self.history_table.currentRow() if hasattr(self, "history_table") else -1
        if not hasattr(self, "undo_button"):
            return
        batch = self._history_rows[row] if 0 <= row < len(self._history_rows) else None
        self.undo_button.setEnabled(batch is not None and bool(batch["moved"]) and self._thread is None)
        if batch:
            items = self.journal.items(batch["id"])
            lines = [f"{STATE_NAMES.get(batch['state'], batch['state'])} · {batch['message']}"]
            for item in items:
                lines.append(f"\n[{ITEM_NAMES.get(item['state'], item['state'])}] {item['source']}\n  → {item['destination']}" + (f"\n  {item['message']}" if item['message'] else ""))
            self.history_details.setPlainText("\n".join(lines))

    def preview_undo(self) -> None:
        row = self.history_table.currentRow()
        if not 0 <= row < len(self._history_rows):
            return
        batch = self._history_rows[row]
        items = [item for item in self.journal.items(batch["id"]) if item["state"] == "moved"]
        dialog = PreviewDialog([(item["destination"], item["source"], "恢复到原来的位置") for item in items],
                               "确认撤销这次操作", f"确认撤销 {len(items)} 个文件", self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.start_job(lambda progress: self.operator.undo(batch["id"], confirmed=True, cancel=self._cancel, progress=progress),
                           self.operation_finished)

    def recover_history(self) -> None:
        self.start_job(lambda progress: self.operator.recover(), self.recovery_finished)

    def recovery_finished(self, ids: list[str]) -> None:
        self.refresh_history()
        self.scan_summary.setText(f"已检查 {len(ids)} 条中断记录 · 检查过程未移动或删除文件")

    def open_parent(self, file: Path) -> None:
        try:
            self.operator.policy.check_path(file.parent)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(file.parent)))
        except (OSError, SafetyError) as exc:
            QMessageBox.warning(self, "无法打开文件夹", str(exc))

    def show_help(self) -> None:
        QMessageBox.information(self, "FilePilot 使用说明",
            "1. 选择具体文件夹，点击「只读扫描」。\n"
            "2. 勾选文件，预览来源和目标，核对后确认移动。\n"
            "3. 在「重复检查」中查看内容相同的文件；副本可以移入隔离区。\n"
            "4. 在「操作历史」中预览并确认撤销。\n\n"
            "默认跳过系统敏感目录、符号链接、联接点、重解析点、硬链接和开发缓存。\n"
            "首版仅支持同一磁盘内移动。文件内容不上传，没有永久删除功能。\n"
            "隔离区保留副本，因此隔离不会立刻释放磁盘空间。")

    def show_issues(self) -> None:
        if self.result is None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("扫描中跳过的项目")
        dialog.resize(1000, 550)
        layout = QVBoxLayout(dialog)
        layout.addWidget(label(f"已跳过 {len(self.result.issues)} 项", "Section"))
        table = QTableWidget(len(self.result.issues), 2)
        table.setHorizontalHeaderLabels(["路径", "原因"])
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.verticalHeader().hide()
        for row, issue in enumerate(self.result.issues):
            for column, text in enumerate((str(issue.path), issue.reason)):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                table.setItem(row, column, item)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(table)
        layout.addWidget(button("关闭", dialog.accept))
        dialog.exec()

    def closeEvent(self, event) -> None:
        if self._thread is not None:
            self._closing = True
            self.cancel_job()
            event.ignore()
        else:
            event.accept()
