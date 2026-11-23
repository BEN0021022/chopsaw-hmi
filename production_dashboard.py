"""Glanceable shop-floor production dashboard summarizing cut_history.csv."""
from collections import Counter, defaultdict
import csv
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
import os
from pathlib import Path
import sys

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


@dataclass(frozen=True)
class PeriodStats:
    cuts: int = 0
    truing_cuts: int = 0
    boards: int = 0
    total_inches: float = 0.0
    board_inches: float = 0.0
    auto_cuts: int = 0
    manual_cuts: int = 0

    @property
    def linear_feet(self) -> float:
        return self.total_inches / 12.0

    @property
    def avg_cut_inches(self) -> float:
        return (self.total_inches / self.cuts) if self.cuts > 0 else 0.0

    @property
    def yield_pct(self) -> float | None:
        if self.board_inches <= 0 or self.total_inches <= 0:
            return None
        return min(100.0, self.total_inches / self.board_inches * 100.0)


@dataclass(frozen=True)
class DayBucket:
    day: date
    cuts: int = 0
    linear_feet: float = 0.0


@dataclass(frozen=True)
class DashboardMetrics:
    today: PeriodStats = field(default_factory=PeriodStats)
    last_7_days: PeriodStats = field(default_factory=PeriodStats)
    last_30_days: PeriodStats = field(default_factory=PeriodStats)
    all_time: PeriodStats = field(default_factory=PeriodStats)
    daily_7: tuple[DayBucket, ...] = ()
    top_lengths: tuple[tuple[float, int], ...] = ()
    last_cut_local: datetime | None = None
    record_count: int = 0


def _parse_float(raw: str | None) -> float | None:
    if not raw:
        return None
    try:
        value = float(raw)
        return value if value >= 0 else None
    except ValueError:
        return None


def _parse_local_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.astimezone() if dt.tzinfo is not None else dt
    except ValueError:
        return None


class _PeriodAccumulator:
    def __init__(self):
        self.cuts = 0
        self.truing_cuts = 0
        self.total_inches = 0.0
        self.auto_cuts = 0
        self.manual_cuts = 0
        self._boards: dict[str, float] = {}

    def add(self, cut_type: str, mode: str, length_in: float | None, board_id: str, board_len: float | None):
        if board_id:
            if board_id not in self._boards or (board_len is not None and self._boards[board_id] <= 0):
                self._boards[board_id] = board_len or 0.0
        if cut_type == "truing":
            self.truing_cuts += 1
            return
        if cut_type == "cut":
            self.cuts += 1
            if length_in is not None:
                self.total_inches += length_in
            if mode == "auto":
                self.auto_cuts += 1
            elif mode == "manual":
                self.manual_cuts += 1

    def freeze(self) -> PeriodStats:
        return PeriodStats(
            cuts=self.cuts,
            truing_cuts=self.truing_cuts,
            boards=len(self._boards),
            total_inches=self.total_inches,
            board_inches=sum(v for v in self._boards.values() if v > 0),
            auto_cuts=self.auto_cuts,
            manual_cuts=self.manual_cuts,
        )


def load_dashboard_metrics(csv_path: str | Path, today: date | None = None) -> DashboardMetrics:
    """Aggregate cut_history.csv into clean KPIs without loading raw rows into the UI."""
    ref_day = today or datetime.now().astimezone().date()
    day_7_start = ref_day - timedelta(days=6)
    day_30_start = ref_day - timedelta(days=29)

    today_acc = _PeriodAccumulator()
    week_acc = _PeriodAccumulator()
    month_acc = _PeriodAccumulator()
    all_acc = _PeriodAccumulator()
    daily_cuts: dict[date, int] = defaultdict(int)
    daily_inches: dict[date, float] = defaultdict(float)
    length_counts: Counter[float] = Counter()
    last_cut: datetime | None = None
    record_count = 0

    path = Path(csv_path)
    if path.exists():
        try:
            with path.open("r", newline="", encoding="utf-8") as stream:
                for row in csv.DictReader(stream):
                    record_count += 1
                    if row.get("event_type") not in ("completed_cycle", ""):
                        continue
                    dt = _parse_local_datetime(row.get("timestamp_utc"))
                    cut_type = (row.get("cut_type") or "").strip().lower()
                    mode = (row.get("mode") or "").strip().lower()
                    length_in = _parse_float(row.get("cut_length_in"))
                    board_id = (row.get("board_id") or "").strip()
                    board_len = _parse_float(row.get("board_length_in")) or _parse_float(
                        row.get("board_preset_in")
                    )

                    all_acc.add(cut_type, mode, length_in, board_id, board_len)
                    if cut_type == "cut" and length_in is not None and length_in > 0:
                        length_counts[round(length_in, 2)] += 1

                    if dt is not None:
                        if last_cut is None or dt > last_cut:
                            last_cut = dt
                        row_day = dt.date()
                        if row_day == ref_day:
                            today_acc.add(cut_type, mode, length_in, board_id, board_len)
                        if day_7_start <= row_day <= ref_day:
                            week_acc.add(cut_type, mode, length_in, board_id, board_len)
                            if cut_type == "cut":
                                daily_cuts[row_day] += 1
                                if length_in is not None:
                                    daily_inches[row_day] += length_in
                        if day_30_start <= row_day <= ref_day:
                            month_acc.add(cut_type, mode, length_in, board_id, board_len)
        except (OSError, csv.Error):
            pass

    daily_7 = tuple(
        DayBucket(
            day=day_7_start + timedelta(days=offset),
            cuts=daily_cuts[day_7_start + timedelta(days=offset)],
            linear_feet=daily_inches[day_7_start + timedelta(days=offset)] / 12.0,
        )
        for offset in range(7)
    )
    top_lengths = tuple(length_counts.most_common(6))
    return DashboardMetrics(
        today=today_acc.freeze(),
        last_7_days=week_acc.freeze(),
        last_30_days=month_acc.freeze(),
        all_time=all_acc.freeze(),
        daily_7=daily_7,
        top_lengths=top_lengths,
        last_cut_local=last_cut,
        record_count=record_count,
    )


