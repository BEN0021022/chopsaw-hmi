"""Dark PyQt6 dashboard for sensor and guarded clamp-output bring-up."""

from __future__ import annotations

from dataclasses import dataclass
import time

from PyQt6.QtCore import QSettings, Qt, QTimer
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .protocol import ParsedMessage, parse_int, parse_line
from .serial_link import SerialLink


GREEN = "#22c55e"
RED = "#ef4444"
AMBER = "#f59e0b"
BLUE = "#2563eb"
SLATE = "#475569"


@dataclass(frozen=True)
class SensorDefinition:
    key: str
    label: str
    connection: str
    pin: str


DIRECT_SENSORS = (
    SensorDefinition("HOME", "Carriage Home", "Limit X", "D20"),
    SensorDefinition("BOARD_EDGE", "Board Edge", "Limit Y", "D21"),
    SensorDefinition("FENCE_DOOR", "Fence / Guard Door", "Door", "D29"),
    SensorDefinition("CL57T_ALM", "CL57T Alarm", "Halt", "D14"),
    SensorDefinition("SAW_UP", "Saw Fully Up", "ST0", "D36"),
    SensorDefinition("SAW_DOWN", "Saw Fully Down", "ST1", "D30"),
    SensorDefinition("FENCE_CLOSED", "Fence Closed", "ST2", "D34"),
    SensorDefinition("OUTFEED", "Outfeed Position", "ST3", "D35"),
)

CLAMP_OUTPUTS = (
    (0, "Clamp 1", "AUX0 TTL", "D31"),
    (1, "Clamp 2", "AUX1 TTL", "D32"),
    (2, "Clamp 3", "AUX2 TTL", "D33"),
)


def _pill(text: str, color: str = SLATE) -> QLabel:
    label = QLabel(text)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setMinimumHeight(32)
    label.setStyleSheet(
        f"background:{color}; color:white; border-radius:9px; padding:4px 10px; font-weight:700;"
    )
    return label


def _set_pill(label: QLabel, text: str, color: str) -> None:
    label.setText(text)
    label.setStyleSheet(
        f"background:{color}; color:white; border-radius:9px; padding:4px 10px; font-weight:700;"
    )


class HealthCard(QFrame):
    def __init__(self, title: str, subtitle: str):
        super().__init__()
        self.setObjectName("healthCard")
        layout = QVBoxLayout(self)
        title_label = QLabel(title)
        title_label.setStyleSheet("font-size:18px; font-weight:800;")
        self.status = _pill("WAITING", SLATE)
        self.detail = QLabel(subtitle)
        self.detail.setWordWrap(True)
        self.detail.setStyleSheet("color:#94a3b8;")
        layout.addWidget(title_label)
        layout.addWidget(self.status)
        layout.addWidget(self.detail)

    def set_state(self, text: str, color: str, detail: str | None = None) -> None:
        _set_pill(self.status, text, color)
        if detail is not None:
            self.detail.setText(detail)


class SensorRow:
    def __init__(self, definition: SensorDefinition, settings: QSettings):
        self.definition = definition
        self.raw = _pill("UNKNOWN", SLATE)
        self.state = _pill("UNKNOWN", SLATE)
        self.polarity = QCheckBox("Active-low")
        # Active-low is the safe bench default for NPN/open-collector devices.
        # Every channel remains user-adjustable until its real device is proven.
        default = True
        saved = settings.value(f"polarity/{definition.key}", default)
        self.polarity.setChecked(str(saved).lower() not in {"false", "0", "no"})
        self.value: int | None = None

    def set_value(self, value: int | None) -> None:
        self.value = value
        if value not in (0, 1):
            _set_pill(self.raw, "UNKNOWN", SLATE)
            _set_pill(self.state, "UNKNOWN", SLATE)
            return
        _set_pill(self.raw, "HIGH" if value else "LOW", BLUE if value else AMBER)
        active = value == 0 if self.polarity.isChecked() else value == 1
        _set_pill(self.state, "ON" if active else "OFF", GREEN if active else SLATE)


