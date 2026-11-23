# main.py

from collections import deque
from contextlib import contextmanager
import os
import re
import sys
import threading
import time

import serial
import serial.tools.list_ports
from PyQt6.QtCore import QSettings, Qt, QTimer
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from _version import __version__ as APP_VERSION
from config import (
    BAUD_RATE,
    HOME_POSITION_INCHES,
    PROFILE_MAP,
    SERIAL_PORT,
    STEPS_PER_INCH,
    TEENSY_PROFILE_MAP,
)
from controller_backends import (
    CONTROLLER_MODES,
    LEGACY_MEGA,
    TEENSY_CARRIAGE,
    create_controller_backend,
)
from cut_history import CutHistory
from cut_list_parser import (
    GROUP_COLORS,
    group_cuts_by_board,
    parse_cut_list_lines,
    render_cut_list_html,
)
from cutlist_manager import CutListManagerTab
from direct_controls import DirectControls
from dry_run_control import (
    COMMAND as DRY_COMMAND,
    NativeDryRun,
    SECOND_COMMAND,
    TRAVEL as DRY_TRAVEL,
)
from full_auto_live import refresh_full_auto
from hmi_tabs import (
    APP_STYLESHEET,
    build_auto_tab,
    build_legacy_full_auto_tab,
    build_manual_tab,
    build_settings_tab,
)
from live_health import (
    HealthState,
    TelemetryActivity,
    native_health,
    simulator_data_valid,
    simulator_health,
)
from machine_workbench import MachineWorkbench
from sequence_state import SequenceStage
from serial_handler import SignalBridge, listen_for_data
from sim_cycle import SimulatorCycleMixin
from simulator import VirtualController
from teensy_carriage import TeensyCarriagePanel
import updater
from update_manager import UpdateManager
from wheel_guard import install_wheel_guard

_TEENSY_PROFILE_NAMES = {idx: name for name, idx in TEENSY_PROFILE_MAP.items()}


