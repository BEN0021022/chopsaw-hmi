"""Native main-app carriage controls using one shared serial connection.

The controller owns pulse timing and interlocks. This panel never synthesizes
an absolute position, homes automatically, or sends MEGA/pneumatic commands.
"""
import math
import re
import time

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QGroupBox,
    QCheckBox, QPushButton, QDoubleSpinBox,
)
from sensor_bench.protocol import parse_line, parse_int

STEPS_PER_INCH = 127.12
READS = {"HELLO", "PINMAP", "STATUS", "PING"}
STOPS = {"OFF", "XARM 0", "XDISABLE", "RESET"}
IDENTITY = {
    "PROTO": "2", "BOARD": "TEENSY41", "MAP": "T41U5XBB_V2_20",
    "X_APP": "CARRIAGE_V3", "X_TEST": "MANUAL_JOG_V1",
    "X_MAP": "STEP2_DIR3_EN40", "INPUT_MAP": "DOOR29_UP22_DOWN16",
    "OUTPUT_MAP": "AUX2_AUX1_FLOOD", "INTERLOCKS": "DOOR_POSITION_V1",
    "COMMISSIONING": "VALVES_ISOLATED", "CAL_SPI": "127.12",
    "MAX_JOG": "254", "RATE_PPS": "40", "HOME_CHECK": "LEVEL_ONLY",
}
JOG = re.compile(r"XJOG (-1|1) ([1-9][0-9]{0,2})")


