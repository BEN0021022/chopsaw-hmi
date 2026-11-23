import json
import os
import shutil
from typing import Callable, List, Optional

from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from cut_list_parser import parse_cut_list_lines
from cut_optimizer import (
    format_cuts_as_lines,
    format_summary_text,
    optimize_cut_list,
    summarize_cut_list,
)


class CutListManagerTab(QWidget):
    def __init__(
        self,
        storage_path: str,
        on_load_lines: Callable[[List[str]], None],
        on_switch_to_auto: Optional[Callable[[], None]] = None,
        log_fn: Callable[[str], None] | None = None,
        get_board_length: Optional[Callable[[], float]] = None,
        get_kerf: Optional[Callable[[], float]] = None,
    ):
        super().__init__()
        self.storage_path = storage_path
        self.on_load_lines = on_load_lines
        self.on_switch_to_auto = on_switch_to_auto
        self.log_fn = log_fn
        self._get_board_length = get_board_length or (lambda: 144.0)
        self._get_kerf = get_kerf or (lambda: 0.1)

        self.lists = []
        self._pre_optimize_text: Optional[str] = None
        self._build_ui()
        self._load_storage()
        self.refresh_summary()

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

        self.summary_label = QLabel("No cuts in editor")
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet(
            "color: #93c5fd; font-size: 13px; padding: 4px 8px; "
            "background: #0b1222; border: 1px solid #1e293b; border-radius: 6px;"
        )
        right.addWidget(self.summary_label)

        self.editor = QTextEdit()
        self.editor.setPlaceholderText("Enter one cut per line, e.g.\n72\n36\n35")
        self.editor.textChanged.connect(self.refresh_summary)
        right.addWidget(self.editor, 1)

        self.optimize_feedback = QLabel("")
        self.optimize_feedback.setWordWrap(True)
        self.optimize_feedback.setStyleSheet("color: #4ade80; font-size: 13px;")
        self.optimize_feedback.hide()
        right.addWidget(self.optimize_feedback)

        right_btns = QHBoxLayout()
        self.optimize_btn = QPushButton("Optimize Boards")
        self.optimize_btn.setToolTip(
            "Pack cuts onto the fewest boards using Branch-and-Bound, "
            "concentrating scrap into one reusable offcut and placing each board's longest cut last."
        )
        self.optimize_btn.setStyleSheet(
            "background-color: #0284c7; color: white; font-weight: 600;"
        )
        self.optimize_btn.clicked.connect(self._optimize_editor_list)

        self.undo_optimize_btn = QPushButton("Undo Optimize")
        self.undo_optimize_btn.setEnabled(False)
        self.undo_optimize_btn.clicked.connect(self._undo_optimize)

        self.save_btn = QPushButton("Save List")
        self.save_btn.setProperty("class", "accent")
        self.save_btn.clicked.connect(self._save_list)

        self.load_btn = QPushButton("Load into AUTO")
        self.load_btn.setStyleSheet("background-color: #2563eb; color: white; font-weight: 600;")
        self.load_btn.clicked.connect(self._load_into_auto)

        right_btns.addWidget(self.optimize_btn)
        right_btns.addWidget(self.undo_optimize_btn)
        right_btns.addWidget(self.save_btn)
        right_btns.addWidget(self.load_btn)
        right.addLayout(right_btns)

        root.addLayout(left, 1)
        root.addLayout(right, 2)

    def _log(self, message: str):
        if self.log_fn:
            self.log_fn(message)

    def _backup_path(self) -> str:
        return self.storage_path + ".bak"

    def _read_json_file(self, path: str):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or not isinstance(data.get("lists"), list):
            raise ValueError("Cut list JSON missing 'lists' array")
        return data["lists"]

    def _load_storage(self):
        self.lists = []
        if os.path.exists(self.storage_path):
            try:
                self.lists = self._read_json_file(self.storage_path)
            except Exception as exc:
                self._log(f"Cut list storage read error: {exc}")
                backup = self._backup_path()
                if os.path.exists(backup):
                    try:
                        self.lists = self._read_json_file(backup)
                        self._log("Recovered saved cut lists from backup (.bak).")
                    except Exception as bak_exc:
                        self._log(f"Cut list backup read error: {bak_exc}")
        self._refresh_list_widget()

    def _save_storage(self):
        parent = os.path.dirname(self.storage_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        payload = json.dumps({"lists": self.lists}, indent=2)
        tmp_path = self.storage_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        if os.path.exists(self.storage_path):
            try:
                shutil.copy2(self.storage_path, self._backup_path())
            except OSError:
                pass
        os.replace(tmp_path, self.storage_path)

    def _refresh_list_widget(self):
        self.list_widget.clear()
        for item in self.lists:
            self.list_widget.addItem(item.get("name", "Untitled"))

    def refresh_summary(self):
        raw = self.editor.toPlainText()
        cuts, _ = parse_cut_list_lines(raw.splitlines())
        if not cuts:
            self.summary_label.setText("No cuts in editor")
            return
        summary = summarize_cut_list(cuts, self._get_board_length(), self._get_kerf())
        self.summary_label.setText(format_summary_text(summary))

    def _clear_optimize_undo(self):
        self._pre_optimize_text = None
        self.undo_optimize_btn.setEnabled(False)
        self.optimize_feedback.hide()

    def _optimize_editor_list(self):
        raw = self.editor.toPlainText()
        cuts, _ = parse_cut_list_lines(raw.splitlines())
        if not cuts:
            QMessageBox.information(self, "Empty List", "Enter cuts in the editor before optimizing.")
            return
        board_len = self._get_board_length()
        kerf = self._get_kerf()
        result = optimize_cut_list(cuts, board_len, kerf)
        self._pre_optimize_text = raw
        self.undo_optimize_btn.setEnabled(True)
        self.editor.setText("\n".join(format_cuts_as_lines(result.cuts)))

        if result.boards_saved > 0:
            msg = (
                f"Optimized ({'exact' if result.optimal else 'best found'} in {result.elapsed_ms:.0f} ms): "
                f"{result.before.board_count} → {result.after.board_count} boards "
                f"(saved {result.boards_saved}), best offcut {result.after.largest_offcut_in:.1f}\"."
            )
        elif result.after.largest_offcut_in > result.before.largest_offcut_in + 0.05:
            msg = (
                f"Minimum {result.after.board_count} boards ({result.elapsed_ms:.0f} ms): "
                f"improved largest usable offcut from {result.before.largest_offcut_in:.1f}\" "
                f"to {result.after.largest_offcut_in:.1f}\"."
            )
        else:
            msg = (
                f"Already at minimum {result.after.board_count} boards ({result.elapsed_ms:.0f} ms); "
                "reordered each board with longest cut last."
            )
        if result.oversized:
            msg += f" Warning: {len(result.oversized)} cut(s) exceed {board_len:g}\" board length."
        self.optimize_feedback.setText(msg)
        self.optimize_feedback.show()
        self._log(msg)

    def _undo_optimize(self):
        if self._pre_optimize_text is None:
            return
        previous = self._pre_optimize_text
        self._clear_optimize_undo()
        self.editor.setText(previous)
        self._log("Restored pre-optimization cut list order.")

    def _new_list(self):
        self.list_widget.clearSelection()
        self.name_input.setText("")
        self.editor.setText("")
        self._clear_optimize_undo()

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
        self._clear_optimize_undo()
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
