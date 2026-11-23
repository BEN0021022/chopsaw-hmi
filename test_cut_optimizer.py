"""Tests for Branch-and-Bound cut-list optimizer, job summary, and crash-safe cut-list storage."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import tempfile
import unittest

from PyQt6.QtWidgets import QApplication

from cut_optimizer import (
    _heuristic_pack,
    format_cuts_as_lines,
    format_summary_text,
    optimize_cut_list,
    summarize_cut_list,
)
from cutlist_manager import CutListManagerTab


class CutOptimizerTests(unittest.TestCase):
    def test_branch_and_bound_beats_both_ffd_and_bfd(self):
        # Classic 3-board optimum (sum = 300) where greedy FFD and BFD both need 4 boards:
        # Optimal: (48+27+25=100), (48+27+25=100), (46+28+26=100)
        raw = [48, 48, 46, 28, 27, 27, 26, 25, 25]
        sizes = [v * 10_000 for v in raw]
        self.assertEqual(len(_heuristic_pack(sizes, 100 * 10_000, best_fit=False)), 4)
        self.assertEqual(len(_heuristic_pack(sizes, 100 * 10_000, best_fit=True)), 4)

        cuts = [(i + 1, float(v), f"part {i + 1}") for i, v in enumerate(raw)]
        result = optimize_cut_list(cuts, board_length=100.0, kerf=0.0, time_limit_s=0.5)
        self.assertTrue(result.optimal)
        self.assertEqual(result.after.board_count, 3)
        self.assertEqual(result.boards_saved, 1)
        self.assertAlmostEqual(result.after.waste_in, 0.0, places=4)
        self.assertEqual(sorted(c[1] for c in result.cuts), sorted(float(v) for v in raw))
        self.assertEqual(
            sorted(c[2] for c in result.cuts),
            sorted(f"part {i + 1}" for i in range(len(raw))),
        )

    def test_tie_breaker_concentrates_scrap_into_largest_offcut(self):
        # Board 100, kerf 0: [60, 40, 30, 30] -> 2 boards either way:
        #   Split evenly: (60+30=90, rem 10) + (40+30=70, rem 30) -> max offcut 30
        #   Concentrated: (60+40=100, rem 0) + (30+30=60, rem 40) -> max offcut 40
        cuts = [(1, 60.0, "A"), (2, 30.0, "B"), (3, 40.0, "C"), (4, 30.0, "D")]
        result = optimize_cut_list(cuts, board_length=100.0, kerf=0.0, longest_last=True)
        self.assertEqual(result.after.board_count, 2)
        self.assertAlmostEqual(result.after.largest_offcut_in, 40.0, places=4)
        # Fullest board first (40, 60 with longest last), remnant board second (30, 30)
        self.assertEqual([c[1] for c in result.cuts], [40.0, 60.0, 30.0, 30.0])

    def test_kerf_accounting_and_longest_last_ordering(self):
        # Zero-overage + truing kerf: four 36" cuts on a 12' (144.0") board at 0.12" kerf
        # need 0.12 + 4 * 36.12 = 144.60" > 144.0" -> must NOT squeeze onto 1 board.
        four_36 = [(i + 1, 36.0, f"Frame End #{i + 1}") for i in range(4)]
        r_four = optimize_cut_list(four_36, board_length=144.0, kerf=0.12)
        self.assertEqual(r_four.after.board_count, 2)

        # Short pieces cut first (longest-last) so a 7" chunk cuts before longer clamped pieces
        mixed = [(1, 50.0, "long"), (2, 7.0, "Bench Upper"), (3, 36.0, "Frame End")]
        r_last = optimize_cut_list(mixed, board_length=144.0, kerf=0.12, longest_last=True)
        self.assertEqual([c[1] for c in r_last.cuts], [7.0, 36.0, 50.0])

    def test_oversized_cuts_preserved_and_reported(self):
        cuts = [(1, 160.0, "beam"), (2, 40.0, "stud"), (3, 40.0, "stud")]
        result = optimize_cut_list(cuts, board_length=144.0, kerf=0.1)
        self.assertEqual(len(result.oversized), 1)
        self.assertEqual(result.oversized[0][1], 160.0)
        self.assertEqual(len(result.cuts), 3)
        self.assertEqual(result.after.oversized_count, 1)

    def test_realistic_shop_batch_speed_and_summary(self):
        # 48 mixed production cuts on 144.0" boards with 0.125" kerf
        lengths = [78.75] * 6 + [46.5] * 8 + [34.25] * 10 + [22.0] * 12 + [17.5] * 12
        cuts = [(i + 1, length, f"Rafter #{i + 1}") for i, length in enumerate(lengths)]
        result = optimize_cut_list(cuts, board_length=144.0, kerf=0.125, time_limit_s=0.25)
        self.assertLess(result.elapsed_ms, 400.0)
        self.assertLessEqual(result.after.board_count, result.before.board_count)
        self.assertEqual(len(result.cuts), len(cuts))
        summary = summarize_cut_list(result.cuts, 144.0, 0.125)
        text = format_summary_text(summary)
        self.assertIn("48 cuts", text)
        self.assertIn("waste", text)
        lines = format_cuts_as_lines(result.cuts)
        self.assertEqual(len(lines), len(cuts))
        self.assertTrue(lines[0].endswith("Rafter #", ) is False)


class CutListManagerStorageTests(unittest.TestCase):
    def test_atomic_save_backup_recovery_and_editor_optimize_undo(self):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            storage = Path(folder) / "cutlists.json"
            logs = []
            tab = CutListManagerTab(
                storage_path=str(storage),
                on_load_lines=lambda _lines: None,
                log_fn=logs.append,
                get_board_length=lambda: 100.0,
                get_kerf=lambda: 0.0,
            )
            tab.name_input.setText("Fence Rails")
            raw = "\n".join(str(v) for v in (48, 48, 46, 28, 27, 27, 26, 25, 25))
            tab.editor.setText(raw)
            self.assertIn("4 boards", tab.summary_label.text())

            # Optimize in editor should drop from 4 boards -> 3 boards and allow Undo
            tab._optimize_editor_list()
            self.assertIn("3 boards", tab.summary_label.text())
            self.assertTrue(tab.undo_optimize_btn.isEnabled())
            tab._undo_optimize()
            self.assertEqual(tab.editor.toPlainText(), raw)
            self.assertFalse(tab.undo_optimize_btn.isEnabled())

            # Save twice to verify atomic save + .bak backup creation
            tab._save_list()
            self.assertTrue(storage.exists())
            self.assertFalse((Path(folder) / "cutlists.json.tmp").exists())
            tab.editor.setText("50 stud\n50 stud")
            tab._save_list()
            backup = Path(folder) / "cutlists.json.bak"
            self.assertTrue(backup.exists())

            # Corrupt primary JSON and confirm automatic .bak recovery
            storage.write_text("{corrupt json", encoding="utf-8")
            recovered = CutListManagerTab(
                storage_path=str(storage),
                on_load_lines=lambda _lines: None,
                log_fn=logs.append,
            )
            self.assertEqual(len(recovered.lists), 1)
            self.assertEqual(recovered.lists[0]["name"], "Fence Rails")
            self.assertTrue(any("backup" in msg.lower() for msg in logs))


if __name__ == "__main__":
    unittest.main()