class _MemoryLog:
    """Lightweight ring buffer replacing the hidden QTextBrowser log."""

    def __init__(self, maxlen=500):
        self._lines = deque(maxlen=maxlen)

    def append(self, text):
        self._lines.append(str(text))

    def toPlainText(self):
        return "\n".join(self._lines)


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
class MinimalHMI(SimulatorCycleMixin, QMainWindow):
    def __init__(self):
        super().__init__()
        install_wheel_guard()
        icon_path = get_icon_path()
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.setWindowTitle(f"Chop Saw HMI — Profiles & Touch UI  (v{APP_VERSION})")
        self.resize(1280, 900)
        self._pending_update = None
        self._downloaded_exe = None
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
        self.stepper_steps_per_inch = STEPS_PER_INCH
        self.encoder_ticks_per_inch = self.stepper_steps_per_inch * 20.0
        self.cut_list = []
        self.auto_cycle_state = "IDLE"
        self.cycle_generation = 0  # invalidates delayed clamp/saw callbacks
        self.next_cut_number = 1
        # Last position reported by the device. Cycle logic reads this,
        # never the UI labels (which can show interpolated predictions).
        self.current_position = 0.0

        self.home_position = HOME_POSITION_INCHES
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
        self._legacy_cut_completion_ready = False  # simulator harness only
        self.clamp_engaged = False
        self.clamp_left_engaged = False
        self.clamp_right_engaged = False
        self.clamps_engaged_cutting = False
        self.auto_clamp_enabled = False

        # Simulator line-view state
        self.sim_board_remaining = None
        self.sim_board_trimmed = False
        self.sim_edge_pos = 0.0
        self.sim_active_piece = None
        self.sim_next_piece_index = 0
        self._last_saw_sensor = None

        self.current_cut_index = 0
        self.perform_early_return = False
        self.pending_early_return = False
        self.is_early_returning = False
        self.board_sensor_tripped = False
        self.current_draw_amps = 0.0
        self.current_limit_amps = 2.5
        self.current_trip_delay_ms = 150
        self.current_monitoring_enabled = False
        self.overcurrent_tripped = False
        self.current_sensor_voltage = 0.0
        self.current_motor_state = "IDLE"
        self.current_log_path = os.path.join(get_app_dir(), "motor_current_log.csv")
        self.cut_history = CutHistory(get_app_dir(), APP_VERSION)
        self.last_current_log_time = 0.0
        self.settings = QSettings("ChopSawHMI", "ChopSawHMI")
        self.selected_serial_port = self.settings.value("serial_port", SERIAL_PORT)
        self.selected_controller_mode = self.settings.value("controller_mode", TEENSY_CARRIAGE)
        self.controller = create_controller_backend(self.selected_controller_mode)

        # Simulator motion prediction
        self.pred_timer = QTimer(self)
        self.pred_timer.setInterval(30)
        self.pred_timer.timeout.connect(self.tick_predict)
        self.pred_active = False
        self.pred_start_time = 0.0
        self.pred_start_pos = 0.0
        self.pred_target_pos = 0.0
        self.pred_vmax_in = 0.0
        self.pred_acc_in = 0.0
        self.pred_dir = 1.0

        self._health_session = None
        self._health_started = time.monotonic()
        self._sim_health_fields = {}
        self._sim_health_received = self._sim_activity_received = None
        self._health_activity = TelemetryActivity()
        self._ui_batch_depth = 0
        self._ui_dirty_teensy = False
        self._ui_dirty_dry = False

        self.update_manager = UpdateManager(self, updater, APP_VERSION)
        self.dry_run = NativeDryRun(self)
        self.direct_controls = DirectControls(self)
        self.init_ui()
        self.apply_theme()
        self._load_settings()
        self.update_current_monitor_ui()

        self.health_timer = QTimer(self)
        self.health_timer.setInterval(100)
        self.health_timer.timeout.connect(self.refresh_live_health)
        self.health_timer.start()
        self.refresh_live_health()

        self.update_manager.schedule_startup_check()
        self._update_checker = self.update_manager.startup_checker

    # ---------- Theme & Pills ----------
    def apply_theme(self):
        self.setStyleSheet(APP_STYLESHEET)

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
        if widget.text() != text:
            widget.setText(text)
        style = f"background-color:{bg}; color:{fg}; font-weight:bold; border-radius:10px; padding:4px 8px;"
        if widget.styleSheet() != style:
            widget.setStyleSheet(style)

    # ---------- UI Construction ----------
    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # Top connection bar
        top = QHBoxLayout()
        top.addWidget(QLabel("Controller:"))
        self.controller_combo = QComboBox()
        self.controller_combo.setMinimumWidth(190)
        self.controller_combo.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        for mode in CONTROLLER_MODES:
            self.controller_combo.addItem(mode.label, mode.key)
        controller_index = self.controller_combo.findData(self.selected_controller_mode)
        if controller_index < 0:
            controller_index = self.controller_combo.findData(TEENSY_CARRIAGE)
        if controller_index >= 0:
            self.controller_combo.setCurrentIndex(controller_index)
            self.selected_controller_mode = self.controller_combo.currentData() or TEENSY_CARRIAGE
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

        self.connect_button = QPushButton("Connect")
        self.connect_button.setProperty("class", "accent")
        self.connect_button.clicked.connect(self.toggle_connection)
        self.status_label = self.pill("Disconnected", "#ef4444")
        self.status_label.setMinimumWidth(120)
        top.addWidget(self.connect_button)
        top.addWidget(self.status_label)
        top.addStretch()
        root.addLayout(top)
        self.refresh_serial_ports()

        # Update banner
        self.update_banner = self.update_manager.build_banner()
        self.update_banner_label = self.update_manager.banner_label
        self.update_install_btn = self.update_manager.install_btn
        self.update_later_btn = self.update_manager.later_btn
        root.addWidget(self.update_banner)

        # Tabs
        self.tabs = QTabWidget()
        root.addWidget(self.tabs)
        self.legacy_tab = self.create_legacy_tab()
        self.auto_tab = self.create_auto_tab()
        self.speed_tab = self.create_speed_tab()
        self.full_auto_tab = self.create_full_auto_tab()
        self.preset_tab = self.create_preset_tab()

        self.carriage_tab = TeensyCarriagePanel(
            self.send_command, lambda line: self.log.append(line), self
        )
        self.carriage_tab.home_preferences = self.saved_homing_settings
        self.carriage_tab.profile_changed.connect(self.update_teensy_profile)
        self.carriage_tab.profile_parameters_confirmed.connect(self.save_confirmed_profile)
        self.carriage_tab.homed_changed.connect(self.update_homed_status)
        self.carriage_tab.machine_position_changed.connect(self.update_position_label_from_device)
        self._teensy_settings_dirty = set()
        self._teensy_settings_snapshot = None
        self._teensy_settings_active = None
        self.carriage_tab.state_changed.connect(self._on_carriage_state_changed)
        for profile, widgets in self.profile_setting_widgets().items():
            for widget in widgets:
                widget.valueChanged.connect(
                    lambda _value, p=profile: self.mark_teensy_profile_edit(p)
                )
        self.auto_jog_input.valueChanged.connect(self.refresh_teensy_tabs)
        for radio, _, _ in self.board_size_radios:
            radio.toggled.connect(self.refresh_teensy_tabs)

        self.tabs.addTab(self.carriage_tab, "CARRIAGE")
        self.tabs.addTab(self.legacy_tab, "MANUAL / SIM")
        self.tabs.addTab(self.auto_tab, "AUTO")
        self.tabs.currentChanged.connect(
            lambda _index: (
                self.cut_length_keypad.hide()
                if self.tabs.currentWidget() is not self.auto_tab
                else None
            )
        )
        self.tabs.addTab(self.full_auto_tab, "FULL AUTO")
        self.tabs.addTab(self.speed_tab, "SETTINGS")
        self.tabs.addTab(self.preset_tab, "CUT LISTS")

        self.log = _MemoryLog(maxlen=500)
        self.manual_pneumatics.state_changed.connect(self.refresh_manual_motion_locks)
        self.dry_run.changed.connect(self._on_dry_run_changed)
        self.cut_history_warning = QLabel()
        self.cut_history_warning.setWordWrap(True)
        self.cut_history_warning.setStyleSheet('color:#fbbf24;padding:4px;')
        self.cut_history_warning.hide()
        root.addWidget(self.cut_history_warning)
        self.set_controls_enabled(False)
        self.update_clamp_ui()

    def create_legacy_tab(self):
        return build_manual_tab(self)

    def create_auto_tab(self):
        return build_auto_tab(self)

    def create_speed_tab(self):
        return build_settings_tab(self)

    def create_preset_tab(self):
        storage_path = os.path.join(get_app_dir(), "cutlists.json")
        return CutListManagerTab(
            storage_path=storage_path,
            on_load_lines=self.load_cut_list_lines,
            on_switch_to_auto=lambda: self.tabs.setCurrentWidget(self.auto_tab),
            log_fn=lambda msg: self.log.append(msg),
        )

    def create_full_auto_tab(self):
        self.full_auto_legacy = self.create_legacy_full_auto_tab()
        self.machine_workbench = MachineWorkbench(self, self.full_auto_legacy)
        return self.machine_workbench

    def create_legacy_full_auto_tab(self):
        return build_legacy_full_auto_tab(self)

    # ---------- Coalesced UI Refresh ----------
    @contextmanager
    def _batch_ui_refresh(self):
        self._ui_batch_depth += 1
        try:
            yield
        finally:
            self._ui_batch_depth -= 1
            if self._ui_batch_depth == 0:
                dry_dirty = self._ui_dirty_dry
                teensy_dirty = self._ui_dirty_teensy
                self._ui_dirty_dry = False
                self._ui_dirty_teensy = False
                if dry_dirty:
                    self._flush_dry_run_ui()
                elif teensy_dirty:
                    self.refresh_teensy_tabs()

    def _on_carriage_state_changed(self):
        if self._ui_batch_depth > 0:
            self._ui_dirty_teensy = True
            return
        self.refresh_teensy_tabs()

    def _on_dry_run_changed(self):
        if self._ui_batch_depth > 0:
            self._ui_dirty_dry = True
            return
        self._flush_dry_run_ui()

    def _flush_dry_run_ui(self):
        self.manual_pneumatics.refresh()
        self.refresh_teensy_tabs()
        if self.machine_workbench.isVisible():
            self.machine_workbench.refresh()
        self.refresh_cut_history_status()

    def refresh_cut_history_status(self):
        warning = self.cut_history.warning
        self.cut_history_warning.setText(warning)
        self.cut_history_warning.setVisible(bool(warning))

    # ---------- Auto Mode Sub-Tab & Approval ----------
    def change_auto_page(self, index):
        d = self.dry_run
        if d.sequence:
            if not d.intervention.manual_window():
                index = int(d.sequence.semi)
                self.auto_modes.blockSignals(True)
                self.auto_modes.setCurrentIndex(index)
                self.auto_modes.blockSignals(False)
            else:
                if not d.intervention.paused():
                    d.intervention.pause()
                d.sequence.semi = index == 1
        self.auto_mode_pages[index].layout().addWidget(self._auto_shared_panel)
        self.refresh_teensy_tabs()

    def approve_auto_cut(self):
        d = self.dry_run
        if d.sequence and d.sequence.stage in (
            SequenceStage.WAIT_OPERATOR_CUT,
            SequenceStage.EARLY_RETURN_ARM,
            SequenceStage.EARLY_RETURN_WAIT,
            SequenceStage.EARLY_RETURN_DISARM,
        ):
            return d.confirm_operator_cut()
        return d.approve_cut()

    # ---------- Controller Capabilities & Enablement ----------
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

        for name in ("norm_speed", "norm_accel", "gentle_speed", "gentle_accel", "fast_speed", "fast_accel"):
            widget = getattr(self, name, None)
            if widget is not None:
                widget.setEnabled(controller.key != TEENSY_CARRIAGE)

        manual_ready = connected and capabilities.manual_motion_ready
        auto_ready = connected and capabilities.automatic_cycle_ready
        native_manual = controller.key == TEENSY_CARRIAGE
        self.cylinder_timing.set_simulator_mode(isinstance(self.ser, VirtualController))
        self.tabs.setTabText(
            self.tabs.indexOf(self.legacy_tab), "MANUAL" if native_manual else "MANUAL / SIM"
        )
        self.legacy_tab.setEnabled(manual_ready or (connected and native_manual))
        self.enable_chk.setVisible(not native_manual)
        self.enable_chk.setEnabled(not native_manual)
        self.start_cycle_button.setText('Start Auto' if native_manual else 'START CYCLE')
        self.manual_home_button.setText("Home")
        self.enable_chk.setToolTip("Enable or release the simulated carriage motor.")
        if not native_manual:
            self.enable_chk.blockSignals(True)
            self.enable_chk.setChecked(
                isinstance(self.ser, VirtualController) and self.ser.motor_enabled
            )
            self.enable_chk.blockSignals(False)
            for widget in (self.manual_home_button, self.enable_chk, self.keypad):
                widget.setEnabled(True)
        self.auto_tab.setEnabled(auto_ready or native_manual)
        self.current_group.setVisible(not native_manual)
        self.cancel_cycle_button.setText("STOP / DISARM" if native_manual else "CANCEL CYCLE")
        self.resume_on_reset_button.setEnabled(auto_ready)
        self.resume_on_reset_button.setVisible(not native_manual)
        self._set_start_enabled(auto_ready)
        self.auto_jog_input.setRange(0.01 if native_manual else 0.001, 2 if native_manual else 100)
        if not native_manual:
            for widget in (
                self.load_button,
                self.cancel_cycle_button,
                self.auto_jog_input,
                self.auto_jog_left_btn,
                self.auto_jog_right_btn,
                self.qjog_left_01,
                self.qjog_right_01,
                self.qjog_left_025,
                self.qjog_right_025,
                self.qjog_left_1,
                self.qjog_right_1,
                self.qjog_left_2,
                self.qjog_right_2,
            ):
                widget.setEnabled(True)
        if hasattr(self, "full_auto_tab"):
            self.full_auto_tab.setEnabled(True)
            self.full_auto_legacy.setEnabled(True)

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
        refresh_full_auto(self)

    def refresh_manual_motion_locks(self):
        if not isinstance(self.ser, VirtualController):
            if hasattr(self, 'direct_controls'):
                self.manual_home_button.setEnabled(self.direct_controls.can_motion('home'))
                self.keypad.setEnabled(self.carriage_tab.ready_link())
                self.keypad.enter_button.setEnabled(self.direct_controls.can_motion())
            return
        free = self.is_connected() and not self.manual_pneumatics.motion_locked()
        self.keypad.enter_button.setEnabled(free and self.ser.motor_enabled)
        for widget in (
            self.manual_home_button,
            self.keypad,
            self.enable_chk,
            self.load_button,
            self.resume_on_reset_button,
            self.auto_jog_left_btn,
            self.auto_jog_right_btn,
            self.qjog_left_01,
            self.qjog_right_01,
            self.qjog_left_025,
            self.qjog_right_025,
            self.qjog_left_1,
            self.qjog_right_1,
            self.qjog_left_2,
            self.qjog_right_2,
        ):
            widget.setEnabled(free)
        if not free:
            self._set_start_enabled(False)
        elif self.auto_cycle_state in ('IDLE', 'FINISHED', 'WAITING_FOR_NEW_BOARD'):
            self._set_start_enabled(True)

    # ---------- Cut List ----------
    def load_cut_list_lines(self, lines):
        self._rebuild_cut_list(lines)

    def add_cut_to_list(self):
        if not self.cut_length_keypad.valid_length():
            return
        length = self.cut_length_input.value()
        if length > 0:
            self.cut_list.append((self.next_cut_number, length, ""))
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
                bar.setStyleSheet(
                    "QProgressBar { background-color: #1e293b; border-radius: 8px; border: 1px solid #334155; }\n"
                    f"QProgressBar::chunk {{ background-color: {color}; border-radius: 8px; }}"
                )
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
        cut_groups, group_used_map = group_cuts_by_board(self.cut_list, board_length, kerf)

        active_index = self.current_cut_index
        d = self.dry_run
        if (
            self.active_controller().key == TEENSY_CARRIAGE
            and d.progress_batch == tuple(self.cut_list)
            and d.progress_index is not None
        ):
            active_index = d.progress_index
        self._displayed_cut_index = active_index

        active_group = cut_groups[active_index] if active_index < len(cut_groups) else cut_groups[-1]
        active_used = group_used_map.get(active_group, 0.0)
        fill_ratio = min(1.0, active_used / board_length) if board_length > 0 else 0.0
        fill_color = GROUP_COLORS[active_group % len(GROUP_COLORS)]
        self._set_board_fill(
            fill_ratio,
            fill_color,
            f'Board {active_group + 1}: {active_used:.2f}" / {board_length:.2f}" ({fill_ratio * 100:.1f}%)',
        )

        html = render_cut_list_html(self.cut_list, cut_groups, active_index)
        self.cut_list_display.setHtml(html)
        if hasattr(self, 'fa_cut_list_display'):
            self.fa_cut_list_display.setHtml(html)

        if active_index < len(self.cut_list):
            current_num = self.cut_list[active_index][0]
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
        doc.setTextWidth(display.viewport().width())
        block_rect = doc.documentLayout().blockBoundingRect(cursor.block())
        scrollbar = display.verticalScrollBar()
        scrollbar.setValue(int(block_rect.center().y()) - display.viewport().height() // 2)

    def load_list_from_file(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self, "Open Cut List", "", "Text Files (*.txt);;All Files (*)"
        )
        if file_name:
            try:
                with open(file_name, 'r', encoding='utf-8') as f:
                    self._rebuild_cut_list(f.readlines())
            except Exception as e:
                self.log.append(f"Error reading file: {e}")

    def update_list_from_box(self):
        try:
            text = self.cut_list_display.toPlainText()
            self._rebuild_cut_list(text.split('\n'))
        except Exception as e:
            self.log.append(f"Error parsing list: {e}")

    def _rebuild_cut_list(self, lines):
        cuts, warnings = parse_cut_list_lines(lines)
        self.cut_list = cuts
        self.next_cut_number = len(cuts) + 1
        for warning in warnings:
            self.log.append(warning)
        self.current_cut_index = 0
        self._sync_sim_index()
        self.update_cut_list_display()
        self.log.append(f"Loaded {len(self.cut_list)} cuts into the list.")

    # ---------- Auto Cycle Entry Points ----------
    def cancel_auto_cycle(self):
        """Stop any active auto cycle and reset state."""
        if self.active_controller().key == TEENSY_CARRIAGE:
            return self.dry_run.stop() if self.dry_run.compatible else self.carriage_tab.stop()
        self.cycle_generation += 1
        self._simulation_pneumatic_pending = False
        if isinstance(self.ser, VirtualController):
            self.ser.cancel_saw_cycle()
        self.send_backend_commands(self.active_controller().stop_motion(), "stop carriage motion")
        self.log.append("Auto cycle canceled by user.")
        self.auto_cycle_state = "IDLE"
        self.perform_early_return = False
        self.is_early_returning = False
        self.clamps_engaged_cutting = False
        self.sim_active_piece = None
        self.current_cut_index = 0
        self._sync_sim_index()
        self._release_all_clamps()
        self._update_saw_sensor_pill("--", "#475569")
        self._set_cycle_status("STATUS: Cycle Canceled. Ready.")
        self._set_start_enabled(True)
        self._set_cut_complete_enabled(False)
        self.update_cut_list_display()

    def start_auto_cycle(self):
        if self.active_controller().key == TEENSY_CARRIAGE:
            return (
                self.dry_run.begin_auto()
                if self.dry_run.waiting_for_board()
                else self.direct_controls.request('auto')
            )
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
            self.log.append("AUTO MODE ERROR: System must be homed first.")
            return
        if not self.cut_list:
            self.log.append("AUTO MODE ERROR: Cut list is empty.")
            return
        if self.auto_cycle_state in ("IDLE", "FINISHED"):
            self.current_cut_index = 0
            self._sync_sim_index()
        self.update_cut_list_display()
        self.switch_profile("GENTLE", True)
        self.auto_cycle_state = "DETECTING"
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
        self._legacy_cut_completion_ready = bool(enabled and isinstance(self.ser, VirtualController))

    # ---------- Serial & Commands ----------
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
        mode_key = self.controller_combo.currentData() or TEENSY_CARRIAGE
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
        # Stop before closing the serial port; firmware watchdog is the fallback.
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
        if self.status_label.text() == "Disconnected":
            return
        self._stop_listener()
        self.set_pill(self.status_label, "Disconnected", "#ef4444")
        self.connect_button.setText("Connect")
        self.set_controls_enabled(False)
        self.log.append(f"Serial connection lost: {error}")

    def send_command(self, cmd):
        if self.manual_pneumatics.motion_locked() and (
            cmd == 'H' or re.fullmatch(r'[SJN][+-]?[0-9.]+', cmd)
        ):
            self.log.append('MOVE BLOCKED: release the manual clamp and return/release the saw first.')
            return False
        if self.active_controller().key == TEENSY_CARRIAGE:
            dry = self.dry_run
            stopping = cmd in ('OFF', 'XARM 0', 'XDISABLE', 'RESET', 'DOFF')
            if stopping and not dry.issuing_sequence:
                self.direct_controls.cancel()
                dry.auto_start = None
                dry.manual_start = None
                dry.trigger_held = False
            if dry.sequence and not dry.issuing_sequence:
                if stopping and self.carriage_tab.local_fault:
                    dry.intervention.capture_fault(self.carriage_tab.local_fault)
                if dry.intervention.recovering() and stopping:
                    pass
                elif dry.intervention.paused() and cmd == 'XARM 0':
                    pass
                elif stopping:
                    dry.sequence = None
                    dry.pending = None
                    dry.message = 'Unloaded dry list stopped.'
                elif not dry.intervention.paused() and cmd not in ('HELLO', 'PINMAP', 'STATUS', 'PING', 'KEEPALIVE'):
                    self.log.append('BLOCKED: unloaded list owns machine sequencing.')
                    return False
            if (
                dry.motion_locked()
                and not dry.intervention.paused()
                and not dry.issuing_sequence
                and not stopping
                and cmd not in ('HELLO', 'PINMAP', 'STATUS', 'PING', 'KEEPALIVE')
                and not DRY_COMMAND.fullmatch(cmd)
                and not SECOND_COMMAND.fullmatch(cmd)
            ):
                self.log.append('BLOCKED: unloaded pneumatics own machine control.')
                return False
            if cmd == 'XDISABLE' and dry.motion_locked():
                self.log.append('BLOCKED: stop the unloaded test before releasing motor holding.')
                return False
            allowed = (
                dry.allowed(cmd)
                if DRY_COMMAND.fullmatch(cmd)
                or SECOND_COMMAND.fullmatch(cmd)
                or (cmd == 'KEEPALIVE' and dry.data.get('ARMED') == '1')
                else self.carriage_tab.allowed(cmd)
            )
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

    # ---------- Direct Motion Commands ----------
    def home_motor(self):
        if self.active_controller().key == TEENSY_CARRIAGE:
            return self.direct_controls.request('home')
        self.send_backend_commands(self.active_controller().home(), "home the carriage")

    def load_position(self):
        if self.active_controller().key == TEENSY_CARRIAGE:
            return self.direct_controls.request('load', self.native_load_target())
        self.switch_profile("FAST", True)
        target_pos = self.home_position
        log_msg = f'Moving to HOME load position: {target_pos:.2f}"'
        for radio, _, load_pos in self.board_size_radios:
            if radio.isChecked() and load_pos is not None:
                target_pos = load_pos
                log_msg = f'Moving to short load position: {target_pos:.2f}"'
                break
        self.log.append(log_msg)
        self.set_length(target_pos)

    def native_load_target(self):
        for radio, _, load_pos in self.board_size_radios:
            if radio.isChecked() and load_pos is not None:
                return load_pos
        return int(self.carriage_tab.x.get("SOFT_MAX_MILLI", "0")) / 1000

    def toggle_motor_power(self, checked):
        if self.active_controller().key == TEENSY_CARRIAGE:
            if checked:
                self.send_command("XARM 1")
            else:
                self.carriage_tab.stop("XDISABLE")
            self.refresh_teensy_tabs()
            return
        self.send_backend_commands(
            self.active_controller().motor_power(checked), "change motor power"
        )

    def set_length(self, length):
        target = length
        if self.active_controller().key == TEENSY_CARRIAGE:
            return self.direct_controls.request('move', target)
        if 0.0 <= target <= self.home_position:
            if self.send_backend_commands(
                self.active_controller().move_absolute_inches(target),
                "move the carriage",
            ):
                self.prepare_prediction(target)
        else:
            self.log.append(
                f'MOVE REJECTED: Target {target:.2f}" is outside the valid range (0 to {self.home_position:.2f}").'
            )

    def auto_jog(self, delta):
        if self.active_controller().key == TEENSY_CARRIAGE:
            return self.direct_controls.request('jog', float(delta))
        self.set_length(self.current_position + float(delta))

    # ---------- Profiles & Homing Settings ----------
    def profile_setting_widgets(self):
        return {
            1: (self.gentle_speed, self.gentle_accel),
            2: (self.norm_speed, self.norm_accel),
            3: (self.fast_speed, self.fast_accel),
        }

    def mark_teensy_profile_edit(self, profile):
        if self.active_controller().key == TEENSY_CARRIAGE:
            self._teensy_settings_dirty.add(profile)
            self.refresh_teensy_tabs()

    def saved_motion_profiles(self):
        result = {}
        for profile, defaults in {1: (600, 600), 2: (2500, 900), 3: (3500, 2000)}.items():
            try:
                pair = tuple(
                    int(self.settings.value(f'teensy_profiles/{profile}/{key}', default))
                    for key, default in zip(('rate', 'accel'), defaults)
                )
                if not (1 <= pair[0] <= 20000 and 1 <= pair[1] <= 50000):
                    raise ValueError('Profile outside limits')
            except (TypeError, ValueError):
                pair = defaults
            result[profile] = pair
        return result

    def save_confirmed_profile(self, profile, rate, accel):
        for key, value in (('rate', rate), ('accel', accel)):
            self.settings.setValue(f'teensy_profiles/{profile}/{key}', value)
        self.settings.sync()
        self._teensy_settings_dirty.discard(profile)
        for widget, value in zip(self.profile_setting_widgets()[profile], (rate, accel)):
            widget.blockSignals(True)
            widget.setValue(value)
            widget.blockSignals(False)

    def prepare_saved_profiles(self):
        """Called only during an explicit motion/Auto gesture; wait for each ACK."""
        p = self.carriage_tab
        if p.profile_pending:
            return None
        for profile, pair in self.saved_motion_profiles().items():
            if p.profile_values.get(profile) != pair:
                return None if p.edit_profile(profile, *pair) else False
        return True

    def saved_homing_settings(self):
        def value(key, default, maximum):
            try:
                result = int(self.settings.value(key, default))
            except (TypeError, ValueError):
                return default
            return result if 1 <= result <= maximum else default

        return value('homing/rate_pps', 40, 20000), value('homing/accel_pps2', 200, 50000)

    def save_homing_settings(self):
        rate, accel = int(self.homing_speed.value()), int(self.homing_accel.value())
        self.settings.setValue('homing/rate_pps', rate)
        self.settings.setValue('homing/accel_pps2', accel)
        self.settings.sync()
        p = self.carriage_tab
        if (
            p.ready_link()
            and p.home_profile_supported
            and self.dry_run.safe_link(False)
            and not self.dry_run.sequence
            and not self.direct_controls.intent
            and not p.armed
            and all(self.dry_run.data.get(k) == '0' for k in ('ARMED', 'CLAMP', 'SAW', 'TRIGGER'))
        ):
            p.consent.setChecked(True)
            p.edit_home_profile(rate, accel)
        self.refresh_homing_settings()

    def refresh_homing_settings(self, *_args):
        if not hasattr(self, 'homing_feedback') or not hasattr(self, 'carriage_tab'):
            return
        p = self.carriage_tab
        busy = p.connected and bool(
            p.armed
            or p.homing
            or p.edge_searching
            or p.pending
            or p.profile_pending
            or p.full_home_pending
            or self.direct_controls.intent
            or self.dry_run.data.get('ARMED') == '1'
        )
        for widget in (self.homing_speed, self.homing_accel, self.save_homing_button):
            widget.setEnabled(not busy)
        saved = self.saved_homing_settings()
        draft = (int(self.homing_speed.value()), int(self.homing_accel.value()))
        prefix = 'Unsaved edits. ' if draft != saved else f'Saved: {saved[0]} pulses/s, {saved[1]} pulses/s². '
        if not p.ready_link():
            text = 'Offline. Firmware 0.23+ loads the saved values before Home.'
        elif not p.home_profile_supported:
            text = 'Connected firmware has fixed homing speed. Flash 0.23.0 to activate these settings.'
        elif p.profile_pending and p.profile_pending[0] == 'HOME':
            text = 'Waiting for controller acknowledgment.'
        else:
            text = (
                f"Controller: {p.x.get('HOME_RATE_PPS')} pulses/s, "
                f"{p.x.get('HOME_ACCEL_PPS2')} pulses/s². Saved values load automatically before Home."
            )
        self.homing_feedback.setText(prefix + text)
        self.homing_feedback.setStyleSheet(
            'color:#fbbf24;' if p.ready_link() and not p.home_profile_supported else 'color:#94a3b8;'
        )

    def update_teensy_profile(self, profile):
        self.active_profile_name = _TEENSY_PROFILE_NAMES.get(profile, "COMMISSIONING")

    def switch_profile(self, name, push_params=True):
        if self.active_controller().key == TEENSY_CARRIAGE:
            profile = TEENSY_PROFILE_MAP.get(name)
            return False if profile is None else self.carriage_tab.select_profile(profile)
        if name not in PROFILE_MAP:
            self.log.append(f"Unknown profile '{name}'")
            return
        idx = PROFILE_MAP[name]
        if not self.send_backend_commands(
            self.active_controller().profile_select(idx), "select a motion profile"
        ):
            return
        self.active_profile_name = name
        if push_params:
            if name == "NORMAL":
                spd, acc = self.norm_speed.value(), self.norm_accel.value()
            elif name == "GENTLE":
                spd, acc = self.gentle_speed.value(), self.gentle_accel.value()
            else:
                spd, acc = self.fast_speed.value(), self.fast_accel.value()
            self.send_backend_commands(
                self.active_controller().set_motor_parameters(spd, acc),
                "set motion profile parameters",
            )
            self.log.append(f"Applied {name} profile params: speed={spd:.0f}, accel={acc:.0f}")

    def apply_current_profile_params(self):
        name = self.settings_profile_combo.currentData()
        if self.active_controller().key == TEENSY_CARRIAGE:
            profile = TEENSY_PROFILE_MAP[name]
            rate, accel = (widget.value() for widget in self.profile_setting_widgets()[profile])
            return self.carriage_tab.edit_profile(profile, rate, accel)
        return self.switch_profile(name, True)

    # ---------- Teensy Live UI Mirror ----------
    def refresh_teensy_tabs(self, *_args):
        """Mirror controller-owned state into Manual/Auto/Settings; never sends commands."""
        if not hasattr(self, "carriage_tab") or not hasattr(self, "settings_profile_combo"):
            return
        p = self.carriage_tab
        self.refresh_homing_settings()
        self.refresh_live_health()
        self.refresh_auto_approval()
        second = self.dry_run
        second_text = (
            'ON COMMANDED'
            if second.fresh() and second.second_supported and second.data.get('SECOND_CLAMP') == '1'
            else 'DISABLED'
            if not second.supervision.second_requested()
            else 'NEEDS FIRMWARE 0.24'
            if not second.second_supported
            else 'UNKNOWN'
            if not second.fresh()
            else 'ON COMMANDED'
            if second.data.get('SECOND_CLAMP') == '1'
            else 'OFF COMMANDED'
        )
        self.set_pill(
            self.auto_second_clamp_label,
            second_text,
            '#92400e' if second_text == 'ON COMMANDED' else '#475569',
        )
        if self.active_controller().key != TEENSY_CARRIAGE:
            self.settings_profile_feedback.setText(
                "Simulator profile values; apply the selected profile explicitly."
            )
            self.settings_profile_combo.setEnabled(True)
            self.apply_profile_btn.setEnabled(True)
            return

        link = p.ready_link()
        busy = bool(
            p.pending
            or p.profile_pending
            or p.homing
            or p.edge_searching
            or int(p.x.get("REMAINING", "0"))
        )
        self.manual_home_button.setEnabled(self.direct_controls.can_motion('home'))
        known = link and p.x.get("POS_KNOWN") == "1" and not p.local_fault
        self.update_homed_status(1 if known else 0)
        if not known:
            self.position_label.setText("UNKNOWN")
        elif not busy:
            self.position_label.setText(
                f"{HOME_POSITION_INCHES + int(p.x['HOME_OFFSET']) / STEPS_PER_INCH:.4f}"
            )
        self.state_label.setText(
            "FAULT"
            if p.local_fault or p.x.get("FAULT", "NONE") != "NONE"
            else "HOMING"
            if p.homing
            else "MOVING"
            if busy
            else "ARMED"
            if p.armed
            else "DISARMED"
        )
        for name, label in (("HOME", self.sensor_label), ("BOARD_EDGE", self.board_sensor_label)):
            raw = p.inputs.get(name) if p.fresh("INPUTS") else None
            pill_text = "UNKNOWN" if raw not in ("0", "1") else "ON" if raw == "0" else "OFF"
            pill_bg = "#334155" if raw not in ("0", "1") else "#22c55e" if raw == "0" else "#ef4444"
            self.set_pill(label, pill_text, pill_bg)
            mirrors = (
                (self.auto_homing_sensor_label, getattr(self, 'fa_homing_sensor_label', None))
                if name == "HOME"
                else (self.auto_board_sensor_label, getattr(self, 'fa_board_sensor_label', None))
            )
            for mirror in mirrors:
                if mirror is not None:
                    self.set_pill(mirror, pill_text, pill_bg)
            if name == "BOARD_EDGE":
                self.board_sensor_tripped = raw == "0"
        for name, label in self.auto_sensor_pills.items():
            raw = p.inputs.get(name) if p.fresh("INPUTS") else None
            if raw not in ("0", "1"):
                text, color = "UNKNOWN", "#475569"
            elif name == "CL57T_ALM":
                text, color = ("NORMAL", "#22c55e") if raw == "1" else ("ALARM", "#ef4444")
            elif name == "FENCE_DOOR":
                text, color = ("CLOSED", "#22c55e") if raw == "0" else ("OPEN", "#ef4444")
            else:
                text, color = ("ACTIVE", "#22c55e") if raw == "0" else ("INACTIVE", "#475569")
            self.set_pill(label, text, color)
        if self.dry_run.fresh():
            main_state = self.dry_run.data.get('MAIN_CLAMP', self.dry_run.data.get('CLAMP'))
            self.set_pill(
                self.auto_clamp_status_label,
                'ON COMMANDED' if main_state == '1' else 'OFF COMMANDED',
                '#92400e' if main_state == '1' else '#475569',
            )
        else:
            self.set_pill(self.auto_clamp_status_label, "UNKNOWN", "#475569")
        if not known:
            self.auto_position_label.setText("UNKNOWN")
        elif not busy:
            self.auto_position_label.setText(self.position_label.text())
        saw = p.safety.get("SAW_POSITION", "UNKNOWN") if p.fresh("SAFETY") else "UNKNOWN"
        self.set_pill(
            self.fa_saw_position_label,
            saw,
            "#22c55e" if saw == "UP" else "#ef4444" if saw == "CONFLICT" else "#475569",
        )
        self.auto_home_button.setEnabled(self.direct_controls.can_motion('home'))
        self.auto_clear_error.setEnabled(
            p.ready_link()
            and not p.armed
            and (not self.dry_run.sequence or self.dry_run.intervention.recovering())
            and self.dry_run.data.get('CLAMP') == '0'
            and p.safety.get('RESET_READY') == '1'
        )
        self.auto_cancel_button.setEnabled(p.connected)
        self.auto_release_clamps.setEnabled(self.dry_run.allowed('DRELEASE'))
        self.auto_pause_button.setEnabled(
            bool(
                self.dry_run.sequence
                and self.dry_run.sequence.stage
                not in (SequenceStage.PAUSED, SequenceStage.PAUSING, SequenceStage.FAULT_RECOVERY)
                and not self.dry_run.intervention.after_cut
            )
        )
        self.auto_pause_button.setText(
            'Pausing after cut...' if self.dry_run.intervention.after_cut else 'Pause Cycle'
        )
        self.auto_resume_button.setEnabled(self.dry_run.intervention.resume_plan() is not None)
        self.auto_modes.tabBar().setEnabled(
            (not self.dry_run.sequence or self.dry_run.intervention.manual_window())
            and not self.dry_run.auto_start
        )
        for checkbox in (self.repeat_pattern, self.clear_between_boards, self.clear_at_list_end):
            checkbox.setEnabled(
                not self.dry_run.sequence
                and not self.dry_run.auto_start
                and (checkbox is not self.clear_at_list_end or not self.repeat_pattern.isChecked())
            )
        self.cancel_cycle_button.setEnabled(p.connected)
        self.start_cycle_button.setEnabled(
            self.dry_run.can_begin_auto() or self.direct_controls.can_motion('auto')
        )
        self.start_cycle_button.setText(
            'Continue cut list / next board'
            if self.dry_run.waiting_for_board()
            else 'Start Semi-Auto — dry run'
            if self.auto_modes.currentIndex() == 1
            else 'Start Auto — dry run'
        )
        progress = (self.dry_run.progress_batch, self.dry_run.progress_index)
        if getattr(self, '_native_progress_rendered', None) != progress:
            self._native_progress_rendered = progress
            self.update_cut_list_display()
        self.auto_status_label.setText(
            self.dry_run.message
            if self.dry_run.sequence
            else self.dry_run.supervision.summary() + ' ' + self.dry_run.message
        )
        refresh_full_auto(self)

        self.load_button.setEnabled(self.direct_controls.can_motion('load'))
        self.load_button.setToolTip("Return to Load using the stored FAST profile.")
        jogs = (
            (self.auto_jog_left_btn, self.auto_jog_input.value()),
            (self.auto_jog_right_btn, -self.auto_jog_input.value()),
            (self.qjog_left_01, 0.1),
            (self.qjog_right_01, -0.1),
            (self.qjog_left_025, 0.25),
            (self.qjog_right_025, -0.25),
            (self.qjog_left_1, 1),
            (self.qjog_right_1, -1),
            (self.qjog_left_2, 2),
            (self.qjog_right_2, -2),
        )
        for button, delta in jogs:
            button.setEnabled(self.direct_controls.can_motion('jog'))
            button.setToolTip("Toward Home" if delta > 0 else "Toward saw")
        self.auto_jog_input.setEnabled(not busy)
        self.auto_jog_left_btn.setText("Home")
        self.auto_jog_right_btn.setText("Saw")
        for radio, _, _ in self.board_size_radios:
            radio.setEnabled(not busy)
        self.keypad.setEnabled(link)
        self.keypad.enter_button.setEnabled(self.direct_controls.can_motion())
        self.keypad.enter_button.setToolTip(
            'Move to this position.'
            if self.direct_controls.can_motion()
            else 'Home first.'
            if not known
            else 'Return saw UP and release clamp/trigger before moving.'
        )

        edit = link and not p.armed and not busy
        if not link:
            self._teensy_settings_snapshot = None
            self._teensy_settings_active = None
        else:
            for profile, widgets in self.profile_setting_widgets().items():
                if profile not in self._teensy_settings_dirty:
                    for widget, value in zip(widgets, self.saved_motion_profiles()[profile]):
                        widget.blockSignals(True)
                        widget.setValue(value)
                        widget.blockSignals(False)
            self._teensy_settings_snapshot = dict(p.profile_values)
            active = int(p.x["PROFILE_ID"])
            if active != self._teensy_settings_active:
                self._teensy_settings_active = active
                if active in (1, 2, 3):
                    name = _TEENSY_PROFILE_NAMES[active]
                    self.settings_profile_combo.blockSignals(True)
                    self.settings_profile_combo.setCurrentIndex(
                        self.settings_profile_combo.findData(name)
                    )
                    self.settings_profile_combo.blockSignals(False)
        for widgets in self.profile_setting_widgets().values():
            for widget in widgets:
                widget.setEnabled(edit)
        self.settings_profile_combo.setEnabled(edit)
        profile = TEENSY_PROFILE_MAP[self.settings_profile_combo.currentData()]
        rate, accel = (int(widget.value()) for widget in self.profile_setting_widgets()[profile])
        self.apply_profile_btn.setEnabled(p.allowed(f"XPROFILE {profile} {rate} {accel}"))
        selected = p.profile_values[profile]
        note = (
            "Waiting for fresh compatible controller feedback"
            if not link
            else (
                f"Controller active: {self.active_profile_name}; selected profile readback: "
                f"{selected[0]} pulses/s, {selected[1]} pulses/s^2. "
                + ("UNAPPLIED EDITS. " if self._teensy_settings_dirty else "")
                + ("Waiting for parameter acknowledgment. " if p.profile_pending else "")
            )
        )
        self.settings_profile_feedback.setText(
            note
            + f"Motion status: {p.status.text()}. "
            "Saved PC profiles load before the next carriage/Auto action. Apply saves changes after controller acknowledgment."
        )

    def refresh_auto_approval(self):
        semi = self.auto_modes.currentIndex() == 1
        native = self.active_controller().key == TEENSY_CARRIAGE
        d = self.dry_run
        stage = d.sequence.stage if d.sequence else ''
        waiting = stage in (
            SequenceStage.WAIT_OPERATOR_CUT,
            SequenceStage.EARLY_RETURN_ARM,
            SequenceStage.EARLY_RETURN_WAIT,
            SequenceStage.EARLY_RETURN_DISARM,
            SequenceStage.RETURN_CUT_ACK,
            SequenceStage.RETURN_CUT_WAIT,
        )
        semi_wait = stage == SequenceStage.WAIT_CUT_APPROVAL or (
            d.intervention.paused() and bool(d.sequence.semi)
        )
        if getattr(self, '_rendered_auto_mode', None) != semi:
            self.auto_mode_label.setText(
                'SEMI-AUTO — positions each cut; waits for your cut button.'
                if semi
                else 'AUTOMATIC — positions, clamps and cycles each cut.'
            )
            self.auto_mode_label.setStyleSheet(
                'font-weight:bold; padding:8px; border-left:3px solid '
                + ('#f59e0b; color:#fcd34d;' if semi else '#38bdf8; color:#7dd3fc;')
            )
            self._rendered_auto_mode = semi
        self.operator_cut_button.setVisible(semi or waiting or semi_wait)
        attention = stage in (
            SequenceStage.EARLY_RETURN_ARM,
            SequenceStage.EARLY_RETURN_WAIT,
            SequenceStage.EARLY_RETURN_DISARM,
        )
        if self.operator_cut_button.property('earlyReturnAttention') != attention:
            self.operator_cut_button.setProperty('earlyReturnAttention', attention)
            self.operator_cut_button.style().unpolish(self.operator_cut_button)
            self.operator_cut_button.style().polish(self.operator_cut_button)
            self.operator_cut_button.update()
        self.operator_cut_button.setEnabled(
            native and (d.can_confirm_operator_cut() if waiting else d.can_approve_cut())
        )
        truing = bool(d.sequence and d.sequence.index < 0)
        self.operator_cut_button.setText(
            'Wood secured / run cut\nSaw unplugged'
            if waiting
            else 'True-up / advance\nSaw unplugged'
            if truing
            else 'Clamp / Cut / Advance\nSaw unplugged'
        )
        self.operator_cut_button.setToolTip(
            (
                'Press during the authorized Fast return to start this operator cut; both clamps stay OFF.'
                if self.carriage_tab.parallel_supported()
                else 'Available once the carriage stops. No saw stroke is queued during return.'
            )
            if waiting
            else 'Enabled when the cycle is waiting for cut approval. You can jog to adjust the positioned cut first.'
        )
        approval_wait = waiting or semi_wait
        if approval_wait and not getattr(self, '_cut_approval_waiting', False):
            self.operator_cut_button.parentWidget().layout().activate()
            self.auto_right_scroll.widget().layout().activate()
            self.auto_right_scroll.ensureWidgetVisible(self.operator_cut_button)
        self._cut_approval_waiting = approval_wait

    # ---------- Inbound Serial & Telemetry ----------
    def update_message_log(self, msg):
        if self.active_controller().key == TEENSY_CARRIAGE:
            with self._batch_ui_refresh():
                self.carriage_tab.handle_line(msg)
                self.dry_run.handle(msg)
        elif isinstance(self.ser, VirtualController) and self.is_connected() and msg.startswith("POS:"):
            self.refresh_live_health()
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
            state = native_health(
                connected=connected and p.connected,
                compatible=p.compatible,
                records={"X": p.x, "SAFETY": p.safety, "INPUTS": p.inputs},
                received=p.received,
                started=self._health_started,
                now=now,
                local_fault=p.local_fault or self.dry_run.local_fault,
                stale_seconds=p.stale_seconds,
                allow_saw_travel=self.dry_run.fresh()
                and self.dry_run.data.get('STATE') in DRY_TRAVEL,
            )
            receipt = p.received.get("X") if connected and p.connected and p.compatible else None
            if state.level == 'healthy' and self.dry_run.sequence:
                if self.dry_run.sequence.stage == SequenceStage.WAIT_OPERATOR_CUT:
                    state = HealthState(
                        'waiting',
                        'Waiting for operator — secure unclamped wood',
                        ('No clamp grip is measured. One explicit unplugged stroke is required.',),
                    )
                elif self.dry_run.sequence.stage in (
                    SequenceStage.PAUSED,
                    SequenceStage.PAUSING,
                    SequenceStage.WAIT_CUT_APPROVAL,
                ):
                    state = HealthState(
                        'waiting',
                        'Cycle paused'
                        if self.dry_run.sequence.stage != SequenceStage.WAIT_CUT_APPROVAL
                        else 'Position ready — approve cut',
                    )
        elif mode == "sim":
            state = simulator_health(
                connected=connected,
                fields=self._sim_health_fields,
                received=self._sim_health_received,
                started=self._health_started,
                now=now,
            )
            receipt = self._sim_activity_received if connected else None
        else:
            state = HealthState("neutral", "Health unavailable in this mode")

        color = {
            "healthy": "#22c55e",
            "fault": "#ef4444",
            "neutral": "#64748b",
            "waiting": "#f59e0b",
        }[state.level]
        if self.auto_live_status.property("healthState") != state.level:
            self.auto_live_status.setProperty("healthState", state.level)
            self.auto_live_status.setStyleSheet(
                f"QGroupBox#autoLiveStatus {{ border: 2px solid {color}; }}"
            )
            self.live_health_label.setStyleSheet(f"color:{color}; font-size:13px; font-weight:600;")
        self.live_health_label.setText(state.text)
        self.live_health_label.setToolTip("\n".join(state.details) or state.text)
        self.auto_live_status.setAccessibleDescription(state.text)
        intensity = round(self._health_activity.update(receipt, now) * 255)
        if self.live_health_dot.property("intensity") != intensity:
            self.live_health_dot.setProperty("intensity", intensity)
            self.live_health_dot.setProperty("active", intensity > 0)
            channels = [
                round(dim + (bright - dim) * intensity / 255)
                for dim, bright in zip((51, 65, 85), (56, 189, 248))
            ]
            self.live_health_dot.setStyleSheet(
                f"background:rgb({channels[0]},{channels[1]},{channels[2]}); border-radius:5px;"
            )

    def update_position_label_from_device(self, pos):
        self.current_position = pos
        self.position_label.setText(f"{pos:.4f}")
        self.auto_position_label.setText(f"{pos:.4f}")
        if hasattr(self, 'fa_position_label'):
            self.fa_position_label.setText(f"{pos:.4f}")
        self._sim_track_carriage(pos)
        if self.pred_active:
            self.pred_start_pos = pos
            self.pred_start_time = time.monotonic()

    def update_homed_status(self, status):
        text = "HOMED" if status == 1 else "NOT HOMED"
        color = "#22c55e" if status == 1 else "orange"
        self.homed_label.setText(text)
        self.homed_label.setStyleSheet(f"color: {color}; font-weight: bold;")

    # ---------- Settings Persistence ----------
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
        self.cut_length_keypad_checkbox.setChecked(
            self.settings.value("cut_length_keypad", False, type=bool)
        )
        for key, widget in self._settings_widgets().items():
            if self.active_controller().key == TEENSY_CARRIAGE and key in {
                'norm_speed',
                'norm_accel',
                'gentle_speed',
                'gentle_accel',
                'fast_speed',
                'fast_accel',
            }:
                continue
            value = self.settings.value(key)
            if value is not None:
                try:
                    widget.setValue(type(widget.value())(value))
                except (TypeError, ValueError):
                    pass
        if self.active_controller().key == TEENSY_CARRIAGE:
            for profile, widgets in self.profile_setting_widgets().items():
                for widget, value in zip(widgets, self.saved_motion_profiles()[profile]):
                    widget.blockSignals(True)
                    widget.setValue(value)
                    widget.blockSignals(False)
        self.current_monitoring_enabled = self.settings.value("current_monitoring", False, type=bool)
        self.current_monitoring_checkbox.setChecked(self.current_monitoring_enabled)
        self.current_limit_amps = self.current_limit_input.value()
        self.current_trip_delay_ms = int(self.current_delay_input.value())
        self.current_graph.set_limit(self.current_limit_amps)
        self.auto_clamp_enabled = self.settings.value("auto_clamp_enabled", False, type=bool)
        self.auto_clamp_checkbox.setChecked(self.auto_clamp_enabled)

    def _save_settings(self):
        self.cylinder_timing.save()
        for key, widget in self._settings_widgets().items():
            if self.active_controller().key == TEENSY_CARRIAGE and key in {
                "norm_speed",
                "norm_accel",
                "gentle_speed",
                "gentle_accel",
                "fast_speed",
                "fast_accel",
            }:
                continue  # live Teensy RAM readbacks must not overwrite archived simulator settings
            self.settings.setValue(key, widget.value())
        self.settings.setValue("current_monitoring", self.current_monitoring_checkbox.isChecked())
        self.settings.setValue("auto_clamp_enabled", self.auto_clamp_checkbox.isChecked())
        self.settings.setValue("cut_length_keypad", self.cut_length_keypad_checkbox.isChecked())
        self.settings.setValue("serial_port", self.selected_serial_port)
        self.settings.setValue("controller_mode", self.selected_controller_mode)

    # ---------- Software Updates ----------
    def _on_update_found(self, info):
        self.update_manager.on_update_found(info)

    def check_updates_manual(self):
        self.update_manager.check_manual()

    def _install_update(self):
        self.update_manager.install_update()

    def closeEvent(self, event):
        for timer in self.findChildren(QTimer):
            timer.stop()
        self.update_manager.shutdown()
        self._save_settings()
        self._stop_listener()
        self.cut_history.close()
        event.accept()


if __name__ == "__main__":
    smoke_dir = os.environ.get('CHOPSAW_RELEASE_SMOKE_DIR')
    if smoke_dir:
        from release_smoke import run as run_release_smoke
        sys.exit(run_release_smoke(MinimalHMI, smoke_dir))
    app = QApplication(sys.argv)
    icon_path = get_icon_path()
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    window = MinimalHMI()
    window.show()
    sys.exit(app.exec())
