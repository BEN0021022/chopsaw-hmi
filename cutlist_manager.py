import json
import os
from typing import Callable, List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QTextEdit,
    QLineEdit,
    QMessageBox,
)


class CutListManagerTab(QWidget):
    def __init__(
        self,
        storage_path: str,
        on_load_lines: Callable[[List[str]], None],
        on_switch_to_auto: Optional[Callable[[], None]] = None,
        log_fn: Callable[[str], None] | None = None,
    ):
        super().__init__()
        self.storage_path = storage_path
        self.on_load_lines = on_load_lines
        self.on_switch_to_auto = on_switch_to_auto
        self.log_fn = log_fn

        self.lists = []
        self._build_ui()
        self._load_storage()

    def _build_ui(self):
        root = QHBoxLayout(self)

        left = QVBoxLayout()
        left_label = QLabel("Saved Cut Lists")
        left_label.setStyleSheet("font-weight: bold; font-size: 16px;")
        left.addWidget(left_label)

        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet(
            "font-size: 16px; background-color: #0b1222; color: #e2e8f0; border: 1px solid #334155;"
        )
        self.list_widget.currentRowChanged.connect(self._on_select_list)
        left.addWidget(self.list_widget, 1)

        left_btns = QHBoxLayout()
        self.new_btn = QPushButton("New List")
        self.new_btn.clicked.connect(self._new_list)
        self.duplicate_btn = QPushButton("Duplicate")
        self.duplicate_btn.clicked.connect(self._duplicate_list)
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.clicked.connect(self._delete_list)
        left_btns.addWidget(self.new_btn)
        left_btns.addWidget(self.duplicate_btn)
        left_btns.addWidget(self.delete_btn)
        left.addLayout(left_btns)

        right = QVBoxLayout()
        right_label = QLabel("Cut List Editor")
        right_label.setStyleSheet("font-weight: bold; font-size: 16px;")
        right.addWidget(right_label)

        name_row = QHBoxLayout()
        name_label = QLabel("Name:")
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Example: 12ft Cedar Runs")
        name_row.addWidget(name_label)
        name_row.addWidget(self.name_input, 1)
        right.addLayout(name_row)

        self.editor = QTextEdit()
        self.editor.setPlaceholderText("Enter one cut per line, e.g.\n72\n36\n35")
        right.addWidget(self.editor, 1)

        right_btns = QHBoxLayout()
        self.save_btn = QPushButton("Save List")
        self.save_btn.setProperty("class", "accent")
        self.save_btn.clicked.connect(self._save_list)
        self.load_btn = QPushButton("Load into AUTO")
        self.load_btn.setStyleSheet("background-color: #2563eb; color: white; font-weight: 600;")
        self.load_btn.clicked.connect(self._load_into_auto)
        right_btns.addWidget(self.save_btn)
        right_btns.addWidget(self.load_btn)
        right.addLayout(right_btns)

        root.addLayout(left, 1)
        root.addLayout(right, 2)

    def _log(self, message: str):
        if self.log_fn:
            self.log_fn(message)

    def _load_storage(self):
        self.lists = []
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.lists = data.get("lists", [])
            except Exception as exc:
                self._log(f"Cut list storage read error: {exc}")
        self._refresh_list_widget()

    def _save_storage(self):
        os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
        data = {"lists": self.lists}
        with open(self.storage_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def _refresh_list_widget(self):
        self.list_widget.clear()
        for item in self.lists:
            self.list_widget.addItem(item.get("name", "Untitled"))

    def _new_list(self):
        self.list_widget.clearSelection()
        self.name_input.setText("")
        self.editor.setText("")

    def _duplicate_list(self):
        index = self.list_widget.currentRow()
        if index < 0 or index >= len(self.lists):
            QMessageBox.warning(self, "Select List", "Select a cut list to duplicate.")
            return
        source = self.lists[index]
        base_name = source.get("name", "Untitled") + " Copy"
        existing_names = {item.get("name", "Untitled") for item in self.lists}
        name = base_name
        counter = 2
        while name in existing_names:
            name = f"{base_name} {counter}"
            counter += 1
        new_item = {"name": name, "raw_text": source.get("raw_text", "")}
        self.lists.append(new_item)
        self._save_storage()
        self._refresh_list_widget()
        self.list_widget.setCurrentRow(len(self.lists) - 1)
        self._log(f"Duplicated cut list as '{name}'.")

    def _on_select_list(self, index: int):
        if index < 0 or index >= len(self.lists):
            return
        item = self.lists[index]
        self.name_input.setText(item.get("name", ""))
        self.editor.setText(item.get("raw_text", ""))

    def _save_list(self):
        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Missing Name", "Please enter a name for the cut list.")
            return
        raw_text = self.editor.toPlainText().strip()
        selected_index = self.list_widget.currentRow()
        duplicate_index = next(
            (i for i, item in enumerate(self.lists) if item.get("name") == name and i != selected_index),
            None,
        )
        if duplicate_index is not None:
            QMessageBox.warning(self, "Duplicate Name", "A cut list with that name already exists.")
            return
        if 0 <= selected_index < len(self.lists):
            self.lists[selected_index] = {"name": name, "raw_text": raw_text}
        else:
            self.lists.append({"name": name, "raw_text": raw_text})
        self._save_storage()
        self._refresh_list_widget()
        updated_index = next(
            (i for i, item in enumerate(self.lists) if item.get("name") == name and item.get("raw_text") == raw_text),
            -1,
        )
        if updated_index >= 0:
            self.list_widget.setCurrentRow(updated_index)
        self._log(f"Saved cut list '{name}'.")

    def _delete_list(self):
        index = self.list_widget.currentRow()
        if index < 0 or index >= len(self.lists):
            return
        name = self.lists[index].get("name", "Untitled")
        confirm = QMessageBox.question(
            self,
            "Delete Cut List",
            f"Delete '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self.lists.pop(index)
        self._save_storage()
        self._refresh_list_widget()
        self._new_list()
        self._log(f"Deleted cut list '{name}'.")

    def _load_into_auto(self):
        raw_text = self.editor.toPlainText().strip()
        if not raw_text:
            QMessageBox.warning(self, "Empty List", "No cut list data to load.")
            return
        lines = raw_text.splitlines()
        self.on_load_lines(lines)
        if self.on_switch_to_auto:
            self.on_switch_to_auto()
        self._log("Loaded cut list into AUTO tab.")
