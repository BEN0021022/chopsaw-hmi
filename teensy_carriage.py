"""Native main-app carriage controls using one shared serial connection.

The controller owns pulse timing and interlocks. This panel never synthesizes
an absolute position, homes automatically, or sends MEGA/pneumatic commands.
"""
import math
import re
import time

from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QGroupBox,
    QCheckBox, QPushButton, QDoubleSpinBox, QScrollArea, QComboBox,
)
from sensor_bench.protocol import parse_line, parse_int

STEPS_PER_INCH = 127.12
READS = {"HELLO", "PINMAP", "STATUS", "PING"}
STOPS = {"OFF", "XARM 0", "XDISABLE", "RESET"}
IDENTITY = {
    "PROTO": "2", "BOARD": "TEENSY41", "MAP": "T41U5XBB_V2_20",
    "X_APP": "CARRIAGE_V7", "X_TEST": "MANUAL_JOG_V1",
    "X_MAP": "STEP2_DIR3_EN40", "INPUT_MAP": "DOOR29_UP22_DOWN16",
    "OUTPUT_MAP": "AUX2_AUX1_FLOOD", "INTERLOCKS": "DOOR_POSITION_V1",
    "COMMISSIONING": "VALVES_ISOLATED", "CAL_SPI": "127.12",
    "MAX_JOG": "254", "BASE_RATE": "40", "MAX_RATE": "127", "PROFILES": "RAMP_V1", "HOME_CHECK": "LEVEL_ONLY",
    "HOMING": "BOUNDED_V1", "HOME_MAX": "20594", "HOME_REF": "160.5",
    "ABSOLUTE": "REFERENCED_V1", "MAX_MOVE": "20594",
    "EDGE_SEARCH": "BOUNDED_V1",
}
EDGE = re.compile(r"XEDGE ([1-9][0-9]{0,4}) (0|[1-9][0-9]{0,5}) (0|[1-9][0-9]{0,5})")
TRUING = re.compile(r"XTRUING (0|[1-9][0-9]{0,9})")
PROFILE = re.compile(r"XPROFILE ([0-3])")
PROFILE_LIMITS = {0:(40,0),1:(40,40),2:(80,160),3:(127,254)}
ABSOLUTE = re.compile(r"XMOVE (0|[1-9][0-9]{0,5})")
HOME = re.compile(r"XHOME ([1-9][0-9]{0,4})")
HOME_STAGES = {"SEEK", "RELEASE", "BACKOFF", "LATCH", "PULL_RELEASE", "PULL_OFF"}
JOG = re.compile(r"XJOG (-1|1) ([1-9][0-9]{0,2})")


