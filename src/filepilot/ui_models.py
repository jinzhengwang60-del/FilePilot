from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QColor

from .models import FileRecord, ScanResult, format_bytes


class FileTableModel(QAbstractTableModel):
    selection_changed = Signal()

    def __init__(self, *, duplicates: bool = False, parent=None):
        super().__init__(parent)
        self.duplicates = duplicates
        self.files: list[FileRecord] = []
        self.checked: set[Path] = set()
        self.notes: dict[Path, str] = {}
        self.suggested_copies: set[Path] = set()

    def set_result(self, result: ScanResult | None) -> None:
        self.beginResetModel()
        self.checked.clear()
        self.notes.clear()
        self.suggested_copies.clear()
        if result is None:
            self.files = []
        elif self.duplicates:
            self.files = []
            for index, group in enumerate(result.duplicates, 1):
                for position, file in enumerate(group.files):
                    self.files.append(file)
                    self.notes[file.path] = f"组 {index:02d} · {'建议保留' if position == 0 else '可隔离的副本'}"
                    if position:
                        self.suggested_copies.add(file.path)
        else:
            self.files = list(result.files)
        self.endResetModel()
        self.selection_changed.emit()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.files)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 6

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return ("选择", "文件名", "类型", "大小", "相对路径", "重复组 / 建议" if self.duplicates else "整理建议")[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.files):
            return None
        file = self.files[index.row()]
        column = index.column()
        if role == Qt.ItemDataRole.CheckStateRole and column == 0:
            return Qt.CheckState.Checked if file.path in self.checked else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.DisplayRole:
            return ("", file.path.name, file.category, format_bytes(file.size), file.relative,
                    self.notes.get(file.path, f"→ {file.category} /"))[column]
        if role == Qt.ItemDataRole.UserRole:
            return file.size if column == 3 else self.data(index, Qt.ItemDataRole.DisplayRole)
        if role == Qt.ItemDataRole.ToolTipRole:
            return str(file.path) + (f"\nSHA-256: {file.digest}" if file.digest else "")
        if role == Qt.ItemDataRole.ForegroundRole:
            return QColor("#236e64" if column == 5 else "#69778b" if column in (2, 3, 4) else "#1d2b40")
        if role == Qt.ItemDataRole.TextAlignmentRole and column == 3:
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        return None

    def flags(self, index):
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        return flags | Qt.ItemFlag.ItemIsUserCheckable if index.column() == 0 else flags

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if index.isValid() and index.column() == 0 and role == Qt.ItemDataRole.CheckStateRole:
            path = self.files[index.row()].path
            if value == Qt.CheckState.Checked.value or value == Qt.CheckState.Checked:
                self.checked.add(path)
            else:
                self.checked.discard(path)
            self.dataChanged.emit(index, index, [role])
            self.selection_changed.emit()
            return True
        return False

    def select_paths(self, paths: set[Path]) -> None:
        self.checked = paths & {file.path for file in self.files}
        if self.files:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.files) - 1, 0), [Qt.ItemDataRole.CheckStateRole])
        self.selection_changed.emit()