class TeensyCarriagePanel(QWidget):
    stale_seconds = 2.0

    def __init__(self, send, log, parent=None):
        super().__init__(parent)
        self.send, self.log = send, log
        self.connected = self.compatible = False
        self.x, self.safety, self.inputs = {}, {}, {}
        self.received = {}
        self.pending = None
        self.stopping = False
        self.local_fault = ""
        self.previous_uptime = None
        layout = QVBoxLayout(self)
        title = QLabel("TEENSY CARRIAGE")
        title.setStyleSheet("font-size:24px; font-weight:bold; color:#60a5fa")
        layout.addWidget(title)
        self.status = QLabel("Disconnected")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.position = QLabel("Commanded displacement: unknown")
        self.position.setStyleSheet("font-size:24px; color:#e2e8f0")
        layout.addWidget(self.position)
        layout.addWidget(QLabel(
            "Pulse-count displacement since controller startup; absolute blade position is not established.\n"
            "127.12 pulses/inch recovered from MEGA V2.5. Positive is away from the saw, toward Home."
        ))
        sensors = QGroupBox("Machine feedback")
        grid = QGridLayout(sensors)
        self.sensor_labels = {}
        for i, (name, label) in enumerate((
            ("FENCE_DOOR", "Door closed"), ("SAW_UP", "Saw fully UP"),
            ("SAW_DOWN", "Saw fully DOWN"), ("HOME", "Home sensor"),
            ("BOARD_EDGE", "Board-edge sensor"), ("CL57T_ALM", "Driver alarm input"),
        )):
            grid.addWidget(QLabel(label), i // 2, (i % 2) * 2)
            self.sensor_labels[name] = QLabel("UNKNOWN")
            grid.addWidget(self.sensor_labels[name], i // 2, (i % 2) * 2 + 1)
        layout.addWidget(sensors)
        setup = QGroupBox("Prepare carriage motion")
        setup_layout = QVBoxLayout(setup)
        isolation_note = QLabel(
            "Saw unplugged; valve 12V disconnected; air isolated; carriage clear; driver green ON/red OFF."
        )
        isolation_note.setWordWrap(True)
        setup_layout.addWidget(isolation_note)
        self.consent = QCheckBox(
            "Isolation and driver checks confirmed"
        )
        self.consent.toggled.connect(self._consent_changed)
        setup_layout.addWidget(self.consent)
        self.setup_note = QLabel(
            "Home sensor must be clear; no trip/release sequence is needed after restart. "
            "Verified driver settings: enable LOW; healthy alarm HIGH."
        )
        self.setup_note.setWordWrap(True)
        setup_layout.addWidget(self.setup_note)
        row = QHBoxLayout()
        self.configure_button = QPushButton("Confirm driver setup")
        self.configure_button.clicked.connect(lambda: self.send("XCONFIG 0 1"))
        self.arm_button = QPushButton("ARM MANUAL CONTROL")
        self.arm_button.clicked.connect(self.toggle_arm)
        self.reset_button = QPushButton("Acknowledge fault")
        self.reset_button.clicked.connect(self.acknowledge)
        for button in (self.configure_button, self.arm_button, self.reset_button):
            row.addWidget(button)
        setup_layout.addLayout(row)
        layout.addWidget(setup)
        jog_box = QGroupBox("Manual carriage jog")
        jog_layout = QVBoxLayout(jog_box)
        row = QHBoxLayout()
        row.addWidget(QLabel("Distance (inches):"))
        self.distance = QDoubleSpinBox()
        self.distance.setRange(0.01, 2.0)
        self.distance.setDecimals(3)
        self.distance.setSingleStep(0.1)
        self.distance.setValue(0.1)
        self.distance.valueChanged.connect(self.refresh)
        row.addWidget(self.distance)
        self.toward_saw = QPushButton("A: TOWARD SAW")
        self.toward_home = QPushButton("B: TOWARD HOME")
        for button, direction in ((self.toward_saw, -1), (self.toward_home, 1)):
            button.setAutoRepeat(False)
            button.clicked.connect(lambda _checked=False, d=direction: self.jog(d))
            row.addWidget(button)
        jog_layout.addLayout(row)
        self.progress = QLabel()
        jog_layout.addWidget(self.progress)
        jog_layout.addWidget(QLabel(
            "One move per click, up to 2 inches. Repeat jogs while armed; no session travel budget.\n"
            "Home, absolute length moves and automatic cutting remain unavailable pending commissioning."
        ))
        layout.addWidget(jog_box)
        row = QHBoxLayout()
        self.stop_button = QPushButton("STOP / DISARM")
        self.stop_button.setStyleSheet("background:#b91c1c; color:white; font-weight:bold; min-height:42px")
        self.stop_button.clicked.connect(lambda: self.stop())
        self.release_button = QPushButton("Release motor holding torque")
        self.release_button.clicked.connect(lambda: self.stop("XDISABLE"))
        row.addWidget(self.stop_button)
        row.addWidget(self.release_button)
        layout.addLayout(row)
        layout.addWidget(QLabel("Current sensing deferred. Pneumatic and blade controls are unavailable in this mode."))
        layout.addStretch()
        for label in self.findChildren(QLabel):
            label.setWordWrap(True)
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        self.refresh()

    def session(self, connected):
        self.connected = connected
        self.compatible = False
        self.x, self.safety, self.inputs, self.received = {}, {}, {}, {}
        self.pending = None
        self.stopping = False
        self.local_fault = ""
        self.previous_uptime = None
        self.consent.setChecked(False)
        self.refresh()

    def fresh(self, name):
        return name in self.received and time.monotonic() - self.received[name] <= self.stale_seconds

    @property
    def armed(self):
        return self.x.get("ARMED") == "1"

    def ready_link(self):
        return self.connected and self.compatible and self.fresh("X") and self.fresh("SAFETY")

    def allowed(self, command):
        """Applied at the main app's serial-write boundary, including programmatic calls."""
        if command in READS or command in STOPS:
            return True
        if (not self.ready_link() or self.local_fault or self.stopping
                or not self.consent.isChecked() or self.x.get("FAULT") != "NONE"
                or self.safety.get("FAULT") != "NONE"
                or self.safety.get("DOOR_CLOSED") != "1"
                or self.safety.get("SAW_POSITION") != "UP"
                or self.x.get("HOME_RAW") != "1" or self.x.get("ALARM_RAW") != "1"):
            return False
        if command == "KEEPALIVE":
            return self.armed
        idle = not self.armed and self.x.get("REMAINING") == "0"
        if command == "XCONFIG 0 1":
            return idle and self.safety.get("READY") == "1"
        if command == "XARM 1":
            return idle and self.x.get("READY") == "1" and self.x.get("CONFIGURED") == "1"
        match = JOG.fullmatch(command)
        if not match:
            return False
        count = int(match[2])
        return (self.armed and not self.pending and self.x.get("REMAINING") == "0"
                and self.x.get("JOG_READY") == "1"
                and 1 <= count <= parse_int(self.x.get("MAX_JOG"), 0))

    def handle_line(self, line):
        if not self.connected:
            return
        message = parse_line(line)
        if not message:
            return
        f = message.fields
        if message.kind == "BENCH_HELLO":
            compatible = all(f.get(k) == value for k, value in IDENTITY.items())
            if self.compatible and not compatible:
                self.trip_local("Controller identity changed")
            self.compatible = compatible
        elif message.kind == "BENCH_X":
            numeric = ("ARMED", "CONFIGURED", "READY", "HOME_VERIFIED", "HOME_RAW", "ALARM_RAW",
                       "STEP", "DIR", "ENA", "MAX_JOG", "REMAINING", "POS_STEPS", "MOVE_ID", "UP_MS", "JOG_READY", "RATE_PPS")
            if any(parse_int(f.get(k)) is None for k in numeric) or f.get("CAL_SPI") != "127.12":
                self.trip_local("Invalid carriage telemetry")
                return
            if any(f.get(k) not in ("0", "1") for k in (*numeric[:9], "JOG_READY")):
                self.trip_local("Invalid carriage state")
                return
            if (f["MAX_JOG"] != "254" or f["RATE_PPS"] != "40"
                    or not 0 <= int(f["REMAINING"]) <= int(f["MAX_JOG"])):
                self.trip_local("Invalid manual jog limit")
                return
            uptime = int(f["UP_MS"])
            if self.previous_uptime is not None and uptime < self.previous_uptime:
                self.trip_local("Controller restarted; verify Home and driver setup again")
            self.previous_uptime = uptime
            self.x = f
            if f["ARMED"] == "0":
                self.stopping = False
            self.received["X"] = time.monotonic()
            if self.pending and (int(f["MOVE_ID"]) != self.pending[0] or f["ARMED"] == "0"):
                self.pending = None
        elif message.kind == "BENCH_SAFETY":
            if f.get("READY") not in ("0", "1") or f.get("DOOR_CLOSED") not in ("0", "1"):
                self.trip_local("Invalid safety telemetry")
                return
            self.safety = f
            self.received["SAFETY"] = time.monotonic()
        elif message.kind == "BENCH_INPUTS":
            self.inputs = f
            self.received["INPUTS"] = time.monotonic()
        elif message.kind == "BENCH_ERROR":
            self.log("Teensy rejected command: " + f.get("CODE", "UNKNOWN"))
            if self.pending:
                self.stop()
        self.refresh()

    def trip_local(self, reason):
        if not self.local_fault:
            self.local_fault = reason
            self.log(reason)
            if self.connected:
                self.send("OFF")
        self.pending = None
        self.consent.setChecked(False)
        self.refresh()

    def _consent_changed(self, checked):
        if not checked and self.armed:
            self.stop()
        self.refresh()

    def acknowledge(self):
        if not self.ready_link():
            return
        self.local_fault = ""
        self.send("RESET")
        self.refresh()  # reset does not arm or restore consent

    def stop(self, command="OFF"):
        if self.connected:
            self.stopping = True
            self.send(command)
        self.pending = None
        self.refresh()

    def toggle_arm(self):
        self.send("XARM 0" if self.armed else "XARM 1")

    def jog(self, direction):
        count = int(math.floor(self.distance.value() * STEPS_PER_INCH + 0.5))
        command = f"XJOG {direction} {count}"
        if self.allowed(command) and self.send(command):
            self.pending = (int(self.x["MOVE_ID"]), time.monotonic())
            self.refresh()

    def tick(self):
        if self.connected and self.armed:
            if not self.ready_link():
                self.trip_local("Controller telemetry stale; motion stopped")
            elif not self.consent.isChecked() or self.local_fault:
                self.stop()
            elif self.stopping:
                pass  # Await a disarmed acknowledgment; never refresh the watchdog.
            elif not self.allowed("KEEPALIVE"):
                self.trip_local("Controller safety conditions changed; motion stopped")
            else:
                self.send("KEEPALIVE")
        if self.pending and time.monotonic() - self.pending[1] > 1.0:
            self.trip_local("Move acknowledgment timed out")
        self.refresh()

    def refresh(self, *_args):
        link = self.ready_link()
        fault = self.x.get("FAULT", "NONE")
        remaining = parse_int(self.x.get("REMAINING"), 0)
        max_jog = parse_int(self.x.get("MAX_JOG"), 0)
        busy = bool(remaining or self.pending)
        if not self.connected:
            text = "Disconnected - select Teensy Carriage and connect"
        elif not self.compatible:
            text = "Waiting for compatible manual-jog firmware 0.9.0 and verified machine pin map"
        elif not link:
            text = "Waiting for fresh controller and safety feedback"
        elif self.local_fault or fault != "NONE":
            text = "FAULT: " + (self.local_fault or fault)
        elif busy:
            text = "MOVING" if remaining else "Waiting for move acknowledgment"
        elif self.stopping:
            text = "Stopping - waiting for controller acknowledgment"
        elif self.armed:
            text = ("ARMED - ready for repeatable manual jogs" if self.x.get("JOG_READY") == "1"
                    else "ARMED - waiting for driver enable to settle")
        else:
            blocker = self.safety.get("BLOCKER", "verify setup")
            if blocker != "NONE":
                text = "DISARMED - " + blocker
            elif not self.consent.isChecked():
                text = "Confirm isolation and driver checks to prepare manual motion"
            elif self.x.get("CONFIGURED") != "1":
                text = "Click Confirm driver setup, then arm manual control"
            else:
                text = "Ready - click ARM MANUAL CONTROL"
        self.status.setText(text)
        self.status.setStyleSheet("color:" + ("#ef4444" if self.local_fault or fault != "NONE" else "#60a5fa"))
        steps = parse_int(self.x.get("POS_STEPS")) if self.fresh("X") else None
        self.position.setText("Commanded displacement: unknown" if steps is None else
                              f"Commanded displacement: {steps / STEPS_PER_INCH:+.4f} in ({steps} pulses)")
        for key, label in self.sensor_labels.items():
            raw = self.inputs.get(key) if self.fresh("INPUTS") else None
            value = "UNKNOWN" if raw not in ("0", "1") else (
                ("ALARM" if raw == "0" else "NORMAL") if key == "CL57T_ALM" else
                ("ACTIVE" if raw == "0" else "INACTIVE"))
            label.setText(value)
        home_clear = self.x.get("HOME_RAW") == "1"
        self.setup_note.setText(
            ("Home limit clear" if home_clear else "Home limit active or unknown - manual motion blocked")
            + " | Enable LOW; healthy alarm HIGH. No sensor trip is required after restart."
        )
        self.progress.setText(f"Move remaining: {remaining} pulses | Maximum per click: {max_jog} pulses (~2 in) | 40 pulses/s")
        self.configure_button.setEnabled(self.allowed("XCONFIG 0 1"))
        self.arm_button.setText("DISARM MANUAL CONTROL" if self.armed else "ARM MANUAL CONTROL")
        self.arm_button.setEnabled(self.connected and (self.armed or self.allowed("XARM 1")))
        count = int(math.floor(self.distance.value() * STEPS_PER_INCH + 0.5))
        self.toward_saw.setEnabled(self.allowed(f"XJOG -1 {count}"))
        self.toward_home.setEnabled(self.allowed(f"XJOG 1 {count}"))
        self.distance.setEnabled(not busy)
        self.reset_button.setEnabled(link and not self.armed)
        self.stop_button.setEnabled(self.connected)
        self.release_button.setEnabled(self.connected and self.compatible)
