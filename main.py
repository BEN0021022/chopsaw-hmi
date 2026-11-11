# main.py

import sys
import os
import serial
import serial.tools.list_ports
import time
import threading
from math import sqrt
import re
from datetime import datetime
from PyQt6.QtWidgets import QSizePolicy



from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QPushButton, QTextBrowser, QLabel, QGridLayout,
    QDoubleSpinBox, QGroupBox, QCheckBox, QTabWidget, QToolButton,
    QFileDialog, QTextEdit, QRadioButton, QComboBox, QProgressBar,
    QFormLayout, QMessageBox, QProgressDialog, QScrollArea
)
from PyQt6.QtCore import Qt, QTimer, QSettings, QThread, pyqtSignal
from PyQt6.QtGui import QTextCursor, QIcon

# Import from our other modules
from config import SERIAL_PORT, BAUD_RATE, PROFILE_MAP
from serial_handler import SignalBridge, listen_for_data
from ui_components import KeypadWidget, CutLengthKeypad, CurrentGraphWidget
from live_health import native_health, simulator_health, simulator_data_valid, HealthState, TelemetryActivity
from pneumatic_timing import CylinderTimingPanel, CLAMPS, simulation_clamps
from manual_pneumatics import ManualPneumatics
from dry_run_control import NativeDryRun, COMMAND as DRY_COMMAND, TRAVEL as DRY_TRAVEL
from cutlist_manager import CutListManagerTab
from simulator import VirtualController, TRUING_TRIM
from sim_view import SawSimWidget, PIECE_COLORS, TRIM_COLOR, SCRAP_COLOR
from _version import __version__ as APP_VERSION
from controller_backends import (
    CONTROLLER_MODES,
    LEGACY_MEGA,
    TEENSY_CARRIAGE,
    TEENSY_HARDWARE_TEST,
    create_controller_backend,
)
import updater
from teensy_carriage import TeensyCarriagePanel


class _UpdateChecker(QThread):
    """Background check for a newer GitHub release; won't freeze startup."""
    update_found = pyqtSignal(dict)

    def run(self):
        try:
            info = updater.check_for_update()
        except Exception:
            info = None
        if info:
            self.update_found.emit(info)


class _UpdateDownloader(QThread):
    """Downloads the release EXE off the UI thread, reporting progress."""
    progress = pyqtSignal(int, int)       # downloaded, total bytes
    finished_path = pyqtSignal(object)    # local Path, or None on failure

    def __init__(self, info, parent=None):
        super().__init__(parent)
        self._info = info

    def run(self):
        try:
            path = updater.download_update(
                self._info, progress_cb=lambda d, t: self.progress.emit(d, t)
            )
        except Exception:
            path = None
        self.finished_path.emit(path)

def get_app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def get_icon_path():
    icon_name = "chopsaw_hmi.ico"
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        bundled_icon = os.path.join(sys._MEIPASS, icon_name)
        if os.path.exists(bundled_icon):
            return bundled_icon
    return os.path.join(get_app_dir(), icon_name)