class TeensyCarriagePanel(QWidget):
    profile_changed = pyqtSignal(int)
    homed_changed = pyqtSignal(int)
    machine_position_changed = pyqtSignal(float)
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
        self._target_initialized = False
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { background:#0b1222; border:0; }")
        body = QWidget()
        body.setObjectName("carriageBody")
        body.setStyleSheet("QWidget#carriageBody { background:#0b1222; }")
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        layout = QVBoxLayout(body)
        title = QLabel("TEENSY CARRIAGE")
        title.setStyleSheet("font-size:24px; font-weight:bold; color:#60a5fa")
        layout.addWidget(title)
        self.status = QLabel("Disconnected")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.position = QLabel("Commanded displacement: unknown")
        self.position.setStyleSheet("font-size:24px; color:#e2e8f0")
        layout.addWidget(self.position)
        self.machine_position = QLabel("Machine position: UNKNOWN - not homed")
        self.machine_position.setStyleSheet("font-size:22px; color:#fbbf24")
        layout.addWidget(self.machine_position)
        layout.addWidget(QLabel(
            "Machine position is established only by a completed Home cycle; faults and motor release invalidate it.\n"
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
        profile_row = QHBoxLayout()
        self.profile_combo = QComboBox()
        for name, profile in (("Commissioning - 40 pulses/s (proven)",0),
                              ("Gentle - 40 pulses/s, ramped",1),
                              ("Normal - 80 pulses/s, ramped",2),
                              ("Fast - 127 pulses/s, ramped",3)):
            self.profile_combo.addItem(name,profile)
        self.profile_apply = QPushButton("Apply profile (disarmed)")
        self.profile_apply.clicked.connect(lambda: self.select_profile(self.profile_combo.currentData()))
        self.profile_label = QLabel("Controller profile: unknown")
        profile_row.addWidget(self.profile_combo)
        profile_row.addWidget(self.profile_apply)
        setup_layout.addLayout(profile_row)
        setup_layout.addWidget(self.profile_label)
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
            "Homed jogs obey the same soft limits as absolute moves. Automatic cutting remains unavailable."
        ))
        home_box = QGroupBox("Home carriage - automatic bounded sequence")
        home_layout = QVBoxLayout(home_box)
        row = QHBoxLayout()
        row.addWidget(QLabel("Maximum initial search (inches):"))
        self.home_search = QDoubleSpinBox()
        self.home_search.setRange(0.25, 162)
        self.home_search.setDecimals(2)
        self.home_search.setValue(2)
        row.addWidget(self.home_search)
        self.home_button = QPushButton("HOME CARRIAGE")
        self.home_button.clicked.connect(self.home)
        row.addWidget(self.home_button)
        home_layout.addLayout(row)
        home_note = QLabel(
            "Disarm manual control first. HOME starts motion toward B/Home, then backs away, "
            "re-approaches slowly and pulls clear. Allow up to 1.35 inches of backoff clearance. "
            "Start near Home with the default 2-inch search. Home reference: 160.5 inches."
        )
        home_note.setWordWrap(True)
        home_layout.addWidget(home_note)
        layout.addWidget(home_box)
        layout.addWidget(jog_box)
        absolute_box = QGroupBox("Referenced position and loading")
        absolute_layout = QVBoxLayout(absolute_box)
        row = QHBoxLayout()
        row.addWidget(QLabel("Target blade distance (inches):"))
        self.target = QDoubleSpinBox()
        self.target.setRange(0, 160.5)
        self.target.setDecimals(3)
        self.target.setSingleStep(1)
        row.addWidget(self.target)
        self.go_button = QPushButton("GO TO POSITION")
        self.go_button.clicked.connect(lambda: self.move_to(self.target.value()))
        row.addWidget(self.go_button)
        absolute_layout.addLayout(row)
        row = QHBoxLayout()
        self.load_preset = QComboBox()
        self.load_preset.setStyleSheet(
            "QComboBox { background:#0b1222; color:#e2e8f0; border:1px solid #334155; padding:8px; }"
            "QComboBox:disabled { color:#64748b; }"
            "QComboBox QAbstractItemView { background:#0b1222; color:#e2e8f0; selection-background-color:#1e40af; }"
        )
        for label, target in (("Home / load position", None), ("10 ft stock - load at 135 in", 135),
                              ("8 ft stock - load at 111 in", 111), ("6 ft stock - load at 87 in", 87),
                              ("4 ft stock - load at 63 in", 63)):
            self.load_preset.addItem(label, target)
        row.addWidget(self.load_preset)
        self.load_button = QPushButton("MOVE TO LOAD POSITION")
        self.load_button.clicked.connect(lambda: self.move_to(self.selected_load_position()))
        row.addWidget(self.load_button)
        absolute_layout.addLayout(row)
        self.limit_note = QLabel()
        absolute_layout.addWidget(self.limit_note)
        self.absolute_progress = QLabel()
        absolute_layout.addWidget(self.absolute_progress)
        absolute_layout.addWidget(QLabel(
            "Home successfully, arm carriage motion, then select a target. Confirm the entire path is clear. "
            "Moves use the acknowledged controller profile. STOP cancels; moves never queue or resume automatically."
        ))
        layout.addWidget(absolute_box)
        edge_box = QGroupBox("Board-edge search and truing proposal")
        edge_layout = QVBoxLayout(edge_box)
        row = QHBoxLayout()
        self.edge_search = QDoubleSpinBox()
        self.edge_search.setRange(0.01, 162)
        self.edge_search.setDecimals(2)
        self.edge_search.setValue(2)
        self.sensor_offset = QDoubleSpinBox()
        self.sensor_offset.setRange(0,160.5)
        self.sensor_offset.setDecimals(3)
        self.sensor_offset.setValue(10.8)
        self.trim_overlap = QDoubleSpinBox()
        self.trim_overlap.setRange(0,160.5)
        self.trim_overlap.setDecimals(3)
        self.trim_overlap.setValue(0.25)
        for text, control in (("Search limit (in)",self.edge_search),
                              ("Sensor offset (in)",self.sensor_offset),
                              ("Trim overlap (in)",self.trim_overlap)):
            row.addWidget(QLabel(text)); row.addWidget(control)
        edge_layout.addLayout(row)
        self.edge_button = QPushButton("FIND BOARD EDGE")
        self.edge_button.clicked.connect(self.find_edge)
        edge_layout.addWidget(self.edge_button)
        self.edge_result = QLabel("No valid board-edge capture")
        edge_layout.addWidget(self.edge_result)
        self.truing_button = QPushButton("MOVE TO CAPTURED TRUING POSITION")
        self.truing_button.clicked.connect(self.move_to_truing)
        edge_layout.addWidget(self.truing_button)
        edge_layout.addWidget(QLabel(
            "Home, arm, and start with the edge sensor clear. Search moves A/toward saw at 40 pulses/s, "
            "then stops and disarms on detection. Inspect the proposed position and rearm for a separate move. "
            "Defaults are recovered geometry, awaiting physical acceptance. No clamp or saw action occurs."
        ))
        layout.addWidget(edge_box)
        row = QHBoxLayout()
        self.stop_button = QPushButton("STOP / DISARM")
        self.stop_button.setStyleSheet("background:#b91c1c; color:white; font-weight:bold; min-height:42px")
        self.stop_button.clicked.connect(lambda: self.stop())
        self.release_button = QPushButton("Release motor holding torque")
        self.release_button.clicked.connect(lambda: self.stop("XDISABLE"))
        row.addWidget(self.stop_button)
        row.addWidget(self.release_button)
        outer.addLayout(row)
        layout.addWidget(QLabel("Current sensing deferred. Pneumatic and blade controls are unavailable in this mode."))
        layout.addStretch()
        for label in self.findChildren(QLabel):
            label.setWordWrap(True)
        self.target.valueChanged.connect(self.refresh)
        self.load_preset.currentIndexChanged.connect(self.refresh)
        self.home_search.valueChanged.connect(self.refresh)
        for control in (self.edge_search,self.sensor_offset,self.trim_overlap):
            control.valueChanged.connect(self.refresh)
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
        self._target_initialized = False
        self.consent.setChecked(False)
        self.homed_changed.emit(0)
        self.refresh()

    def fresh(self, name):
        return name in self.received and time.monotonic() - self.received[name] <= self.stale_seconds

    @property
    def armed(self):
        return self.x.get("ARMED") == "1"

    @property
    def homing(self):
        return self.x.get("HOME_STATE") in HOME_STAGES

    @property
    def edge_searching(self):
        return self.x.get("EDGE_STATE") == "SEEK"

    def edge_command(self):
        pulses = int(math.floor(self.edge_search.value()*STEPS_PER_INCH+0.5))
        offset = int(math.floor(self.sensor_offset.value()*1000+0.5))
        trim = int(math.floor(self.trim_overlap.value()*1000+0.5))
        return f"XEDGE {pulses} {offset} {trim}"

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
                or self.x.get("ALARM_RAW") != "1"):
            return False
        if PROFILE.fullmatch(command):
            return not self.armed and not self.pending and self.x.get("REMAINING") == "0"
        if command == "KEEPALIVE":
            return self.armed and (self.homing or self.x.get("HOME_RAW") == "1")
        idle = not self.armed and self.x.get("REMAINING") == "0"
        if command == "XCONFIG 0 1":
            return idle and self.safety.get("READY") == "1"
        home = HOME.fullmatch(command)
        if home:
            return (idle and not self.pending and self.x.get("CONFIGURED") == "1"
                    and self.safety.get("READY") == "1" and 1 <= int(home[1]) <= 20594)
        if self.x.get("HOME_RAW") != "1":
            return False
        if command == "XARM 1":
            return idle and self.x.get("READY") == "1" and self.x.get("CONFIGURED") == "1"
        edge = EDGE.fullmatch(command)
        if edge:
            return (self.armed and not self.pending and self.x.get("REMAINING") == "0"
                    and self.x.get("JOG_READY") == "1" and self.x.get("POS_KNOWN") == "1"
                    and self.fresh("INPUTS") and self.inputs.get("BOARD_EDGE") == "1"
                    and 1 <= int(edge[1]) <= 20594 and 0 <= int(edge[2]) <= 160500
                    and 0 <= int(edge[3]) <= 160500
                    and int(self.x["HOME_OFFSET"]) - int(edge[1]) >= int(self.x["SOFT_MIN_OFFSET"]))
        truing = TRUING.fullmatch(command)
        if truing:
            return (self.armed and not self.pending and self.x.get("REMAINING") == "0"
                    and self.x.get("JOG_READY") == "1" and self.x.get("EDGE_VALID") == "1"
                    and truing[1] == self.x.get("MOVE_ID"))
        absolute = ABSOLUTE.fullmatch(command)
        if absolute:
            return (self.armed and not self.pending and self.x.get("REMAINING") == "0"
                    and self.x.get("JOG_READY") == "1" and self.x.get("POS_KNOWN") == "1"
                    and 0 <= int(absolute[1]) <= parse_int(self.x.get("SOFT_MAX_MILLI"), -1))
        match = JOG.fullmatch(command)
        if not match:
            return False
        count = int(match[2])
        if self.x.get("POS_KNOWN") == "1":
            next_offset = int(self.x["HOME_OFFSET"]) + int(match[1]) * count
            if not int(self.x["SOFT_MIN_OFFSET"]) <= next_offset <= int(self.x["SOFT_MAX_OFFSET"]):
                return False
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
                       "STEP", "DIR", "ENA", "MAX_JOG", "REMAINING", "POS_STEPS", "MOVE_ID", "UP_MS", "JOG_READY", "RATE_PPS", "POS_KNOWN", "HOME_OFFSET", "SOFT_MIN_OFFSET", "SOFT_MAX_OFFSET", "SOFT_MAX_MILLI", "MAX_MOVE", "TARGET_OFFSET", "PROFILE_ID", "ACCEL_PPS2",
                       "EDGE_VALID", "EDGE_MILLI", "TRUING_MILLI", "SENSOR_OFFSET_MILLI", "TRIM_MILLI")
            if any(parse_int(f.get(k)) is None for k in numeric) or f.get("CAL_SPI") != "127.12":
                self.trip_local("Invalid carriage telemetry")
                return
            if any(f.get(k) not in ("0", "1") for k in (*numeric[:9], "JOG_READY", "POS_KNOWN", "EDGE_VALID")):
                self.trip_local("Invalid carriage state")
                return
            if (f.get("HOME_REF") != "160.5" or f.get("HOME_STATE") not in HOME_STAGES | {"IDLE", "DONE", "FAILED", "CANCELLED"}
                    or (f["POS_KNOWN"] == "1" and f.get("HOME_STATE") in HOME_STAGES)):
                self.trip_local("Invalid homing telemetry")
                return
            if (f["MAX_JOG"] != "254" or
                    PROFILE_LIMITS.get(int(f["PROFILE_ID"])) != (int(f["RATE_PPS"]),int(f["ACCEL_PPS2"]))
                    or f.get("MAX_MOVE") != "20594" or f.get("MOVE_KIND") not in {"IDLE", "JOG", "ABSOLUTE", "EDGE"}
                    or not 0 <= int(f["REMAINING"]) <= int(f["MAX_MOVE"])
                    or (f["MOVE_KIND"] == "JOG" and int(f["REMAINING"]) > int(f["MAX_JOG"]))):
                self.trip_local("Invalid manual jog limit")
                return
            uptime = int(f["UP_MS"])
            if self.previous_uptime is not None and uptime < self.previous_uptime:
                self.trip_local("Controller restarted; verify Home and driver setup again")
            self.previous_uptime = uptime
            if f["POS_KNOWN"] == "1" and not (
                    int(f["SOFT_MIN_OFFSET"]) <= int(f["HOME_OFFSET"]) <= int(f["SOFT_MAX_OFFSET"]) <= 0
                    and 0 <= int(f["SOFT_MAX_MILLI"]) <= 160500):
                self.trip_local("Referenced position outside soft limits")
                return
            if f["MOVE_KIND"] == "ABSOLUTE" and (f["POS_KNOWN"] != "1" or not
                    int(f["SOFT_MIN_OFFSET"]) <= int(f["TARGET_OFFSET"]) <= int(f["SOFT_MAX_OFFSET"])):
                self.trip_local("Invalid referenced move telemetry")
                return
            if (f.get("EDGE_STATE") not in {"IDLE","SEEK","FOUND","FAILED","CANCELLED"}
                    or (f["MOVE_KIND"] == "EDGE" and (f["EDGE_STATE"] != "SEEK" or f["POS_KNOWN"] != "1" or f["ARMED"] != "1"))
                    or (f["EDGE_STATE"] == "SEEK" and f["MOVE_KIND"] != "EDGE")
                    or (f["EDGE_VALID"] == "1" and (f["EDGE_STATE"] != "FOUND" or f["POS_KNOWN"] != "1"
                        or not 0 <= int(f["TRUING_MILLI"]) <= int(f["SOFT_MAX_MILLI"])
                        or int(f["TRUING_MILLI"]) != int(f["EDGE_MILLI"])-int(f["SENSOR_OFFSET_MILLI"])+int(f["TRIM_MILLI"])))):
                self.trip_local("Invalid board-edge telemetry")
                return
            self.x = f
            self.profile_changed.emit(int(f["PROFILE_ID"]))
            self.homed_changed.emit(int(f["POS_KNOWN"]))
            if f["POS_KNOWN"] == "1":
                self.machine_position_changed.emit(160.5 + int(f["HOME_OFFSET"]) / STEPS_PER_INCH)
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

    def select_profile(self, profile):
        command = f"XPROFILE {profile}"
        return self.allowed(command) and self.send(command)

    def find_edge(self):
        return self.request_move(self.edge_command())

    def move_to_truing(self):
        return self.request_move(f"XTRUING {self.x.get('MOVE_ID','-1')}")

    def request_move(self, command):
        if self.allowed(command) and self.send(command):
            self.pending = (int(self.x["MOVE_ID"]),time.monotonic())
            self.refresh()
            return True
        return False

    def selected_load_position(self):
        value = self.load_preset.currentData()
        return int(self.x.get("SOFT_MAX_MILLI", "0")) / 1000 if value is None else float(value)

    def move_to(self, inches):
        if not isinstance(inches, (int, float)) or not math.isfinite(inches) or inches < 0:
            return False
        milli = int(math.floor(inches * 1000 + 0.5))
        command = f"XMOVE {milli}"
        if self.allowed(command) and self.send(command):
            self.pending = (int(self.x["MOVE_ID"]), time.monotonic())
            self.refresh()
            return True
        return False

    def home(self):
        count = int(math.floor(self.home_search.value() * STEPS_PER_INCH + 0.5))
        command = f"XHOME {count}"
        if self.allowed(command) and self.send(command):
            self.pending = (int(self.x["MOVE_ID"]), time.monotonic())
            self.refresh()

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
        busy = bool(remaining or self.pending or self.homing or self.edge_searching)
        if not self.connected:
            text = "Disconnected - select Teensy Carriage and connect"
        elif not self.compatible:
            text = "Waiting for compatible carriage firmware 0.13.0 and verified machine pin map"
        elif not link:
            text = "Waiting for fresh controller and safety feedback"
        elif self.local_fault or fault != "NONE":
            text = "FAULT: " + (self.local_fault or fault) + (" / " + self.x.get("HOME_ERROR", "") if fault == "HOME_FAILED" else "")
        elif self.homing:
            text = "HOMING: " + self.x.get("HOME_STATE", "")
        elif self.edge_searching:
            text = "FINDING BOARD EDGE - toward saw at 40 pulses/s"
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
            ("Home limit clear" if home_clear else "Home limit active or unknown - manual jog blocked; Home can release it")
            + " | Enable LOW; healthy alarm HIGH. No sensor trip is required after restart."
        )
        self.progress.setText(f"Current move: {remaining} pulses left | Jog limit: {max_jog} pulses (~2 in) | {self.x.get('RATE_PPS', '?')} pulses/s")
        if self.x.get("MOVE_KIND") == "ABSOLUTE" and self.fresh("X"):
            destination = 160.5 + int(self.x["TARGET_OFFSET"]) / STEPS_PER_INCH
            self.absolute_progress.setText(f"Moving to {destination:.3f} in; {remaining/STEPS_PER_INCH:.3f} in remaining. STOP cancels.")
        else:
            self.absolute_progress.setText("No absolute move in progress")
        if self.fresh("X") and self.x.get("POS_KNOWN") == "1":
            machine = 160.5 + int(self.x["HOME_OFFSET"]) / STEPS_PER_INCH
            self.machine_position.setText(f"Machine position (HOMED): {machine:.4f} in")
        else:
            self.machine_position.setText("Machine position: UNKNOWN - Home required for referenced moves")
        count_home = int(math.floor(self.home_search.value() * STEPS_PER_INCH + 0.5))
        known = self.fresh("X") and self.x.get("POS_KNOWN") == "1"
        maximum = int(self.x.get("SOFT_MAX_MILLI", "0")) / 1000 if known else 0
        self.target.blockSignals(True)
        self.target.setMaximum(maximum)
        if known and not self._target_initialized:
            self.target.setValue(min(maximum, 160.5 + int(self.x["HOME_OFFSET"]) / STEPS_PER_INCH))
            self._target_initialized = True
        if not known:
            self._target_initialized = False
        self.target.blockSignals(False)
        self.target.setEnabled(known and not busy)
        self.load_preset.setEnabled(known and not busy)
        self.go_button.setEnabled(self.allowed(f"XMOVE {int(math.floor(self.target.value()*1000+0.5))}"))
        self.load_button.setEnabled(self.allowed(f"XMOVE {int(math.floor(self.selected_load_position()*1000+0.5))}"))
        self.limit_note.setText(f"Software range: 0.000 to {maximum:.3f} in (Home pull-off). Targets round to whole motor steps." if known
                                else "Home required before absolute or load-position moves")
        self.home_button.setEnabled(self.allowed(f"XHOME {count_home}"))
        self.edge_button.setEnabled(self.allowed(self.edge_command()))
        self.truing_button.setEnabled(self.allowed(f"XTRUING {self.x.get('MOVE_ID','-1')}"))
        for control in (self.edge_search,self.sensor_offset,self.trim_overlap):
            control.setEnabled(not busy)
        if self.fresh("X") and self.x.get("EDGE_VALID") == "1":
            self.edge_result.setText(
                f"Captured edge at {int(self.x['EDGE_MILLI'])/1000:.3f} in; proposed truing position "
                f"{int(self.x['TRUING_MILLI'])/1000:.3f} in. Rearm, then explicitly request that move. "
                f"Capture uses {int(self.x['SENSOR_OFFSET_MILLI'])/1000:.3f} in offset and "
                f"{int(self.x['TRIM_MILLI'])/1000:.3f} in overlap."
            )
        else:
            self.edge_result.setText("No valid board-edge capture | " + self.x.get("EDGE_STATE","UNKNOWN")
                                    + " | " + self.x.get("EDGE_ERROR",""))
        self.home_search.setEnabled(not self.armed and not self.pending)
        profile = parse_int(self.x.get("PROFILE_ID"))
        self.profile_label.setText("Controller profile: unknown" if profile not in PROFILE_LIMITS else
                                  f"Controller profile: {profile} | {self.x['RATE_PPS']} pulses/s | acceleration {self.x['ACCEL_PPS2']} pulses/s?")
        self.profile_combo.setEnabled(not self.armed and not self.pending)
        self.profile_apply.setEnabled(self.allowed(f"XPROFILE {self.profile_combo.currentData()}"))
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
