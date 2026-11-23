"""Tests for the shop-floor Production Dashboard aggregation and Qt widget."""
import csv
from datetime import date, datetime, timedelta, timezone
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import tempfile
import unittest

from PyQt6.QtWidgets import QApplication

from cut_history import FIELDS
from production_dashboard import ProductionDashboardTab, load_dashboard_metrics


def _make_row(ts: datetime, *, cut_type="cut", mode="auto", length="24.0", board_id="b1", board_len="144.0"):
    row = {key: "" for key in FIELDS}
    row.update(
        timestamp_utc=ts.astimezone(timezone.utc).isoformat(timespec="milliseconds"),
        event_id=f"e:{ts.timestamp()}",
        session_id="s1",
        board_id=board_id,
        run_type="production",
        mode=mode,
        event_type="completed_cycle",
        completed_count="1",
        cut_type=cut_type,
        cut_length_in=length,
        board_length_in=board_len,
    )
    return row


class ProductionDashboardTests(unittest.TestCase):
    def test_aggregates_today_week_month_all_time_and_top_lengths(self):
        with tempfile.TemporaryDirectory() as folder:
            csv_path = Path(folder) / "cut_history.csv"
            ref_day = date(2026, 11, 22)
            local_tz = datetime.now().astimezone().tzinfo
            today_noon = datetime(2026, 11, 22, 12, 0, tzinfo=local_tz)
            three_days_ago = today_noon - timedelta(days=3)
            twenty_days_ago = today_noon - timedelta(days=20)
            old_day = today_noon - timedelta(days=60)

            rows = [
                _make_row(today_noon, cut_type="truing", length="0.1", board_id="b-today", board_len="144.0"),
                _make_row(today_noon + timedelta(minutes=1), length="36.0", board_id="b-today", board_len="144.0"),
                _make_row(today_noon + timedelta(minutes=2), length="36.0", board_id="b-today", board_len="144.0"),
                _make_row(today_noon + timedelta(minutes=3), mode="manual", length="48.0", board_id="b-today", board_len="144.0"),
                _make_row(three_days_ago, length="24.0", board_id="b-week", board_len="120.0"),
                _make_row(twenty_days_ago, length="36.0", board_id="b-month", board_len="144.0"),
                _make_row(old_day, length="18.0", board_id="b-old", board_len="96.0"),
            ]
            with csv_path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerows(rows)

            metrics = load_dashboard_metrics(csv_path, today=ref_day)
            self.assertEqual(metrics.today.cuts, 3)
            self.assertEqual(metrics.today.truing_cuts, 1)
            self.assertEqual(metrics.today.boards, 1)
            self.assertAlmostEqual(metrics.today.linear_feet, 10.0)
            self.assertAlmostEqual(metrics.today.yield_pct, 120.0 / 144.0 * 100.0)

            self.assertEqual(metrics.last_7_days.cuts, 4)
            self.assertEqual(metrics.last_7_days.boards, 2)
            self.assertEqual(metrics.last_30_days.cuts, 5)
            self.assertEqual(metrics.all_time.cuts, 6)
            self.assertEqual(metrics.all_time.boards, 4)
            self.assertEqual(len(metrics.daily_7), 7)
            self.assertEqual(metrics.daily_7[-1].cuts, 3)
            self.assertEqual(metrics.top_lengths[0], (36.0, 3))

            app = QApplication.instance() or QApplication([])
            widget = ProductionDashboardTab(csv_path)
            widget.refresh(today=ref_day)
            self.assertEqual(widget.card_today_cuts.value_label.text(), "3")
            self.assertEqual(widget.card_today_feet.value_label.text(), "10.0 ft")
            self.assertEqual(widget.card_today_boards.value_label.text(), "1")
            self.assertIn("6 cuts", widget.card_all_time.value_label.text())
            widget.close()
            _ = app

    def test_handles_missing_csv_cleanly(self):
        with tempfile.TemporaryDirectory() as folder:
            metrics = load_dashboard_metrics(Path(folder) / "does_not_exist.csv")
            self.assertEqual(metrics.all_time.cuts, 0)
            self.assertEqual(len(metrics.daily_7), 7)
            self.assertIsNone(metrics.last_cut_local)


if __name__ == "__main__":
    unittest.main()
