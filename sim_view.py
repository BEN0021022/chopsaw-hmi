# sim_view.py

from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF
from PyQt6.QtGui import QColor, QPainter, QPen, QFont, QPolygonF
from PyQt6.QtWidgets import QWidget

PIECE_COLORS = ["#38bdf8", "#f59e0b", "#22c55e", "#a78bfa", "#f472b6", "#facc15"]
TRIM_COLOR = "#8d6e4a"
SCRAP_COLOR = "#64748b"


class SawSimWidget(QWidget):
    """
    2D line view of the saw: the carriage (left) pushes the board right toward
    the blade. Inches are measured from the blade; negative = outfeed side.
    Cut pieces are colored per cut so the board optimization is visible, with
    kerf drawn as dark notches (exaggerated to a 2 px minimum so it shows at
    this scale). The last ejected piece slides into the outfeed lane below.
    """
    OUTFEED_IN = 60.0

    def __init__(self, home_position=168.0, parent=None):
        super().__init__(parent)
        self.home_position = float(home_position)
        self.sensor_location = 10.8
        self.carriage = 0.0
        self.board_present = False
        self.board_edge = 0.0          # leading edge, inches from blade
        self.segments = []             # [(length_in, color_hex or None=kerf, label)]
        self.saw_state = "--"          # UP / DOWN / CUTTING / --
        self.clamps = (False, False, False)  # left, right, fence
        self.board_sensor_on = False
        self._eject = None
        self._eject_timer = QTimer(self)
        self._eject_timer.setInterval(25)
        self._eject_timer.timeout.connect(self._tick_eject)
        self.setMinimumHeight(170)

    # ---------- state setters ----------
    def set_home_position(self, pos):
        self.home_position = max(1.0, float(pos))
        self.update()

    def set_sensor_location(self, inches):
        self.sensor_location = float(inches)
        self.update()

    def set_carriage(self, pos):
        self.carriage = float(pos)
        self.update()

    def set_saw_state(self, state):
        if state != self.saw_state:
            self.saw_state = state
            self.update()

    def set_clamps(self, left, right, fence):
        self.clamps = (left, right, fence)
        self.update()

    def set_board_sensor(self, on):
        if bool(on) != self.board_sensor_on:
            self.board_sensor_on = bool(on)
            self.update()

    def set_board(self, present, edge_pos, segments):
        self.board_present = present
        self.board_edge = float(edge_pos)
        self.segments = segments
        self.update()

    def set_board_edge(self, edge_pos):
        self.board_edge = float(edge_pos)
        self.update()

    def eject_piece(self, length, color, label):
        self._eject = {"length": float(length), "color": color, "label": label, "t": 0.0}
        self._eject_timer.start()

    def _tick_eject(self):
        if self._eject is None:
            self._eject_timer.stop()
            return
        self._eject["t"] = min(1.0, self._eject["t"] + 0.07)
        if self._eject["t"] >= 1.0:
            self._eject_timer.stop()
        self.update()

    # ---------- painting ----------
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        p.fillRect(rect, QColor("#0b1222"))
        p.setPen(QPen(QColor("#334155"), 1))
        p.drawRoundedRect(rect, 10, 10)
        if rect.width() < 80 or rect.height() < 80:
            return

        left = rect.left() + 12
        right = rect.right() - 12
        total_in = self.home_position + self.OUTFEED_IN
        scale = (right - left) / total_in

        def X(inch):
            return left + (self.home_position - inch) * scale

        board_h = max(18, int(rect.height() * 0.17))
        b_top = rect.top() + int(rect.height() * 0.40) - board_h // 2
        table_y = b_top + board_h + 3
        blade_x = X(0.0)

        small = QFont(self.font())
        small.setPointSize(8)
        p.setFont(small)

        # Caption
        p.setPen(QPen(QColor("#64748b"), 1))
        caption = f'Carriage: {self.carriage:.2f}"'
        if self.board_present:
            board_total = sum(s[0] for s in self.segments)
            caption += f'    Board: {board_total:.2f}"'
        p.drawText(int(left), rect.top() + 16, caption)

        # Table
        p.setPen(QPen(QColor("#334155"), 2))
        p.drawLine(int(left), table_y, int(right), table_y)

        # Board sensor mark
        sx = X(self.sensor_location)
        p.setBrush(QColor("#22c55e") if self.board_sensor_on else QColor("#475569"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPolygon(QPolygonF([
            QPointF(sx - 5, table_y + 11),
            QPointF(sx + 5, table_y + 11),
            QPointF(sx, table_y + 3),
        ]))

        # Board segments, from the leading edge back toward the carriage
        if self.board_present:
            cursor = self.board_edge
            for length, color, label in self.segments:
                x_right = X(cursor)
                x_left = X(cursor + length)
                w = x_right - x_left
                if color is None:  # kerf: dark notch, exaggerated minimum width
                    kw = max(2.0, w)
                    p.fillRect(QRectF(x_right - kw, b_top, kw, board_h), QColor("#0f172a"))
                else:
                    p.setPen(QPen(QColor("#0f172a"), 1))
                    p.setBrush(QColor(color))
                    p.drawRect(QRectF(x_left, b_top, w, board_h))
                    if label and w > 34:
                        p.drawText(QRectF(x_left, b_top, w, board_h),
                                   int(Qt.AlignmentFlag.AlignCenter), label)
                cursor += length

        # Clamp indicators near the blade (Fence/Left infeed, Right outfeed)
        for name, inch, on in (("F", 16.0, self.clamps[2]),
                               ("L", 8.0, self.clamps[0]),
                               ("R", -8.0, self.clamps[1])):
            cx = X(inch)
            p.setBrush(QColor("#2563eb") if on else QColor("#1e293b"))
            p.setPen(QPen(QColor("#334155"), 1))
            p.drawRect(QRectF(cx - 6, b_top - 17, 12, 12))
            p.setPen(QPen(QColor("#94a3b8"), 1))
            p.drawText(QRectF(cx - 6, b_top - 18, 12, 12),
                       int(Qt.AlignmentFlag.AlignCenter), name)

        # Carriage (pusher): face at its position, body on the infeed side
        cx = X(self.carriage)
        p.setBrush(QColor("#2563eb"))
        p.setPen(QPen(QColor("#1d4ed8"), 1))
        p.drawRoundedRect(QRectF(cx - 26, b_top - 8, 26, board_h + 16), 4, 4)
        p.setPen(QPen(QColor("#93c5fd"), 2))
        p.drawLine(QPointF(cx, b_top - 8), QPointF(cx, b_top + board_h + 8))

        # Saw head + blade
        cutting = self.saw_state in ("CUTTING", "DOWN")
        blade_color = QColor("#ef4444") if cutting else QColor("#94a3b8")
        head_y = (b_top - 4) if cutting else (rect.top() + 22)
        p.setBrush(QColor("#1e293b"))
        p.setPen(QPen(blade_color, 1))
        p.drawRoundedRect(QRectF(blade_x - 10, head_y - 16, 20, 14), 3, 3)
        p.setBrush(blade_color)
        p.setPen(Qt.PenStyle.NoPen)
        if cutting:
            p.drawRect(QRectF(blade_x - 1.5, head_y - 2, 3, table_y - head_y + 2))
        else:
            p.drawRect(QRectF(blade_x - 1.5, head_y - 2, 3, 12))
        p.setPen(QPen(QColor("#94a3b8"), 1))
        p.drawText(QRectF(blade_x - 30, rect.top() + 2, 60, 12),
                   int(Qt.AlignmentFlag.AlignCenter),
                   self.saw_state if self.saw_state != "--" else "SAW")

        # Ejected piece sliding into the outfeed lane
        if self._eject:
            e = self._eject
            ease = 1.0 - (1.0 - e["t"]) ** 2
            lane_y = table_y + 14
            disp_len = min(e["length"], self.OUTFEED_IN - 12.0)
            w = max(8.0, disp_len * scale)
            x_start = blade_x + 4
            x_end = right - w - 4
            x_left = x_start + (x_end - x_start) * ease
            p.setBrush(QColor(e["color"]))
            p.setPen(QPen(QColor("#0f172a"), 1))
            p.drawRect(QRectF(x_left, lane_y, w, board_h * 0.8))
            if e["label"]:
                p.setPen(QPen(QColor("#e2e8f0"), 1))
                p.drawText(QPointF(x_left, lane_y + board_h * 0.8 + 12), e["label"])