# =============== MAIN WINDOW =====================
class MinimalHMI(QMainWindow):
    def __init__(self):
        super().__init__()
        icon_path = get_icon_path()
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.setWindowTitle(f"Chop Saw HMI — Profiles & Touch UI  (v{APP_VERSION})")
        self.resize(1280, 900)
        self._pending_update = None      # update info dict awaiting install
        self._downloaded_exe = None      # local Path of a downloaded installer
        self._update_dialog = None

        # Serial
        self.ser = None
        self.listener_thread = None
        self.listener_stop_event = threading.Event()
        self.signal_bridge = SignalBridge()

        # Signals
        self.signal_bridge.message_received.connect(self.update_message_log)
        self.signal_bridge.position_updated.connect(self.update_position_label_from_device)
        self.signal_bridge.homed_status_updated.connect(self.update_homed_status)
        self.signal_bridge.motor_state_updated.connect(self.update_motor_state)
        self.signal_bridge.sensor_state_updated.connect(self.update_sensor_status)
        self.signal_bridge.board_sensor_state_updated.connect(self.update_board_sensor_status)
        self.signal_bridge.current_updated.connect(self.update_current_draw)
        self.signal_bridge.overcurrent_updated.connect(self.update_overcurrent_status)
        self.signal_bridge.calibration_updated.connect(self.update_calibration_factors)
        self.signal_bridge.home_position_updated.connect(self.update_home_position)
        self.signal_bridge.current_voltage_updated.connect(self.update_current_voltage)
        self.signal_bridge.disconnected.connect(self.handle_serial_disconnect)
        self.signal_bridge.saw_sensor_state_updated.connect(self.update_saw_position_sensor_status)

        # State
        self.stepper_steps_per_inch = 127.12
        self.encoder_ticks_per_inch = self.stepper_steps_per_inch * 20.0
        self.cut_list = []
        self.auto_cycle_state = "IDLE"
        self.cycle_generation = 0  # invalidates delayed clamp/saw callbacks
        self.next_cut_number = 1
        # Last position reported by the device. All cycle/clamp logic reads this,
        # never the UI labels (which can show interpolated predictions).
        self.current_position = 0.0

        self.home_position = 160.5  # matches firmware HOME_POSITION_INCHES (V2.5)
        self.standard_board_length = 144.5
        # (radio label, usable board length, carriage load position).
        # load_pos None = use the live home position. Load positions are
        # usable length + 15" of lead-in.
        self.board_load_options = [
            ("Standard Load (Home position)", self.standard_board_length, None),
            ("10' Load", 120.0, 135.0),
            ("8' Load", 96.0, 111.0),
            ("6' Load", 72.0, 87.0),
            ("4' Load", 48.0, 63.0),
        ]

        self.active_profile_name = "NORMAL"
        self._legacy_cut_completion_ready = False  # simulator harness only; no operator button
        self.clamp_engaged = False
        self.clamp_left_engaged = False
        self.clamp_right_engaged = False
        self.clamp_fence_engaged = False
        self.clamps_engaged_cutting = False   # True while saw is down, awaiting sensor return
        self.actuator_direction = "off"
        # Auto clamp/saw sequencing. OFF = manual mode: the HMI sends no cylinder
        # (C1-3 / D1-3) or saw (V1) commands, so it stays compatible with firmware
        # that has no cylinder support (e.g. Closed-Loop AUTO V2.5, where C1 would
        # collide with the calibration command). Operator cuts and presses CUT
        # COMPLETE, exactly like the 03.07 build.
        self.auto_clamp_enabled = False
        # Line-view animation state: mirrors the physical board through the cycle
        self.sim_board_remaining = None   # inches of board left (None = no board on the line)
        self.sim_board_trimmed = False    # truing cut done
        self.sim_edge_pos = 0.0           # leading edge, inches from blade (negative = past it)
        self.sim_active_piece = None      # piece the current saw stroke is cutting
        self.sim_next_piece_index = 0     # first cut_list index still on the board
        self._last_saw_sensor = None      # last SSEN value, for rising-edge detection
        self.current_cut_index = 0
        self.perform_early_return = False
        self.pending_early_return = False
        self.is_early_returning = False
        self.board_sensor_tripped = False
        self.board_sensor_distance_inches = 10.8
        self.current_draw_amps = 0.0
        self.current_limit_amps = 2.5
        self.current_trip_delay_ms = 150
        self.current_monitoring_enabled = False
        self.overcurrent_tripped = False
        self.current_sensor_voltage = 0.0
        self.current_motor_state = "IDLE"
        self.current_log_path = os.path.join(get_app_dir(), "motor_current_log.csv")
        self.last_current_log_time = 0.0
        self.settings = QSettings("ChopSawHMI", "ChopSawHMI")
        self.selected_serial_port = self.settings.value("serial_port", SERIAL_PORT)
        self.selected_controller_mode = self.settings.value(
            "controller_mode", TEENSY_CARRIAGE
        )
        self.controller = create_controller_backend(self.selected_controller_mode)

        # Prediction
        self.pred_timer = QTimer(self); self.pred_timer.setInterval(30); self.pred_timer.timeout.connect(self.tick_predict)
        self.pred_active = False; self.pred_start_time = 0.0; self.pred_start_pos = 0.0; self.pred_target_pos = 0.0; self.pred_vmax_in = 0.0; self.pred_acc_in = 0.0; self.pred_dir = 1.0

        self._health_session = None
        self._health_started = time.monotonic()
        self._sim_health_fields = {}
        self._sim_health_received = self._sim_activity_received = None
        self._health_activity = TelemetryActivity()
        self.dry_run = NativeDryRun(self)
        self.init_ui()
        self.apply_theme()
        self._load_settings()
        self.update_current_monitor_ui()
        self.health_timer = QTimer(self)
        self.health_timer.setInterval(50)
        self.health_timer.timeout.connect(self.refresh_live_health)
        self.health_timer.start()
        self.refresh_live_health()

        # Background update check (silent; only surfaces a banner if newer)
        self._update_checker = _UpdateChecker(self)
        self._update_checker.update_found.connect(self._on_update_found)
        self._update_checker.start()

    # ---------- Theme ----------
    def apply_theme(self):
        self.setStyleSheet("""
            QMainWindow { background-color: #0f172a; }
            QLabel { color: #e2e8f0; font-size: 15px; }
            QTextBrowser, QTextEdit { background:#0b1222; color:#e2e8f0; border:1px solid #334155; border-radius:12px; font-family: Consolas, monospace; }
            QGroupBox {
                color: #e2e8f0; font-weight:bold; border: 1px solid #334155;
                border-radius: 12px; margin-top: 10px; padding: 8px;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 6px; }
            QDoubleSpinBox, QLineEdit, QTabWidget::pane {
                background: #0b1222; color: #e2e8f0; border: 1px solid #334155;
                border-radius: 10px; padding: 6px;
            }
            QTabBar::tab { background:#0b1222; color:#e2e8f0; padding:10px; border:1px solid #334155; border-bottom:none; min-width: 120px; }
            QTabBar::tab:selected { background:#111827; border-bottom:2px solid #2563eb; }
            QTabWidget::pane { border:1px solid #334155; top:-1px; border-radius: 12px; }

            QPushButton { /* compact default */
                background: #1e293b; color: #e2e8f0; border: 1px solid #334155;
                padding: 8px 10px; border-radius: 10px; font-weight: 600;
                min-height: 28px; min-width: 80px;
            }
            QPushButton:hover { background: #243142; }

            QPushButton[role="touch"] { /* only keypad + cycle control */
            min-height: 80px;         /* Increased from 64px */
            min-width: 120px;         /* Increased from 110px */
            font-size: 32px;          /* --- THIS IS THE KEY CHANGE --- */
            font-weight: 800;
            padding: 12px 14px;
}
            QPushButton[class="primary"] { background: #2563eb; border: none; }
            QPushButton[class="primary"]:hover { background: #1d4ed8; }
            QPushButton[class="accent"] { background: #10b981; border: none; }
            QPushButton[class="accent"]:hover { background: #059669; }
            QCheckBox { color: #e2e8f0; font-size: 15px; }
            /* MODIFIED: Style for the new checkbox */
            QCheckBox { padding: 8px 0; }
                           
            QPushButton[role="small"] {
            background: #1e293b; color: #e2e8f0; border: 1px solid #334155;
            padding: 6px 10px; border-radius: 10px; font-weight: 600;
            min-height: 32px; min-width: 0px;  /* allow shrink */
            font-size: 14px;
}
            QPushButton[role="small"]:hover { background: #243142; }

        """)

            


    def pill(self, text, bg):
        lbl = QLabel(text)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setWordWrap(False)
        lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)
        lbl.setMinimumHeight(34)
        lbl.setMaximumHeight(44)
        lbl.setStyleSheet(
            f"background-color:{bg}; color:white; font-weight:bold; border-radius:10px; padding:4px 8px;"
        )
        return lbl

    def set_pill(self, widget, text, bg, fg="white"):
        """Set the text and background of any status pill label."""
        widget.setText(text)
        widget.setStyleSheet(
            f"background-color:{bg}; color:{fg}; font-weight:bold; border-radius:10px; padding:4px 8px;"
        )

    # ---------- UI ----------
    def init_ui(self):
        central = QWidget(); self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # Top bar
        top = QHBoxLayout()
        top.addWidget(QLabel("Controller:"))
        self.controller_combo = QComboBox()
        self.controller_combo.setMinimumWidth(190)
        self.controller_combo.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        for mode in CONTROLLER_MODES:
            self.controller_combo.addItem(mode.label, mode.key)
        controller_index = self.controller_combo.findData(self.selected_controller_mode)
        if controller_index < 0:
            controller_index = self.controller_combo.findData(TEENSY_HARDWARE_TEST)
        if controller_index >= 0:
            self.controller_combo.setCurrentIndex(controller_index)
            self.selected_controller_mode = (
                self.controller_combo.currentData() or TEENSY_HARDWARE_TEST
            )
            self.controller = create_controller_backend(self.selected_controller_mode)
        self.controller_combo.currentIndexChanged.connect(self.on_controller_mode_changed)
        top.addWidget(self.controller_combo)
        top.addWidget(QLabel("COM Port:"))
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(210)
        self.port_combo.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.port_combo.currentIndexChanged.connect(self.on_serial_port_changed)
        top.addWidget(self.port_combo)
        self.refresh_ports_button = QPushButton("Refresh Ports")
        self.refresh_ports_button.clicked.connect(self.refresh_serial_ports)
        top.addWidget(self.refresh_ports_button)
        self.connect_button = QPushButton("Connect"); self.connect_button.setProperty("class","accent"); self.connect_button.clicked.connect(self.toggle_connection)
        self.status_label = self.pill("Disconnected", "#ef4444")
        self.status_label.setMinimumWidth(120)
        top.addWidget(self.connect_button)
        top.addWidget(self.status_label)
        top.addStretch()
        root.addLayout(top)
        self.refresh_serial_ports()

        # Update banner (hidden until a newer release is detected)
        self.update_banner = QWidget()
        self.update_banner.setStyleSheet(
            "background-color:#1e3a8a; border:1px solid #2563eb; border-radius:10px;"
        )
        banner_row = QHBoxLayout(self.update_banner)
        banner_row.setContentsMargins(12, 6, 12, 6)
        self.update_banner_label = QLabel("Update available")
        self.update_banner_label.setStyleSheet("color:#e2e8f0; font-weight:bold; background:transparent; border:none;")
        banner_row.addWidget(self.update_banner_label, 1)
        self.update_install_btn = QPushButton("Install && Restart")
        self.update_install_btn.setStyleSheet("background-color:#22c55e; color:white; font-weight:700;")
        self.update_install_btn.clicked.connect(self._install_update)
        banner_row.addWidget(self.update_install_btn)
        self.update_later_btn = QPushButton("Later")
        self.update_later_btn.clicked.connect(lambda: self.update_banner.setVisible(False))
        banner_row.addWidget(self.update_later_btn)
        self.update_banner.setVisible(False)
        root.addWidget(self.update_banner)

        # Tabs
        self.tabs = QTabWidget(); root.addWidget(self.tabs)
        self.legacy_tab = self.create_legacy_tab()
        self.auto_tab = self.create_auto_tab()
        self.speed_tab = self.create_speed_tab()
        self.full_auto_tab = self.create_full_auto_tab()
        self.preset_tab = self.create_preset_tab()

        self.carriage_tab = TeensyCarriagePanel(self.send_command, lambda line: self.log.append(line), self)
        self.carriage_tab.profile_changed.connect(self.update_teensy_profile)
        self.carriage_tab.homed_changed.connect(self.update_homed_status)
        self.carriage_tab.machine_position_changed.connect(self.update_position_label_from_device)
        self._teensy_settings_dirty = set()
        self._teensy_settings_snapshot = None
        self._teensy_settings_active = None
        self.carriage_tab.state_changed.connect(self.refresh_teensy_tabs)
        for profile, widgets in self.profile_setting_widgets().items():
            for widget in widgets:
                widget.valueChanged.connect(lambda _value, p=profile: self.mark_teensy_profile_edit(p))
        self.auto_jog_input.valueChanged.connect(self.refresh_teensy_tabs)
        for radio,_,_ in self.board_size_radios: radio.toggled.connect(self.refresh_teensy_tabs)
        self.tabs.addTab(self.carriage_tab, "CARRIAGE")
        self.tabs.addTab(self.legacy_tab, "MANUAL / SIM")
        self.tabs.addTab(self.auto_tab, "AUTO")
        self.tabs.currentChanged.connect(
            lambda _index: self.cut_length_keypad.hide() if self.tabs.currentWidget() is not self.auto_tab else None
        )
        self.tabs.addTab(self.full_auto_tab, "FULL AUTO")
        self.tabs.addTab(self.speed_tab, "SETTINGS")
        self.tabs.addTab(self.preset_tab, "CUT LISTS")
        self.migration_tab = self.create_migration_tab()
        self.tabs.addTab(self.migration_tab, "MIGRATION")

        # Log (hidden — keep object so log.append() calls don't crash)
        self.log = QTextBrowser()
        self.log.document().setMaximumBlockCount(500)
        self.manual_pneumatics.state_changed.connect(self.refresh_manual_motion_locks)
        self.dry_run.changed.connect(self.manual_pneumatics.refresh)
        self.set_controls_enabled(False)
        self.update_clamp_ui()

    def create_migration_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(QLabel("Migration checklist - software completion and physical acceptance tracked separately"))
        refresh = QPushButton("Refresh checklist")
        self.migration_checklist = QTextBrowser()
        self.migration_checklist.setOpenLinks(False)
        self.migration_checklist.setStyleSheet("QTextBrowser { font-family:'Segoe UI'; font-size:15px; padding:12px; }")
        refresh.clicked.connect(self.refresh_migration_checklist)
        layout.addWidget(refresh)
        layout.addWidget(self.migration_checklist, 1)
        self.refresh_migration_checklist()
        return tab

    def refresh_migration_checklist(self):
        root = getattr(sys, "_MEIPASS", get_app_dir())
        path = os.path.join(root, "TEENSY_APP_MIGRATION_CHECKLIST.md")
        try:
            with open(path, encoding="utf-8") as stream:
                self.migration_checklist.setMarkdown(stream.read())
        except OSError as error:
            self.migration_checklist.setPlainText(f"Checklist unavailable: {error}")

    def create_legacy_tab(self):
        w = QWidget(); content = QHBoxLayout(w)
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setStyleSheet('QScrollArea { background:#0b1222; border:0; }')
        left_body = QWidget(); left_body.setObjectName('manualBody')
        left_body.setStyleSheet('QWidget#manualBody { background:#0b1222; }')
        left = QVBoxLayout(left_body)
        left_scroll.setWidget(left_body)
        dash = QGroupBox("Dashboard"); grid = QGridLayout(dash)
        grid.addWidget(QLabel("Homed Status:"), 0, 0)
        self.homed_label = QLabel("NOT HOMED"); self.homed_label.setStyleSheet("color: orange; font-weight: bold;"); grid.addWidget(self.homed_label, 0, 1)
        grid.addWidget(QLabel("Motor State:"), 1, 0); self.state_label = QLabel("IDLE"); self.state_label.setStyleSheet("color: #22c55e; font-weight: bold;"); grid.addWidget(self.state_label, 1, 1)
        grid.addWidget(QLabel("Homing Sensor:"), 2, 0); self.sensor_label = self.pill("OFF", "#ef4444"); grid.addWidget(self.sensor_label, 2, 1)
        grid.addWidget(QLabel("Board Sensor:"), 3, 0); self.board_sensor_label = self.pill("OFF", "#ef4444"); grid.addWidget(self.board_sensor_label, 3, 1)
        grid.addWidget(QLabel("Current Position (in):"), 4, 0)
        self.position_label = QLabel("0.0000"); self.position_label.setStyleSheet("font-size: 24px; font-weight: bold; color: #60a5fa;"); grid.addWidget(self.position_label, 4, 1)
        dash.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        left.addWidget(dash)

        ctrl = QGroupBox("Controls"); v = QVBoxLayout(ctrl)
        self.manual_teensy_setup = QGroupBox("Teensy preparation - shared with CARRIAGE")
        prep = QVBoxLayout(self.manual_teensy_setup)
        self.manual_teensy_status = QLabel()
        self.manual_teensy_status.setWordWrap(True)
        prep.addWidget(self.manual_teensy_status)
        isolation_note=QLabel("Unloaded test only: saw unplugged, blade trigger locked OFF; driver and carriage clearance checked.")
        isolation_note.setWordWrap(True); prep.addWidget(isolation_note)
        self.manual_isolation = QCheckBox("Unloaded / unplugged and driver checks confirmed")
        self.manual_isolation.toggled.connect(lambda checked: self.carriage_tab.consent.setChecked(checked))
        prep.addWidget(self.manual_isolation)
        row = QHBoxLayout()
        self.manual_configure = QPushButton("Confirm driver setup")
        self.manual_configure.clicked.connect(lambda: self.send_command("XCONFIG 0 1"))
        self.manual_arm = QPushButton("ARM MANUAL CONTROL")
        self.manual_arm.clicked.connect(lambda: self.carriage_tab.toggle_arm())
        row.addWidget(self.manual_configure); row.addWidget(self.manual_arm)
        prep.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("Home search limit (in):"))
        self.manual_home_search = QDoubleSpinBox()
        self.manual_home_search.setRange(0.25,162); self.manual_home_search.setDecimals(2); self.manual_home_search.setValue(2)
        self.manual_home_search.valueChanged.connect(lambda value: self.carriage_tab.home_search.setValue(value))
        row.addWidget(self.manual_home_search)
        prep.addLayout(row)
        home_hint=QLabel("HOME runs while disarmed. Set the maximum search distance before starting.")
        home_hint.setWordWrap(True); prep.addWidget(home_hint)
        v.addWidget(self.manual_teensy_setup)
        self.enable_chk = QCheckBox("Motor Power Enabled")
        self.enable_chk.toggled.connect(self.toggle_motor_power)
        v.addWidget(self.enable_chk)
        self.manual_home_button = QPushButton("Home")
        self.manual_home_button.clicked.connect(self.home_motor)
        v.addWidget(self.manual_home_button)
        self.manual_teensy_actions = QWidget()
        actions = QHBoxLayout(self.manual_teensy_actions); actions.setContentsMargins(0,0,0,0)
        self.manual_stop = QPushButton("STOP / DISARM")
        self.manual_stop.setStyleSheet("background:#b91c1c; color:white; font-weight:bold")
        self.manual_stop.clicked.connect(lambda: self.carriage_tab.stop())
        self.manual_reset = QPushButton("Acknowledge fault")
        self.manual_reset.clicked.connect(lambda: self.dry_run.acknowledge())
        self.manual_release = QPushButton("Release motor")
        self.manual_release.clicked.connect(lambda: self.carriage_tab.stop("XDISABLE"))
        for button in (self.manual_stop,self.manual_reset,self.manual_release): actions.addWidget(button)
        v.addWidget(self.manual_teensy_actions)

        ctrl.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        left.addWidget(ctrl)
        self.manual_pneumatics = ManualPneumatics(self)
        left.addWidget(self.manual_pneumatics)
        left.addStretch()

        right_column_layout = QVBoxLayout()
        right_column_layout.addWidget(QLabel("Carriage target (in)"))
        self.keypad = KeypadWidget()
        self.keypad.setToolTip("Enter a carriage target in inches. ENTER requests a move using the active controller's checks.")
        self.keypad.value_entered.connect(self.set_length)
        right_column_layout.addWidget(self.keypad)
        right_column_layout.addStretch()

        content.addWidget(left_scroll, 2)
        content.addLayout(right_column_layout, 1)
        return w

    def create_auto_tab(self):
        w = QWidget(); root = QVBoxLayout(w)
        top_row = QHBoxLayout()
        
        # --- MODIFIED: Reduced spacing to reduce padding between frames ---
        top_row.setSpacing(5) 
        top_row.setContentsMargins(5, 5, 5, 5)

        # Left: Live Status
        left_col = QVBoxLayout()
        live = QGroupBox("Live Status"); g1 = QGridLayout(live)
        self.auto_live_status = live
        live.setObjectName("autoLiveStatus")
        g1.setContentsMargins(12, 10, 12, 10)
        g1.setHorizontalSpacing(12)
        g1.setVerticalSpacing(4)
        g1.setColumnStretch(0, 0)
        g1.setColumnStretch(1, 1)
        g1.addWidget(QLabel("Current Position (in):"), 0, 0)
        self.auto_position_label = QLabel("0.0000")
        self.auto_position_label.setStyleSheet("font-size: 24px; font-weight: bold; color: #60a5fa;")
        self.auto_position_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        g1.addWidget(self.auto_position_label, 0, 1)
        g1.addWidget(QLabel("Homing Sensor:"), 1, 0)
        self.auto_homing_sensor_label = self.pill("OFF", "#ef4444")
        g1.addWidget(self.auto_homing_sensor_label, 1, 1)
        g1.addWidget(QLabel("Board Sensor:"), 2, 0)
        self.auto_board_sensor_label = self.pill("OFF", "#ef4444")
        g1.addWidget(self.auto_board_sensor_label, 2, 1)
        g1.addWidget(QLabel("Clamp Status:"), 3, 0)
        self.auto_clamp_status_label = self.pill("UNCLAMPED", "#475569")
        g1.addWidget(self.auto_clamp_status_label, 3, 1)
        self.auto_sensor_pills = {}
        for row,(key,title) in enumerate((("FENCE_DOOR","Guard door:"),("SAW_UP","Saw fully UP:"),
                                          ("SAW_DOWN","Saw fully DOWN:"),("CL57T_ALM","Driver alarm:")),4):
            label=self.pill("UNKNOWN","#475569")
            g1.addWidget(QLabel(title),row,0); g1.addWidget(label,row,1)
            self.auto_sensor_pills[key]=label
        health_row = QHBoxLayout()
        health_row.setSpacing(8)
        self.live_health_dot = QLabel()
        self.live_health_dot.setFixedSize(10, 10)
        self.live_health_dot.setAccessibleName("Telemetry activity")
        self.live_health_dot.setToolTip("Telemetry activity: five-second breathing cycle while data stays fresh.")
        health_row.addWidget(self.live_health_dot)
        self.live_health_label = QLabel("Disconnected")
        self.live_health_label.setWordWrap(True)
        health_row.addWidget(self.live_health_label, 1)
        g1.addLayout(health_row, 8, 0, 1, 2)
        live.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        left_col.addWidget(live)

        
        # ... setup code ...

        current_group = QGroupBox("Motor Current")
        self.current_group = current_group
        main_layout = QVBoxLayout(current_group)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)

        self.current_card_collapsed_height = 250
        self.current_card_expanded_height = 320
        self.current_graph_collapsed_min_height = 130
        self.current_graph_expanded_min_height = 90
        current_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        current_group.setMinimumHeight(self.current_card_collapsed_height)
        current_group.setMaximumHeight(self.current_card_collapsed_height)

        # --- 1. TOP HEADER (Value & Status Pill) ---
        header_layout = QHBoxLayout()

        self.current_value_label = QLabel("0.00 A")
        self.current_value_label.setStyleSheet("font-size: 30px; font-weight: 800; color: #22c55e; letter-spacing: 0.5px;")

        self.current_status_label = self.pill("Current OK", "#22c55e")
        # Prevent the pill from stretching horizontally
        self.current_status_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.current_status_label.setMinimumWidth(96)
        self.current_status_label.setMaximumWidth(170)
        self.current_status_label.setFixedHeight(38)

        self.reset_overcurrent_btn = QPushButton("Reset Trip")
        self.reset_overcurrent_btn.setFixedHeight(34)
        self.reset_overcurrent_btn.setStyleSheet(
            "QPushButton { background:#7f1d1d; color:white; font-weight:700; border:1px solid #b91c1c; border-radius:10px; padding:0 12px; }"
            "QPushButton:hover { background:#991b1b; }"
            "QPushButton:pressed { background:#450a0a; }"
        )
        self.reset_overcurrent_btn.clicked.connect(self.reset_overcurrent_trip)

        self.current_settings_toggle = QToolButton()
        self.current_settings_toggle.setText("⚙")
        self.current_settings_toggle.setCheckable(True)
        self.current_settings_toggle.setChecked(False)
        self.current_settings_toggle.setToolTip("Show current protection settings")
        self.current_settings_toggle.setStyleSheet(
            "font-size: 17px; font-weight: 700; min-width: 34px; max-width: 34px; min-height: 34px; max-height: 34px; "
            "padding: 0; border-radius: 17px; background:#1e293b; color:#e2e8f0; border:1px solid #334155;"
        )
        self.current_settings_toggle.toggled.connect(self.toggle_current_settings)

        header_layout.addWidget(self.current_value_label)
        header_layout.addStretch() # This pushes the value left and the controls right
        header_layout.addWidget(self.current_status_label)
        header_layout.addSpacing(8)
        header_layout.addWidget(self.reset_overcurrent_btn)
        header_layout.addSpacing(8)
        header_layout.addWidget(self.current_settings_toggle)

        main_layout.addLayout(header_layout)

        # --- 2. MIDDLE GRAPH (Prioritized) ---
        self.current_graph = CurrentGraphWidget(max_seconds=5.0, sample_rate_hz=4)
        self.current_graph.set_limit(self.current_limit_amps)
        self.current_graph.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.current_graph.setMinimumHeight(self.current_graph_collapsed_min_height)

        # stretch=1 forces the layout to give the graph all remaining vertical space
        main_layout.addWidget(self.current_graph, stretch=1) 

        # --- 3. BOTTOM SETTINGS (Compacted horizontally) ---
        self.current_settings_panel = QWidget()
        settings_layout = QHBoxLayout(self.current_settings_panel)
        settings_layout.setContentsMargins(0, 10, 0, 0) # Add a little top margin to separate from the graph

        self.current_monitoring_checkbox = QCheckBox("Enable Monitoring")
        self.current_monitoring_checkbox.setChecked(self.current_monitoring_enabled)

        # Compact Limit Input
        self.current_limit_input = QDoubleSpinBox()
        self.current_limit_input.setRange(0.1, 30.0)
        self.current_limit_input.setDecimals(2)
        self.current_limit_input.setValue(self.current_limit_amps)
        self.current_limit_input.setFixedWidth(65)
        self.current_limit_input.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)

        # Compact Delay Input
        self.current_delay_input = QDoubleSpinBox()
        self.current_delay_input.setRange(10, 5000)
        self.current_delay_input.setDecimals(0)
        self.current_delay_input.setValue(self.current_trip_delay_ms)
        self.current_delay_input.setFixedWidth(65)
        self.current_delay_input.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)

        # Compact Apply Button
        self.apply_current_protection_btn = QPushButton("Apply")
        self.apply_current_protection_btn.setFixedWidth(84) # Keep it small
        self.apply_current_protection_btn.clicked.connect(self.apply_current_protection_settings)

        # Build the single row
        settings_layout.addWidget(self.current_monitoring_checkbox)
        settings_layout.addSpacing(15)
        settings_layout.addWidget(QLabel("Limit (A):"))
        settings_layout.addWidget(self.current_limit_input)
        settings_layout.addSpacing(15) # Visual breather between the two settings
        settings_layout.addWidget(QLabel("Delay (ms):"))
        settings_layout.addWidget(self.current_delay_input)
        settings_layout.addStretch() # Pushes the inputs left and the Apply button right
        settings_layout.addWidget(self.apply_current_protection_btn)

        self.current_settings_panel.setVisible(False)
        main_layout.addWidget(self.current_settings_panel)

        left_col.addWidget(current_group)

        self.auto_teensy_setup = QGroupBox("Prepare carriage")
        prep=QVBoxLayout(self.auto_teensy_setup)
        self.auto_isolation=QCheckBox("Unloaded / unplugged and driver checks confirmed")
        self.auto_isolation.toggled.connect(lambda checked: self.carriage_tab.consent.setChecked(checked))
        prep.addWidget(self.auto_isolation)
        hint=QLabel("No stock; saw unplugged; blade trigger locked OFF.")
        hint.setWordWrap(True); prep.addWidget(hint)
        row=QHBoxLayout()
        self.auto_configure=QPushButton("Setup")
        self.auto_configure.setToolTip("Confirm the verified driver setup")
        self.auto_configure.clicked.connect(lambda: self.send_command("XCONFIG 0 1"))
        self.auto_home=QPushButton("HOME")
        self.auto_home.clicked.connect(self.home_motor)
        row.addWidget(self.auto_configure); row.addWidget(self.auto_home)
        self.auto_arm=QPushButton("ARM CARRIAGE")
        self.auto_arm.clicked.connect(lambda: self.carriage_tab.toggle_arm())
        row.addWidget(self.auto_arm); prep.addLayout(row)
        left_col.addWidget(self.auto_teensy_setup)

        # Jog controls (AUTO)
        jog = QGroupBox("Jog"); jg = QVBoxLayout(jog)
        # Make jog compact and add spacing so controls aren't cramped
        jog.setMaximumHeight(200)
        jg.setContentsMargins(6, 6, 6, 6)
        jg.setSpacing(8)
        # Row with Left button, value input, Right button
        jrow = QHBoxLayout(); jrow.setSpacing(8)
        self.auto_jog_left_btn = QPushButton("◀")
        self.auto_jog_left_btn.setProperty("role", "small")
        self.auto_jog_left_btn.setMinimumWidth(40)
        self.auto_jog_left_btn.clicked.connect(lambda: self.auto_jog(abs(self.auto_jog_input.value())))
        jrow.addWidget(self.auto_jog_left_btn)

        self.auto_jog_input = QDoubleSpinBox(); self.auto_jog_input.setRange(0.001, 100.0); self.auto_jog_input.setDecimals(4); self.auto_jog_input.setValue(1.0000)
        self.auto_jog_input.setMinimumWidth(120)
        jrow.addWidget(self.auto_jog_input, 1)

        self.auto_jog_right_btn = QPushButton("▶")
        self.auto_jog_right_btn.setProperty("role", "small")
        self.auto_jog_right_btn.setMinimumWidth(48)
        self.auto_jog_right_btn.clicked.connect(lambda: self.auto_jog(-abs(self.auto_jog_input.value())))
        jrow.addWidget(self.auto_jog_right_btn)
        jg.addLayout(jrow)

        # Quick jog buttons (smallest to largest): 0.1", 0.25", 1", 2"
        qrow1 = QHBoxLayout(); qrow1.setSpacing(8)
        self.qjog_left_01 = QPushButton("0.1\" Left"); self.qjog_left_01.setProperty("role", "small"); self.qjog_left_01.setMinimumWidth(64)
        self.qjog_left_01.clicked.connect(lambda: self.auto_jog(0.1))
        qrow1.addWidget(self.qjog_left_01)

        self.qjog_right_01 = QPushButton("0.1\" Right"); self.qjog_right_01.setProperty("role", "small"); self.qjog_right_01.setMinimumWidth(64)
        self.qjog_right_01.clicked.connect(lambda: self.auto_jog(-0.1))
        qrow1.addWidget(self.qjog_right_01)

        self.qjog_left_025 = QPushButton("0.25\" Left"); self.qjog_left_025.setProperty("role", "small"); self.qjog_left_025.setMinimumWidth(64)
        self.qjog_left_025.clicked.connect(lambda: self.auto_jog(0.25))
        qrow1.addWidget(self.qjog_left_025)

        self.qjog_right_025 = QPushButton("0.25\" Right"); self.qjog_right_025.setProperty("role", "small"); self.qjog_right_025.setMinimumWidth(64)
        self.qjog_right_025.clicked.connect(lambda: self.auto_jog(-0.25))
        qrow1.addWidget(self.qjog_right_025)
        jg.addLayout(qrow1)

        qrow2 = QHBoxLayout(); qrow2.setSpacing(8)
        self.qjog_left_1 = QPushButton("1\" Left"); self.qjog_left_1.setProperty("role", "small"); self.qjog_left_1.setMinimumWidth(64)
        self.qjog_left_1.clicked.connect(lambda: self.auto_jog(1.0))
        qrow2.addWidget(self.qjog_left_1)

        self.qjog_right_1 = QPushButton("1\" Right"); self.qjog_right_1.setProperty("role", "small"); self.qjog_right_1.setMinimumWidth(64)
        self.qjog_right_1.clicked.connect(lambda: self.auto_jog(-1.0))
        qrow2.addWidget(self.qjog_right_1)

        self.qjog_left_2 = QPushButton("2\" Left"); self.qjog_left_2.setProperty("role", "small"); self.qjog_left_2.setMinimumWidth(64)
        self.qjog_left_2.clicked.connect(lambda: self.auto_jog(2.0))
        qrow2.addWidget(self.qjog_left_2)

        self.qjog_right_2 = QPushButton("2\" Right"); self.qjog_right_2.setProperty("role", "small"); self.qjog_right_2.setMinimumWidth(64)
        self.qjog_right_2.clicked.connect(lambda: self.auto_jog(-2.0))
        qrow2.addWidget(self.qjog_right_2)
        jg.addLayout(qrow2)

        left_col.addWidget(jog)
        
        # --- MODIFIED: Removed setMaximumWidth(460) to allow widening ---
        left_wrap = QWidget(); left_wrap.setLayout(left_col) 
        top_row.addWidget(left_wrap)

        # Center: touch-friendly cut entry on top + Cut List below
        center_col = QVBoxLayout()
        setup = QGroupBox("Cut Entry"); g2 = QGridLayout(setup)
        g2.addWidget(QLabel("Cut Length (in):"), 0, 0)
        self.cut_length_input = QDoubleSpinBox(); self.cut_length_input.setRange(0.1, 2000); self.cut_length_input.setDecimals(4); self.cut_length_input.setValue(18.0)
        self.cut_length_input.setMinimumHeight(64)
        self.cut_length_input.setStyleSheet("font-size: 28px; padding: 10px 12px;")
        self.cut_length_input.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        self.cut_length_keypad_checkbox = QCheckBox("Keypad")
        self.cut_length_keypad_checkbox.setMinimumHeight(44)
        self.cut_length_keypad_checkbox.setToolTip("Show the on-screen keypad when Cut Length is tapped. Physical keyboard entry stays available.")
        g2.addWidget(self.cut_length_keypad_checkbox, 0, 1, Qt.AlignmentFlag.AlignRight)
        g2.addWidget(self.cut_length_input, 1, 0, 1, 2)
        self.cut_length_keypad = CutLengthKeypad(self.cut_length_input, left_wrap)
        self.cut_length_keypad_checkbox.toggled.connect(self.cut_length_keypad.set_active)
        self.add_cut_button = QPushButton("Add Cut to List"); self.add_cut_button.clicked.connect(self.add_cut_to_list); g2.addWidget(self.add_cut_button, 2, 0, 1, 2)
        self.add_cut_button.setMinimumHeight(48)
        self.add_cut_button.setStyleSheet("font-size: 18px;")
        self.add_cut_button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        center_col.addWidget(setup)

        cut_list_group = QGroupBox("Cut List"); vcl = QVBoxLayout(cut_list_group)

        # Board utilization fill bar
        self.board_fill_label = QLabel("No cuts loaded")
        self.board_fill_label.setStyleSheet("font-size: 13px; color: #94a3b8;")
        vcl.addWidget(self.board_fill_label)

        self.board_fill_bar = QProgressBar()
        self.board_fill_bar.setRange(0, 1000)
        self.board_fill_bar.setValue(0)
        self.board_fill_bar.setTextVisible(False)
        self.board_fill_bar.setFixedHeight(16)
        self.board_fill_bar.setStyleSheet("""
            QProgressBar { background-color: #1e293b; border-radius: 8px; border: 1px solid #334155; }
            QProgressBar::chunk { background-color: #38bdf8; border-radius: 8px; }
        """)
        vcl.addWidget(self.board_fill_bar)

        self.cut_list_display = QTextEdit()
        # Increase cut list font size for small screen readability
        self.cut_list_display.setStyleSheet("font-size: 22px;")
        
        # --- MODIFIED: Flexible size policy + removed fixed height ---
        self.cut_list_display.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        # Optional safe minimum
        self.cut_list_display.setMinimumHeight(150)
        
        vcl.addWidget(self.cut_list_display)

        list_button_layout = QHBoxLayout()
        self.load_list_button = QPushButton("Load from File")
        self.load_list_button.clicked.connect(self.load_list_from_file)
        self.update_from_box_button = QPushButton("Update from Box")
        self.update_from_box_button.clicked.connect(self.update_list_from_box)
        self.clear_list_button = QPushButton("Clear List")
        self.clear_list_button.clicked.connect(self.clear_cut_list)
        list_button_layout.addWidget(self.load_list_button)
        list_button_layout.addWidget(self.update_from_box_button)
        list_button_layout.addWidget(self.clear_list_button)
        vcl.addLayout(list_button_layout)

        # --- MODIFIED: Added stretch factor 1 to Cut List group ---
        center_col.addWidget(cut_list_group, 1)
        
        # --- MODIFIED: Removed setMaximumWidth(520) to allow widening ---
        center_wrap = QWidget(); center_wrap.setLayout(center_col)
        top_row.addWidget(center_wrap)


        # Right: Cycle Control
        right_col = QVBoxLayout()
        cycle_group = QGroupBox("Cycle Control"); cyc = QVBoxLayout(cycle_group)
        
        top_button_layout = QHBoxLayout()
        
        self.load_button = QPushButton("LOAD POSITION")
        self.load_button.setProperty("role", "touch") 
        self.load_button.clicked.connect(self.load_position)
        self.load_button.setStyleSheet("""
            font-size: 12px;
            min-height: 20px;
        """)
        top_button_layout.addWidget(self.load_button)

        self.cancel_cycle_button = QPushButton("CANCEL CYCLE")
        self.cancel_cycle_button.setProperty("role", "touch")
        self.cancel_cycle_button.clicked.connect(self.cancel_auto_cycle)
        self.cancel_cycle_button.setStyleSheet("""
            background-color: #ef4444;
            font-size: 12px;
            min-height: 20px;
        """)
        top_button_layout.addWidget(self.cancel_cycle_button)
        
        cyc.addLayout(top_button_layout) 
        
                # NEW: Resume after a hardware reset / rehome
        self.resume_on_reset_button = QPushButton("RESUME ON RESET")
        self.resume_on_reset_button.setProperty("role", "touch")
        self.resume_on_reset_button.clicked.connect(self.resume_after_reset)
        self.resume_on_reset_button.setStyleSheet("""
            background-color: #f59e0b;  /* amber */
            font-size: 12px;
            min-height: 20px;
        """)
        top_button_layout.addWidget(self.resume_on_reset_button)

        # After constructing each of the three buttons:
        self.load_button.setProperty("role", "small")
        self.load_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.cancel_cycle_button.setProperty("role", "small")
        self.cancel_cycle_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.resume_on_reset_button.setProperty("role", "small")
        self.resume_on_reset_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        # Give the row a bit of breathing room
        top_button_layout.setSpacing(8)


        # --- MODIFIED SECTION: Replaced QGroupBox with a simple QVBoxLayout ---
        # Instead of a QGroupBox, just use a vertical layout for the radio buttons
        radio_layout = QVBoxLayout()
        radio_layout.setContentsMargins(0, 5, 0, 5) # Reduce internal padding
        radio_layout.setSpacing(2) # Reduce spacing between radio buttons

        # Build one radio per entry in board_load_options; standard (index 0) is default
        radio_style = "font-size: 15px; padding: 2px 0; color: #e2e8f0;"
        self.board_size_radios = []
        for i, (label, board_length, load_pos) in enumerate(self.board_load_options):
            text = label if load_pos is None else f"{label} ({load_pos:.2f}\")"
            radio = QRadioButton(text)
            radio.setStyleSheet(radio_style)
            radio.setChecked(i == 0)
            radio.toggled.connect(self.update_cut_list_display)
            radio_layout.addWidget(radio)
            self.board_size_radios.append((radio, board_length, load_pos))

        cyc.addLayout(radio_layout) # Add the radio button layout to the main cycle_group layout
        # --- END MODIFIED SECTION ---

        # Start remains unavailable for live Teensy until automatic-cycle acceptance.
        self.start_cycle_button = QPushButton("START CYCLE")
        self.start_cycle_button.setProperty("role", "touch")
        self.start_cycle_button.clicked.connect(self.start_auto_cycle)
        self.start_cycle_button.setStyleSheet("""
            QPushButton { background-color: #22c55e; color: white; font-weight: bold; font-size: 24px; min-height: 25px; max-height: 55px; }
            QPushButton:hover { background-color: #16a34a; }
            QPushButton:disabled { background-color: #166534; color: #4ade80; }
        """)
        cyc.addWidget(self.start_cycle_button)

            
            
        right_col.addWidget(cycle_group)

        # ... (the rest of your create_auto_tab method)





        status_group = QGroupBox("Status")
        sv = QVBoxLayout(status_group)

        # --- NEW: Set the min/max height for the status box ---
        status_group.setMinimumHeight(90)
        status_group.setMaximumHeight(120)

        self.auto_status_label = QLabel("STATUS: Waiting to Start")
        self.auto_status_label.setWordWrap(True)
        self.auto_status_label.setStyleSheet("font-weight:bold; font-size:14px; color:#e2e8f0;")


        sv.addWidget(self.auto_status_label)
        right_col.addWidget(status_group)
        self.auto_dry_group = QGroupBox('Unloaded cut-list test')
        dry_layout = QVBoxLayout(self.auto_dry_group)
        self.auto_dry_consent = QCheckBox('Unloaded / unplugged; air checks confirmed')
        self.auto_dry_consent.toggled.connect(self.dry_run.consent.setChecked)
        self.dry_run.consent.toggled.connect(self.auto_dry_consent.setChecked)
        dry_layout.addWidget(self.auto_dry_consent)
        dry_hint=QLabel('Blade trigger locked OFF. Home first. Trip and hold the board detector until truing starts. Cut-list progress is preserved.')
        dry_hint.setWordWrap(True); dry_layout.addWidget(dry_hint)
        self.auto_dry_configure=QPushButton('Load dry-run timings')
        self.auto_dry_configure.clicked.connect(self.dry_run.configure)
        self.auto_dry_run=QPushButton('Run unloaded cut-list test')
        self.auto_dry_run.clicked.connect(self.dry_run.start_sequence)
        self.auto_dry_stop=QPushButton('Stop dry run / release clamp')
        self.auto_dry_stop.clicked.connect(lambda: self.dry_run.stop())
        self.auto_dry_status=QLabel('Requires matching 0.18.0 firmware.'); self.auto_dry_status.setWordWrap(True)
        for widget in (self.auto_dry_configure,self.auto_dry_run,self.auto_dry_stop,self.auto_dry_status): dry_layout.addWidget(widget)
        right_col.insertWidget(0, self.auto_dry_group)


        # --- MODIFIED: Removed setMaximumWidth(420) to allow widening ---
        right_wrap = QWidget(); right_wrap.setLayout(right_col)
        right_wrap.setObjectName('autoCycleColumn')
        right_wrap.setStyleSheet('QWidget#autoCycleColumn { background:#0b1222; }')
        right_scroll = QScrollArea(); right_scroll.setWidgetResizable(True)
        right_scroll.setStyleSheet('QScrollArea { background:#0b1222; border:0; }')
        right_scroll.setWidget(right_wrap)
        top_row.addWidget(right_scroll)
        root.addLayout(top_row)

        # Profiles moved to Speed Settings tab
        return w

    def create_speed_tab(self):
        w = QWidget(); outer = QVBoxLayout(w)
        self.settings_scroll = QScrollArea()
        self.settings_scroll.setWidgetResizable(True)
        self.settings_scroll.setStyleSheet('QScrollArea { background:#0f172a; border:0; }')
        body = QWidget(); body.setObjectName('settingsBody')
        body.setStyleSheet('QWidget#settingsBody { background:#0f172a; }')
        root = QVBoxLayout(body)
        self.settings_scroll.setWidget(body); outer.addWidget(self.settings_scroll)
        cutting = QGroupBox("Cutting and Sensors")
        geometry = QFormLayout(cutting)
        self.kerf_input = QDoubleSpinBox()
        self.kerf_input.setRange(0.0, 0.5)
        self.kerf_input.setDecimals(4)
        self.kerf_input.setValue(0.100)
        self.kerf_input.setToolTip("Blade cut width used in cut-list and stock calculations.")
        geometry.addRow("Blade Kerf (in):", self.kerf_input)
        self.board_sensor_location_input = QDoubleSpinBox()
        self.board_sensor_location_input.setRange(0, 2000)
        self.board_sensor_location_input.setDecimals(4)
        self.board_sensor_location_input.setValue(10.80)
        self.board_sensor_location_input.setToolTip("Distance from the saw blade to the board sensor.")
        geometry.addRow("Board Sensor Distance (in):", self.board_sensor_location_input)
        for field in (self.kerf_input, self.board_sensor_location_input):
            field.setMinimumHeight(44)
            field.setMaximumWidth(320)
            field.setStyleSheet("font-size: 18px;")
        root.addWidget(cutting)
        self.cylinder_timing = CylinderTimingPanel(self.settings)
        root.addWidget(self.cylinder_timing)
        self.auto_clamp_checkbox = QCheckBox('Automatic clamp/saw simulation')
        self.auto_clamp_checkbox.setToolTip('Simulator only. Live automatic clamp/saw operation remains unavailable until controller sequencing is commissioned.')
        self.auto_clamp_checkbox.toggled.connect(self._on_auto_clamp_toggled)
        root.addWidget(self.auto_clamp_checkbox)
        profiles = QGroupBox("Motion Profiles - Pulse Rates & Accelerations"); pg = QGridLayout(profiles)

        pg.addWidget(QLabel("NORMAL - board feed"), 0, 0, 1, 2)
        pg.addWidget(QLabel("Pulse rate (pulses/s)"), 1, 0)
        self.norm_speed = QDoubleSpinBox(); self.norm_speed.setRange(1, 20000); self.norm_speed.setDecimals(0); self.norm_speed.setValue(2500); pg.addWidget(self.norm_speed, 1, 1)
        pg.addWidget(QLabel("Acceleration (pulses/s^2)"), 2, 0)
        self.norm_accel = QDoubleSpinBox(); self.norm_accel.setRange(1, 50000); self.norm_accel.setDecimals(0); self.norm_accel.setValue(900); pg.addWidget(self.norm_accel, 2, 1)

        pg.addWidget(QLabel("GENTLE - approach"), 0, 2, 1, 2)
        pg.addWidget(QLabel("Pulse rate (pulses/s)"), 1, 2)
        self.gentle_speed = QDoubleSpinBox(); self.gentle_speed.setRange(1, 20000); self.gentle_speed.setDecimals(0); self.gentle_speed.setValue(600); pg.addWidget(self.gentle_speed, 1, 3)
        pg.addWidget(QLabel("Acceleration (pulses/s^2)"), 2, 2)
        self.gentle_accel = QDoubleSpinBox(); self.gentle_accel.setRange(1, 50000); self.gentle_accel.setDecimals(0); self.gentle_accel.setValue(600); pg.addWidget(self.gentle_accel, 2, 3)

        pg.addWidget(QLabel("FAST - carriage return"), 0, 4, 1, 2)
        pg.addWidget(QLabel("Pulse rate (pulses/s)"), 1, 4)
        self.fast_speed = QDoubleSpinBox(); self.fast_speed.setRange(1, 20000); self.fast_speed.setDecimals(0); self.fast_speed.setValue(3500); pg.addWidget(self.fast_speed, 1, 5)
        pg.addWidget(QLabel("Acceleration (pulses/s^2)"), 2, 4)
        self.fast_accel = QDoubleSpinBox(); self.fast_accel.setRange(1, 50000); self.fast_accel.setDecimals(0); self.fast_accel.setValue(2500); pg.addWidget(self.fast_accel, 2, 5)

        self.settings_profile_combo = QComboBox()
        self.settings_profile_combo.setStyleSheet(
            "QComboBox { background:#0b1222; color:#e2e8f0; border:1px solid #334155; padding:8px; }"
            "QComboBox QAbstractItemView { background:#0b1222; color:#e2e8f0; selection-background-color:#1e40af; }"
        )
        for name in ("NORMAL","GENTLE","FAST"): self.settings_profile_combo.addItem(name,name)
        self.settings_profile_combo.currentIndexChanged.connect(lambda: self.refresh_teensy_tabs())
        pg.addWidget(QLabel("Profile to apply:"),3,0)
        pg.addWidget(self.settings_profile_combo,3,1)
        self.apply_profile_btn = QPushButton("Apply Selected Profile Settings Now"); self.apply_profile_btn.clicked.connect(self.apply_current_profile_params); pg.addWidget(self.apply_profile_btn, 3, 2, 1, 4)
        self.settings_profile_feedback = QLabel()
        self.settings_profile_feedback.setWordWrap(True)
        pg.addWidget(self.settings_profile_feedback,4,0,1,6)
        root.addWidget(profiles)

        # Software updates
        updates_group = QGroupBox("Software")
        ug = QHBoxLayout(updates_group)
        self.version_label = QLabel(f"Version {APP_VERSION}")
        ug.addWidget(self.version_label)
        ug.addStretch()
        self.check_updates_btn = QPushButton("Check for Updates")
        self.check_updates_btn.clicked.connect(self.check_updates_manual)
        ug.addWidget(self.check_updates_btn)
        root.addWidget(updates_group)

        serial_group = QGroupBox("Serial Monitor")
        serial_layout = QVBoxLayout(serial_group)
        serial_hint = QLabel("Live inbound serial messages from the controller.")
        serial_hint.setStyleSheet("color:#94a3b8; font-size:13px;")
        serial_layout.addWidget(serial_hint)
        self.speed_serial_console = QTextBrowser()
        self.speed_serial_console.setMinimumHeight(180)
        self.speed_serial_console.document().setMaximumBlockCount(500)
        self.speed_serial_console.setOpenExternalLinks(False)
        serial_layout.addWidget(self.speed_serial_console)
        root.addWidget(serial_group, stretch=1)
        return w
    
    def create_preset_tab(self):
        storage_path = os.path.join(get_app_dir(), "cutlists.json")
        return CutListManagerTab(
            storage_path=storage_path,
            on_load_lines=self.load_cut_list_lines,
            on_switch_to_auto=lambda: self.tabs.setCurrentWidget(self.auto_tab),
            log_fn=lambda msg: self.log.append(msg),
        )

    def create_full_auto_tab(self):
        w = QWidget()
        root_layout = QVBoxLayout(w)
        root_layout.setSpacing(6)
        root_layout.setContentsMargins(6, 6, 6, 6)

        # ── TOP: Live Status (full width) ─────────────────────────────────────
        live_group = QGroupBox("Live Status")
        live_layout = QHBoxLayout(live_group)
        live_layout.setSpacing(14)

        pos_col = QVBoxLayout()
        pos_col.addWidget(QLabel("Position (in):"))
        self.fa_position_label = QLabel("0.0000")
        self.fa_position_label.setStyleSheet("font-size: 26px; font-weight: bold; color: #60a5fa;")
        pos_col.addWidget(self.fa_position_label)
        live_layout.addLayout(pos_col)

        live_layout.addStretch()

        pills_layout = QHBoxLayout()
        pills_layout.setSpacing(8)

        pills_layout.addWidget(QLabel("Homing:"))
        self.fa_homing_sensor_label = self.pill("OFF", "#ef4444")
        pills_layout.addWidget(self.fa_homing_sensor_label)

        pills_layout.addWidget(QLabel("Board:"))
        self.fa_board_sensor_label = self.pill("OFF", "#ef4444")
        pills_layout.addWidget(self.fa_board_sensor_label)

        pills_layout.addWidget(QLabel("Outfeed:"))
        self.fa_outfeed_sensor_label = self.pill("--", "#475569")
        pills_layout.addWidget(self.fa_outfeed_sensor_label)

        pills_layout.addWidget(QLabel("Saw Pos:"))
        self.fa_saw_position_label = self.pill("--", "#475569")
        pills_layout.addWidget(self.fa_saw_position_label)

        pills_layout.addWidget(QLabel("Fence Closed:"))
        self.fa_fence_closed_label = self.pill("--", "#475569")
        pills_layout.addWidget(self.fa_fence_closed_label)

        live_layout.addLayout(pills_layout)
        root_layout.addWidget(live_group)

        # ── MIDDLE ROW ────────────────────────────────────────────────────────
        middle_row = QHBoxLayout()
        middle_row.setSpacing(6)

        # LEFT: Cut List panel
        cut_list_group = QGroupBox("Cut List")
        vcl = QVBoxLayout(cut_list_group)

        self.fa_board_fill_label = QLabel("No cuts loaded")
        self.fa_board_fill_label.setStyleSheet("font-size: 13px; color: #94a3b8;")
        vcl.addWidget(self.fa_board_fill_label)

        self.fa_board_fill_bar = QProgressBar()
        self.fa_board_fill_bar.setRange(0, 1000)
        self.fa_board_fill_bar.setValue(0)
        self.fa_board_fill_bar.setTextVisible(False)
        self.fa_board_fill_bar.setFixedHeight(16)
        self.fa_board_fill_bar.setStyleSheet("""
            QProgressBar { background-color: #1e293b; border-radius: 8px; border: 1px solid #334155; }
            QProgressBar::chunk { background-color: #38bdf8; border-radius: 8px; }
        """)
        vcl.addWidget(self.fa_board_fill_bar)

        self.fa_cut_list_display = QTextEdit()
        self.fa_cut_list_display.setReadOnly(True)
        self.fa_cut_list_display.setStyleSheet("font-size: 18px;")
        self.fa_cut_list_display.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.fa_cut_list_display.setMinimumHeight(150)
        vcl.addWidget(self.fa_cut_list_display, 1)

        fa_list_btns = QHBoxLayout()
        fa_load_btn = QPushButton("Load from File")
        fa_load_btn.clicked.connect(self.load_list_from_file)
        fa_clear_btn = QPushButton("Clear List")
        fa_clear_btn.clicked.connect(self.clear_cut_list)
        fa_list_btns.addWidget(fa_load_btn)
        fa_list_btns.addWidget(fa_clear_btn)
        vcl.addLayout(fa_list_btns)

        left_wrap = QWidget()
        left_wrap.setLayout(QVBoxLayout())
        left_wrap.layout().setContentsMargins(0, 0, 0, 0)
        left_wrap.layout().addWidget(cut_list_group)
        left_wrap.setMaximumWidth(360)
        left_wrap.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        middle_row.addWidget(left_wrap)

        # CENTER/RIGHT: I/O area + Cycle Control
        io_and_cycle = QVBoxLayout()
        io_and_cycle.setSpacing(6)

        # Cylinders — single compact row to leave room for the line simulation
        cylinders_group = QGroupBox("Simulated Clamps")
        cyl_layout = QHBoxLayout(cylinders_group)
        cyl_layout.setSpacing(8)
        cyl_layout.setContentsMargins(10, 4, 10, 4)

        cyl_defs = [
            ("Main Clamp", 1, "fa_cyl1_status"),
            ("Outfeed Clamp", 2, "fa_cyl2_status"),
            ("Fence Clamp", 3, "fa_cyl3_status"),
        ]
        for cyl_name, cyl_id, pill_attr in cyl_defs:
            name_lbl = QLabel(cyl_name)
            name_lbl.setStyleSheet("font-weight: bold; font-size: 13px;")
            cyl_layout.addWidget(name_lbl)

            status_pill = self.pill("RETRACTED", "#475569")
            status_pill.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            status_pill.setMinimumWidth(96)
            setattr(self, pill_attr, status_pill)
            cyl_layout.addWidget(status_pill)
            cyl_layout.addSpacing(6)

        cyl_layout.addStretch()
        cylinders_group.setMaximumHeight(64)
        io_and_cycle.addWidget(cylinders_group)

        # Line simulation: carriage, board segments, saw, ejected pieces
        sim_group = QGroupBox("Line Simulation")
        sim_layout = QVBoxLayout(sim_group)
        sim_layout.setContentsMargins(8, 8, 8, 8)
        self.saw_sim = SawSimWidget(home_position=self.home_position)
        self.saw_sim.set_sensor_location(self.board_sensor_location_input.value())
        self.board_sensor_location_input.valueChanged.connect(self.saw_sim.set_sensor_location)
        sim_layout.addWidget(self.saw_sim)
        io_and_cycle.addWidget(sim_group, 1)

        middle_row.addLayout(io_and_cycle)
        root_layout.addLayout(middle_row, 1)

        # ── BOTTOM: Status + START CYCLE + CUT COMPLETE in one row ───────────
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(8)
        bottom_row.setContentsMargins(4, 4, 4, 4)

        self.fa_auto_status_label = QLabel("STATUS: Waiting to Start")
        self.fa_auto_status_label.setWordWrap(False)
        self.fa_auto_status_label.setStyleSheet("font-weight: bold; font-size: 15px; color: #e2e8f0;")
        bottom_row.addWidget(self.fa_auto_status_label, 1)

        fa_jog_right_btn = QPushButton("0.1\" ▶")
        fa_jog_right_btn.setFixedHeight(50)
        fa_jog_right_btn.setMinimumWidth(110)
        fa_jog_right_btn.setStyleSheet("""
            QPushButton { background-color: #1e293b; color: #e2e8f0; font-weight: bold; font-size: 16px; border-radius: 10px; border: 1px solid #334155; padding: 0 12px; }
            QPushButton:hover { background-color: #243142; }
        """)
        fa_jog_right_btn.clicked.connect(lambda: self.auto_jog(-0.1))
        bottom_row.addWidget(fa_jog_right_btn)

        self.fa_start_cycle_button = QPushButton("START CYCLE")
        self.fa_start_cycle_button.setFixedHeight(50)
        self.fa_start_cycle_button.setMinimumWidth(160)
        self.fa_start_cycle_button.setStyleSheet("""
            QPushButton { background-color: #22c55e; color: white; font-weight: bold; font-size: 17px; border-radius: 10px; padding: 0 16px; }
            QPushButton:hover { background-color: #16a34a; }
            QPushButton:disabled { background-color: #166534; color: #4ade80; }
        """)
        self.fa_start_cycle_button.clicked.connect(self.start_auto_cycle)
        bottom_row.addWidget(self.fa_start_cycle_button)


        bottom_widget = QWidget()
        bottom_widget.setLayout(bottom_row)
        bottom_widget.setFixedHeight(58)
        root_layout.addWidget(bottom_widget)

        return w

    def cylinder_extend(self, cyl_id):
        if not self.send_backend_commands(
            self.active_controller().clamp_extend(cyl_id),
            f"extend cylinder {cyl_id}",
        ):
            return False
        if cyl_id == 1:
            self.clamp_left_engaged = True
        elif cyl_id == 2:
            self.clamp_right_engaged = True
        elif cyl_id == 3:
            self.clamp_fence_engaged = True
        self._update_cylinder_ui(cyl_id)
        return True

    def cylinder_retract(self, cyl_id):
        if not self.send_backend_commands(
            self.active_controller().clamp_retract(cyl_id),
            f"retract cylinder {cyl_id}",
        ):
            return False
        if cyl_id == 1:
            self.clamp_left_engaged = False
        elif cyl_id == 2:
            self.clamp_right_engaged = False
        elif cyl_id == 3:
            self.clamp_fence_engaged = False
        self._update_cylinder_ui(cyl_id)
        return True

    def set_actuator_direction(self, direction):
        """Set off/forward/reverse through the backend's off-first interlock."""
        direction = str(direction).strip().lower()
        if direction not in {"off", "forward", "reverse"}:
            self.log.append(f"ACTUATOR BLOCKED: invalid direction '{direction}'.")
            return False
        controller = self.active_controller()
        if not controller.capabilities.actuator:
            self.log.append(
                f"UNSUPPORTED: {controller.label} has no validated actuator output."
            )
            return False
        if not self.send_backend_commands(
            controller.actuator_direction(direction),
            f"set actuator direction to {direction}",
        ):
            return False
        self.actuator_direction = direction
        return True

    def _update_cylinder_ui(self, cyl_id):
        engaged_map = {
            1: self.clamp_left_engaged,
            2: self.clamp_right_engaged,
            3: self.clamp_fence_engaged,
        }
        pill_map = {1: "fa_cyl1_status", 2: "fa_cyl2_status", 3: "fa_cyl3_status"}
        engaged = engaged_map[cyl_id]
        pill_attr = pill_map[cyl_id]
        if hasattr(self, pill_attr):
            pill_widget = getattr(self, pill_attr)
            if engaged:
                self.set_pill(pill_widget, "EXTENDED", "#2563eb")
            else:
                self.set_pill(pill_widget, "RETRACTED", "#475569", fg="#e2e8f0")
        if hasattr(self, 'saw_sim'):
            self.saw_sim.set_clamps(self.clamp_left_engaged, self.clamp_right_engaged,
                                    self.clamp_fence_engaged)

    def _update_saw_sensor_pill(self, text, color):
        if hasattr(self, 'fa_saw_position_label'):
            self.set_pill(self.fa_saw_position_label, text, color)
        if hasattr(self, 'saw_sim'):
            self.saw_sim.set_saw_state(text)

    def update_saw_position_sensor_status(self, status):
        """
        Virtual SSEN:1 confirms UP; SSEN:0 means not UP. Native saw endpoints
        use BENCH feedback and never execute this simulator cut sequence.
        A genuine virtual UP edge starts the configured return/release waits.
        """
        rising = (status == 1 and self._last_saw_sensor == 0)
        if status != self._last_saw_sensor:
            if status == 1:
                self._update_saw_sensor_pill("UP", "#22c55e")
            elif self.clamps_engaged_cutting:
                self._update_saw_sensor_pill("CUTTING", "#ef4444")
            else:
                self._update_saw_sensor_pill("DOWN", "#ef4444")
        self._last_saw_sensor = status

        if rising and self.clamps_engaged_cutting:
            self.clamps_engaged_cutting = False
            was_early = bool((self.sim_active_piece or {}).get("early")) or self.is_early_returning
            timing = self._cycle_cylinder_timings
            clamps = self._cycle_clamps

            def complete():
                self._simulation_pneumatic_pending = False
                self._on_cut_finished()
                self._set_cut_complete_enabled(not was_early)
                if was_early:
                    if self.auto_cycle_state == 'FINISHED':
                        self._set_cycle_status('STATUS: Cycle Complete!')
                        self._set_start_enabled(True)
                    elif self.auto_cycle_state != 'WAITING_FOR_NEW_BOARD':
                        self._set_cycle_status("STATUS: Saw up — clamps released. Loading next board...")
                else:
                    self._set_cycle_status("STATUS: Simulation stroke complete; awaiting simulated completion.")

            def release():
                self._run_simulation_clamps(clamps, timing, 'release', complete)

            self._set_cycle_status('STATUS: Saw UP — waiting for trigger release and clamp clearance.')
            wait = timing['saw.up_settle'] + timing['trigger.release_delay'] + timing['trigger.brake_wait']
            self._schedule_simulation_phase(wait, release)

    def _actuate_saw(self):
        """
        Start the virtual saw cycle with this cut's timing snapshot.
        Live native automatic cutting remains capability-blocked.
        """
        controller = self.active_controller()
        if not controller.capabilities.automatic_cutting_ready:
            self.clamps_engaged_cutting = False
            self._release_all_clamps()
            self._update_saw_sensor_pill("BLOCKED", "#ef4444")
            self._set_cycle_status(
                f"STATUS: Saw blocked — {controller.label} lacks verified saw feedback."
            )
            self.log.append(
                f"SAFETY BLOCK: automatic saw is not ready for {controller.label}."
            )
            return False

        if isinstance(self.ser, VirtualController):
            if not self.auto_clamp_enabled or not getattr(self, '_simulation_pneumatic_pending', False):
                return False
            self.ser.configure_saw_timing(self._cycle_cylinder_timings)
        if not self.send_backend_commands(controller.saw_actuate(), "actuate saw"):
            self.clamps_engaged_cutting = False
            self._release_all_clamps()
            self._update_saw_sensor_pill("BLOCKED", "#ef4444")
            self._set_cycle_status("STATUS: Saw command failed — clamps released.")
            return False

        # Require a virtual SSEN 0 -> 1 edge; never synthesize physical feedback.
        self.clamps_engaged_cutting = True
        self._update_saw_sensor_pill("CUTTING", "#ef4444")
        self._set_cycle_status("STATUS: Cutting — waiting for saw-up feedback...")
        return True

    def _release_all_clamps(self):
        """Immediate simulator cancellation release; normal cycles use timed release."""
        if not self.auto_clamp_enabled:
            return
        self.cylinder_retract(1)
        self.cylinder_retract(2)
        self.cylinder_retract(3)

    def _on_auto_clamp_toggled(self, checked):
        controller = self.active_controller()
        if checked and not controller.capabilities.automatic_cutting_ready:
            self.auto_clamp_checkbox.blockSignals(True)
            self.auto_clamp_checkbox.setChecked(False)
            self.auto_clamp_checkbox.blockSignals(False)
            self.auto_clamp_enabled = False
            self.log.append(
                f"SAFETY BLOCK: auto clamp/saw is unavailable for {controller.label}."
            )
            self._set_cycle_status(
                f"STATUS: Auto clamp/saw unavailable for {controller.label}."
            )
            return
        if self.auto_clamp_enabled and not checked:
            self.cancel_auto_cycle()
        self.auto_clamp_enabled = checked
        mode = "Automatic clamp/saw simulation enabled" if checked else "Manual cut simulation"
        self.log.append(mode)
        if checked:
            self._set_cycle_status("STATUS: Automatic clamp/saw simulation enabled.")

    def _record_sim_piece(self, early_return, is_truing):
        """Record what the next stroke cuts, for the line-view animation."""
        if is_truing:
            self.sim_active_piece = {"truing": True}
        elif self.current_cut_index < len(self.cut_list):
            _, length, _ = self.cut_list[self.current_cut_index]
            self.sim_active_piece = {
                "truing": False, "early": early_return, "length": length,
                "color": PIECE_COLORS[self.current_cut_index % len(PIECE_COLORS)],
            }

    # ---------- Line-view simulation tracking ----------
    def _sync_sim_index(self):
        self.sim_next_piece_index = self.current_cut_index

    def _sim_track_carriage(self, pos):
        """The carriage pushes the board toward the blade; retracting leaves it."""
        if not hasattr(self, 'saw_sim'):
            return
        if self.sim_board_remaining is not None:
            back = self.sim_edge_pos + self.sim_board_remaining
            if pos < back - 1e-9:
                self.sim_edge_pos = pos - self.sim_board_remaining
                self.saw_sim.set_board_edge(self.sim_edge_pos)
        self.saw_sim.set_carriage(pos)

    def _refresh_sim_board(self):
        """Rebuild the colored piece segments for the board currently on the line."""
        if not hasattr(self, 'saw_sim'):
            return
        if self.sim_board_remaining is None or self.sim_board_remaining <= 0.01:
            self.saw_sim.set_board(False, 0.0, [])
            return
        kerf = self.kerf_input.value()
        segs = []
        rem = self.sim_board_remaining
        if not self.sim_board_trimmed:
            trim = min(TRUING_TRIM, rem)
            segs.append((trim, TRIM_COLOR, None))
            rem -= trim
        i = self.sim_next_piece_index
        while rem > 0.01 and i < len(self.cut_list):
            _, length, _ = self.cut_list[i]
            if length + kerf > rem + 1e-6:
                break
            segs.append((length, PIECE_COLORS[i % len(PIECE_COLORS)], f'{length:g}"'))
            segs.append((min(kerf, rem - length), None, None))
            rem -= length + kerf
            i += 1
        if rem > 0.01:
            segs.append((rem, SCRAP_COLOR, "scrap" if self.sim_board_trimmed else None))
        self.saw_sim.set_board(True, self.sim_edge_pos, segs)

    def _on_cut_finished(self):
        """Book a completed saw stroke: consume board, eject the piece."""
        piece = self.sim_active_piece
        self.sim_active_piece = None
        if piece is None:
            return
        kerf = self.kerf_input.value()
        if self.sim_board_remaining is not None:
            if piece.get("truing"):
                self.sim_board_remaining -= min(TRUING_TRIM, self.sim_board_remaining)
                self.sim_board_trimmed = True
            else:
                self.sim_board_remaining = max(
                    0.0, self.sim_board_remaining - piece["length"] - kerf
                )
            self.sim_edge_pos = 0.0
        if piece.get("truing"):
            self._sync_sim_index()
        elif piece.get("early"):
            self.sim_next_piece_index = self.current_cut_index  # already incremented
        else:
            self.sim_next_piece_index = self.current_cut_index + 1
        if hasattr(self, 'saw_sim'):
            if piece.get("truing"):
                self.saw_sim.eject_piece(TRUING_TRIM, TRIM_COLOR, "trim")
            else:
                self.saw_sim.eject_piece(piece["length"], piece["color"], f'{piece["length"]:g}"')
        self._refresh_sim_board()

    def _schedule_simulation_phase(self, delay_ms, callback):
        """Cancel pending normal-cycle delays on stop/disconnect/mode changes."""
        generation, port = self.cycle_generation, self.ser

        def run():
            if (generation == self.cycle_generation and self.ser is port
                    and isinstance(port, VirtualController) and port.is_open and self.auto_clamp_enabled):
                callback()
        QTimer.singleShot(int(delay_ms), run)

    def _engage_clamps_for_cut(self, early_return=False):
        """Three-clamp virtual fixture only; native eligibility/feedback remains uncommissioned."""
        if not isinstance(self.ser, VirtualController) or not self.auto_clamp_enabled:
            return False
        position = self.current_position
        is_truing = (not early_return) and self.auto_cycle_state == "WAITING_FOR_TRUING_CUT"
        clamps = simulation_clamps(position, is_truing)
        timing = self.cylinder_timing.snapshot()
        self._cycle_clamps = clamps
        self._cycle_cylinder_timings = timing  # immutable for this cut, including release
        self._simulation_pneumatic_pending = True
        self._set_cut_complete_enabled(False)
        self._set_cycle_status('STATUS: Board in position — settling before simulated clamping...')
        self._record_sim_piece(early_return, is_truing)

        def _do_clamp():
            self._run_simulation_clamps(clamps, timing, 'engage', self._actuate_saw)

        self._schedule_simulation_phase(timing['board.settle'], _do_clamp)
        return True

    def _run_simulation_clamps(self, clamps, timing, phase, complete):
        """Wait for every participating virtual clamp, including zero-delay phases."""
        finished = set()
        def ready(cid):
            finished.add(cid)
            if len(finished) == len(clamps):
                complete()
        for cid in clamps:
            def command(c=cid):
                action = self.cylinder_extend if phase == 'engage' else self.cylinder_retract
                if not action(c):
                    self.cancel_auto_cycle()
                    self._set_cycle_status('STATUS: Simulated clamp command failed — cut blocked.')
                    return
                wait_key = 'engage_settle' if phase == 'engage' else 'release_clearance'
                self._schedule_simulation_phase(timing[f'{CLAMPS[c]}.{wait_key}'], lambda: ready(c))
            self._schedule_simulation_phase(timing[f'{CLAMPS[cid]}.{phase}_delay'], command)

    def load_cut_list_lines(self, lines):
        self._rebuild_cut_list(lines)

    # ---------- Clamp Control Methods ----------
    def toggle_clamp(self):
        requested_state = not self.clamp_engaged
        if not self.send_backend_commands(
            self.active_controller().clamp_all(requested_state),
            "engage all clamps" if requested_state else "release all clamps",
        ):
            return
        self.clamp_engaged = requested_state
        self.update_clamp_ui()

    def update_clamp_ui(self):
        if self.active_controller().key == TEENSY_CARRIAGE:
            self.set_pill(self.auto_clamp_status_label,"UNKNOWN","#475569")
            self.auto_clamp_status_label.setToolTip("No clamp feedback sensor is configured.")
            return
        if self.clamp_engaged:
            if hasattr(self, 'clamp_button'):
                self.clamp_button.setText("UNCLAMP")
                self.clamp_button.setStyleSheet("background-color: #2563eb; color: white; font-weight: bold;")
            self.set_pill(self.auto_clamp_status_label, "CLAMPED", "#2563eb")
        else:
            if hasattr(self, 'clamp_button'):
                self.clamp_button.setText("CLAMP")
                self.clamp_button.setStyleSheet("background-color: #4b5563; color: #e2e8f0; font-weight: bold;")
            self.set_pill(self.auto_clamp_status_label, "UNCLAMPED", "#4b5563", fg="#e2e8f0")

    # ---------- Enable/Disable ----------
    def set_controls_enabled(self, enabled):
        self.connection_controls_enabled = bool(enabled)
        self.apply_controller_capabilities()

    def is_connected(self):
        return bool(self.ser and self.ser.is_open)

    def apply_controller_capabilities(self):
        """Expose only operations that are verified safe for the live backend."""
        connected = bool(getattr(self, "connection_controls_enabled", False)) and self.is_connected()
        controller = self.active_controller()
        capabilities = controller.capabilities
        if hasattr(self, "carriage_tab"):
            carriage_selected = controller.key == TEENSY_CARRIAGE
            self.tabs.setTabVisible(self.tabs.indexOf(self.carriage_tab), carriage_selected)
            if self.carriage_tab.connected != (connected and carriage_selected):
                self.carriage_tab.session(connected and carriage_selected)
            if carriage_selected:
                self.tabs.setCurrentWidget(self.carriage_tab)

        if hasattr(self, "controller_combo"):
            self.controller_combo.setEnabled(not connected)
        if hasattr(self, "port_combo"):
            self.port_combo.setEnabled(not connected)
        if hasattr(self, "refresh_ports_button"):
            self.refresh_ports_button.setEnabled(not connected)

        for name in ("norm_speed","norm_accel","gentle_speed","gentle_accel","fast_speed","fast_accel"):
            widget = getattr(self,name,None)
            if widget is not None:
                widget.setEnabled(controller.key != TEENSY_CARRIAGE)
        manual_ready = connected and capabilities.manual_motion_ready
        auto_ready = connected and capabilities.automatic_cycle_ready
        native_manual = controller.key == TEENSY_CARRIAGE
        self.auto_dry_group.setVisible(native_manual)
        self.cylinder_timing.set_simulator_mode(isinstance(self.ser, VirtualController))
        self.tabs.setTabText(self.tabs.indexOf(self.legacy_tab),"MANUAL" if native_manual else "MANUAL / SIM")
        self.legacy_tab.setEnabled(manual_ready or (connected and native_manual))
        self.manual_teensy_setup.setVisible(native_manual)
        self.manual_teensy_actions.setVisible(native_manual)
        self.manual_home_button.setText("Home")
        self.enable_chk.setToolTip(
            "Check to enable and arm through the shared driver checks. Uncheck to release the motor; Home must be repeated. "
            "Reflects the controller enable output, not measured motor power."
            if native_manual else "Enable or release the simulated carriage motor."
        )
        if not native_manual:
            self.enable_chk.blockSignals(True)
            self.enable_chk.setChecked(isinstance(self.ser, VirtualController) and self.ser.motor_enabled)
            self.enable_chk.blockSignals(False)
            for widget in (self.manual_home_button,self.enable_chk,self.keypad):
                widget.setEnabled(True)
        self.auto_tab.setEnabled(auto_ready or native_manual)  # offline list planning remains available
        self.current_group.setVisible(not native_manual)
        self.auto_teensy_setup.setVisible(native_manual)
        self.cancel_cycle_button.setText("STOP / DISARM" if native_manual else "CANCEL CYCLE")
        self.resume_on_reset_button.setEnabled(auto_ready)
        self.resume_on_reset_button.setVisible(not native_manual)
        self._set_start_enabled(auto_ready)
        self.auto_jog_input.setRange(0.01 if native_manual else 0.001,2 if native_manual else 100)
        if not native_manual:
            for widget in (self.load_button,self.cancel_cycle_button,self.auto_jog_input,self.auto_jog_left_btn,self.auto_jog_right_btn,
                           self.qjog_left_01,self.qjog_right_01,self.qjog_left_025,self.qjog_right_025,
                           self.qjog_left_1,self.qjog_right_1,self.qjog_left_2,self.qjog_right_2): widget.setEnabled(True)
        if hasattr(self, "full_auto_tab"):
            self.full_auto_tab.setEnabled(auto_ready)

        if hasattr(self, "auto_clamp_checkbox"):
            cutting_ready = auto_ready and capabilities.automatic_cutting_ready
            self.auto_clamp_checkbox.setEnabled(cutting_ready)
            if not cutting_ready and self.auto_clamp_checkbox.isChecked():
                self.auto_clamp_checkbox.blockSignals(True)
                self.auto_clamp_checkbox.setChecked(False)
                self.auto_clamp_checkbox.blockSignals(False)
                self.auto_clamp_enabled = False

        if connected and not manual_ready and not auto_ready and not capabilities.carriage_jog_ready:
            self._set_cycle_status(
                f"STATUS: {controller.label} is diagnostics-only until validation is complete."
            )
        self.refresh_teensy_tabs()
        self.manual_pneumatics.refresh()
        self.refresh_manual_motion_locks()

    def refresh_manual_motion_locks(self):
        if not isinstance(self.ser, VirtualController):
            if self.dry_run.motion_locked():
                for widget in (self.manual_home_button,self.keypad,self.enable_chk,self.manual_configure,
                               self.manual_arm,self.manual_release,self.load_button,self.auto_arm,self.auto_home,
                               self.auto_configure,self.auto_jog_left_btn,self.auto_jog_right_btn,
                               self.qjog_left_01,self.qjog_right_01,self.qjog_left_025,self.qjog_right_025,
                               self.qjog_left_1,self.qjog_right_1,self.qjog_left_2,self.qjog_right_2): widget.setEnabled(False)
            return
        free = self.is_connected() and not self.manual_pneumatics.motion_locked()
        for widget in (self.manual_home_button,self.keypad,self.enable_chk,self.load_button,self.resume_on_reset_button,
                       self.auto_jog_left_btn,self.auto_jog_right_btn,self.qjog_left_01,self.qjog_right_01,
                       self.qjog_left_025,self.qjog_right_025,self.qjog_left_1,self.qjog_right_1,
                       self.qjog_left_2,self.qjog_right_2):
            widget.setEnabled(free)
        if not free:
            self._set_start_enabled(False)
        elif self.auto_cycle_state in ('IDLE','FINISHED','WAITING_FOR_NEW_BOARD'):
            self._set_start_enabled(True)

    # ---------- Cut list ----------
    def add_cut_to_list(self):
        if not self.cut_length_keypad.valid_length():
            return
        L = self.cut_length_input.value()
        if L > 0:
            self.cut_list.append((self.next_cut_number, L, ""))
            self.next_cut_number += 1
            self.update_cut_list_display()
            self.cut_length_input.setFocus(Qt.FocusReason.OtherFocusReason)
            self.cut_length_input.selectAll()

    def clear_cut_list(self):
        self.cut_list.clear()
        self.next_cut_number = 1
        self.current_cut_index = 0
        self._sync_sim_index()
        self.update_cut_list_display()

    def get_active_board_length(self):
        for radio, board_length, _ in self.board_size_radios:
            if radio.isChecked():
                return board_length
        return self.standard_board_length

    def _set_board_fill(self, ratio, color, text):
        """Update the board utilization bar and label on both AUTO and FULL AUTO tabs."""
        for bar_attr, label_attr in (
            ("board_fill_bar", "board_fill_label"),
            ("fa_board_fill_bar", "fa_board_fill_label"),
        ):
            bar = getattr(self, bar_attr, None)
            if bar is not None:
                bar.setValue(int(ratio * 1000))
                bar.setStyleSheet(f"""
                    QProgressBar {{ background-color: #1e293b; border-radius: 8px; border: 1px solid #334155; }}
                    QProgressBar::chunk {{ background-color: {color}; border-radius: 8px; }}
                """)
            label = getattr(self, label_attr, None)
            if label is not None:
                label.setText(text)

    def update_cut_list_display(self):
        if not self.cut_list:
            self.cut_list_display.setText("")
            self.cut_list_display.setPlaceholderText("No cuts in list.")
            if hasattr(self, 'fa_cut_list_display'):
                self.fa_cut_list_display.setText("")
                self.fa_cut_list_display.setPlaceholderText("No cuts in list.")
            self._set_board_fill(0.0, "#38bdf8", "No cuts loaded")
            return

        board_length = self.get_active_board_length()
        kerf = self.kerf_input.value()
        group_colors = ["#38bdf8", "#f59e0b"]

        # Single pass: which board group each cut lands on and each group's used length
        cut_groups = []
        group_used_map = {}
        gi, gu = 0, 0.0
        for _, length, _ in self.cut_list:
            needed = length + kerf
            if gu + needed > board_length and gu > 0:
                group_used_map[gi] = gu
                gi += 1
                gu = 0.0
            gu += needed
            cut_groups.append(gi)
        group_used_map[gi] = gu

        # The active board group is the one containing current_cut_index
        if self.current_cut_index < len(cut_groups):
            active_group = cut_groups[self.current_cut_index]
        else:
            active_group = cut_groups[-1]

        active_used = group_used_map.get(active_group, 0.0)
        fill_ratio = min(1.0, active_used / board_length) if board_length > 0 else 0.0
        fill_color = group_colors[active_group % len(group_colors)]
        self._set_board_fill(
            fill_ratio, fill_color,
            f"Board {active_group + 1}: {active_used:.2f}\" / {board_length:.2f}\" ({fill_ratio * 100:.1f}%)"
        )

        html_lines = []
        for i, (num, length, desc) in enumerate(self.cut_list):
            color = group_colors[cut_groups[i] % len(group_colors)]
            line_text = f"Cut {num}: {length:<9.4f}\" {desc}"

            if i == self.current_cut_index:
                html_lines.append(
                    f"<div style='background-color:#334155;'><b><span style='color:{color};'>&gt; {line_text}</span></b></div>"
                )
            else:
                html_lines.append(f"<span style='color:{color};'>&nbsp; {line_text}</span>")

        html = "<br>".join(html_lines)
        self.cut_list_display.setHtml(html)

        # Mirror to FULL AUTO tab
        if hasattr(self, 'fa_cut_list_display'):
            self.fa_cut_list_display.setHtml(html)

        if self.current_cut_index < len(self.cut_list):
            current_num = self.cut_list[self.current_cut_index][0]
            self._center_cut_in_display(self.cut_list_display, current_num)
            if hasattr(self, 'fa_cut_list_display'):
                self._center_cut_in_display(self.fa_cut_list_display, current_num)

        self._refresh_sim_board()

    def _center_cut_in_display(self, display, cut_num):
        """Scroll the cut list so the highlighted current cut sits mid-viewport."""
        doc = display.document()
        cursor = doc.find(f"> Cut {cut_num}:")
        if cursor.isNull():
            return
        display.setTextCursor(cursor)
        # Document layout after setHtml is lazy (normally done at paint time);
        # setting the text width forces it now so the geometry below is valid.
        doc.setTextWidth(display.viewport().width())
        block_rect = doc.documentLayout().blockBoundingRect(cursor.block())
        scrollbar = display.verticalScrollBar()
        scrollbar.setValue(int(block_rect.center().y()) - display.viewport().height() // 2)

    def load_list_from_file(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "Open Cut List", "", "Text Files (*.txt);;All Files (*)")
        if file_name:
            try:
                with open(file_name, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    self._rebuild_cut_list(lines)
            except Exception as e:
                self.log.append(f"Error reading file: {e}")

    def update_list_from_box(self):
        try:
            text = self.cut_list_display.toPlainText()
            lines = text.split('\n')
            self._rebuild_cut_list(lines)
        except Exception as e:
            self.log.append(f"Error parsing list: {e}")

    def _rebuild_cut_list(self, lines):
        self.cut_list.clear()
        self.next_cut_number = 1
        for line in lines:
            clean_line = line.strip()
            if not clean_line:
                continue

            # Lines round-tripped from the on-screen list render as
            # 'Cut 3: 18.0000  " description'. Parse those exactly so a
            # description containing digits can't be mistaken for the length.
            display_match = re.match(r'^[>\s]*Cut\s+\d+:\s*(\d+\.?\d*)\s*"?\s*(.*)$', clean_line)
            if display_match:
                length = float(display_match.group(1))
                description = display_match.group(2).strip(' ,:"')
                if length > 0:
                    self.cut_list.append((self.next_cut_number, length, description))
                    self.next_cut_number += 1
                continue

            # Length-first format: '<length> <description>' (e.g. '78.75  Roof Side #1').
            # Must be checked before the last-number fallback, which would
            # otherwise grab the '1' from '#1' as the cut length.
            leading_match = re.match(r'^(\d+\.?\d*)\s*(.*)$', clean_line)
            if leading_match:
                length = float(leading_match.group(1))
                description = leading_match.group(2).strip(' ,:"')
                if length > 0:
                    self.cut_list.append((self.next_cut_number, length, description))
                    self.next_cut_number += 1
                continue

            if ':' in clean_line:
                data_part = clean_line.rsplit(':', 1)[-1]
            else:
                data_part = clean_line

            matches = list(re.finditer(r'(\d+\.?\d*)', data_part))

            if matches:
                try:
                    match = matches[-1]
                    length = float(match.group(1))
                    start, end = match.span(1)
                    description = (data_part[:start] + data_part[end:]).strip(' ,:"')

                    if length > 0:
                        self.cut_list.append((self.next_cut_number, length, description))
                        self.next_cut_number += 1
                except (ValueError, IndexError):
                    self.log.append(f"Could not parse number from: '{data_part}'")
            else:
                self.log.append(f"No number found in line: '{line}'")

        self.current_cut_index = 0
        self._sync_sim_index()
        self.update_cut_list_display()
        self.log.append(f"Loaded {len(self.cut_list)} cuts into the list.")

    # ---------- Auto Cycle ----------
    # --- NEW: Method to cancel the auto cycle ---
    def cancel_auto_cycle(self):
        """Stops any active auto cycle and resets the state."""
        if self.active_controller().key == TEENSY_CARRIAGE:
            return self.carriage_tab.stop()
        # 1. Send a command to stop the motor's current movement. M0 (Move 0) is a safe stop command.
        self.cycle_generation += 1
        self._simulation_pneumatic_pending = False
        if isinstance(self.ser, VirtualController):
            self.ser.cancel_saw_cycle()
        self.send_backend_commands(
            self.active_controller().stop_motion(), "stop carriage motion"
        )
        self.log.append("Auto cycle canceled by user.")

        # 2. Reset the state machine and related flags
        self.auto_cycle_state = "IDLE"
        self.perform_early_return = False
        self.is_early_returning = False
        self.clamps_engaged_cutting = False
        self.sim_active_piece = None
        self.current_cut_index = 0
        self._sync_sim_index()

        # 3. Update UI controls and status
        self._release_all_clamps()
        self._update_saw_sensor_pill("--", "#475569")
        self._set_cycle_status("STATUS: Cycle Canceled. Ready.")
        self._set_start_enabled(True)
        self._set_cut_complete_enabled(False)
        self.update_cut_list_display() # Refresh list to show first item as current
    # --- END NEW ---

    def resume_after_reset(self):
        if self.manual_pneumatics.motion_locked():
            return False
        if getattr(self, '_simulation_pneumatic_pending', False):
            return False
        
        # Use after the driver faults, you reset it and rehome.
        # This resumes at the CURRENT cut index without losing your place.
        # It does NOT increment the cut; it re-advances for the same cut length.
        
        # 0) Guard rails
        if not self.active_controller().capabilities.automatic_cycle_ready:
            self.log.append(
                f"RESUME BLOCKED: {self.active_controller().label} is not approved for automatic cycles."
            )
            return
        self.cycle_generation += 1
        if self.homed_label.text() != "HOMED":
            self.log.append("RESUME ERROR: Home the system first, then press RESUME ON RESET.")
            return
        if not self.cut_list:
            self.log.append("RESUME ERROR: Cut list is empty.")
            return

        # 1) Make sure index is in range
        if self.current_cut_index >= len(self.cut_list):
            self.current_cut_index = max(0, len(self.cut_list) - 1)

        # 2) Reset internal flags that affect the state machine
        self.perform_early_return = False
        self.is_early_returning = False
        self.clamps_engaged_cutting = False
        self.sim_active_piece = None
        self._sync_sim_index()

        # 3) Tell the UI/state machine what's happening
        cut_num, cut_length, _ = self.cut_list[self.current_cut_index]
        self._set_cycle_status(f"STATUS: Resuming after reset at cut {cut_num} ({cut_length:.2f}\")")
        self.update_cut_list_display()

        # 4) Choose a profile and state, then let the normal logic take over
        self.switch_profile("GENTLE", True)
        self.auto_cycle_state = "DETECTING"
        self._set_start_enabled(False)
        self._set_cut_complete_enabled(False)

        # 5) Kick the state machine
        self.advance_auto_cycle()


    def start_auto_cycle(self):
        if self.manual_pneumatics.motion_locked():
            return False
        if getattr(self, '_simulation_pneumatic_pending', False):
            return False
        controller = self.active_controller()
        if not controller.capabilities.automatic_cycle_ready:
            self.log.append(
                f"AUTO MODE BLOCKED: {controller.label} is not approved for automatic cycles."
            )
            self._set_cycle_status(
                f"STATUS: Automatic cycle unavailable for {controller.label}."
            )
            return
        self.cycle_generation += 1
        if self.homed_label.text() != "HOMED":
            self.log.append("AUTO MODE ERROR: System must be homed first."); return
        if not self.cut_list:
            self.log.append("AUTO MODE ERROR: Cut list is empty."); return
            
        if self.auto_cycle_state == "IDLE" or self.auto_cycle_state == "FINISHED":
            self.current_cut_index = 0
            self._sync_sim_index()

        self.update_cut_list_display()
        self.switch_profile("GENTLE", True)
        self.auto_cycle_state = "DETECTING"
        self.advance_auto_cycle()

    def cut_complete_pressed(self):
        if not isinstance(self.ser,VirtualController):
            return False
        if getattr(self, '_simulation_pneumatic_pending', False):
            return False
        if self.clamps_engaged_cutting:
            return False
        if self.sim_active_piece is not None:
            # Manual mode: the operator made the cut; book it for the animation
            self._on_cut_finished()
        self._update_saw_sensor_pill("UP", "#22c55e")
        if self.auto_cycle_state == "WAITING_FOR_TRUING_CUT":
            self.switch_profile("NORMAL", True)
            self.auto_cycle_state = "ADVANCING"
            self.advance_auto_cycle()
        elif self.auto_cycle_state == "WAITING_FOR_CUT":
            if self.current_cut_index < len(self.cut_list):
                self.current_cut_index += 1
            self.update_cut_list_display()
            if self.current_cut_index >= len(self.cut_list):
                self.auto_cycle_state = "FINISHED"
            else:
                self.auto_cycle_state = "ADVANCING"
            self.switch_profile("NORMAL", True)
            self.advance_auto_cycle()

    def _set_cycle_status(self, text):
        self.auto_status_label.setText(text)
        if hasattr(self, 'fa_auto_status_label'):
            self.fa_auto_status_label.setText(text)

    def _set_start_enabled(self, enabled):
        allowed = (
            enabled
            and not getattr(self, '_simulation_pneumatic_pending', False)
            and not self.manual_pneumatics.motion_locked()
            and self.is_connected()
            and self.active_controller().capabilities.automatic_cycle_ready
        )
        self.start_cycle_button.setEnabled(allowed)
        if hasattr(self, 'fa_start_cycle_button'):
            self.fa_start_cycle_button.setEnabled(allowed)

    def _set_cut_complete_enabled(self, enabled):
        self._legacy_cut_completion_ready = bool(enabled and isinstance(self.ser,VirtualController))

    def advance_auto_cycle(self):
        if not self.active_controller().capabilities.automatic_cycle_ready:
            return False
        self.perform_early_return = False # Reset flag at start of each advance
        if self.auto_cycle_state == "DETECTING":
            self._set_cycle_status("STATUS: Detecting board edge...")
            sensor_offset = self.board_sensor_location_input.value()
            # A fresh board lands against the carriage (operator load)
            self.sim_board_remaining = self.get_active_board_length() + TRUING_TRIM
            self.sim_board_trimmed = False
            self.sim_edge_pos = self.current_position - self.sim_board_remaining
            self._sync_sim_index()
            if isinstance(self.ser, VirtualController):
                self.ser.board_length = self.sim_board_remaining
            self._refresh_sim_board()
            if not self.send_backend_commands(
                self.active_controller().truing_cycle(sensor_offset),
                "start truing cycle",
            ):
                self.auto_cycle_state = "IDLE"
                self._set_cycle_status("STATUS: Truing cycle unsupported or command failed.")
                self._set_start_enabled(True)
                return
            self.auto_cycle_state = "WAITING_FOR_TRUING_CUT"
            self._set_start_enabled(False)
            self._set_cut_complete_enabled(False)
        elif self.auto_cycle_state == "ADVANCING":
            if self.current_cut_index >= len(self.cut_list):
                self.auto_cycle_state = "FINISHED"; self.advance_auto_cycle(); return

            current_pos = self.current_position
            cut_num, cut_length, cut_desc = self.cut_list[self.current_cut_index]
            kerf = self.kerf_input.value()
            total_material_needed = cut_length + kerf

            if current_pos < total_material_needed:
                self.auto_cycle_state = "WAITING_FOR_NEW_BOARD"
                self._set_cycle_status("STATUS: Board empty. Load new board.")
                self._set_start_enabled(True)
                self._set_cut_complete_enabled(False)
                self.load_position()
                return

            self._set_cycle_status(f"STATUS: Advancing for cut {cut_num} ({cut_length:.2f}\")")
            new_pos = current_pos - total_material_needed

            next_cut_index = self.current_cut_index + 1
            if next_cut_index < len(self.cut_list):
                next_cut_length = self.cut_list[next_cut_index][1]
                needed_for_next = next_cut_length + kerf
                if new_pos < needed_for_next:
                    self.perform_early_return = True
                    self._set_cycle_status("STATUS: Final cut on board. Returning to load...")
            else:
                self.perform_early_return = True
                self._set_cycle_status("STATUS: Final cut on board. Returning to load...")

            self.set_length(new_pos)
            self.auto_cycle_state = "WAITING_FOR_CUT"
            self._set_cut_complete_enabled(False)
        elif self.auto_cycle_state == "FINISHED":
            self._set_cycle_status("STATUS: Cycle Complete!")
            self._set_start_enabled(True)
            self._set_cut_complete_enabled(False)
            self.auto_cycle_state = "IDLE"

    # ---------- Serial / Commands ----------
    def refresh_serial_ports(self):
        previous_port = self.selected_serial_port
        ports = sorted(serial.tools.list_ports.comports(), key=lambda p: p.device)
        self.port_combo.blockSignals(True)
        self.port_combo.clear()
        for port in ports:
            description = f"{port.device} - {port.description}" if port.description else port.device
            self.port_combo.addItem(description, port.device)
        self.port_combo.addItem("SIMULATOR - virtual machine", "SIM")
        self.port_combo.setEnabled(True)
        devices = [port.device for port in ports] + ["SIM"]
        if previous_port in devices:
            target_port = previous_port
        else:
            target_port = ports[0].device if ports else "SIM"
        index = self.port_combo.findData(target_port)
        if index >= 0:
            self.port_combo.setCurrentIndex(index)
            self.selected_serial_port = target_port
        self.port_combo.blockSignals(False)

    def on_serial_port_changed(self):
        if hasattr(self, "port_combo"):
            self.selected_serial_port = self.port_combo.currentData() or ""

    def on_controller_mode_changed(self):
        if not hasattr(self, "controller_combo"):
            return
        if self.is_connected():
            self.controller_combo.blockSignals(True)
            previous_index = self.controller_combo.findData(self.selected_controller_mode)
            if previous_index >= 0:
                self.controller_combo.setCurrentIndex(previous_index)
            self.controller_combo.blockSignals(False)
            if hasattr(self, "log"):
                self.log.append("SAFETY BLOCK: disconnect before changing controller mode.")
            return
        mode_key = self.controller_combo.currentData() or TEENSY_HARDWARE_TEST
        self.selected_controller_mode = mode_key
        self.controller = create_controller_backend(mode_key)
        if hasattr(self, "log"):
            self.log.append(f"Controller mode: {self.controller.label}")
        if hasattr(self, "legacy_tab"):
            self.apply_controller_capabilities()

    def toggle_connection(self):
        if self.ser is None or not self.ser.is_open:
            port_name = self.selected_serial_port or SERIAL_PORT
            if not port_name:
                self.log.append("ERROR: No serial ports detected.")
                return
            try:
                if port_name == "SIM":
                    self.ser = VirtualController()
                    self.set_pill(self.status_label, "SIM MODE", "#f59e0b", fg="#0f172a")
                else:
                    self.ser = serial.Serial(port_name, BAUD_RATE, timeout=0.15, write_timeout=1)
                    self.set_pill(self.status_label, "Connected", "#22c55e", fg="#0f172a")
                self.listener_stop_event = threading.Event()
                self.connect_button.setText("Disconnect")
                self.set_controls_enabled(True)
                self.listener_thread = threading.Thread(
                    target=listen_for_data,
                    args=(self.ser, self.signal_bridge, self.listener_stop_event),
                    daemon=True,
                    name="chopsaw-serial-listener",
                )
                self.listener_thread.start()
                self.log.append(f"Successfully connected to {port_name}")
                for command in self.active_controller().startup_commands():
                    self.send_command(command)
                if self.active_controller().capabilities.current_monitoring:
                    self.apply_current_protection_settings()
                self.update_current_monitor_ui()
            except serial.SerialException as e:
                self._stop_listener()
                self.set_controls_enabled(False)
                self.log.append(f"ERROR: {e}")
                self.refresh_serial_ports()
        else:
            self._stop_listener()
            self.set_pill(self.status_label, "Disconnected", "#ef4444")
            self.connect_button.setText("Connect")
            self.set_controls_enabled(False)
            self.log.append("Disconnected.")

    def _stop_listener(self):
        self.cycle_generation += 1
        self._simulation_pneumatic_pending = False
        # Stop before closing the serial port. The firmware watchdog is the
        # fallback if the port or process has already failed.
        if getattr(self, "carriage_tab", None) and self.carriage_tab.connected:
            if self.ser and self.ser.is_open:
                try:
                    self.ser.write(b"OFF\n")
                except (serial.SerialException, OSError):
                    pass
            self.carriage_tab.session(False)
        self.listener_stop_event.set()
        port = self.ser
        if port is not None and hasattr(port, "cancel_read"):
            try:
                port.cancel_read()
            except (serial.SerialException, OSError):
                pass
        thread = self.listener_thread
        if thread and thread.is_alive() and threading.current_thread() is not thread:
            thread.join(timeout=1.0)
        try:
            if port and port.is_open:
                port.close()
        except (serial.SerialException, OSError):
            pass
        self.listener_thread = None

    def handle_serial_disconnect(self, error):
        # Also fired by the listener thread after an intentional disconnect;
        # skip if the UI already reflects the disconnected state.
        if self.status_label.text() == "Disconnected":
            return
        self._stop_listener()
        self.set_pill(self.status_label, "Disconnected", "#ef4444")
        self.connect_button.setText("Connect")
        self.set_controls_enabled(False)
        self.log.append(f"Serial connection lost: {error}")

    def send_command(self, cmd):
        if (self.manual_pneumatics.motion_locked()
                and (cmd == 'H' or re.fullmatch(r'[SJN][+-]?[0-9.]+', cmd))):
            self.log.append('MOVE BLOCKED: release the manual clamp and return/release the saw first.')
            return False
        if self.active_controller().key == TEENSY_CARRIAGE:
            dry = self.dry_run
            stopping = cmd in ('OFF','XARM 0','XDISABLE','RESET','DOFF')
            if dry.sequence and not dry.issuing_sequence:
                if stopping:
                    dry.sequence=None; dry.pending=None; dry.message='Unloaded dry list stopped.'
                elif cmd not in ('HELLO','PINMAP','STATUS','PING','KEEPALIVE'):
                    self.log.append('BLOCKED: unloaded list owns machine sequencing.'); return False
            if (dry.motion_locked() and not dry.issuing_sequence and not stopping and
                    cmd not in ('HELLO','PINMAP','STATUS','PING','KEEPALIVE') and not DRY_COMMAND.fullmatch(cmd)):
                self.log.append('BLOCKED: unloaded pneumatics own machine control.'); return False
            if cmd=='XDISABLE' and dry.motion_locked():
                self.log.append('BLOCKED: stop the unloaded test before releasing motor holding.'); return False
            allowed = (dry.allowed(cmd) if DRY_COMMAND.fullmatch(cmd) or (cmd=='KEEPALIVE' and dry.data.get('ARMED')=='1')
                       else self.carriage_tab.allowed(cmd))
            if not allowed:
                self.log.append(f"BLOCKED in Teensy Carriage mode: {cmd}")
                return False
        if self.ser and self.ser.is_open:
            try:
                self.ser.write((cmd + '\n').encode('utf-8'))
                self.log.append(f"Sent: '{cmd}'")
                return True
            except (serial.SerialException, OSError) as error:
                self.handle_serial_disconnect(error)
                return False
        self.log.append("Cannot send command, not connected.")
        return False

    def active_controller(self):
        if isinstance(self.ser, VirtualController):
            return create_controller_backend(LEGACY_MEGA)
        return self.controller

    def send_backend_commands(self, commands, action="requested operation"):
        if not commands:
            self.log.append(
                f"UNSUPPORTED: {self.active_controller().label} cannot {action}."
            )
            return False
        sent_all = True
        for command in commands:
            sent_all = self.send_command(command) and sent_all
        return sent_all

    def home_motor(self):
        if self.active_controller().key == TEENSY_CARRIAGE:
            return self.carriage_tab.home()
        self.send_backend_commands(self.active_controller().home(), "home the carriage")
    def load_position(self):
        if self.active_controller().key == TEENSY_CARRIAGE:
            return self.carriage_tab.move_load_to(self.native_load_target())
        self.switch_profile("FAST", True)

        # The selected radio determines the load position; None means home position
        target_pos = self.home_position
        log_msg = f"Moving to HOME load position: {target_pos:.2f}\""
        for radio, _, load_pos in self.board_size_radios:
            if radio.isChecked() and load_pos is not None:
                target_pos = load_pos
                log_msg = f"Moving to short load position: {target_pos:.2f}\""
                break

        self.log.append(log_msg)
        self.set_length(target_pos)

    def native_load_target(self):
        for radio, _, load_pos in self.board_size_radios:
            if radio.isChecked() and load_pos is not None:
                return load_pos
        return int(self.carriage_tab.x.get("SOFT_MAX_MILLI","0"))/1000

    def toggle_motor_power(self, checked):
        if self.active_controller().key == TEENSY_CARRIAGE:
            if checked:
                self.send_command("XARM 1")
            else:
                self.carriage_tab.stop("XDISABLE")
            self.refresh_teensy_tabs()  # display readback, never an optimistic enable
            return
        self.send_backend_commands(
            self.active_controller().motor_power(checked), "change motor power"
        )

    def set_length(self, length):
        target = length
        if self.active_controller().key == TEENSY_CARRIAGE:
            return self.carriage_tab.move_to(target)

        # --- THIS IS THE GATEKEEPER CHECK ---
        if 0.0 <= target <= self.home_position:
            if self.send_backend_commands(
                self.active_controller().move_absolute_inches(target),
                "move the carriage",
            ):
                self.prepare_prediction(target)
        else:
            self.log.append(f"MOVE REJECTED: Target {target:.2f}\" is outside the valid range (0 to {self.home_position:.2f}\").")
    # AUTO jog helper: move by a relative delta from current position
    def auto_jog(self, delta):
        if self.active_controller().key == TEENSY_CARRIAGE:
            return self.carriage_tab.jog_distance(float(delta))
        target = self.current_position + float(delta)
        self.set_length(target)
    def toggle_current_settings(self, visible):
        if hasattr(self, 'current_settings_panel'):
            self.current_settings_panel.setVisible(visible)
        if hasattr(self, 'current_group'):
            target_height = self.current_card_expanded_height if visible else self.current_card_collapsed_height
            self.current_group.setMinimumHeight(target_height)
            self.current_group.setMaximumHeight(target_height)
        if hasattr(self, 'current_graph'):
            self.current_graph.setMinimumHeight(
                self.current_graph_expanded_min_height if visible else self.current_graph_collapsed_min_height
            )
        if hasattr(self, 'current_settings_toggle'):
            self.current_settings_toggle.setToolTip(
                "Hide current protection settings" if visible else "Show current protection settings"
            )
            self.current_settings_toggle.setChecked(visible)
    def update_current_monitor_ui(self):
        enabled = self.current_monitoring_enabled
        if hasattr(self, "current_limit_input"):
            self.current_limit_input.setEnabled(enabled)
        if hasattr(self, "current_delay_input"):
            self.current_delay_input.setEnabled(enabled)
        if hasattr(self, "apply_current_protection_btn"):
            self.apply_current_protection_btn.setText("Apply" if enabled else "Apply Off")
        if hasattr(self, "reset_overcurrent_btn"):
            self.reset_overcurrent_btn.setEnabled(enabled)
        if hasattr(self, "current_status_label") and not self.overcurrent_tripped:
            if enabled:
                self.set_pill(self.current_status_label, "Current OK", "#22c55e", fg="#0f172a")
            else:
                self.set_pill(self.current_status_label, "Monitoring Off", "#475569", fg="#e2e8f0")
        if not enabled:
            self.current_draw_amps = 0.0
            self.current_sensor_voltage = 0.0
            if hasattr(self, "current_value_label"):
                self.current_value_label.setText("0.00 A")
                self.current_value_label.setStyleSheet("font-size: 28px; font-weight: bold; color: #94a3b8;")

    def apply_current_protection_settings(self):
        self.current_monitoring_enabled = self.current_monitoring_checkbox.isChecked()
        self.current_limit_amps = self.current_limit_input.value()
        self.current_trip_delay_ms = int(self.current_delay_input.value())
        self.current_graph.set_limit(self.current_limit_amps)
        if not self.active_controller().capabilities.current_monitoring:
            self.current_monitoring_enabled = False
            self.current_monitoring_checkbox.setChecked(False)
            self.log.append(
                f"UNSUPPORTED: current monitoring is unavailable for {self.active_controller().label}."
            )
            self.update_current_monitor_ui()
            return
        self.send_backend_commands(
            self.active_controller().current_monitoring(self.current_monitoring_enabled),
            "change current monitoring",
        )
        if self.current_monitoring_enabled:
            self.send_backend_commands(
                self.active_controller().current_protection(
                    self.current_limit_amps, self.current_trip_delay_ms
                ),
                "configure current protection",
            )
        self.update_current_monitor_ui()

    def reset_overcurrent_trip(self):
        if not self.current_monitoring_enabled:
            return
        self.send_backend_commands(
            self.active_controller().reset_overcurrent(), "reset overcurrent protection"
        )
        self.update_overcurrent_status(0)
        if hasattr(self, "auto_status_label"):
            self._set_cycle_status("STATUS: Overcurrent reset requested.")

    # ---------- Profiles ----------
    def profile_setting_widgets(self):
        return {1:(self.gentle_speed,self.gentle_accel),2:(self.norm_speed,self.norm_accel),
                3:(self.fast_speed,self.fast_accel)}

    def mark_teensy_profile_edit(self, profile):
        if (self.active_controller().key == TEENSY_CARRIAGE and self._teensy_settings_snapshot is not None):
            self._teensy_settings_dirty.add(profile)
            self.refresh_teensy_tabs()

    def refresh_teensy_tabs(self, *_args):
        """Mirror one controller-owned state into Manual/Settings; never sends commands."""
        if not hasattr(self,"carriage_tab") or not hasattr(self,"settings_profile_combo"):
            return
        p = self.carriage_tab
        self.refresh_live_health()
        if self.active_controller().key != TEENSY_CARRIAGE:
            self.settings_profile_feedback.setText("Simulator profile values; apply the selected profile explicitly.")
            self.settings_profile_combo.setEnabled(True)
            self.apply_profile_btn.setEnabled(True)
            return

        link = p.ready_link()
        busy = bool(p.pending or p.profile_pending or p.homing or p.edge_searching or int(p.x.get("REMAINING","0")))
        self.manual_teensy_status.setText(p.status.text())
        self.manual_isolation.blockSignals(True)
        self.manual_isolation.setChecked(p.consent.isChecked())
        self.manual_isolation.blockSignals(False)
        self.manual_configure.setEnabled(p.allowed("XCONFIG 0 1"))
        self.manual_arm.setText("DISARM MANUAL CONTROL" if p.armed else "ARM MANUAL CONTROL")
        self.manual_arm.setEnabled(p.connected and (p.armed or p.allowed("XARM 1")))
        self.manual_home_button.setEnabled(p.home_button.isEnabled())
        self.manual_home_search.blockSignals(True)
        self.manual_home_search.setValue(p.home_search.value())
        self.manual_home_search.blockSignals(False)
        self.manual_home_search.setEnabled(not p.armed and not busy)
        self.manual_stop.setEnabled(p.connected)
        self.manual_reset.setEnabled(link and not p.armed)
        self.manual_release.setEnabled(p.connected and p.compatible)
        enabled = link and p.x.get("ENA") == "0"
        self.enable_chk.blockSignals(True)
        self.enable_chk.setChecked(enabled)
        self.enable_chk.blockSignals(False)
        self.enable_chk.setEnabled(link and (enabled or p.allowed("XARM 1")))
        known = link and p.x.get("POS_KNOWN") == "1" and not p.local_fault
        self.update_homed_status(1 if known else 0)
        if not known:
            self.position_label.setText("UNKNOWN")
        elif not busy:
            self.position_label.setText(f"{160.5+int(p.x['HOME_OFFSET'])/127.12:.4f}")
        self.state_label.setText("FAULT" if p.local_fault or p.x.get("FAULT","NONE") != "NONE" else
                                 "HOMING" if p.homing else "MOVING" if busy else "ARMED" if p.armed else "DISARMED")
        for name,label in (("HOME",self.sensor_label),("BOARD_EDGE",self.board_sensor_label)):
            raw=p.inputs.get(name) if p.fresh("INPUTS") else None
            self.set_pill(label,"UNKNOWN" if raw not in ("0","1") else "ON" if raw == "0" else "OFF",
                          "#334155" if raw not in ("0","1") else "#22c55e" if raw == "0" else "#ef4444")
            for mirror in ((self.auto_homing_sensor_label,getattr(self,'fa_homing_sensor_label',None)) if name == "HOME" else
                           (self.auto_board_sensor_label,getattr(self,'fa_board_sensor_label',None))):
                if mirror is not None:
                    self.set_pill(mirror,label.text(),"#334155" if raw not in ("0","1") else "#22c55e" if raw == "0" else "#ef4444")
            if name == "BOARD_EDGE": self.board_sensor_tripped = raw == "0"
        for name,label in self.auto_sensor_pills.items():
            raw=p.inputs.get(name) if p.fresh("INPUTS") else None
            if raw not in ("0","1"):
                text,color="UNKNOWN","#475569"
            elif name == "CL57T_ALM":
                text,color=("NORMAL","#22c55e") if raw == "1" else ("ALARM","#ef4444")
            elif name == "FENCE_DOOR":
                text,color=("CLOSED","#22c55e") if raw == "0" else ("OPEN","#ef4444")
            else:
                text,color=("ACTIVE","#22c55e") if raw == "0" else ("INACTIVE","#475569")
            self.set_pill(label,text,color)
        if self.dry_run.fresh():
            self.set_pill(self.auto_clamp_status_label,'ON COMMANDED' if self.dry_run.data.get('CLAMP')=='1' else 'OFF COMMANDED','#92400e' if self.dry_run.data.get('CLAMP')=='1' else '#475569')
        else:
            self.set_pill(self.auto_clamp_status_label,"UNKNOWN","#475569")
        if not known: self.auto_position_label.setText("UNKNOWN")
        elif not busy: self.auto_position_label.setText(self.position_label.text())
        saw=p.safety.get("SAW_POSITION","UNKNOWN") if p.fresh("SAFETY") else "UNKNOWN"
        self.set_pill(self.fa_saw_position_label,saw,"#22c55e" if saw == "UP" else "#ef4444" if saw == "CONFLICT" else "#475569")
        for label in (self.fa_outfeed_sensor_label,self.fa_fence_closed_label):
            self.set_pill(label,"UNKNOWN","#475569")  # uncommissioned inputs are not confirmed feedback
        self.auto_isolation.blockSignals(True)
        self.auto_isolation.setChecked(p.consent.isChecked()); self.auto_isolation.blockSignals(False)
        self.auto_configure.setEnabled(p.allowed("XCONFIG 0 1"))
        self.auto_home.setEnabled(p.home_button.isEnabled())
        self.auto_arm.setText("DISARM" if p.armed else "ARM")
        self.auto_arm.setEnabled(p.connected and (p.armed or p.allowed("XARM 1")))
        self.cancel_cycle_button.setEnabled(p.connected)
        self.start_cycle_button.setEnabled(False)
        self.fa_start_cycle_button.setEnabled(False)
        self.auto_status_label.setText("Cutting unavailable. Use the unloaded test above. " + p.status.text())
        self.load_button.setEnabled(p.allowed(f"XLOAD {int(self.native_load_target()*1000+0.5)}"))
        self.load_button.setToolTip("Uses stored FAST profile. Requires Home, explicit arm and a clear path.")
        jogs=((self.auto_jog_left_btn,self.auto_jog_input.value()),(self.auto_jog_right_btn,-self.auto_jog_input.value()),
              (self.qjog_left_01,0.1),(self.qjog_right_01,-0.1),(self.qjog_left_025,0.25),(self.qjog_right_025,-0.25),
              (self.qjog_left_1,1),(self.qjog_right_1,-1),(self.qjog_left_2,2),(self.qjog_right_2,-2))
        for button,delta in jogs:
            button.setEnabled(p.allowed(f"XJOG {1 if delta>0 else -1} {int(abs(delta)*127.12+0.5)}"))
            button.setToolTip("Toward Home" if delta>0 else "Toward saw")
        self.auto_jog_input.setEnabled(not busy)
        self.auto_jog_left_btn.setText("Home")
        self.auto_jog_right_btn.setText("Saw")
        for radio,_,_ in self.board_size_radios: radio.setEnabled(not busy)
        self.keypad.setEnabled(known and not busy)

        edit = link and not p.armed and not busy
        if not link:
            self._teensy_settings_snapshot = None
            self._teensy_settings_active = None
            self._teensy_settings_dirty.clear()
        else:
            initial = self._teensy_settings_snapshot is None
            for profile,widgets in self.profile_setting_widgets().items():
                actual = p.profile_values[profile]
                draft = tuple(int(widget.value()) for widget in widgets)
                if draft == actual:
                    self._teensy_settings_dirty.discard(profile)
                if initial or profile not in self._teensy_settings_dirty:
                    for widget,value in zip(widgets,actual):
                        widget.blockSignals(True); widget.setValue(value); widget.blockSignals(False)
            self._teensy_settings_snapshot = dict(p.profile_values)
            active=int(p.x["PROFILE_ID"])
            if active != self._teensy_settings_active:
                self._teensy_settings_active=active
                if active in (1,2,3):
                    name={1:"GENTLE",2:"NORMAL",3:"FAST"}[active]
                    self.settings_profile_combo.blockSignals(True)
                    self.settings_profile_combo.setCurrentIndex(self.settings_profile_combo.findData(name))
                    self.settings_profile_combo.blockSignals(False)
        for widgets in self.profile_setting_widgets().values():
            for widget in widgets: widget.setEnabled(edit)
        self.settings_profile_combo.setEnabled(edit)
        profile={"GENTLE":1,"NORMAL":2,"FAST":3}[self.settings_profile_combo.currentData()]
        rate,accel=(int(widget.value()) for widget in self.profile_setting_widgets()[profile])
        self.apply_profile_btn.setEnabled(p.allowed(f"XPROFILE {profile} {rate} {accel}"))
        selected=p.profile_values[profile]
        note = ("Waiting for fresh compatible controller feedback" if not link else
                f"Controller active: {self.active_profile_name}; selected profile readback: {selected[0]} pulses/s, "
                f"{selected[1]} pulses/s^2. " + ("UNAPPLIED EDITS. " if self._teensy_settings_dirty else "") +
                ("Waiting for parameter acknowledgment. " if p.profile_pending else ""))
        self.settings_profile_feedback.setText(note+f"Motion status: {p.status.text()}. "
                                              "Disarm to apply. Values are controller RAM settings and reset on reboot.")

    def update_teensy_profile(self, profile):
        self.active_profile_name = {0:"COMMISSIONING",1:"GENTLE",2:"NORMAL",3:"FAST"}.get(profile,"COMMISSIONING")

    def switch_profile(self, name, push_params=True):
        if self.active_controller().key == TEENSY_CARRIAGE:
            profile = {"COMMISSIONING":0,"GENTLE":1,"NORMAL":2,"FAST":3}.get(name)
            return False if profile is None else self.carriage_tab.select_profile(profile)
        if name not in PROFILE_MAP: self.log.append(f"Unknown profile '{name}'"); return
        idx = PROFILE_MAP[name]
        if not self.send_backend_commands(
            self.active_controller().profile_select(idx), "select a motion profile"
        ):
            return
        self.active_profile_name = name
        if push_params:
            if name == "NORMAL": spd, acc = self.norm_speed.value(), self.norm_accel.value()
            elif name == "GENTLE": spd, acc = self.gentle_speed.value(), self.gentle_accel.value()
            else: spd, acc = self.fast_speed.value(), self.fast_accel.value()
            self.send_backend_commands(
                self.active_controller().set_motor_parameters(spd, acc),
                "set motion profile parameters",
            )
            self.log.append(f"Applied {name} profile params: speed={spd:.0f}, accel={acc:.0f}")
    def apply_current_profile_params(self):
        name=self.settings_profile_combo.currentData()
        if self.active_controller().key == TEENSY_CARRIAGE:
            profile={"GENTLE":1,"NORMAL":2,"FAST":3}[name]
            rate,accel=(widget.value() for widget in self.profile_setting_widgets()[profile])
            return self.carriage_tab.edit_profile(profile,rate,accel)
        return self.switch_profile(name, True)

    # ---------- Position updates ----------
    def update_message_log(self, msg):
        if self.active_controller().key == TEENSY_CARRIAGE:
            self.carriage_tab.handle_line(msg)
            self.dry_run.handle(msg)
        elif isinstance(self.ser, VirtualController) and self.is_connected() and msg.startswith("POS:"):
            self.refresh_live_health()  # establish this connection's session before storing data
            self._sim_health_fields = dict(part.split(":", 1) for part in msg.split(",") if ":" in part)
            self._sim_health_received = time.monotonic()
            if simulator_data_valid(self._sim_health_fields):
                self._sim_activity_received = self._sim_health_received
            self.refresh_live_health()
        self.log.append(msg)
        if hasattr(self, "speed_serial_console"):
            self.speed_serial_console.append(msg)
    def refresh_live_health(self):
        """Display-only: cannot configure, arm, acknowledge or move hardware."""
        if not hasattr(self, "carriage_tab"):
            return
        now = time.monotonic()
        mode = "sim" if isinstance(self.ser, VirtualController) else self.active_controller().key
        connected = self.is_connected()
        session = (self.ser, mode, connected)
        if session != self._health_session:
            self._health_session = session
            self._health_started = now
            self._sim_health_fields = {}
            self._sim_health_received = self._sim_activity_received = None
            self._health_activity = TelemetryActivity()
        receipt = None
        if mode == TEENSY_CARRIAGE:
            p = self.carriage_tab
            state = native_health(connected=connected and p.connected, compatible=p.compatible,
                                  records={"X":p.x, "SAFETY":p.safety, "INPUTS":p.inputs},
                                  received=p.received, started=self._health_started, now=now,
                                  local_fault=p.local_fault or self.dry_run.local_fault, stale_seconds=p.stale_seconds,
                                  allow_saw_travel=self.dry_run.fresh() and self.dry_run.data.get('STATE') in DRY_TRAVEL)
            receipt = p.received.get("X") if connected and p.connected and p.compatible else None
        elif mode == "sim":
            state = simulator_health(connected=connected, fields=self._sim_health_fields,
                                     received=self._sim_health_received, started=self._health_started, now=now)
            receipt = self._sim_activity_received if connected else None
        else:
            state = HealthState("neutral", "Health unavailable in this mode")
        color = {"healthy":"#22c55e", "fault":"#ef4444", "neutral":"#64748b"}[state.level]
        if self.auto_live_status.property("healthState") != state.level:
            self.auto_live_status.setProperty("healthState", state.level)
            self.auto_live_status.setStyleSheet(f"QGroupBox#autoLiveStatus {{ border: 2px solid {color}; }}")
            self.live_health_label.setStyleSheet(f"color:{color}; font-size:13px; font-weight:600;")
        self.live_health_label.setText(state.text)
        self.live_health_label.setToolTip("\n".join(state.details) or state.text)
        self.auto_live_status.setAccessibleDescription(state.text)
        intensity = round(self._health_activity.update(receipt, now) * 255)
        if self.live_health_dot.property("intensity") != intensity:
            self.live_health_dot.setProperty("intensity", intensity)
            self.live_health_dot.setProperty("active", intensity > 0)
            channels = [round(dim + (bright-dim)*intensity/255)
                        for dim,bright in zip((51,65,85), (56,189,248))]
            self.live_health_dot.setStyleSheet(f"background:rgb({channels[0]},{channels[1]},{channels[2]}); border-radius:5px;")

    def update_position_label_from_device(self, pos):
        self.current_position = pos
        self.position_label.setText(f"{pos:.4f}")
        self.auto_position_label.setText(f"{pos:.4f}")
        if hasattr(self, 'fa_position_label'):
            self.fa_position_label.setText(f"{pos:.4f}")
        self._sim_track_carriage(pos)
        if self.pred_active: self.pred_start_pos = pos; self.pred_start_time = time.monotonic()

    def update_homed_status(self, status):
        text = "HOMED" if status == 1 else "NOT HOMED"; color = "#22c55e" if status == 1 else "orange"
        self.homed_label.setText(text); self.homed_label.setStyleSheet(f"color: {color}; font-weight: bold;")

    def update_motor_state(self, state):
        if isinstance(self.ser, VirtualController):
            self.enable_chk.blockSignals(True)
            self.enable_chk.setChecked(self.ser.motor_enabled)
            self.enable_chk.blockSignals(False)
        self.current_motor_state = state
        previous_motor_state = self.state_label.text()
        self.state_label.setText(state)
        color = {"IDLE": "#22c55e", "MOVING": "#60a5fa", "HOMING": "#60a5fa", "DETECTING": "#60a5fa", "OVERCURRENT": "#ef4444"}.get(state, "#a78bfa")
        self.state_label.setStyleSheet(f"color: {color}; font-weight: bold;")
        if state == "OVERCURRENT":
            self.update_overcurrent_status(1)
        
        if state != "MOVING":
            self.pred_active = False

        if state == "IDLE" and previous_motor_state in ["MOVING", "DETECTING"]:
            if self.perform_early_return:
                # Last cut on this board — cut happens while the carriage returns.
                self.perform_early_return = False
                self.is_early_returning = True

                if self.auto_clamp_enabled:
                    self._engage_clamps_for_cut(early_return=True)  # clamps + sensor-gated release
                else:
                    # Manual mode: book the cut for the animation, no hardware commands
                    self._record_sim_piece(early_return=True, is_truing=False)
                    if self.sim_active_piece is not None:
                        self._on_cut_finished()

                if self.current_cut_index < len(self.cut_list):
                    self.current_cut_index += 1
                self.update_cut_list_display()

                self.load_position()
                return

            elif self.is_early_returning:
                self.is_early_returning = False

                if self.current_cut_index >= len(self.cut_list):
                    self.auto_cycle_state = "FINISHED"
                    self._set_cycle_status("STATUS: Cycle Complete!")
                else:
                    self.auto_cycle_state = "WAITING_FOR_NEW_BOARD"
                    self._set_cycle_status("STATUS: Board empty. Load new board.")

                self._set_start_enabled(True)
                self._set_cut_complete_enabled(False)

            elif self.auto_cycle_state in ["WAITING_FOR_TRUING_CUT", "WAITING_FOR_CUT"]:
                self._set_cut_complete_enabled(True)
                if self.auto_clamp_enabled:
                    self._engage_clamps_for_cut()
                else:
                    # Manual mode: just record the piece; CUT COMPLETE books it
                    is_truing = self.auto_cycle_state == "WAITING_FOR_TRUING_CUT"
                    self._record_sim_piece(early_return=False, is_truing=is_truing)
                    self._set_cycle_status("STATUS: Simulation in position; awaiting simulated completion.")

    def update_sensor_status(self, status):
        text = "ON" if status == 1 else "OFF"; bg = "#22c55e" if status == 1 else "#ef4444"
        for widget in (self.sensor_label, self.auto_homing_sensor_label,
                       getattr(self, 'fa_homing_sensor_label', None)):
            if widget is not None:
                self.set_pill(widget, text, bg)

    def update_board_sensor_status(self, status):
        text = "ON" if status == 1 else "OFF"; bg = "#22c55e" if status == 1 else "#ef4444"
        self.board_sensor_tripped = (status == 1)
        for widget in (self.board_sensor_label, self.auto_board_sensor_label,
                       getattr(self, 'fa_board_sensor_label', None)):
            if widget is not None:
                self.set_pill(widget, text, bg)
        if hasattr(self, 'saw_sim'):
            self.saw_sim.set_board_sensor(status == 1)

    def update_current_voltage(self, volts):
        self.current_sensor_voltage = max(0.0, volts)

    def append_current_log_row(self):
        now = time.monotonic()
        if now - self.last_current_log_time < 0.25:
            return
        self.last_current_log_time = now

        log_exists = os.path.exists(self.current_log_path)
        # Roll the log when it grows past ~5 MB so it can't fill the disk
        if log_exists:
            try:
                if os.path.getsize(self.current_log_path) > 5_000_000:
                    os.replace(self.current_log_path, self.current_log_path + ".old")
                    log_exists = False
            except OSError:
                pass
        row = (
            f"{datetime.now().isoformat(timespec='seconds')},"
            f"{self.current_sensor_voltage:.4f},"
            f"{self.current_draw_amps:.4f},"
            f"{self.current_limit_amps:.2f},"
            f"{self.current_trip_delay_ms},"
            f"{int(self.overcurrent_tripped)},"
            f"{self.current_motor_state}\n"
        )
        try:
            with open(self.current_log_path, "a", encoding="utf-8") as f:
                if not log_exists:
                    f.write("timestamp,a2_voltage,current_amps,current_limit_amps,trip_delay_ms,overcurrent_tripped,motor_state\n")
                f.write(row)
        except Exception as exc:
            if hasattr(self, "log"):
                self.log.append(f"Current log write failed: {exc}")

    def update_current_draw(self, amps):
        if not self.current_monitoring_enabled:
            return
        self.current_draw_amps = max(0.0, amps)
        if hasattr(self, 'current_value_label'):
            color = "#ef4444" if self.current_draw_amps > self.current_limit_amps else "#22c55e"
            self.current_value_label.setText(f"{self.current_draw_amps:.2f} A")
            self.current_value_label.setStyleSheet(f"font-size: 28px; font-weight: bold; color: {color};")
        if hasattr(self, 'current_graph'):
            self.current_graph.push_sample(self.current_draw_amps)
        self.append_current_log_row()

    def update_overcurrent_status(self, status):
        if not self.current_monitoring_enabled:
            self.overcurrent_tripped = False
            self.update_current_monitor_ui()
            return
        self.overcurrent_tripped = (status == 1)
        if hasattr(self, 'current_status_label'):
            if self.overcurrent_tripped:
                self.set_pill(self.current_status_label, "Overcurrent Tripped", "#ef4444")
                if hasattr(self, 'auto_status_label'):
                    self._set_cycle_status("STATUS: Overcurrent protection tripped.")
            else:
                self.set_pill(self.current_status_label, "Current OK", "#22c55e", fg="#0f172a")

    def update_calibration_factors(self, new_encoder_tpi, new_stepper_spi):
        self.encoder_ticks_per_inch = new_encoder_tpi; self.stepper_steps_per_inch = new_stepper_spi; self.log.append("HMI calibration factors updated.")

    def update_home_position(self, pos):
        self.home_position = pos
        self.log.append(f"Max travel distance set to: {pos}\"")
        try:
            if hasattr(self, 'board_sensor_location_input') and self.board_sensor_location_input is not None:
                self.board_sensor_location_input.setRange(0, pos)
                
            if hasattr(self, 'load_button') and self.load_button is not None:
                self.load_button.setText(f"LOAD POSITION ({pos:.2f}\")")

            if hasattr(self, 'saw_sim'):
                self.saw_sim.set_home_position(pos)
                
        except Exception as e:
            print("update_home_position guarded:", e)

    # ---------- Prediction model ----------
    def prepare_prediction(self, target_in):
        start_in = self.current_position
        self.pred_start_pos = start_in; self.pred_target_pos = target_in; self.pred_dir = 1.0 if (target_in - start_in) >= 0 else -1.0
        if self.active_profile_name == "NORMAL": spd_steps, acc_steps = self.norm_speed.value(), self.norm_accel.value()
        elif self.active_profile_name == "GENTLE": spd_steps, acc_steps = self.gentle_speed.value(), self.gentle_accel.value()
        else: spd_steps, acc_steps = self.fast_speed.value(), self.fast_accel.value()
        if self.stepper_steps_per_inch <= 0: self.pred_vmax_in = 0.0; self.pred_acc_in = 0.0
        else:
            self.pred_vmax_in = float(spd_steps) / self.stepper_steps_per_inch
            self.pred_acc_in  = float(acc_steps) / self.stepper_steps_per_inch
        self.pred_start_time = time.monotonic(); self.pred_active = True
        if not self.pred_timer.isActive(): self.pred_timer.start()

    def tick_predict(self):
        if not self.pred_active: return
        now = time.monotonic(); t = now - self.pred_start_time
        s0 = self.pred_start_pos; sf = self.pred_target_pos; D = abs(sf - s0)
        if D < 1e-6 or self.pred_vmax_in <= 0 or self.pred_acc_in <= 0: self.pred_active = False; return
        a = self.pred_acc_in; v = self.pred_vmax_in
        t_acc = v / a; d_acc = 0.5 * a * t_acc * t_acc
        if 2*d_acc < D:
            d_cruise = D - 2*d_acc; t_cruise = d_cruise / v
            if t <= t_acc: s = 0.5*a*t*t
            elif t <= t_acc + t_cruise: s = d_acc + v*(t - t_acc)
            else:
                td = t - (t_acc + t_cruise)
                if td >= t_acc: s = D; self.pred_active = False
                else: s = d_acc + d_cruise + (v*td - 0.5*a*td*td)
        else:
            t_acc_tri = sqrt(D / a)
            if t <= t_acc_tri: s = 0.5 * a * t * t
            else:
                td = t - t_acc_tri
                if td >= t_acc_tri: s = D; self.pred_active = False
                else:
                    v_peak = a * t_acc_tri
                    s = 0.5*a*t_acc_tri*t_acc_tri + (v_peak*td - 0.5*a*td*td)
        pos = s0 + self.pred_dir * s
        if (self.pred_dir > 0 and pos > sf) or (self.pred_dir < 0 and pos < sf): pos = sf; self.pred_active = False
        self.position_label.setText(f"{pos:.4f}"); self.auto_position_label.setText(f"{pos:.4f}")
        if hasattr(self, 'fa_position_label'): self.fa_position_label.setText(f"{pos:.4f}")
        self._sim_track_carriage(pos)

    # ---------- Settings persistence ----------
    def _settings_widgets(self):
        """Spin boxes whose values persist across sessions, keyed for QSettings."""
        return {
            "norm_speed": self.norm_speed,
            "norm_accel": self.norm_accel,
            "gentle_speed": self.gentle_speed,
            "gentle_accel": self.gentle_accel,
            "fast_speed": self.fast_speed,
            "fast_accel": self.fast_accel,
            "kerf": self.kerf_input,
            "cut_length": self.cut_length_input,
            "board_sensor_location": self.board_sensor_location_input,
            "current_limit": self.current_limit_input,
            "current_trip_delay": self.current_delay_input,
        }

    def _load_settings(self):
        self.cylinder_timing.load()
        self.cut_length_keypad_checkbox.setChecked(self.settings.value("cut_length_keypad", False, type=bool))
        for key, widget in self._settings_widgets().items():
            value = self.settings.value(key)
            if value is not None:
                try:
                    widget.setValue(type(widget.value())(value))
                except (TypeError, ValueError):
                    pass
        self.current_monitoring_enabled = self.settings.value("current_monitoring", False, type=bool)
        self.current_monitoring_checkbox.setChecked(self.current_monitoring_enabled)
        self.current_limit_amps = self.current_limit_input.value()
        self.current_trip_delay_ms = int(self.current_delay_input.value())
        self.current_graph.set_limit(self.current_limit_amps)
        # Default OFF: stay firmware-compatible unless explicitly enabled before
        self.auto_clamp_enabled = self.settings.value("auto_clamp_enabled", False, type=bool)
        self.auto_clamp_checkbox.setChecked(self.auto_clamp_enabled)

    def _save_settings(self):
        self.cylinder_timing.save()
        for key, widget in self._settings_widgets().items():
            if self.active_controller().key == TEENSY_CARRIAGE and key in {
                "norm_speed","norm_accel","gentle_speed","gentle_accel","fast_speed","fast_accel"
            }:
                continue  # live Teensy RAM readbacks must not overwrite archived simulator settings
            self.settings.setValue(key, widget.value())
        self.settings.setValue("current_monitoring", self.current_monitoring_checkbox.isChecked())
        self.settings.setValue("auto_clamp_enabled", self.auto_clamp_checkbox.isChecked())
        self.settings.setValue("cut_length_keypad", self.cut_length_keypad_checkbox.isChecked())
        self.settings.setValue("serial_port", self.selected_serial_port)
        self.settings.setValue("controller_mode", self.selected_controller_mode)

    # ---------- Software updates ----------
    def _on_update_found(self, info):
        self._pending_update = info
        notes = info.get("notes", "")
        first_line = notes.splitlines()[0] if notes else ""
        text = f"Update v{info.get('version')} is available"
        if first_line:
            text += f" — {first_line}"
        self.update_banner_label.setText(text)
        self.update_banner.setVisible(True)

    def check_updates_manual(self):
        self.check_updates_btn.setEnabled(False)
        self.check_updates_btn.setText("Checking…")
        QApplication.processEvents()
        try:
            info = updater.check_for_update()
        except Exception:
            info = None
        self.check_updates_btn.setEnabled(True)
        self.check_updates_btn.setText("Check for Updates")

        if info:
            self._on_update_found(info)
            QMessageBox.information(
                self, "Update Available",
                f"Version {info.get('version')} is available.\n\n"
                "Use the banner at the top to install and restart.")
        else:
            # Distinguish "offline / error" from "genuinely up to date", and
            # surface the real error so it can be diagnosed from the field.
            error_detail = None
            try:
                updater._http_get(updater.API_LATEST, updater.DEFAULT_TIMEOUT)
            except Exception as exc:
                error_detail = f"{type(exc).__name__}: {exc}"
            if error_detail is None:
                QMessageBox.information(
                    self, "Up to Date",
                    f"You are running the latest version (v{APP_VERSION}).")
            else:
                QMessageBox.warning(
                    self, "Update Check Failed",
                    "Could not reach the update server.\n\n"
                    f"Update source:\n{updater.API_LATEST}\n\n"
                    f"Details:\n{error_detail}\n\n"
                    "Check the internet connection / firewall and try again.")

    def _install_update(self):
        info = self._pending_update
        if not info:
            QMessageBox.warning(self, "No Update", "No pending update to install.")
            return
        if not getattr(sys, "frozen", False):
            QMessageBox.information(
                self, "Developer Mode",
                "Updates can only be installed from the packaged .exe, "
                "not when running from source.")
            return

        # Download with a modal progress dialog
        self._update_dialog = QProgressDialog(
            "Downloading update…", "Cancel", 0, 100, self)
        self._update_dialog.setWindowTitle("Updating")
        self._update_dialog.setMinimumDuration(0)
        self._update_dialog.setValue(0)

        self._downloader = _UpdateDownloader(info, self)
        self._downloader.progress.connect(self._on_download_progress)
        self._downloader.finished_path.connect(self._on_download_finished)
        self._update_dialog.canceled.connect(self._downloader.requestInterruption)
        self.update_install_btn.setEnabled(False)
        self._downloader.start()

    def _on_download_progress(self, downloaded, total):
        if self._update_dialog and total > 0:
            self._update_dialog.setValue(int(downloaded * 100 / total))

    def _on_download_finished(self, path):
        if self._update_dialog:
            self._update_dialog.close()
            self._update_dialog = None
        self.update_install_btn.setEnabled(True)

        if not path:
            QMessageBox.critical(
                self, "Update Failed",
                "The update could not be downloaded or failed its integrity "
                "check. Please try again later.")
            return

        self._downloaded_exe = path
        if not updater.schedule_update(path):
            QMessageBox.critical(
                self, "Update Failed",
                "Could not schedule the update install.")
            return
        QMessageBox.information(
            self, "Restarting",
            "The update has been downloaded. The app will now close and "
            "restart on the new version.")
        self.close()

    def closeEvent(self, event):
        self.health_timer.stop()
        self.manual_pneumatics.timer.stop()
        self.dry_run.timer.stop()
        self._save_settings()
        self._stop_listener()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    icon_path = get_icon_path()
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    window = MinimalHMI()
    window.show()
    sys.exit(app.exec())