class _KpiCard(QFrame):
    """Big-number dashboard metric card."""

    def __init__(self, title: str, accent: str = "#38bdf8"):
        super().__init__()
        self.setObjectName("kpiCard")
        self.setStyleSheet(
            "QFrame#kpiCard { background: #0b1222; border: 1px solid #334155; border-radius: 12px; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)

        self.title_label = QLabel(title)
        self.title_label.setStyleSheet("color: #94a3b8; font-size: 13px; font-weight: 600; border: none;")
        self.value_label = QLabel("0")
        self.value_label.setStyleSheet(f"color: {accent}; font-size: 32px; font-weight: 800; border: none;")
        self.sub_label = QLabel("")
        self.sub_label.setWordWrap(True)
        self.sub_label.setStyleSheet("color: #cbd5e1; font-size: 13px; border: none;")

        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.sub_label)
        layout.addStretch()

    def set_data(self, value: str, subtitle: str):
        self.value_label.setText(value)
        self.sub_label.setText(subtitle)


class DailyBarChartWidget(QWidget):
    """Compact 7-day painted bar chart showing daily cuts and linear feet."""

    def __init__(self):
        super().__init__()
        self._buckets: tuple[DayBucket, ...] = ()
        self.setMinimumHeight(180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_buckets(self, buckets: tuple[DayBucket, ...]):
        self._buckets = buckets
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        h = self.height()
        painter.fillRect(0, 0, w, h, QColor("#0b1222"))

        if not self._buckets:
            return

        left, right, top, bottom = 16, 16, 26, 36
        plot_w = max(1, w - left - right)
        plot_h = max(1, h - top - bottom)
        max_cuts = max((b.cuts for b in self._buckets), default=0)

        # Subtle baseline
        painter.setPen(QPen(QColor("#334155"), 1))
        painter.drawLine(left, top + plot_h, w - right, top + plot_h)

        if max_cuts == 0:
            painter.setPen(QColor("#64748b"))
            painter.setFont(QFont("Segoe UI", 11))
            painter.drawText(
                QRectF(left, top, plot_w, plot_h),
                Qt.AlignmentFlag.AlignCenter,
                "No production cuts recorded in the last 7 days",
            )

        slot_w = plot_w / len(self._buckets)
        bar_w = min(64.0, slot_w * 0.52)

        for idx, bucket in enumerate(self._buckets):
            cx = left + slot_w * (idx + 0.5)
            bar_x = cx - bar_w / 2.0
            is_today = idx == len(self._buckets) - 1

            if max_cuts > 0 and bucket.cuts > 0:
                bar_h = max(6.0, (bucket.cuts / max_cuts) * (plot_h - 14))
                bar_y = top + plot_h - bar_h
                color = QColor("#22c55e" if is_today else "#38bdf8")
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(color)
                painter.drawRoundedRect(QRectF(bar_x, bar_y, bar_w, bar_h), 5, 5)

                # Count + linear feet label above bar
                painter.setPen(QColor("#e2e8f0"))
                painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
                label = f"{bucket.cuts} ({bucket.linear_feet:.0f}ft)" if bucket.linear_feet >= 1 else str(bucket.cuts)
                painter.drawText(
                    QRectF(cx - slot_w / 2, bar_y - 20, slot_w, 18),
                    Qt.AlignmentFlag.AlignCenter,
                    label,
                )

            # Day label under baseline
            painter.setPen(QColor("#f8fafc" if is_today else "#94a3b8"))
            painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold if is_today else QFont.Weight.Normal))
            day_text = "Today" if is_today else bucket.day.strftime("%a %m/%d")
            painter.drawText(
                QRectF(cx - slot_w / 2, top + plot_h + 6, slot_w, 22),
                Qt.AlignmentFlag.AlignCenter,
                day_text,
            )


