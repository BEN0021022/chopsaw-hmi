# ui_components.py

from collections import deque

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QGridLayout, QLineEdit, QPushButton
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QColor, QPainter, QPen, QPainterPath

class KeypadWidget(QWidget):
    """A reusable numeric keypad widget for data entry."""
    value_entered = pyqtSignal(float)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_input = ""
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        self.display = QLineEdit()
        self.display.setReadOnly(True)
        self.display.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.display.setMaxLength(10)
        self.display.setStyleSheet("font-size: 20px; padding: 10px; border-radius: 10px;")
        layout.addWidget(self.display)

        grid = QGridLayout()
        buttons = ['7','8','9','4','5','6','1','2','3','.','0','CLR']
        pos = [(i,j) for i in range(4) for j in range(3)]
        for (i,j), txt in zip(pos, buttons):
            b = QPushButton(txt); b.setProperty("role","touch")
            b.clicked.connect(lambda _, t=txt: self.button_clicked(t))
            grid.addWidget(b, i, j)
        enter = QPushButton("ENTER"); enter.setProperty("role","touch"); enter.clicked.connect(self.enter_value)
        grid.addWidget(enter, 4, 0, 1, 3)
        layout.addLayout(grid)
        
    def button_clicked(self, c):
        if c == 'CLR': self.current_input = ""
        elif c == '.':
            if '.' not in self.current_input:
                self.current_input += c if self.current_input else "0."
        else: self.current_input += c
        self.display.setText(self.current_input)
        
    def enter_value(self):
        if not self.current_input: return
        try:
            self.value_entered.emit(float(self.current_input))
            self.current_input = ""; self.display.clear()
        except ValueError:
            self.display.setText("Error"); self.current_input = ""


class CurrentGraphWidget(QWidget):
    """Simple rolling current trace for the last few seconds."""
    def __init__(self, max_seconds=5.0, sample_rate_hz=4, parent=None):
        super().__init__(parent)
        self.max_points = max(8, int(max_seconds * sample_rate_hz))
        self.samples = deque([0.0] * self.max_points, maxlen=self.max_points)
        self.current_limit = 0.0
        self.setMinimumHeight(120)

    def push_sample(self, amps):
        self.samples.append(float(max(0.0, amps)))
        self.update()

    def set_limit(self, amps):
        self.current_limit = float(max(0.0, amps))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)

        painter.fillRect(rect, QColor("#0b1222"))
        painter.setPen(QPen(QColor("#334155"), 1))
        painter.drawRoundedRect(rect, 10, 10)

        if rect.width() <= 4 or rect.height() <= 4:
            return

        top = rect.top() + 10
        bottom = rect.bottom() - 10
        left = rect.left() + 10
        right = rect.right() - 10
        height = max(1, bottom - top)
        width = max(1, right - left)

        max_sample = max(self.samples) if self.samples else 0.0
        scale_max = max(3.0, self.current_limit * 1.25 if self.current_limit > 0 else 0.0, max_sample * 1.15)

        grid_pen = QPen(QColor("#1e293b"), 1)
        painter.setPen(grid_pen)
        for frac in (0.25, 0.5, 0.75):
            y = bottom - int(height * frac)
            painter.drawLine(left, y, right, y)

        if self.current_limit > 0:
            limit_y = bottom - int((self.current_limit / scale_max) * height)
            painter.setPen(QPen(QColor("#f59e0b"), 2, Qt.PenStyle.DashLine))
            painter.drawLine(left, limit_y, right, limit_y)

        if len(self.samples) < 2:
            return

        path = QPainterPath()
        x_step = width / (len(self.samples) - 1)
        for i, sample in enumerate(self.samples):
            x = left + (i * x_step)
            y = bottom - ((sample / scale_max) * height)
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)

        painter.setPen(QPen(QColor("#22c55e"), 3))
        painter.drawPath(path)
