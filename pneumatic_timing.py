"""Shared timing configuration; physical clamp eligibility is a separate policy."""
from dataclasses import dataclass
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QGroupBox, QVBoxLayout, QFormLayout, QLabel, QComboBox, QWidget, QSpinBox, QPushButton, QSizePolicy


@dataclass(frozen=True)
class TimingField:
    key: str
    label: str
    default: int = 0
    legacy: str = ""
    planned_limit: bool = False


CLAMPS = {1:'main', 2:'outfeed', 3:'fence'}  # virtual fixture IDs, NOT Teensy output indices


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
    ('Outfeed clamp — planned', clamp_fields('outfeed')),
    ('Backstop / fence clamp — planned', clamp_fields('fence')),
)
FIELDS = tuple(field for _, fields in DEVICES for field in fields)


def simulation_clamps(position, truing):
    """Archived three-clamp virtual fixture only; never authorize real stock holding."""
    return (1,3) if truing else (1,2,3) if position >= 3.0 else (2,)


class CylinderTimingPanel(QGroupBox):
    def __init__(self, settings, parent=None):
        super().__init__('Cylinder Timing', parent)
        self.settings = settings
        self.fields = {}
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(self)
        hint = QLabel('Shared across motion profiles. Select an actuator to edit its independent timings; all values are milliseconds.')
        hint.setWordWrap(True); layout.addWidget(hint)
        self.mode_hint = QLabel()
        self.mode_hint.setWordWrap(True)
        self.mode_hint.setStyleSheet('color:#fbbf24; font-size:14px;')
        layout.addWidget(self.mode_hint)
        self.device_combo = QComboBox()
        self.device_combo.setMinimumHeight(40)
        self.device_combo.setStyleSheet('QComboBox {background:#0b1222;color:#e2e8f0;border:1px solid #334155;padding:8px;} QComboBox QAbstractItemView {background:#0b1222;color:#e2e8f0;selection-background-color:#1e40af;}')
        self.pages = QWidget()
        page_layout = QVBoxLayout(self.pages)
        page_layout.setContentsMargins(0, 0, 0, 0)
        self.device_pages = []
        for index, (title, fields) in enumerate(DEVICES):
            self.device_combo.addItem(title)
            page = QWidget(); form = QFormLayout(page)
            for field in fields:
                spin = QSpinBox()
                spin.setRange(1 if field.planned_limit else 0, 60000)
                spin.setValue(field.default)
                spin.setSuffix(' ms')
                spin.setMinimumHeight(36)
                spin.setMaximumWidth(260)
                spin.setStyleSheet('QSpinBox { background:#0b1222;color:#e2e8f0;border:1px solid #334155;border-radius:8px;padding:6px;font-size:16px; }')
                if field.planned_limit:
                    spin.setToolTip('Saw travel limits are enforced after loading into 0.19.0 saw-unplugged firmware (100–5000 ms). Clamp confirmation limits require future feedback; they remain planned.')
                self.fields[field.key] = spin
                form.addRow(field.label + ':', spin)
            page_layout.addWidget(page)
            page.setVisible(index == 0)
            self.device_pages.append(page)
        self.device_combo.currentIndexChanged.connect(self.show_device)
        layout.addWidget(self.device_combo)
        layout.addWidget(self.pages)
        self.save_button = QPushButton('Save Timing Settings')
        self.save_button.clicked.connect(self.save)
        layout.addWidget(self.save_button)
        self.feedback = QLabel('Save retains settings on this PC. For native unloaded tests, explicitly Load dry-run timings while disarmed; wait for acknowledgment.')
        self.feedback.setWordWrap(True)
        self.feedback.setStyleSheet('color:#94a3b8; font-size:13px;')
        layout.addWidget(self.feedback)

    def show_device(self, index):
        for i, page in enumerate(self.device_pages):
            page.setVisible(i == index)

    def set_simulator_mode(self, simulator):
        self.mode_hint.setText(
            'Simulator: normal-cycle delays are active. Confirmation/travel limits remain planned.' if simulator else
            'Saw-unplugged tests: Manual enable / Start Auto load main-clamp, saw and trigger timings. '
            'Delays 0–5000 ms; travel limits 100–5000 ms. Full cycle includes spin-up and brake waits. '
            'Held-trigger individual tests remain hold-to-test. Timers do not verify grip or blade stop. '
            'Clamp confirmation and additional clamps remain planned.'
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