class ProductionDashboardTab(QWidget):
    """Clean, summary-first shop production dashboard backed by cut_history.csv."""

    def __init__(self, csv_path: str | Path, flush_fn=None):
        super().__init__()
        self.csv_path = Path(csv_path)
        self._flush_fn = flush_fn
        self.metrics = DashboardMetrics()
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { background: #0f172a; border: 0; }")
        body = QWidget()
        body.setObjectName("dashboardBody")
        body.setStyleSheet("QWidget#dashboardBody { background: #0f172a; }")
        root = QVBoxLayout(body)
        root.setSpacing(12)
        scroll.setWidget(body)
        outer.addWidget(scroll)

        # Header toolbar
        header = QHBoxLayout()
        title = QLabel("Production Dashboard")
        title.setStyleSheet("font-size: 20px; font-weight: 800; color: #f8fafc;")
        header.addWidget(title)
        self.last_cut_label = QLabel("No cuts recorded yet")
        self.last_cut_label.setStyleSheet("color: #94a3b8; font-size: 13px;")
        header.addSpacing(12)
        header.addWidget(self.last_cut_label)
        header.addStretch()

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh)
        self.open_csv_btn = QPushButton("Open CSV Log")
        self.open_csv_btn.setToolTip("Open the full cut_history.csv spreadsheet for detailed inspection.")
        self.open_csv_btn.clicked.connect(self._open_csv)
        header.addWidget(self.refresh_btn)
        header.addWidget(self.open_csv_btn)
        root.addLayout(header)

        # Row 1: 4 big KPI cards
        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(10)
        self.card_today_cuts = _KpiCard("TODAY'S CUTS", "#22c55e")
        self.card_today_feet = _KpiCard("TODAY'S LINEAR FEET", "#38bdf8")
        self.card_today_boards = _KpiCard("TODAY'S BOARDS", "#f59e0b")
        self.card_all_time = _KpiCard("ALL-TIME PRODUCTION", "#a78bfa")
        for card in (
            self.card_today_cuts,
            self.card_today_feet,
            self.card_today_boards,
            self.card_all_time,
        ):
            kpi_row.addWidget(card, 1)
        root.addLayout(kpi_row)

        # Row 2: 7-day bar chart
        chart_group = QGroupBox("Last 7 Days — Daily Cuts & Linear Feet")
        chart_layout = QVBoxLayout(chart_group)
        self.bar_chart = DailyBarChartWidget()
        chart_layout.addWidget(self.bar_chart)
        root.addWidget(chart_group)

        # Row 3: Two compact side-by-side summary panels
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(10)

        # Left: Period Summary (Today / 7d / 30d / All Time)
        period_group = QGroupBox("Period Summary")
        pg = QGridLayout(period_group)
        pg.setHorizontalSpacing(14)
        pg.setVerticalSpacing(8)
        headers = ("Period", "Cuts", "Boards", "Linear Ft", "Avg Cut", "Yield")
        for col, text in enumerate(headers):
            lbl = QLabel(text)
            lbl.setStyleSheet("color: #94a3b8; font-size: 13px; font-weight: 700;")
            pg.addWidget(lbl, 0, col, Qt.AlignmentFlag.AlignRight if col > 0 else Qt.AlignmentFlag.AlignLeft)
        self._period_rows: dict[str, list[QLabel]] = {}
        for row_idx, (key, title_text) in enumerate(
            (("today", "Today"), ("week", "Last 7 Days"), ("month", "Last 30 Days"), ("all", "All Time")),
            start=1,
        ):
            name_lbl = QLabel(title_text)
            name_lbl.setStyleSheet("font-weight: 600; color: #e2e8f0;")
            pg.addWidget(name_lbl, row_idx, 0)
            cells = []
            for col in range(1, len(headers)):
                val = QLabel("—")
                val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                val.setStyleSheet("color: #cbd5e1; font-family: Consolas, monospace;")
                pg.addWidget(val, row_idx, col)
                cells.append(val)
            self._period_rows[key] = cells
        bottom_row.addWidget(period_group, 3)

        # Right: Top Cut Lengths
        top_group = QGroupBox("Most Cut Lengths (All Time)")
        self._top_layout = QGridLayout(top_group)
        self._top_layout.setHorizontalSpacing(10)
        self._top_layout.setVerticalSpacing(6)
        self._top_placeholder = QLabel("No cut lengths recorded yet.")
        self._top_placeholder.setStyleSheet("color: #64748b;")
        self._top_layout.addWidget(self._top_placeholder, 0, 0)
        bottom_row.addWidget(top_group, 2)

        root.addLayout(bottom_row)
        root.addStretch()

    def refresh(self, today: date | None = None):
        if self._flush_fn:
            try:
                self._flush_fn(0.25)
            except Exception:
                pass
        m = load_dashboard_metrics(self.csv_path, today=today)
        self.metrics = m

        if m.last_cut_local is not None:
            self.last_cut_label.setText(
                f"Last cut: {m.last_cut_local.strftime('%b %d, %I:%M %p')}"
            )
        else:
            self.last_cut_label.setText("No cuts recorded yet")

        # KPI cards
        truing_note = (
            f"+ {m.today.truing_cuts} truing trims"
            if m.today.truing_cuts
            else "Confirmed production cuts"
        )
        self.card_today_cuts.set_data(f"{m.today.cuts:,}", truing_note)

        avg_text = (
            f'Avg {m.today.avg_cut_inches:.1f}" per cut'
            if m.today.cuts
            else "Ready for first cut"
        )
        self.card_today_feet.set_data(f"{m.today.linear_feet:,.1f} ft", avg_text)

        mode_total = m.today.auto_cuts + m.today.manual_cuts
        if mode_total > 0:
            auto_pct = round(m.today.auto_cuts / mode_total * 100)
            mode_note = f"Auto {auto_pct}% • Manual {100 - auto_pct}%"
        else:
            mode_note = "Distinct boards processed"
        self.card_today_boards.set_data(f"{m.today.boards:,}", mode_note)

        self.card_all_time.set_data(
            f"{m.all_time.cuts:,} cuts",
            f"{m.all_time.linear_feet:,.1f} ft • {m.all_time.boards:,} boards",
        )

        # 7-day bar chart
        self.bar_chart.set_buckets(m.daily_7)

        # Period breakdown table
        for key, stats in (
            ("today", m.today),
            ("week", m.last_7_days),
            ("month", m.last_30_days),
            ("all", m.all_time),
        ):
            cells = self._period_rows[key]
            cells[0].setText(f"{stats.cuts:,}")
            cells[1].setText(f"{stats.boards:,}")
            cells[2].setText(f"{stats.linear_feet:,.1f}")
            cells[3].setText(f'{stats.avg_cut_inches:.1f}"' if stats.cuts else "—")
            cells[4].setText(f"{stats.yield_pct:.0f}%" if stats.yield_pct is not None else "—")

        # Most-cut lengths
        while self._top_layout.count():
            item = self._top_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if not m.top_lengths:
            placeholder = QLabel("No cut lengths recorded yet.")
            placeholder.setStyleSheet("color: #64748b;")
            self._top_layout.addWidget(placeholder, 0, 0)
        else:
            max_count = m.top_lengths[0][1]
            for row_idx, (length_in, count) in enumerate(m.top_lengths):
                len_lbl = QLabel(f'{length_in:g}"')
                len_lbl.setStyleSheet("font-weight: 700; color: #e2e8f0; min-width: 58px;")
                bar = QFrame()
                pct = max(0.08, count / max_count)
                bar.setFixedHeight(14)
                bar.setStyleSheet(
                    "background: #0284c7; border-radius: 5px;"
                )
                bar_wrap = QWidget()
                bw_layout = QHBoxLayout(bar_wrap)
                bw_layout.setContentsMargins(0, 0, 0, 0)
                bw_layout.addWidget(bar, max(1, int(pct * 100)))
                bw_layout.addStretch(max(0, 100 - int(pct * 100)))
                cnt_lbl = QLabel(f"{count:,}x")
                cnt_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                cnt_lbl.setStyleSheet("color: #93c5fd; font-family: Consolas, monospace; min-width: 44px;")
                self._top_layout.addWidget(len_lbl, row_idx, 0)
                self._top_layout.addWidget(bar_wrap, row_idx, 1)
                self._top_layout.addWidget(cnt_lbl, row_idx, 2)
            self._top_layout.setColumnStretch(1, 1)

    def _open_csv(self):
        if not self.csv_path.exists():
            QMessageBox.information(
                self,
                "No Cut History Yet",
                f"No history file has been written yet.\n\nLocation:\n{self.csv_path}",
            )
            return
        try:
            if sys.platform == "win32":
                os.startfile(str(self.csv_path))  # type: ignore[attr-defined]
            else:
                QMessageBox.information(self, "Cut History CSV", str(self.csv_path))
        except OSError as exc:
            QMessageBox.warning(self, "Open Failed", f"Could not open {self.csv_path}:\n{exc}")
