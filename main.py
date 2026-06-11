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
    QSpinBox, QFormLayout
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QTextCursor, QIcon

# Import from our other modules
from config import SERIAL_PORT, BAUD_RATE, PROFILE_MAP
from serial_handler import SignalBridge, listen_for_data
from ui_components import KeypadWidget, CurrentGraphWidget
from cutlist_manager import CutListManagerTab

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
        self.setWindowTitle("Chop Saw HMI — Profiles & Touch UI")
        self.resize(1280, 900)

        # Serial
        self.ser = None
        self.listener_thread = None
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

        # State
        self.stepper_steps_per_inch = 127.0
        self.encoder_ticks_per_inch = self.stepper_steps_per_inch * 20.0
        self.cut_list = []
        self.auto_cycle_state = "IDLE"
        self.next_cut_number = 1
        
        self.home_position = 168.0
        self.standard_board_length = 144.5
        self.short_board_length_135 = 120.0  # 10' board usable length
        self.short_board_length_96 = 96.0    # 8' board usable length
        self.short_board_length_72 = 72.0    # 6' board usable length
        self.short_board_length_60 = 48.0    # 4' board usable length
        self.short_load_pos_135 = self.short_board_length_135 + 15.0
        self.short_load_pos_96 = self.short_board_length_96 + 15.0
        self.short_load_pos_72 = self.short_board_length_72 + 15.0
        self.short_load_pos_60 = self.short_board_length_60 + 15.0

        self.active_profile_name = "NORMAL"
        self.clamp_engaged = False
        self.clamp_left_engaged = False
        self.clamp_right_engaged = False
        self.clamp_fence_engaged = False
        self.clamps_engaged_cutting = False   # True while saw is down, awaiting sensor return
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
        self.selected_serial_port = SERIAL_PORT

        # Prediction
        self.pred_timer = QTimer(self); self.pred_timer.setInterval(30); self.pred_timer.timeout.connect(self.tick_predict)
        self.pred_active = False; self.pred_start_time = 0.0; self.pred_start_pos = 0.0; self.pred_target_pos = 0.0; self.pred_vmax_in = 0.0; self.pred_acc_in = 0.0; self.pred_dir = 1.0

        self.init_ui()
        self.apply_theme()
        self.update_current_monitor_ui()

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

    # ---------- UI ----------
    def init_ui(self):
        central = QWidget(); self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # Top bar
        top = QHBoxLayout()
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

        # Tabs
        self.tabs = QTabWidget(); root.addWidget(self.tabs)
        self.legacy_tab = self.create_legacy_tab()
        self.auto_tab = self.create_auto_tab()
        self.full_auto_tab = self.create_full_auto_tab()
        self.speed_tab = self.create_speed_tab()
        self.preset_tab = self.create_preset_tab()

        self.tabs.addTab(self.legacy_tab, "MANUAL")
        self.tabs.addTab(self.auto_tab, "AUTO")
        self.tabs.addTab(self.full_auto_tab, "FULL AUTO")
        self.tabs.addTab(self.speed_tab, "SETTINGS")
        self.tabs.addTab(self.preset_tab, "CUT LISTS")

        # Log (hidden — keep object so log.append() calls don't crash)
        self.log = QTextBrowser()
        self.set_controls_enabled(False)
        self.update_clamp_ui()

    def create_legacy_tab(self):
        w = QWidget(); content = QHBoxLayout(w)
        left = QVBoxLayout()
        dash = QGroupBox("Dashboard"); grid = QGridLayout(dash)
        grid.addWidget(QLabel("Homed Status:"), 0, 0)
        self.homed_label = QLabel("NOT HOMED"); self.homed_label.setStyleSheet("color: orange; font-weight: bold;"); grid.addWidget(self.homed_label, 0, 1)
        grid.addWidget(QLabel("Motor State:"), 1, 0); self.state_label = QLabel("IDLE"); self.state_label.setStyleSheet("color: #22c55e; font-weight: bold;"); grid.addWidget(self.state_label, 1, 1)
        grid.addWidget(QLabel("Homing Sensor:"), 2, 0); self.sensor_label = self.pill("OFF", "#ef4444"); grid.addWidget(self.sensor_label, 2, 1)
        grid.addWidget(QLabel("Board Sensor:"), 3, 0); self.board_sensor_label = self.pill("OFF", "#ef4444"); grid.addWidget(self.board_sensor_label, 3, 1)
        grid.addWidget(QLabel("Current Position (in):"), 4, 0)
        self.position_label = QLabel("0.0000"); self.position_label.setStyleSheet("font-size: 24px; font-weight: bold; color: #60a5fa;"); grid.addWidget(self.position_label, 4, 1)
        left.addWidget(dash)

        ctrl = QGroupBox("Controls"); v = QVBoxLayout(ctrl)
        self.enable_chk = QCheckBox("Motor Power Enabled"); self.enable_chk.setChecked(True); self.enable_chk.toggled.connect(self.toggle_motor_power); v.addWidget(self.enable_chk)
        self.pid_chk    = QCheckBox("PID Control Enabled"); self.pid_chk.setChecked(True); self.pid_chk.toggled.connect(self.toggle_pid_control); v.addWidget(self.pid_chk)
        home_row = QHBoxLayout()
        home_btn = QPushButton("Home (H)"); home_btn.clicked.connect(self.home_motor); home_row.addWidget(home_btn)
        self.near_cal_btn = QPushButton("Near Calibration"); self.near_cal_btn.clicked.connect(self.near_calibrate); home_row.addWidget(self.near_cal_btn)
        v.addLayout(home_row)

        row = QHBoxLayout(); row.addWidget(QLabel("Set Length:"))
        self.target_input = QDoubleSpinBox(); self.target_input.setRange(0.0, self.home_position); self.target_input.setDecimals(4); row.addWidget(self.target_input)
        set_btn = QPushButton("Go"); set_btn.clicked.connect(self.set_length); row.addWidget(set_btn); v.addLayout(row)

        row2 = QHBoxLayout(); row2.addWidget(QLabel("Jog By:"))
        self.rel_input = QDoubleSpinBox(); self.rel_input.setRange(-100, 100); self.rel_input.setDecimals(4); row2.addWidget(self.rel_input)
        jog_btn = QPushButton("Move"); jog_btn.clicked.connect(self.move_relative); row2.addWidget(jog_btn); v.addLayout(row2)

        row3 = QHBoxLayout(); row3.addWidget(QLabel("Measured Length (in):"))
        self.calibrate_input = QDoubleSpinBox(); self.calibrate_input.setRange(0.01, 1000); self.calibrate_input.setDecimals(4); row3.addWidget(self.calibrate_input)
        cal_btn = QPushButton("Calibrate"); cal_btn.clicked.connect(self.initiate_calibration); row3.addWidget(cal_btn); v.addLayout(row3)

        params = QGroupBox("Motor Parameters (Manual Mode)"); pg = QGridLayout(params)
        pg.addWidget(QLabel("Max Speed (steps/s):"), 0, 0)
        self.max_speed = QDoubleSpinBox(); self.max_speed.setRange(1, 20000); self.max_speed.setDecimals(0); self.max_speed.setValue(3000); pg.addWidget(self.max_speed, 0, 1)
        pg.addWidget(QLabel("Acceleration (steps/s²):"), 1, 0)
        self.acceleration = QDoubleSpinBox(); self.acceleration.setRange(1, 50000); self.acceleration.setDecimals(0); self.acceleration.setValue(1000); pg.addWidget(self.acceleration, 1, 1)
        params_btn = QPushButton("Apply (A speed,accel)"); params_btn.clicked.connect(self.set_motor_parameters); pg.addWidget(params_btn, 2, 0, 1, 2)
        params_btn.setMinimumHeight(15)
        v.addWidget(params)
        left.addWidget(ctrl); left.addStretch()

        right_column_layout = QVBoxLayout()
        self.keypad = KeypadWidget()

        

        self.keypad.value_entered.connect(self.target_input.setValue)
        self.keypad.value_entered.connect(self.set_length)
        right_column_layout.addWidget(self.keypad)
        right_column_layout.addStretch()

        content.addLayout(left, 2)
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
        g1.setContentsMargins(12, 10, 12, 10)
        g1.setHorizontalSpacing(12)
        g1.setVerticalSpacing(10)
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

        # Center: Setup on top + Cut List below
        center_col = QVBoxLayout()
        setup = QGroupBox("Auto-Mode Setup"); g2 = QGridLayout(setup)
        g2.addWidget(QLabel("Board Sensor Location (in):"), 0, 0)
        self.board_sensor_location_input = QDoubleSpinBox(); self.board_sensor_location_input.setRange(0, 2000); self.board_sensor_location_input.setDecimals(4); self.board_sensor_location_input.setValue(10.80); g2.addWidget(self.board_sensor_location_input, 0, 1)
        g2.addWidget(QLabel("Cut Length (in):"), 1, 0)
        self.cut_length_input = QDoubleSpinBox(); self.cut_length_input.setRange(0.1, 2000); self.cut_length_input.setDecimals(4); self.cut_length_input.setValue(18.0); g2.addWidget(self.cut_length_input, 1, 1)
        g2.addWidget(QLabel("Blade Kerf (in):"), 2, 0)
        self.kerf_input = QDoubleSpinBox(); self.kerf_input.setRange(0.0, 0.5); self.kerf_input.setDecimals(4); self.kerf_input.setValue(0.100); g2.addWidget(self.kerf_input, 2, 1)
        self.add_cut_button = QPushButton("Add Cut to List"); self.add_cut_button.clicked.connect(self.add_cut_to_list); g2.addWidget(self.add_cut_button, 3, 0, 1, 2)
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

        self.radio_load_standard = QRadioButton(f"Standard Load (Home position)")
        self.radio_load_135 = QRadioButton(f"10' Load ({self.short_load_pos_135:.2f}\")")
        self.radio_load_96 = QRadioButton(f"8' Load ({self.short_load_pos_96:.2f}\")")
        self.radio_load_72 = QRadioButton(f"6' Load ({self.short_load_pos_72:.2f}\")")
        self.radio_load_60 = QRadioButton(f"4' Load ({self.short_load_pos_60:.2f}\")")

        # Set the standard load as the default checked option
        self.radio_load_standard.setChecked(True)
        
        # Apply a consistent font size and reduce padding for radio buttons
        radio_style = "font-size: 15px; padding: 2px 0; color: #e2e8f0;"
        self.radio_load_standard.setStyleSheet(radio_style)
        self.radio_load_135.setStyleSheet(radio_style)
        self.radio_load_96.setStyleSheet(radio_style)
        self.radio_load_72.setStyleSheet(radio_style)
        self.radio_load_60.setStyleSheet(radio_style)

        self.radio_load_standard.toggled.connect(self.update_cut_list_display)
        self.radio_load_135.toggled.connect(self.update_cut_list_display)
        self.radio_load_96.toggled.connect(self.update_cut_list_display)
        self.radio_load_72.toggled.connect(self.update_cut_list_display)
        self.radio_load_60.toggled.connect(self.update_cut_list_display)

        # Add them to the layout
        radio_layout.addWidget(self.radio_load_standard)
        radio_layout.addWidget(self.radio_load_135)
        radio_layout.addWidget(self.radio_load_96)
        radio_layout.addWidget(self.radio_load_72)
        radio_layout.addWidget(self.radio_load_60)
        
        cyc.addLayout(radio_layout) # Add the radio button layout to the main cycle_group layout
        # --- END MODIFIED SECTION ---

        # The START CYCLE and CUT COMPLETE buttons remain as they were
        self.start_cycle_button = QPushButton("START CYCLE")
        self.start_cycle_button.setProperty("role", "touch")
        self.start_cycle_button.clicked.connect(self.start_auto_cycle)
        self.start_cycle_button.setStyleSheet("""
            QPushButton { background-color: #22c55e; color: white; font-weight: bold; font-size: 24px; min-height: 25px; max-height: 55px; }
            QPushButton:hover { background-color: #16a34a; }
            QPushButton:disabled { background-color: #166534; color: #4ade80; }
        """)
        cyc.addWidget(self.start_cycle_button)

        self.cut_complete_button = QPushButton("CUT COMPLETE")
        self.cut_complete_button.setProperty("role","touch")
        self.cut_complete_button.setEnabled(False)
        self.cut_complete_button.clicked.connect(self.cut_complete_pressed)
        self.cut_complete_button.setStyleSheet("""
            QPushButton { background-color: #1e293b; color: #475569; font-weight: bold; font-size: 24px; min-height: 25px; max-height: 55px; border: 1px solid #334155; }
            QPushButton:enabled { background-color: #2563eb; color: white; border: none; }
            QPushButton:enabled:hover { background-color: #1d4ed8; }
        """)
        cyc.addWidget(self.cut_complete_button)
            
            
        right_col.addWidget(cycle_group)

        # ... (the rest of your create_auto_tab method)





        status_group = QGroupBox("Status")
        sv = QVBoxLayout(status_group)

        # --- NEW: Set the min/max height for the status box ---
        status_group.setMinimumHeight(60) # Adjust this value as needed
        status_group.setMaximumHeight(70) # Adjust this value as needed

        self.auto_status_label = QLabel("STATUS: Waiting to Start")
        self.auto_status_label.setWordWrap(True)
        self.auto_status_label.setStyleSheet("""
            font-weight: bold;
            font-size: 16px;      /* Adjust font size 
        """)


        sv.addWidget(self.auto_status_label)
        right_col.addWidget(status_group)


        # --- MODIFIED: Removed setMaximumWidth(420) to allow widening ---
        right_wrap = QWidget(); right_wrap.setLayout(right_col)
        top_row.addWidget(right_wrap)
        root.addLayout(top_row)

        # Profiles moved to Speed Settings tab
        return w

    def create_speed_tab(self):
        w = QWidget(); root = QVBoxLayout(w)
        profiles = QGroupBox("Auto Profiles - Speeds & Accelerations"); pg = QGridLayout(profiles)

        pg.addWidget(QLabel(f"NORMAL (cutting) - Z{PROFILE_MAP['NORMAL']}"), 0, 0, 1, 2)
        pg.addWidget(QLabel("Max Speed (steps/s)"), 1, 0)
        self.norm_speed = QDoubleSpinBox(); self.norm_speed.setRange(1, 20000); self.norm_speed.setDecimals(0); self.norm_speed.setValue(2500); pg.addWidget(self.norm_speed, 1, 1)
        pg.addWidget(QLabel("Acceleration (steps/s^2)"), 2, 0)
        self.norm_accel = QDoubleSpinBox(); self.norm_accel.setRange(1, 50000); self.norm_accel.setDecimals(0); self.norm_accel.setValue(900); pg.addWidget(self.norm_accel, 2, 1)

        pg.addWidget(QLabel(f"GENTLE approach - Z{PROFILE_MAP['GENTLE']}"), 0, 2, 1, 2)
        pg.addWidget(QLabel("Max Speed (steps/s)"), 1, 2)
        self.gentle_speed = QDoubleSpinBox(); self.gentle_speed.setRange(1, 20000); self.gentle_speed.setDecimals(0); self.gentle_speed.setValue(600); pg.addWidget(self.gentle_speed, 1, 3)
        pg.addWidget(QLabel("Acceleration (steps/s^2)"), 2, 2)
        self.gentle_accel = QDoubleSpinBox(); self.gentle_accel.setRange(1, 50000); self.gentle_accel.setDecimals(0); self.gentle_accel.setValue(600); pg.addWidget(self.gentle_accel, 2, 3)

        pg.addWidget(QLabel(f"FAST return - Z{PROFILE_MAP['FAST']}"), 0, 4, 1, 2)
        pg.addWidget(QLabel("Max Speed (steps/s)"), 1, 4)
        self.fast_speed = QDoubleSpinBox(); self.fast_speed.setRange(1, 20000); self.fast_speed.setDecimals(0); self.fast_speed.setValue(3500); pg.addWidget(self.fast_speed, 1, 5)
        pg.addWidget(QLabel("Acceleration (steps/s^2)"), 2, 4)
        self.fast_accel = QDoubleSpinBox(); self.fast_accel.setRange(1, 50000); self.fast_accel.setDecimals(0); self.fast_accel.setValue(2500); pg.addWidget(self.fast_accel, 2, 5)

        self.apply_profile_btn = QPushButton("Apply Selected Profile Settings Now"); self.apply_profile_btn.clicked.connect(self.apply_current_profile_params); pg.addWidget(self.apply_profile_btn, 3, 0, 1, 6)
        root.addWidget(profiles)

        serial_group = QGroupBox("Serial Monitor")
        serial_layout = QVBoxLayout(serial_group)
        serial_hint = QLabel("Live inbound serial messages from the controller.")
        serial_hint.setStyleSheet("color:#94a3b8; font-size:13px;")
        serial_layout.addWidget(serial_hint)
        self.speed_serial_console = QTextBrowser()
        self.speed_serial_console.setMinimumHeight(320)
        self.speed_serial_console.setOpenExternalLinks(False)
        serial_layout.addWidget(self.speed_serial_console)
        root.addWidget(serial_group, stretch=1)
        return w
    
    def create_preset_tab(self):
        storage_path = os.path.join(get_app_dir(), "cutlists.json")
        return CutListManagerTab(
            storage_path=storage_path,
            on_load_lines=self.load_cut_list_lines,
            on_switch_to_auto=lambda: self.tabs.setCurrentIndex(1),
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

        # Cylinders
        cylinders_group = QGroupBox("Air Cylinders")
        cyl_layout = QHBoxLayout(cylinders_group)
        cyl_layout.setSpacing(12)

        cyl_defs = [
            ("Left Clamp", 1, "fa_cyl1_status"),
            ("Right Clamp", 2, "fa_cyl2_status"),
            ("Fence Clamp", 3, "fa_cyl3_status"),
        ]
        for cyl_name, cyl_id, pill_attr in cyl_defs:
            cyl_col = QVBoxLayout()
            name_lbl = QLabel(cyl_name)
            name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            name_lbl.setStyleSheet("font-weight: bold; font-size: 15px;")
            cyl_col.addWidget(name_lbl)

            status_pill = self.pill("RETRACTED", "#475569")
            setattr(self, pill_attr, status_pill)
            cyl_col.addWidget(status_pill)

            cyl_col.addStretch()
            cyl_layout.addLayout(cyl_col)

        io_and_cycle.addWidget(cylinders_group)

        # Timing Settings
        timing_group = QGroupBox("Timing Settings")
        timing_form = QFormLayout(timing_group)
        timing_form.setContentsMargins(10, 8, 10, 8)
        timing_form.setSpacing(8)

        self.fa_clamp_engage_delay = QSpinBox()
        self.fa_clamp_engage_delay.setRange(0, 5000)
        self.fa_clamp_engage_delay.setValue(300)
        self.fa_clamp_engage_delay.setSuffix(" ms")
        self.fa_clamp_engage_delay.setToolTip("Delay after board arrives before clamp signals fire (settle time)")
        timing_form.addRow("Clamp Engage Delay:", self.fa_clamp_engage_delay)

        self.fa_saw_start_delay = QSpinBox()
        self.fa_saw_start_delay.setRange(0, 5000)
        self.fa_saw_start_delay.setValue(800)
        self.fa_saw_start_delay.setSuffix(" ms")
        self.fa_saw_start_delay.setToolTip("Delay after clamp command before saw actuates (clamp close time)")
        timing_form.addRow("Saw Start Delay:", self.fa_saw_start_delay)

        io_and_cycle.addWidget(timing_group)

        io_and_cycle.addStretch()

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

        self.fa_cut_complete_button = QPushButton("CUT COMPLETE")
        self.fa_cut_complete_button.setFixedHeight(50)
        self.fa_cut_complete_button.setMinimumWidth(160)
        self.fa_cut_complete_button.setEnabled(False)
        self.fa_cut_complete_button.setStyleSheet("""
            QPushButton { background-color: #1e293b; color: #475569; font-weight: bold; font-size: 17px; border-radius: 10px; padding: 0 16px; border: 1px solid #334155; }
            QPushButton:enabled { background-color: #2563eb; color: white; border: none; }
            QPushButton:enabled:hover { background-color: #1d4ed8; }
        """)
        self.fa_cut_complete_button.clicked.connect(self.cut_complete_pressed)
        bottom_row.addWidget(self.fa_cut_complete_button)

        bottom_widget = QWidget()
        bottom_widget.setLayout(bottom_row)
        bottom_widget.setFixedHeight(58)
        root_layout.addWidget(bottom_widget)

        return w

    def cylinder_extend(self, cyl_id):
        self.send_command(f"C{cyl_id}")
        if cyl_id == 1:
            self.clamp_left_engaged = True
        elif cyl_id == 2:
            self.clamp_right_engaged = True
        elif cyl_id == 3:
            self.clamp_fence_engaged = True
        self._update_cylinder_ui(cyl_id)

    def cylinder_retract(self, cyl_id):
        self.send_command(f"D{cyl_id}")
        if cyl_id == 1:
            self.clamp_left_engaged = False
        elif cyl_id == 2:
            self.clamp_right_engaged = False
        elif cyl_id == 3:
            self.clamp_fence_engaged = False
        self._update_cylinder_ui(cyl_id)

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
                pill_widget.setText("EXTENDED")
                pill_widget.setStyleSheet(
                    "background-color: #2563eb; color: white; font-weight: bold; border-radius:10px; padding:4px 8px;"
                )
            else:
                pill_widget.setText("RETRACTED")
                pill_widget.setStyleSheet(
                    "background-color: #475569; color: #e2e8f0; font-weight: bold; border-radius:10px; padding:4px 8px;"
                )

    def _update_saw_sensor_pill(self, text, color):
        if hasattr(self, 'fa_saw_position_label'):
            self.fa_saw_position_label.setText(text)
            self.fa_saw_position_label.setStyleSheet(
                f"background-color: {color}; color: white; font-weight: bold; border-radius:10px; padding:4px 8px;"
            )

    def update_saw_position_sensor_status(self, status):
        """
        Called by real serial handler (status=1 UP, status=0 DOWN) and by simulation.
        Sensor-gated: release clamps only when saw confirms it is UP.
        """
        text = "UP" if status == 1 else "DOWN"
        color = "#22c55e" if status == 1 else "#ef4444"
        self._update_saw_sensor_pill(text, color)

        if status == 1 and self.clamps_engaged_cutting:
            self.clamps_engaged_cutting = False
            self._release_all_clamps()
            if self.is_early_returning:
                self._set_cycle_status("STATUS: Saw up — clamps released. Loading next board...")
            else:
                self._set_cycle_status("STATUS: Saw up — clamps released. Press CUT COMPLETE.")

    def _actuate_saw(self):
        """
        Fire saw-down command (placeholder until hardware wired).
        Sets clamps_engaged_cutting so update_saw_position_sensor_status
        knows to release clamps when the saw returns UP.
        """
        self.clamps_engaged_cutting = True
        self._update_saw_sensor_pill("CUTTING", "#ef4444")
        self._set_cycle_status("STATUS: Cutting...")
        # TODO: self.send_command("V1")  ← real saw actuate command
        # Simulate saw returning UP after 2 s
        QTimer.singleShot(2000, lambda: self.update_saw_position_sensor_status(1))

    def _release_all_clamps(self):
        """Retract all three air cylinder clamps."""
        self.cylinder_retract(1)
        self.cylinder_retract(2)
        self.cylinder_retract(3)

    def _engage_clamps_for_cut(self):
        """
        Clamp logic for normal cut positions (truing and mid-board cuts).
        Applies clamp-engage delay, then saw-start delay before actuating.
        Clamp release is sensor-gated via update_saw_position_sensor_status.

        Rules:
          Truing cut          → Left + Fence only
          position >= 3\"      → All three
          position < 3\"       → Right only
        """
        try:
            position = float(self.position_label.text())
        except ValueError:
            position = 0.0

        is_truing = (self.auto_cycle_state == "WAITING_FOR_TRUING_CUT")

        if is_truing:
            clamps = [1, 3]
            self._set_cycle_status("STATUS: Board in position — clamping L+F...")
        elif position >= 3.0:
            clamps = [1, 2, 3]
            self._set_cycle_status("STATUS: Board in position — clamping all...")
        else:
            clamps = [2]
            self._set_cycle_status(f"STATUS: Short tail ({position:.2f}\") — clamping R only...")

        clamp_delay = self.fa_clamp_engage_delay.value() if hasattr(self, 'fa_clamp_engage_delay') else 300
        saw_delay   = self.fa_saw_start_delay.value()    if hasattr(self, 'fa_saw_start_delay')    else 800

        def _do_clamp():
            for cid in clamps:
                self.cylinder_extend(cid)
            QTimer.singleShot(saw_delay, self._actuate_saw)

        QTimer.singleShot(clamp_delay, _do_clamp)

    def _engage_clamps_for_early_return(self):
        """
        Clamp logic for the last cut on a board (carriage already returning home).
        Same delay chain as normal cuts; clamp release is sensor-gated.

        position >= 3\" → all three clamps
        position < 3\"  → right clamp only
        """
        try:
            position = float(self.position_label.text())
        except ValueError:
            position = 0.0

        if position >= 3.0:
            clamps = [1, 2, 3]
            self._set_cycle_status("STATUS: Last cut — clamping all, returning...")
        else:
            clamps = [2]
            self._set_cycle_status(f"STATUS: Last cut, short tail ({position:.2f}\") — R clamp, returning...")

        clamp_delay = self.fa_clamp_engage_delay.value() if hasattr(self, 'fa_clamp_engage_delay') else 300
        saw_delay   = self.fa_saw_start_delay.value()    if hasattr(self, 'fa_saw_start_delay')    else 800

        def _do_clamp():
            for cid in clamps:
                self.cylinder_extend(cid)
            QTimer.singleShot(saw_delay, self._actuate_saw)

        QTimer.singleShot(clamp_delay, _do_clamp)

    def load_cut_list_lines(self, lines):
        self._rebuild_cut_list(lines)

    # ---------- Clamp Control Methods ----------
    def toggle_clamp(self):
        self.clamp_engaged = not self.clamp_engaged
        cmd = 'L' if self.clamp_engaged else 'U'
        self.send_command(cmd)
        self.update_clamp_ui()

    def update_clamp_ui(self):
        if self.clamp_engaged:
            active_style = "background-color: #2563eb; color: white; font-weight: bold;"
            if hasattr(self, 'clamp_button'):
                self.clamp_button.setText("UNCLAMP")
                self.clamp_button.setStyleSheet(active_style)
            self.auto_clamp_status_label.setText("CLAMPED")
            self.auto_clamp_status_label.setStyleSheet(f"{active_style} border-radius:10px; padding:4px 8px;")
        else:
            inactive_style = "background-color: #4b5563; color: #e2e8f0; font-weight: bold;"
            if hasattr(self, 'clamp_button'):
                self.clamp_button.setText("CLAMP")
                self.clamp_button.setStyleSheet(inactive_style)
            self.auto_clamp_status_label.setText("UNCLAMPED")
            self.auto_clamp_status_label.setStyleSheet(f"{inactive_style} border-radius:10px; padding:4px 8px;")

    # ---------- Enable/Disable ----------
    def set_controls_enabled(self, enabled):
        self.legacy_tab.setEnabled(enabled)
        self.auto_tab.setEnabled(enabled)
        if hasattr(self, 'full_auto_tab'):
            self.full_auto_tab.setEnabled(enabled)

    # ---------- Cut list ----------
    def add_cut_to_list(self):
        L = self.cut_length_input.value()
        if L > 0:
            self.cut_list.append((self.next_cut_number, L, ""))
            self.next_cut_number += 1
            self.update_cut_list_display()

    def clear_cut_list(self):
        self.cut_list.clear()
        self.next_cut_number = 1
        self.current_cut_index = 0
        self.update_cut_list_display()

    def get_active_board_length(self):
        if self.radio_load_135.isChecked():
            return self.short_board_length_135
        if self.radio_load_96.isChecked():
            return self.short_board_length_96
        if self.radio_load_72.isChecked():
            return self.short_board_length_72
        if self.radio_load_60.isChecked():
            return self.short_board_length_60
        return self.standard_board_length

    def update_cut_list_display(self):
        if not self.cut_list:
            self.cut_list_display.setText("")
            self.cut_list_display.setPlaceholderText("No cuts in list.")
            if hasattr(self, 'board_fill_bar'):
                self.board_fill_bar.setValue(0)
                self.board_fill_bar.setStyleSheet("""
                    QProgressBar { background-color: #1e293b; border-radius: 8px; border: 1px solid #334155; }
                    QProgressBar::chunk { background-color: #38bdf8; border-radius: 8px; }
                """)
            if hasattr(self, 'board_fill_label'):
                self.board_fill_label.setText("No cuts loaded")
            if hasattr(self, 'fa_cut_list_display'):
                self.fa_cut_list_display.setText("")
                self.fa_cut_list_display.setPlaceholderText("No cuts in list.")
            if hasattr(self, 'fa_board_fill_bar'):
                self.fa_board_fill_bar.setValue(0)
                self.fa_board_fill_bar.setStyleSheet("""
                    QProgressBar { background-color: #1e293b; border-radius: 8px; border: 1px solid #334155; }
                    QProgressBar::chunk { background-color: #38bdf8; border-radius: 8px; }
                """)
            if hasattr(self, 'fa_board_fill_label'):
                self.fa_board_fill_label.setText("No cuts loaded")
            return

        cursor = self.cut_list_display.textCursor()

        html_lines = []
        current_line_start_pos = 0
        board_length = self.get_active_board_length()
        kerf = self.kerf_input.value()
        group_colors = ["#38bdf8", "#f59e0b"]
        group_index = 0
        used_length = 0.0

        # Pre-pass: compute which group each cut belongs to and each group's used length
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

        # Determine the active board group (the one containing current_cut_index)
        if self.current_cut_index < len(cut_groups):
            active_group = cut_groups[self.current_cut_index]
        else:
            active_group = cut_groups[-1] if cut_groups else 0

        active_used = group_used_map.get(active_group, 0.0)
        fill_ratio = min(1.0, active_used / board_length) if board_length > 0 else 0.0
        fill_color = group_colors[active_group % len(group_colors)]

        if hasattr(self, 'board_fill_bar'):
            self.board_fill_bar.setValue(int(fill_ratio * 1000))
            self.board_fill_bar.setStyleSheet(f"""
                QProgressBar {{ background-color: #1e293b; border-radius: 8px; border: 1px solid #334155; }}
                QProgressBar::chunk {{ background-color: {fill_color}; border-radius: 8px; }}
            """)
        if hasattr(self, 'board_fill_label'):
            self.board_fill_label.setText(
                f"Board {active_group + 1}: {active_used:.2f}\" / {board_length:.2f}\" ({fill_ratio * 100:.1f}%)"
            )

        for i, (num, length, desc) in enumerate(self.cut_list):
            needed = length + kerf
            if used_length + needed > board_length and used_length > 0:
                group_index += 1
                used_length = 0.0
            used_length += needed
            color = group_colors[group_index % len(group_colors)]

            line_text = f"Cut {num}: {length:<9.4f}\" {desc}"
            
            if i == self.current_cut_index:
                current_line_start_pos = len("<br>".join(html_lines))
                html_lines.append(
                    f"<div style='background-color:#334155;'><b><span style='color:{color};'>&gt; {line_text}</span></b></div>"
                )
            else:
                html_lines.append(f"<span style='color:{color};'>&nbsp; {line_text}</span>")
        
        html = "<br>".join(html_lines)
        self.cut_list_display.setHtml(html)

        cursor.setPosition(current_line_start_pos)
        self.cut_list_display.setTextCursor(cursor)
        self.cut_list_display.ensureCursorVisible()

        # Mirror to FULL AUTO tab
        if hasattr(self, 'fa_cut_list_display'):
            self.fa_cut_list_display.setHtml(html)
        if hasattr(self, 'fa_board_fill_bar'):
            self.fa_board_fill_bar.setValue(int(fill_ratio * 1000))
            self.fa_board_fill_bar.setStyleSheet(f"""
                QProgressBar {{ background-color: #1e293b; border-radius: 8px; border: 1px solid #334155; }}
                QProgressBar::chunk {{ background-color: {fill_color}; border-radius: 8px; }}
            """)
        if hasattr(self, 'fa_board_fill_label'):
            self.fa_board_fill_label.setText(
                f"Board {active_group + 1}: {active_used:.2f}\" / {board_length:.2f}\" ({fill_ratio * 100:.1f}%)"
            )

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
        self.update_cut_list_display()
        self.log.append(f"Loaded {len(self.cut_list)} cuts into the list.")

    # ---------- Auto Cycle ----------
    # --- NEW: Method to cancel the auto cycle ---
    def cancel_auto_cycle(self):
        """Stops any active auto cycle and resets the state."""
        # 1. Send a command to stop the motor's current movement. M0 (Move 0) is a safe stop command.
        self.send_command("M0")
        self.log.append("Auto cycle canceled by user.")

        # 2. Reset the state machine and related flags
        self.auto_cycle_state = "IDLE"
        self.perform_early_return = False
        self.is_early_returning = False
        self.current_cut_index = 0

        # 3. Update UI controls and status
        self._release_all_clamps()
        self._update_saw_sensor_pill("--", "#475569")
        self._set_cycle_status("STATUS: Cycle Canceled. Ready.")
        self._set_start_enabled(True)
        self._set_cut_complete_enabled(False)
        self.update_cut_list_display() # Refresh list to show first item as current
    # --- END NEW ---

    def resume_after_reset(self):
        
        # Use after the driver faults, you reset it and rehome.
        # This resumes at the CURRENT cut index without losing your place.
        # It does NOT increment the cut; it re-advances for the same cut length.
        
        # 0) Guard rails
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

        # 3) Tell the UI/state machine what's happening
        cut_num, cut_length, _ = self.cut_list[self.current_cut_index]
        status_text = f"STATUS: Resuming after reset at cut {cut_num} ({cut_length:.2f}\")"
        self.auto_status_label.setText(status_text)
        if hasattr(self, 'fa_auto_status_label'):
            self.fa_auto_status_label.setText(status_text)
        self.update_cut_list_display()

        # 4) Choose a profile and state, then let the normal logic take over
        self.switch_profile("GENTLE", True)
        self.auto_cycle_state = "DETECTING"
        self._set_start_enabled(False)
        self._set_cut_complete_enabled(False)

        # 5) Kick the state machine
        self.advance_auto_cycle()


    def start_auto_cycle(self):
        if self.homed_label.text() != "HOMED":
            self.log.append("AUTO MODE ERROR: System must be homed first."); return
        if not self.cut_list:
            self.log.append("AUTO MODE ERROR: Cut list is empty."); return
            
        if self.auto_cycle_state == "IDLE" or self.auto_cycle_state == "FINISHED":
            self.current_cut_index = 0
        
        self.update_cut_list_display()
        self.switch_profile("GENTLE", True)
        self.auto_cycle_state = "DETECTING"
        self.advance_auto_cycle()

    def cut_complete_pressed(self):
        self._release_all_clamps()
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
        self.start_cycle_button.setEnabled(enabled)
        if hasattr(self, 'fa_start_cycle_button'):
            self.fa_start_cycle_button.setEnabled(enabled)

    def _set_cut_complete_enabled(self, enabled):
        self.cut_complete_button.setEnabled(enabled)
        if hasattr(self, 'fa_cut_complete_button'):
            self.fa_cut_complete_button.setEnabled(enabled)

    def advance_auto_cycle(self):
        self.perform_early_return = False # Reset flag at start of each advance
        if self.auto_cycle_state == "DETECTING":
            self._set_cycle_status("STATUS: Detecting board edge...")
            sensor_offset = self.board_sensor_location_input.value()
            self.send_command(f"J{sensor_offset:.4f}")
            self.auto_cycle_state = "WAITING_FOR_TRUING_CUT"
            self._set_start_enabled(False)
            self._set_cut_complete_enabled(False)
        elif self.auto_cycle_state == "ADVANCING":
            if self.current_cut_index >= len(self.cut_list):
                self.auto_cycle_state = "FINISHED"; self.advance_auto_cycle(); return

            current_pos = float(self.position_label.text())
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
        if not ports:
            self.port_combo.addItem("No ports detected", "")
            self.port_combo.setEnabled(False)
            self.selected_serial_port = ""
        else:
            for port in ports:
                description = f"{port.device} - {port.description}" if port.description else port.device
                self.port_combo.addItem(description, port.device)
            self.port_combo.setEnabled(True)
            target_port = previous_port if any(port.device == previous_port for port in ports) else ports[0].device
            index = self.port_combo.findData(target_port)
            if index >= 0:
                self.port_combo.setCurrentIndex(index)
                self.selected_serial_port = target_port
        self.port_combo.blockSignals(False)

    def on_serial_port_changed(self):
        if hasattr(self, "port_combo"):
            self.selected_serial_port = self.port_combo.currentData() or ""

    def toggle_connection(self):
        if self.ser is None or not self.ser.is_open:
            port_name = self.selected_serial_port or SERIAL_PORT
            if not port_name:
                self.log.append("ERROR: No serial ports detected.")
                return
            try:
                self.ser = serial.Serial(port_name, BAUD_RATE, timeout=1)
                self.status_label.setText("Connected"); self.status_label.setStyleSheet("background-color:#22c55e; color:#0f172a; font-weight:bold; border-radius:12px; padding:6px 10px;")
                self.connect_button.setText("Disconnect"); self.set_controls_enabled(True)
                self.listener_thread = threading.Thread(target=listen_for_data, args=(self.ser, self.signal_bridge), daemon=True); self.listener_thread.start()
                self.log.append(f"Successfully connected to {port_name}")
                self.apply_current_protection_settings()
                self.update_current_monitor_ui()
            except serial.SerialException as e:
                self.log.append(f"ERROR: {e}")
                self.refresh_serial_ports()
        else:
            try: self.ser.close()
            except Exception: pass
            self.status_label.setText("Disconnected"); self.status_label.setStyleSheet("background-color:#ef4444; color:white; font-weight:bold; border-radius:12px; padding:6px 10px;")
            self.connect_button.setText("Connect"); self.set_controls_enabled(False); self.log.append("Disconnected.")

    def handle_serial_disconnect(self, error):
        try:
            if self.ser and self.ser.is_open:
                self.ser.close()
        except Exception:
            pass
        self.status_label.setText("Disconnected")
        self.status_label.setStyleSheet("background-color:#ef4444; color:white; font-weight:bold; border-radius:12px; padding:6px 10px;")
        self.connect_button.setText("Connect")
        self.set_controls_enabled(False)
        self.log.append(f"Serial connection lost: {error}")

    def send_command(self, cmd):
        if self.ser and self.ser.is_open:
            try:
                self.ser.write((cmd + '\n').encode('utf-8'))
                self.log.append(f"Sent: '{cmd}'")
            except (serial.SerialException, OSError) as error:
                self.handle_serial_disconnect(error)
        else: self.log.append("Cannot send command, not connected.")

    def home_motor(self): self.send_command("H")
    def near_calibrate(self):
        if self.homed_label.text() != "HOMED":
            self.log.append("NEAR CAL ERROR: System must be homed first.")
            return
        sensor_offset = self.board_sensor_location_input.value() if hasattr(self, 'board_sensor_location_input') else self.board_sensor_distance_inches
        self.board_sensor_distance_inches = sensor_offset
        self.log.append(f"Starting near calibration using board sensor offset {sensor_offset:.4f}\".")
        self.send_command(f"N{sensor_offset:.4f}")

    # --- MODIFIED: Added logic for short load position ---
    def load_position(self):
        self.switch_profile("FAST", True)
        
        # Check which radio button is selected to determine the target position
        if self.radio_load_135.isChecked():
            target_pos = self.short_load_pos_135
            log_msg = f"Moving to short load position: {target_pos:.2f}\""
        elif self.radio_load_96.isChecked():
            target_pos = self.short_load_pos_96
            log_msg = f"Moving to short load position: {target_pos:.2f}\""
        elif self.radio_load_72.isChecked():
            target_pos = self.short_load_pos_72
            log_msg = f"Moving to short load position: {target_pos:.2f}\""
        elif self.radio_load_60.isChecked():
            target_pos = self.short_load_pos_60
            log_msg = f"Moving to short load position: {target_pos:.2f}\""
        else: # Default case is the standard home position
            target_pos = self.home_position
            log_msg = f"Moving to HOME load position: {target_pos:.2f}\""

        self.log.append(log_msg)
        self.set_length(target_pos)
    # --- END MODIFICATION ---

    def toggle_motor_power(self, checked): self.send_command("E" if checked else "X")
    def toggle_pid_control(self, checked): self.send_command("K1" if checked else "K0")

    # Replace the current set_length function with this:
    def set_length(self, length=None):
        target = length if length is not None else self.target_input.value()

        # --- THIS IS THE GATEKEEPER CHECK ---
        if 0.0 <= target <= self.home_position:
            self.prepare_prediction(target)
            self.send_command(f"S{target:.4f}")
        else:
            self.log.append(f"MOVE REJECTED: Target {target:.2f}\" is outside the valid range (0 to {self.home_position:.2f}\").")
    def move_relative(self):
        delta = self.rel_input.value()
        current_pos = float(self.position_label.text())
        target = current_pos + delta

        # Instead of sending its own command, it now uses our safe function
        self.set_length(target)
    # AUTO jog helper: move by a relative delta from current auto position
    def auto_jog(self, delta):
        try:
            current_pos = float(self.auto_position_label.text())
        except Exception:
            current_pos = 0.0
        target = current_pos + float(delta)
        self.set_length(target)
    def set_motor_parameters(self):
        speed = self.max_speed.value(); accel = self.acceleration.value(); self.send_command(f"A{speed:.0f},{accel:.0f}")
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
                self.current_status_label.setText("Current OK")
                self.current_status_label.setStyleSheet("background-color:#22c55e; color:#0f172a; font-weight:bold; border-radius:12px; padding:6px 10px;")
            else:
                self.current_status_label.setText("Monitoring Off")
                self.current_status_label.setStyleSheet("background-color:#475569; color:#e2e8f0; font-weight:bold; border-radius:12px; padding:6px 10px;")
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
        self.send_command(f"W{1 if self.current_monitoring_enabled else 0}")
        if self.current_monitoring_enabled:
            self.send_command(f"O{self.current_limit_amps:.2f},{self.current_trip_delay_ms}")
        self.update_current_monitor_ui()

    def reset_overcurrent_trip(self):
        if not self.current_monitoring_enabled:
            return
        self.send_command("R")
        self.update_overcurrent_status(0)
        if hasattr(self, "auto_status_label"):
            self._set_cycle_status("STATUS: Overcurrent reset requested.")

    def initiate_calibration(self): self.send_command(f"C{self.calibrate_input.value():.4f}")

    # ---------- Profiles ----------
    def switch_profile(self, name, push_params=True):
        if name not in PROFILE_MAP: self.log.append(f"Unknown profile '{name}'"); return
        idx = PROFILE_MAP[name]; self.send_command(f"Z{idx}"); self.active_profile_name = name
        if push_params:
            if name == "NORMAL": spd, acc = self.norm_speed.value(), self.norm_accel.value()
            elif name == "GENTLE": spd, acc = self.gentle_speed.value(), self.gentle_accel.value()
            else: spd, acc = self.fast_speed.value(), self.fast_accel.value()
            self.send_command(f"A{spd:.0f},{acc:.0f}"); self.log.append(f"Applied {name} profile params: speed={spd:.0f}, accel={acc:.0f}")
    def apply_current_profile_params(self): self.switch_profile(self.active_profile_name, True)

    # ---------- Position updates ----------
    def update_message_log(self, msg):
        self.log.append(msg)
        if hasattr(self, "speed_serial_console"):
            self.speed_serial_console.append(msg)
    def update_position_label_from_device(self, pos):
        self.position_label.setText(f"{pos:.4f}")
        self.auto_position_label.setText(f"{pos:.4f}")
        if hasattr(self, 'fa_position_label'):
            self.fa_position_label.setText(f"{pos:.4f}")
        if self.pred_active: self.pred_start_pos = pos; self.pred_start_time = time.monotonic()

    def update_homed_status(self, status):
        text = "HOMED" if status == 1 else "NOT HOMED"; color = "#22c55e" if status == 1 else "orange"
        self.homed_label.setText(text); self.homed_label.setStyleSheet(f"color: {color}; font-weight: bold;")

    def update_motor_state(self, state):
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
                # Last cut on this board — clamp, simulate cut, and return in parallel.
                # Clamps auto-release after 2 s; no CUT COMPLETE needed.
                self.perform_early_return = False
                self.is_early_returning = True

                self._engage_clamps_for_early_return()  # clamps + 2 s auto-release

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
                self._engage_clamps_for_cut()

    def update_sensor_status(self, status):
        text = "ON" if status == 1 else "OFF"; bg = "#22c55e" if status == 1 else "#ef4444"
        self.sensor_label.setText(text); self.sensor_label.setStyleSheet(f"background-color: {bg}; color: white; font-weight: bold; border-radius:12px; padding:6px 10px;")
        self.auto_homing_sensor_label.setText(text); self.auto_homing_sensor_label.setStyleSheet(f"background-color: {bg}; color: white; font-weight: bold; border-radius:10px; padding:4px 8px;")
        if hasattr(self, 'fa_homing_sensor_label'):
            self.fa_homing_sensor_label.setText(text)
            self.fa_homing_sensor_label.setStyleSheet(f"background-color: {bg}; color: white; font-weight: bold; border-radius:10px; padding:4px 8px;")

    def update_board_sensor_status(self, status):
        text = "ON" if status == 1 else "OFF"; bg = "#22c55e" if status == 1 else "#ef4444"
        self.board_sensor_tripped = (status == 1)

        self.board_sensor_label.setText(text); self.board_sensor_label.setStyleSheet(f"background-color: {bg}; color: white; font-weight: bold; border-radius:10px; padding:4px 8px;")
        self.auto_board_sensor_label.setText(text); self.auto_board_sensor_label.setStyleSheet(f"background-color: {bg}; color: white; font-weight: bold; border-radius:10px; padding:4px 8px;")
        if hasattr(self, 'fa_board_sensor_label'):
            self.fa_board_sensor_label.setText(text)
            self.fa_board_sensor_label.setStyleSheet(f"background-color: {bg}; color: white; font-weight: bold; border-radius:10px; padding:4px 8px;")

    def update_current_voltage(self, volts):
        self.current_sensor_voltage = max(0.0, volts)

    def append_current_log_row(self):
        now = time.monotonic()
        if now - self.last_current_log_time < 0.25:
            return
        self.last_current_log_time = now

        log_exists = os.path.exists(self.current_log_path)
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
                self.current_status_label.setText("Overcurrent Tripped")
                self.current_status_label.setStyleSheet("background-color:#ef4444; color:white; font-weight:bold; border-radius:12px; padding:6px 10px;")
                if hasattr(self, 'auto_status_label'):
                    self._set_cycle_status("STATUS: Overcurrent protection tripped.")
            else:
                self.current_status_label.setText("Current OK")
                self.current_status_label.setStyleSheet("background-color:#22c55e; color:#0f172a; font-weight:bold; border-radius:12px; padding:6px 10px;")

    def update_calibration_factors(self, new_encoder_tpi, new_stepper_spi):
        self.encoder_ticks_per_inch = new_encoder_tpi; self.stepper_steps_per_inch = new_stepper_spi; self.log.append("HMI calibration factors updated.")

    def update_home_position(self, pos):
        self.home_position = pos
        self.log.append(f"Max travel distance set to: {pos}\"")
        try:
            # --- ADD THE NEW LINE HERE ---
            if hasattr(self, 'target_input') and self.target_input is not None:
                self.target_input.setRange(0.0, pos)

            if hasattr(self, 'board_sensor_location_input') and self.board_sensor_location_input is not None:
                self.board_sensor_location_input.setRange(0, pos)
                
            if hasattr(self, 'load_button') and self.load_button is not None:
                self.load_button.setText(f"LOAD POSITION ({pos:.2f}\")")
                
        except Exception as e:
            print("update_home_position guarded:", e)

    # ---------- Prediction model ----------
    def prepare_prediction(self, target_in):
        try: start_in = float(self.position_label.text())
        except ValueError: start_in = 0.0
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

    def closeEvent(self, event):
        try:
            if self.ser and self.ser.is_open: self.ser.close()
        except Exception: pass
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    icon_path = get_icon_path()
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    window = MinimalHMI()
    window.show()
    sys.exit(app.exec())
