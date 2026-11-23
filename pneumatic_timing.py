"""Shared timing configuration; physical clamp eligibility is a separate policy."""
from dataclasses import dataclass
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


@dataclass(frozen=True)
class TimingField:
    key: str
    label: str
    default: int = 0
    legacy: str = ""
    planned_limit: bool = False


CLAMPS = {1:'main', 2:'outfeed'}  # virtual fixture IDs, NOT Teensy output indices


def clamp_fields(device):
    return (
        TimingField(f'{device}.engage_delay', 'Delay before engaging'),
        TimingField(f'{device}.engage_settle', 'Engage settling time', 800, 'saw_start_delay'),
        TimingField(f'{device}.release_delay', 'Delay before releasing'),
        TimingField(f'{device}.release_clearance', 'Release clearance time'),
        TimingField(f'{device}.confirm_timeout', 'Confirmation limit (planned)', 5000, planned_limit=True),
    )


DEVICES = (
    ('Board positioning', (TimingField('board.settle', 'Settle after carriage stops', 300, 'clamp_engage_delay'),)),
    ('Main clamp', clamp_fields('main')),
    ('Saw travel cylinder', (
        TimingField('saw.down_delay', 'Delay before downstroke'),
        TimingField('saw.bottom_dwell', 'Dwell at bottom'),
        TimingField('saw.up_delay', 'Delay before return UP'),
        TimingField('saw.up_settle', 'Settle after confirmed UP'),
        TimingField('saw.down_timeout', 'Down travel limit', 5000, planned_limit=True),
        TimingField('saw.up_timeout', 'UP travel limit', 5000, planned_limit=True),
    )),
    ('Blade trigger cylinder', (
        TimingField('trigger.press_delay', 'Delay before pressing trigger'),
        TimingField('trigger.spinup', 'Blade spin-up wait'),
        TimingField('trigger.release_delay', 'Release delay after saw UP'),
        TimingField('trigger.brake_wait', 'Wait after trigger release'),
    )),
    ('Second / outfeed clamp — Mist D18', clamp_fields('outfeed')),
)
FIELDS = tuple(field for _, fields in DEVICES for field in fields)


def simulation_clamps(position, truing):
    """Two-clamp virtual fixture only; never authorize real stock holding."""
    return (1,) if truing else (1,2) if position >= 3.0 else (2,)


class CylinderTimingPanel(QGroupBox):
    def __init__(self, settings, parent=None):
        super().__init__('Cylinder Timing', parent)
        self.settings = settings
        self.fields = {}
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(10)
        header.addWidget(QLabel('Actuator:'))
        self.device_combo = QComboBox()
        self.device_combo.setMinimumHeight(36)
        self.device_combo.setMinimumWidth(280)
        self.device_combo.setStyleSheet(
            'QComboBox {background:#0b1222;color:#e2e8f0;border:1px solid #334155;padding:6px 10px;} '
            'QComboBox QAbstractItemView {background:#0b1222;color:#e2e8f0;selection-background-color:#1e40af;}'
        )
        header.addWidget(self.device_combo, 1)
        self.save_button = QPushButton('Save Timing Settings')
        self.save_button.setProperty('class', 'primary')
        self.save_button.clicked.connect(self.save)
        header.addWidget(self.save_button)
        layout.addLayout(header)

        self.pages = QWidget()
        page_layout = QVBoxLayout(self.pages)
        page_layout.setContentsMargins(0, 0, 0, 0)
        self.device_pages = []
        for index, (title, fields) in enumerate(DEVICES):
            self.device_combo.addItem(title)
            page = QWidget()
            grid = QGridLayout(page)
            grid.setContentsMargins(0, 4, 0, 4)
            grid.setHorizontalSpacing(18)
            grid.setVerticalSpacing(6)
            for idx, field in enumerate(fields):
                spin = QSpinBox()
                spin.setRange(1 if field.planned_limit else 0, 60000)
                spin.setValue(field.default)
                spin.setSuffix(' ms')
                spin.setMinimumHeight(34)
                spin.setMaximumWidth(150)
                spin.setStyleSheet(
                    'QSpinBox { background:#0b1222;color:#e2e8f0;border:1px solid #334155;'
                    'border-radius:8px;padding:4px 8px;font-size:15px; }'
                )
                if field.planned_limit:
                    spin.setToolTip(
                        'Saw travel limits are enforced in the controller (100–5000 ms). '
                        'Clamp confirmation limits require future feedback; they remain planned.'
                    )
                self.fields[field.key] = spin
                row = idx // 2
                col = (idx % 2) * 2
                grid.addWidget(QLabel(field.label + ':'), row, col)
                grid.addWidget(spin, row, col + 1)
            grid.setColumnStretch(0, 1)
            grid.setColumnStretch(2, 1)
            page_layout.addWidget(page)
            page.setVisible(index == 0)
            self.device_pages.append(page)
        self.device_combo.currentIndexChanged.connect(self.show_device)
        layout.addWidget(self.pages)

        self.mode_hint = QLabel()
        self.mode_hint.setWordWrap(True)
        self.mode_hint.setStyleSheet('color:#fbbf24; font-size:12px;')
        layout.addWidget(self.mode_hint)

        self.feedback = QLabel(
            'Save retains settings on this PC. Timings load automatically to the controller before Manual enable or Start Auto.'
        )
        self.feedback.setWordWrap(True)
        self.feedback.setStyleSheet('color:#94a3b8; font-size:12px;')
        layout.addWidget(self.feedback)

    def show_device(self, index):
        for i, page in enumerate(self.device_pages):
            page.setVisible(i == index)

    def set_simulator_mode(self, simulator):
        self.mode_hint.setText(
            'Simulator: normal-cycle delays are active. Confirmation/travel limits remain planned.' if simulator else
            'Live controller: Manual enable / Start Auto load main-clamp, saw and trigger timings. '
            'Delays 0–5000 ms; travel limits 100–5000 ms. Full cycle includes spin-up and brake waits. '
            'Held-trigger manual controls remain hold-to-test. Timers do not verify grip or blade stop. '
            'Second/outfeed delays are independent on firmware 0.24+, enabled separately in Machine dimensions. '
            'Clamp confirmation feedback remains planned.'
        )

    def snapshot(self):
        return {key: widget.value() for key, widget in self.fields.items()}

    def load(self):
        for field in FIELDS:
            raw = self.settings.value('cylinder_timing/' + field.key)
            if raw is None and field.legacy:
                raw = self.settings.value(field.legacy)
            try:
                value = int(raw) if raw is not None else field.default
            except (TypeError, ValueError):
                value = field.default
            self.fields[field.key].setValue(value)

    def save(self):
        for key, value in self.snapshot().items():
            self.settings.setValue('cylinder_timing/' + key, value)
        self.settings.sync()
        self.feedback.setText('Timing settings saved on this PC. No hardware configuration was sent.'
                              if self.settings.status() == QSettings.Status.NoError else
                              'Timing settings could not be saved. Check write access and try again.')