class SensorBenchWindow(QMainWindow):
    stale_after_seconds = 2.5

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Chop Saw Sensor Bench")
        self.resize(1280, 850)
        self.settings = QSettings("ChopSawHMI", "SensorBench")
        self.link = SerialLink(self)
        self.link.connected.connect(self._on_connected)
        self.link.disconnected.connect(self._on_disconnected)
        self.link.line_received.connect(self.handle_line)
        self.last_packet_at: float | None = None
        self.last_health_at: float | None = None
        self._demo_timer: QTimer | None = None
        self._demo_seq = 0
        self.output_capable = False
        self.outputs_armed = False
        self._stale_output_trip = False

        self._build_ui()
        self._apply_theme()
        self.refresh_ports()

        self.age_timer = QTimer(self)
        self.age_timer.setInterval(250)
        self.age_timer.timeout.connect(self._update_age)
        self.age_timer.start()

        self.keepalive_timer = QTimer(self)
        self.keepalive_timer.setInterval(500)
        self.keepalive_timer.timeout.connect(self._send_output_keepalive)
        self.keepalive_timer.start()

    def _build_ui(self) -> None:
        root_widget = QWidget()
        self.setCentralWidget(root_widget)
        root = QVBoxLayout(root_widget)

        header = QHBoxLayout()
        title = QLabel("SENSOR BENCH")
        title.setStyleSheet("font-size:24px; font-weight:900; color:#60a5fa;")
        header.addWidget(title)
        header.addStretch()
        header.addWidget(QLabel("COM Port:"))
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(260)
        header.addWidget(self.port_combo)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh_ports)
        header.addWidget(refresh)
        self.connect_button = QPushButton("Connect")
        self.connect_button.setProperty("class", "accent")
        self.connect_button.clicked.connect(self.toggle_connection)
        header.addWidget(self.connect_button)
        probe = QPushButton("Probe Hardware")
        probe.clicked.connect(self.probe_hardware)
        header.addWidget(probe)
        self.connection_pill = _pill("DISCONNECTED", RED)
        self.connection_pill.setMinimumWidth(145)
        header.addWidget(self.connection_pill)
        root.addLayout(header)

        health_row = QHBoxLayout()
        self.teensy_card = HealthCard("Teensy 4.1", "Waiting for controller telemetry")
        self.mcp_card = HealthCard("MCP23017", "I2C address 0x27")
        self.ina_card = HealthCard("INA228", "I2C address 0x40")
        for card in (self.teensy_card, self.mcp_card, self.ina_card):
            card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            health_row.addWidget(card)
        root.addLayout(health_row)

        root.addWidget(self._output_panel())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._direct_sensor_panel())
        splitter.addWidget(self._mcp_panel())
        splitter.setSizes([760, 500])
        root.addWidget(splitter, 1)

        log_group = QGroupBox("Serial Log (telemetry + guarded clamp-test commands)")
        log_layout = QVBoxLayout(log_group)
        self.log = QTextBrowser()
        self.log.document().setMaximumBlockCount(400)
        self.log.setMaximumHeight(180)
        log_layout.addWidget(self.log)
        root.addWidget(log_group)

    def _output_panel(self) -> QWidget:
        group = QGroupBox("Air Clamp MOSFET Output Test")
        outer = QVBoxLayout(group)

        warning = QLabel(
            "FIRST TEST: isolate the air supply and disconnect the solenoid loads. "
            "Verify the MOSFET module LED/output with a meter before connecting a valve."
        )
        warning.setWordWrap(True)
        warning.setStyleSheet(
            "background:#451a03; color:#fbbf24; border:1px solid #92400e; "
            "border-radius:9px; padding:8px; font-weight:800;"
        )
        outer.addWidget(warning)

        controls = QHBoxLayout()
        self.output_confirmation = QCheckBox("Air is isolated and the test area is clear")
        self.output_confirmation.toggled.connect(self._confirmation_changed)
        controls.addWidget(self.output_confirmation)
        controls.addStretch()
        self.output_arm_button = QPushButton("ARM OUTPUT TEST")
        self.output_arm_button.clicked.connect(self._toggle_output_arm)
        controls.addWidget(self.output_arm_button)
        self.output_all_off_button = QPushButton("ALL OFF")
        self.output_all_off_button.setProperty("class", "danger")
        self.output_all_off_button.clicked.connect(self._all_outputs_off)
        controls.addWidget(self.output_all_off_button)
        outer.addLayout(controls)

        row = QHBoxLayout()
        self.output_buttons: dict[int, QPushButton] = {}
        self.output_state_pills: dict[str, QLabel] = {}
        for index, label, terminal, pin in CLAMP_OUTPUTS:
            tile = QFrame()
            tile.setObjectName("outputTile")
            tile_layout = QVBoxLayout(tile)
            heading = QLabel(f"{label}  •  {terminal} / {pin}")
            heading.setStyleSheet("font-weight:800;")
            state = _pill("OFF", SLATE)
            button = QPushButton("HOLD TO ENERGIZE")
            button.setProperty("class", "output")
            button.pressed.connect(lambda output=index: self._set_clamp_output(output, True))
            button.released.connect(lambda output=index: self._set_clamp_output(output, False))
            self.output_buttons[index] = button
            self.output_state_pills[f"CLAMP{index + 1}"] = state
            tile_layout.addWidget(heading)
            tile_layout.addWidget(state)
            tile_layout.addWidget(button)
            row.addWidget(tile)
        outer.addLayout(row)
        self._refresh_output_controls()
        return group

    def _direct_sensor_panel(self) -> QWidget:
        group = QGroupBox("Direct Breakout Inputs")
        layout = QGridLayout(group)
        headers = ("Sensor", "Terminal", "Pin", "Raw", "State", "Polarity")
        for column, text in enumerate(headers):
            label = QLabel(text)
            label.setStyleSheet("font-weight:800; color:#94a3b8;")
            layout.addWidget(label, 0, column)

        self.sensor_rows: dict[str, SensorRow] = {}
        for row_number, definition in enumerate(DIRECT_SENSORS, start=1):
            row = SensorRow(definition, self.settings)
            self.sensor_rows[definition.key] = row
            layout.addWidget(QLabel(definition.label), row_number, 0)
            layout.addWidget(QLabel(definition.connection), row_number, 1)
            layout.addWidget(QLabel(definition.pin), row_number, 2)
            layout.addWidget(row.raw, row_number, 3)
            layout.addWidget(row.state, row_number, 4)
            layout.addWidget(row.polarity, row_number, 5)
            row.polarity.toggled.connect(lambda _checked, r=row: self._polarity_changed(r))
        layout.setRowStretch(len(DIRECT_SENSORS) + 1, 1)
        return group

    def _mcp_panel(self) -> QWidget:
        group = QGroupBox("MCP23017 Expansion Inputs")
        outer = QVBoxLayout(group)
        note = QLabel("All channels are input-only with 3.3 V pull-ups. Unassigned channels remain spare.")
        note.setWordWrap(True)
        note.setStyleSheet("color:#94a3b8;")
        outer.addWidget(note)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        grid = QGridLayout(body)
        self.mcp_pills: dict[str, QLabel] = {}
        for index in range(16):
            bank = "PA" if index < 8 else "PB"
            bit = index if index < 8 else index - 8
            name = f"{bank}{bit}"
            tile = QFrame()
            tile.setObjectName("mcpTile")
            tile_layout = QHBoxLayout(tile)
            tile_layout.addWidget(QLabel(name))
            pill = _pill("UNKNOWN", SLATE)
            self.mcp_pills[name] = pill
            tile_layout.addWidget(pill)
            grid.addWidget(tile, index // 2, index % 2)
        scroll.setWidget(body)
        outer.addWidget(scroll)
        return group

    def _apply_theme(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background:#0f172a; color:#e2e8f0; font-size:14px; }
            QGroupBox { border:1px solid #334155; border-radius:12px; margin-top:10px; padding:10px; font-weight:800; }
            QGroupBox::title { subcontrol-origin:margin; left:10px; padding:0 6px; }
            QFrame#healthCard, QFrame#mcpTile, QFrame#outputTile { background:#0b1222; border:1px solid #334155; border-radius:12px; }
            QPushButton { background:#1e293b; color:#e2e8f0; border:1px solid #334155; border-radius:9px; padding:8px 12px; font-weight:700; }
            QPushButton:hover { background:#243142; }
            QPushButton[class="accent"] { background:#10b981; border:none; }
            QPushButton[class="danger"] { background:#b91c1c; border:none; }
            QPushButton[class="output"]:pressed { background:#dc2626; border:none; }
            QPushButton:disabled { background:#111827; color:#64748b; }
            QComboBox { background:#0b1222; color:#e2e8f0; border:1px solid #334155; border-radius:9px; padding:7px; }
            QTextBrowser { background:#020617; color:#cbd5e1; border:1px solid #334155; border-radius:10px; font-family:Consolas,monospace; }
            QScrollArea { border:none; }
            QCheckBox { color:#cbd5e1; }
            """
        )

    def refresh_ports(self) -> None:
        previous = self.port_combo.currentData() or self.settings.value("port", "")
        ports = self.link.ports()
        self.port_combo.clear()
        preferred = -1
        for index, (device, label, vid) in enumerate(ports):
            self.port_combo.addItem(label, device)
            if device == previous or (preferred < 0 and vid == 0x16C0):
                preferred = index
        if preferred >= 0:
            self.port_combo.setCurrentIndex(preferred)

    def toggle_connection(self) -> None:
        if self.link.is_connected:
            self.link.send("OFF")
            self.link.close()
            return
        port = self.port_combo.currentData()
        if not port:
            self._on_disconnected("No serial port selected")
            return
        self.settings.setValue("port", port)
        _set_pill(self.connection_pill, "CONNECTING", AMBER)
        self.link.open(str(port))

    def _on_connected(self, port: str) -> None:
        self.connect_button.setText("Disconnect")
        _set_pill(self.connection_pill, "CONNECTED", GREEN)
        self.teensy_card.set_state("WAITING", AMBER, f"Connected on {port}; waiting for telemetry")
        self.output_capable = False
        self.outputs_armed = False
        self._stale_output_trip = False
        self._refresh_output_controls()
        QTimer.singleShot(250, self.probe_hardware)

    def _on_disconnected(self, reason: str) -> None:
        self.connect_button.setText("Connect")
        _set_pill(self.connection_pill, "DISCONNECTED", RED)
        self.teensy_card.set_state("OFFLINE", RED, reason)
        self.mcp_card.set_state("UNKNOWN", SLATE, "No live controller data")
        self.ina_card.set_state("UNKNOWN", SLATE, "No live controller data")
        self.output_capable = False
        self.outputs_armed = False
        self._set_all_output_pills_unknown()
        self._refresh_output_controls()
        for row in self.sensor_rows.values():
            row.set_value(None)
        for pill in self.mcp_pills.values():
            _set_pill(pill, "UNKNOWN", SLATE)

    def probe_hardware(self) -> None:
        for command in ("HELLO", "PINMAP", "I2C", "STATUS"):
            self.link.send(command)

    def handle_line(self, line: str) -> None:
        self.log.append(line)
        message = parse_line(line)
        if message is None:
            return
        if message.kind != "TEXT":
            self.last_packet_at = time.monotonic()
            self._stale_output_trip = False
            self.teensy_card.set_state("HEALTHY", GREEN, "Live telemetry received")
        self._apply_message(message)

    def _apply_message(self, message: ParsedMessage) -> None:
        fields = message.fields
        if message.kind == "BENCH_HELLO":
            self.output_capable = parse_int(fields.get("TEST_OUTPUTS"), 0) == 3
            capability = "3 guarded clamp outputs" if self.output_capable else "input telemetry only"
            detail = f"Firmware {fields.get('FW', '?')} | Protocol {fields.get('PROTO', '?')} | {capability}"
            self.teensy_card.set_state("HEALTHY", GREEN, detail)
            self._refresh_output_controls()
        elif message.kind == "BENCH_HEALTH":
            self.last_health_at = time.monotonic()
            mcp_ok = parse_int(fields.get("MCP_IO"), 0) == 1
            ina_ok = parse_int(fields.get("INA_ID"), 0) == 1
            self.mcp_card.set_state(
                "HEALTHY" if mcp_ok else "FAULT",
                GREEN if mcp_ok else RED,
                "0x27 register read verified" if mcp_ok else "No valid MCP23017 register response",
            )
            ina_detail = "INA228 IDs verified"
            if fields.get("INA_MFG") or fields.get("INA_DEV"):
                ina_detail += f" | MFG {fields.get('INA_MFG', '?')} DEV {fields.get('INA_DEV', '?')}"
            self.ina_card.set_state("HEALTHY" if ina_ok else "FAULT", GREEN if ina_ok else RED, ina_detail)
        elif message.kind in {"BENCH_INPUTS", "LEGACY_INPUTS"}:
            for key, row in self.sensor_rows.items():
                if key in fields:
                    row.set_value(parse_int(fields[key]))
        elif message.kind == "BENCH_MCP":
            self._set_mcp_bank("PA", parse_int(fields.get("GPIOA")))
            self._set_mcp_bank("PB", parse_int(fields.get("GPIOB")))
        elif message.kind == "BENCH_OUTPUTS":
            self.outputs_armed = parse_int(fields.get("ARMED"), 0) == 1
            for key, pill in self.output_state_pills.items():
                value = parse_int(fields.get(key))
                if value in (0, 1):
                    _set_pill(pill, "ENERGIZED" if value else "OFF", RED if value else SLATE)
                else:
                    _set_pill(pill, "UNKNOWN", SLATE)
            fault = fields.get("FAULT", "NONE")
            if fault != "NONE":
                self.log.append(f"SAFETY: clamp outputs disarmed ({fault})")
            self._refresh_output_controls()
        elif message.kind == "LEGACY_I2C_FOUND":
            address = fields.get("ADDRESS", "").upper()
            if address == "0X27":
                self.mcp_card.set_state("DETECTED", GREEN, "Legacy scan found address 0x27")
            elif address == "0X40":
                self.ina_card.set_state("DETECTED", GREEN, "Legacy scan found address 0x40")

    def _set_mcp_bank(self, bank: str, value: int | None) -> None:
        for bit in range(8):
            pill = self.mcp_pills[f"{bank}{bit}"]
            if value is None:
                _set_pill(pill, "UNKNOWN", SLATE)
                continue
            high = bool(value & (1 << bit))
            _set_pill(pill, "HIGH / OFF" if high else "LOW / ON", SLATE if high else GREEN)

    def _polarity_changed(self, row: SensorRow) -> None:
        self.settings.setValue(f"polarity/{row.definition.key}", row.polarity.isChecked())
        row.set_value(row.value)

    def _refresh_output_controls(self) -> None:
        connected = self.link.is_connected
        confirmed = self.output_confirmation.isChecked() if hasattr(self, "output_confirmation") else False
        capable = connected and self.output_capable
        self.output_arm_button.setEnabled(capable and (confirmed or self.outputs_armed))
        self.output_arm_button.setText("DISARM OUTPUTS" if self.outputs_armed else "ARM OUTPUT TEST")
        self.output_all_off_button.setEnabled(capable)
        for button in self.output_buttons.values():
            button.setEnabled(capable and confirmed and self.outputs_armed)

    def _confirmation_changed(self, confirmed: bool) -> None:
        if not confirmed and self.outputs_armed:
            self._all_outputs_off()
        self._refresh_output_controls()

    def _toggle_output_arm(self) -> None:
        if self.outputs_armed:
            self.link.send("ARM 0")
        elif self.output_confirmation.isChecked():
            self.link.send("ARM 1")

    def _set_clamp_output(self, output: int, energized: bool) -> None:
        # State pills change only when firmware echoes BENCH_OUTPUTS.
        if energized and not (self.outputs_armed and self.output_confirmation.isChecked()):
            return
        self.link.send(f"OUT {output} {1 if energized else 0}")

    def _all_outputs_off(self) -> None:
        self.link.send("OFF")

    def _send_output_keepalive(self) -> None:
        if self.outputs_armed:
            self.link.send("KEEPALIVE")

    def _set_all_output_pills_unknown(self) -> None:
        for pill in self.output_state_pills.values():
            _set_pill(pill, "UNKNOWN", SLATE)

    def _update_age(self) -> None:
        if self.last_packet_at is None or not self.link.is_connected:
            return
        age = time.monotonic() - self.last_packet_at
        if age > self.stale_after_seconds:
            self.teensy_card.set_state("STALE", AMBER, f"No telemetry for {age:.1f} seconds")
            if self.outputs_armed and not self._stale_output_trip:
                self._stale_output_trip = True
                self.link.send("OFF")
                self.outputs_armed = False
                self._refresh_output_controls()

    def start_demo(self) -> None:
        _set_pill(self.connection_pill, "DEMO MODE", BLUE)
        self.connect_button.setEnabled(False)
        self.port_combo.setEnabled(False)
        self.handle_line("BENCH_HELLO,PROTO:2,FW:demo,BOARD:TEENSY41,MAP:T41U5XBB_V2_20,MOTION:0,TEST_OUTPUTS:3")
        self._demo_timer = QTimer(self)
        self._demo_timer.setInterval(600)
        self._demo_timer.timeout.connect(self._demo_tick)
        self._demo_timer.start()

    def _demo_tick(self) -> None:
        self._demo_seq += 1
        bit = self._demo_seq % 2
        self.handle_line(
            f"BENCH_HEALTH,SEQ:{self._demo_seq},UP_MS:{self._demo_seq * 600},"
            "MCP_ACK:1,MCP_IO:1,INA_ACK:1,INA_ID:1,INA_MFG:0x5449,INA_DEV:0x228"
        )
        self.handle_line(
            f"BENCH_INPUTS,SEQ:{self._demo_seq},HOME:1,BOARD_EDGE:{bit},FENCE_DOOR:1,"
            "CL57T_ALM:1,SAW_UP:1,SAW_DOWN:1,FENCE_CLOSED:1,OUTFEED:1"
        )
        self.handle_line(f"BENCH_MCP,SEQ:{self._demo_seq},GPIOA:{hex(0xFF ^ bit)},GPIOB:0xFF")
        self.handle_line("BENCH_OUTPUTS,ARMED:0,CLAMP1:0,CLAMP2:0,CLAMP3:0,FAULT:NONE")

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API name
        if self.link.is_connected:
            self.link.send("OFF")
        self.link.shutdown()
        super().closeEvent(event)
