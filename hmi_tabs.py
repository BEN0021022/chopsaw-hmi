"""PyQt6 tab layout builders and application theme for MinimalHMI."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QTextBrowser,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from _version import __version__ as APP_VERSION
from manual_pneumatics import ManualPneumatics
from pneumatic_timing import CylinderTimingPanel
from sim_view import SawSimWidget
from ui_components import CurrentGraphWidget, CutLengthKeypad, KeypadWidget


APP_STYLESHEET = """
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

    QPushButton[role="touch"] {
        min-height: 80px;
        min-width: 120px;
        font-size: 32px;
        font-weight: 800;
        padding: 12px 14px;
    }
    QPushButton[class="primary"] { background: #2563eb; border: none; }
    QPushButton[class="primary"]:hover { background: #1d4ed8; }
    QPushButton[class="accent"] { background: #10b981; border: none; }
    QPushButton[class="accent"]:hover { background: #059669; }
    QCheckBox { color: #e2e8f0; font-size: 15px; padding: 8px 0; }

    QPushButton[role="small"] {
        background: #1e293b; color: #e2e8f0; border: 1px solid #334155;
        padding: 6px 10px; border-radius: 10px; font-weight: 600;
        min-height: 32px; min-width: 0px;
        font-size: 14px;
    }
    QPushButton[role="small"]:hover { background: #243142; }
"""


def build_manual_tab(w):
    """Build the Manual / Simulator tab and attach its widgets onto window `w`."""
    tab = QWidget()
    content = QHBoxLayout(tab)
    left_scroll = QScrollArea()
    left_scroll.setWidgetResizable(True)
    left_scroll.setStyleSheet('QScrollArea { background:#0b1222; border:0; }')
    left_body = QWidget()
    left_body.setObjectName('manualBody')
    left_body.setStyleSheet('QWidget#manualBody { background:#0b1222; }')
    left = QVBoxLayout(left_body)
    left_scroll.setWidget(left_body)

    dash = QGroupBox("Dashboard")
    grid = QGridLayout(dash)
    grid.addWidget(QLabel("Homed Status:"), 0, 0)
    w.homed_label = QLabel("NOT HOMED")
    w.homed_label.setStyleSheet("color: orange; font-weight: bold;")
    grid.addWidget(w.homed_label, 0, 1)
    grid.addWidget(QLabel("Motor State:"), 1, 0)
    w.state_label = QLabel("IDLE")
    w.state_label.setStyleSheet("color: #22c55e; font-weight: bold;")
    grid.addWidget(w.state_label, 1, 1)
    grid.addWidget(QLabel("Homing Sensor:"), 2, 0)
    w.sensor_label = w.pill("OFF", "#ef4444")
    grid.addWidget(w.sensor_label, 2, 1)
    grid.addWidget(QLabel("Board Sensor:"), 3, 0)
    w.board_sensor_label = w.pill("OFF", "#ef4444")
    grid.addWidget(w.board_sensor_label, 3, 1)
    grid.addWidget(QLabel("Current Position (in):"), 4, 0)
    w.position_label = QLabel("0.0000")
    w.position_label.setStyleSheet("font-size: 24px; font-weight: bold; color: #60a5fa;")
    grid.addWidget(w.position_label, 4, 1)
    dash.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
    left.addWidget(dash)

    ctrl = QWidget()
    v = QVBoxLayout(ctrl)
    v.setContentsMargins(0, 0, 0, 0)
    w.enable_chk = QCheckBox("Motor Power Enabled")
    w.enable_chk.toggled.connect(w.toggle_motor_power)
    v.addWidget(w.enable_chk)
    w.enable_chk.hide()
    w.manual_home_button = QPushButton("Home")
    w.manual_home_button.clicked.connect(w.home_motor)
    v.addWidget(w.manual_home_button)
    ctrl.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
    left.addWidget(ctrl)

    w.manual_pneumatics = ManualPneumatics(w)
    left.addWidget(w.manual_pneumatics)
    left.addStretch()

    right_column_layout = QVBoxLayout()
    right_column_layout.addWidget(QLabel("Carriage target (in)"))
    w.keypad = KeypadWidget()
    w.keypad.setToolTip(
        "Enter a carriage target in inches. ENTER requests a move using the active controller's checks."
    )
    w.keypad.value_entered.connect(w.set_length)
    right_column_layout.addWidget(w.keypad)
    right_column_layout.addStretch()

    content.addWidget(left_scroll, 2)
    content.addLayout(right_column_layout, 1)
    return tab


def build_auto_tab(w):
    """Build the Auto / Semi-Auto tab and attach its widgets onto window `w`."""
    panel = QWidget()
    root = QVBoxLayout(panel)
    top_row = QHBoxLayout()
    top_row.setSpacing(5)
    top_row.setContentsMargins(5, 5, 5, 5)

    # Left: Live Status + Current Monitor (Sim) + Jog
    left_col = QVBoxLayout()
    live = QGroupBox("Live Status")
    g1 = QGridLayout(live)
    w.auto_live_status = live
    live.setObjectName("autoLiveStatus")
    g1.setContentsMargins(12, 10, 12, 10)
    g1.setHorizontalSpacing(12)
    g1.setVerticalSpacing(4)
    g1.setColumnStretch(0, 0)
    g1.setColumnStretch(1, 1)
    g1.addWidget(QLabel("Current Position (in):"), 0, 0)
    w.auto_position_label = QLabel("0.0000")
    w.auto_position_label.setStyleSheet("font-size: 24px; font-weight: bold; color: #60a5fa;")
    w.auto_position_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    g1.addWidget(w.auto_position_label, 0, 1)
    g1.addWidget(QLabel("Homing Sensor:"), 1, 0)
    w.auto_homing_sensor_label = w.pill("OFF", "#ef4444")
    g1.addWidget(w.auto_homing_sensor_label, 1, 1)
    g1.addWidget(QLabel("Board Sensor:"), 2, 0)
    w.auto_board_sensor_label = w.pill("OFF", "#ef4444")
    g1.addWidget(w.auto_board_sensor_label, 2, 1)
    g1.addWidget(QLabel("Clamp Status:"), 3, 0)
    w.auto_clamp_status_label = w.pill("UNCLAMPED", "#475569")
    g1.addWidget(w.auto_clamp_status_label, 3, 1)
    w.auto_sensor_pills = {}
    for row, (key, title) in enumerate(
        (
            ("FENCE_DOOR", "Guard door:"),
            ("SAW_UP", "Saw fully UP:"),
            ("SAW_DOWN", "Saw fully DOWN:"),
            ("CL57T_ALM", "Driver alarm:"),
        ),
        4,
    ):
        label = w.pill("UNKNOWN", "#475569")
        g1.addWidget(QLabel(title), row, 0)
        g1.addWidget(label, row, 1)
        w.auto_sensor_pills[key] = label
    health_row = QHBoxLayout()
    health_row.setSpacing(8)
    w.live_health_dot = QLabel()
    w.live_health_dot.setFixedSize(10, 10)
    w.live_health_dot.setAccessibleName("Telemetry activity")
    w.live_health_dot.setToolTip(
        "Telemetry activity: five-second breathing cycle while data stays fresh."
    )
    health_row.addWidget(w.live_health_dot)
    w.live_health_label = QLabel("Disconnected")
    w.live_health_label.setWordWrap(True)
    health_row.addWidget(w.live_health_label, 1)
    w.auto_second_clamp_label = w.pill('DISABLED', '#475569')
    w.auto_second_clamp_label.setToolTip('Mist TTL D18. Commanded state only; no grip feedback sensor.')
    g1.addWidget(QLabel('Second / outfeed clamp:'), 8, 0)
    g1.addWidget(w.auto_second_clamp_label, 8, 1)
    g1.addLayout(health_row, 9, 0, 1, 2)
    live.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
    left_col.addWidget(live)

    # Motor Current card (Simulator mode)
    current_group = QGroupBox("Motor Current")
    w.current_group = current_group
    main_layout = QVBoxLayout(current_group)
    main_layout.setContentsMargins(10, 10, 10, 10)
    main_layout.setSpacing(8)
    w.current_card_collapsed_height = 250
    w.current_card_expanded_height = 320
    w.current_graph_collapsed_min_height = 130
    w.current_graph_expanded_min_height = 90
    current_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    current_group.setMinimumHeight(w.current_card_collapsed_height)
    current_group.setMaximumHeight(w.current_card_collapsed_height)

    header_layout = QHBoxLayout()
    w.current_value_label = QLabel("0.00 A")
    w.current_value_label.setStyleSheet(
        "font-size: 30px; font-weight: 800; color: #22c55e; letter-spacing: 0.5px;"
    )
    w.current_status_label = w.pill("Current OK", "#22c55e")
    w.current_status_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    w.current_status_label.setMinimumWidth(96)
    w.current_status_label.setMaximumWidth(170)
    w.current_status_label.setFixedHeight(38)

    w.reset_overcurrent_btn = QPushButton("Reset Trip")
    w.reset_overcurrent_btn.setFixedHeight(34)
    w.reset_overcurrent_btn.setStyleSheet(
        "QPushButton { background:#7f1d1d; color:white; font-weight:700; border:1px solid #b91c1c; border-radius:10px; padding:0 12px; }"
        "QPushButton:hover { background:#991b1b; }"
        "QPushButton:pressed { background:#450a0a; }"
    )
    w.reset_overcurrent_btn.clicked.connect(w.reset_overcurrent_trip)

    w.current_settings_toggle = QToolButton()
    w.current_settings_toggle.setText("⚙")
    w.current_settings_toggle.setCheckable(True)
    w.current_settings_toggle.setChecked(False)
    w.current_settings_toggle.setToolTip("Show current protection settings")
    w.current_settings_toggle.setStyleSheet(
        "font-size: 17px; font-weight: 700; min-width: 34px; max-width: 34px; min-height: 34px; max-height: 34px; "
        "padding: 0; border-radius: 17px; background:#1e293b; color:#e2e8f0; border:1px solid #334155;"
    )
    w.current_settings_toggle.toggled.connect(w.toggle_current_settings)

    header_layout.addWidget(w.current_value_label)
    header_layout.addStretch()
    header_layout.addWidget(w.current_status_label)
    header_layout.addSpacing(8)
    header_layout.addWidget(w.reset_overcurrent_btn)
    header_layout.addSpacing(8)
    header_layout.addWidget(w.current_settings_toggle)
    main_layout.addLayout(header_layout)

    w.current_graph = CurrentGraphWidget(max_seconds=5.0, sample_rate_hz=4)
    w.current_graph.set_limit(w.current_limit_amps)
    w.current_graph.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    w.current_graph.setMinimumHeight(w.current_graph_collapsed_min_height)
    main_layout.addWidget(w.current_graph, stretch=1)

    w.current_settings_panel = QWidget()
    settings_layout = QHBoxLayout(w.current_settings_panel)
    settings_layout.setContentsMargins(0, 10, 0, 0)
    w.current_monitoring_checkbox = QCheckBox("Enable Monitoring")
    w.current_monitoring_checkbox.setChecked(w.current_monitoring_enabled)
    w.current_limit_input = QDoubleSpinBox()
    w.current_limit_input.setRange(0.1, 30.0)
    w.current_limit_input.setDecimals(2)
    w.current_limit_input.setValue(w.current_limit_amps)
    w.current_limit_input.setFixedWidth(65)
    w.current_limit_input.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
    w.current_delay_input = QDoubleSpinBox()
    w.current_delay_input.setRange(10, 5000)
    w.current_delay_input.setDecimals(0)
    w.current_delay_input.setValue(w.current_trip_delay_ms)
    w.current_delay_input.setFixedWidth(65)
    w.current_delay_input.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
    w.apply_current_protection_btn = QPushButton("Apply")
    w.apply_current_protection_btn.setFixedWidth(84)
    w.apply_current_protection_btn.clicked.connect(w.apply_current_protection_settings)

    settings_layout.addWidget(w.current_monitoring_checkbox)
    settings_layout.addSpacing(15)
    settings_layout.addWidget(QLabel("Limit (A):"))
    settings_layout.addWidget(w.current_limit_input)
    settings_layout.addSpacing(15)
    settings_layout.addWidget(QLabel("Delay (ms):"))
    settings_layout.addWidget(w.current_delay_input)
    settings_layout.addStretch()
    settings_layout.addWidget(w.apply_current_protection_btn)
    w.current_settings_panel.setVisible(False)
    main_layout.addWidget(w.current_settings_panel)
    left_col.addWidget(current_group)

    # Jog controls
    jog = QGroupBox("Jog")
    jg = QVBoxLayout(jog)
    jog.setMaximumHeight(200)
    jg.setContentsMargins(6, 6, 6, 6)
    jg.setSpacing(8)
    jrow = QHBoxLayout()
    jrow.setSpacing(8)
    w.auto_jog_left_btn = QPushButton("◀")
    w.auto_jog_left_btn.setProperty("role", "small")
    w.auto_jog_left_btn.setMinimumWidth(40)
    w.auto_jog_left_btn.clicked.connect(lambda: w.auto_jog(abs(w.auto_jog_input.value())))
    jrow.addWidget(w.auto_jog_left_btn)

    w.auto_jog_input = QDoubleSpinBox()
    w.auto_jog_input.setRange(0.001, 100.0)
    w.auto_jog_input.setDecimals(4)
    w.auto_jog_input.setValue(1.0000)
    w.auto_jog_input.setMinimumWidth(120)
    jrow.addWidget(w.auto_jog_input, 1)

    w.auto_jog_right_btn = QPushButton("▶")
    w.auto_jog_right_btn.setProperty("role", "small")
    w.auto_jog_right_btn.setMinimumWidth(48)
    w.auto_jog_right_btn.clicked.connect(lambda: w.auto_jog(-abs(w.auto_jog_input.value())))
    jrow.addWidget(w.auto_jog_right_btn)
    jg.addLayout(jrow)

    qrow1 = QHBoxLayout()
    qrow1.setSpacing(8)
    for attr, label, delta in (
        ("qjog_left_01", '0.1" Left', 0.1),
        ("qjog_right_01", '0.1" Right', -0.1),
        ("qjog_left_025", '0.25" Left', 0.25),
        ("qjog_right_025", '0.25" Right', -0.25),
    ):
        btn = QPushButton(label)
        btn.setProperty("role", "small")
        btn.setMinimumWidth(64)
        btn.clicked.connect(lambda _checked=False, d=delta: w.auto_jog(d))
        setattr(w, attr, btn)
        qrow1.addWidget(btn)
    jg.addLayout(qrow1)

    qrow2 = QHBoxLayout()
    qrow2.setSpacing(8)
    for attr, label, delta in (
        ("qjog_left_1", '1" Left', 1.0),
        ("qjog_right_1", '1" Right', -1.0),
        ("qjog_left_2", '2" Left', 2.0),
        ("qjog_right_2", '2" Right', -2.0),
    ):
        btn = QPushButton(label)
        btn.setProperty("role", "small")
        btn.setMinimumWidth(64)
        btn.clicked.connect(lambda _checked=False, d=delta: w.auto_jog(d))
        setattr(w, attr, btn)
        qrow2.addWidget(btn)
    jg.addLayout(qrow2)
    left_col.addWidget(jog)

    left_wrap = QWidget()
    left_wrap.setLayout(left_col)
    top_row.addWidget(left_wrap)

    # Center: touch-friendly cut entry + Cut List
    center_col = QVBoxLayout()
    setup = QGroupBox("Cut Entry")
    g2 = QGridLayout(setup)
    g2.addWidget(QLabel("Cut Length (in):"), 0, 0)
    w.cut_length_input = QDoubleSpinBox()
    w.cut_length_input.setRange(0.1, 2000)
    w.cut_length_input.setDecimals(4)
    w.cut_length_input.setValue(18.0)
    w.cut_length_input.setMinimumHeight(64)
    w.cut_length_input.setStyleSheet("font-size: 28px; padding: 10px 12px;")
    w.cut_length_input.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
    w.cut_length_keypad_checkbox = QCheckBox("Keypad")
    w.cut_length_keypad_checkbox.setMinimumHeight(44)
    w.cut_length_keypad_checkbox.setToolTip(
        "Show the on-screen keypad when Cut Length is tapped. Physical keyboard entry stays available."
    )
    g2.addWidget(w.cut_length_keypad_checkbox, 0, 1, Qt.AlignmentFlag.AlignRight)
    g2.addWidget(w.cut_length_input, 1, 0, 1, 2)
    w.cut_length_keypad = CutLengthKeypad(w.cut_length_input, left_wrap)
    w.cut_length_keypad_checkbox.toggled.connect(w.cut_length_keypad.set_active)
    w.add_cut_button = QPushButton("Add Cut to List")
    w.add_cut_button.clicked.connect(w.add_cut_to_list)
    g2.addWidget(w.add_cut_button, 2, 0, 1, 2)
    w.add_cut_button.setMinimumHeight(48)
    w.add_cut_button.setStyleSheet("font-size: 18px;")
    w.add_cut_button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
    center_col.addWidget(setup)

    cut_list_group = QGroupBox("Cut List")
    vcl = QVBoxLayout(cut_list_group)
    w.board_fill_label = QLabel("No cuts loaded")
    w.board_fill_label.setStyleSheet("font-size: 13px; color: #94a3b8;")
    vcl.addWidget(w.board_fill_label)
    w.board_fill_bar = QProgressBar()
    w.board_fill_bar.setRange(0, 1000)
    w.board_fill_bar.setValue(0)
    w.board_fill_bar.setTextVisible(False)
    w.board_fill_bar.setFixedHeight(16)
    w.board_fill_bar.setStyleSheet("""
        QProgressBar { background-color: #1e293b; border-radius: 8px; border: 1px solid #334155; }
        QProgressBar::chunk { background-color: #38bdf8; border-radius: 8px; }
    """)
    vcl.addWidget(w.board_fill_bar)

    w.cut_list_summary_label = QLabel("")
    w.cut_list_summary_label.setWordWrap(True)
    w.cut_list_summary_label.setStyleSheet("font-size: 12px; color: #93c5fd;")
    w.cut_list_summary_label.hide()
    vcl.addWidget(w.cut_list_summary_label)

    w.cut_list_display = QTextEdit()
    w.cut_list_display.setStyleSheet("font-size: 22px;")
    w.cut_list_display.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    w.cut_list_display.setMinimumHeight(150)
    vcl.addWidget(w.cut_list_display)

    list_button_layout = QHBoxLayout()
    w.load_list_button = QPushButton("Load from File")
    w.load_list_button.clicked.connect(w.load_list_from_file)
    w.update_from_box_button = QPushButton("Update from Box")
    w.update_from_box_button.clicked.connect(w.update_list_from_box)
    w.optimize_list_button = QPushButton("Optimize")
    w.optimize_list_button.setToolTip(
        "Pack cuts onto the fewest boards (Branch-and-Bound), concentrating scrap into one offcut and putting each board's longest cut last."
    )
    w.optimize_list_button.setStyleSheet(
        "background-color: #0284c7; color: white; font-weight: 600;"
    )
    w.optimize_list_button.clicked.connect(w.optimize_current_cut_list)
    w.undo_optimize_button = QPushButton("Undo")
    w.undo_optimize_button.setToolTip("Restore the cut list order from before Optimize.")
    w.undo_optimize_button.clicked.connect(w.undo_optimize_cut_list)
    w.undo_optimize_button.hide()
    w.clear_list_button = QPushButton("Clear List")
    w.clear_list_button.clicked.connect(w.clear_cut_list)
    list_button_layout.addWidget(w.load_list_button)
    list_button_layout.addWidget(w.update_from_box_button)
    list_button_layout.addWidget(w.optimize_list_button)
    list_button_layout.addWidget(w.undo_optimize_button)
    list_button_layout.addWidget(w.clear_list_button)
    vcl.addLayout(list_button_layout)
    center_col.addWidget(cut_list_group, 1)

    center_wrap = QWidget()
    center_wrap.setLayout(center_col)
    top_row.addWidget(center_wrap)

    # Right: Cycle Control + Status
    right_col = QVBoxLayout()
    cycle_group = QGroupBox("Cycle Control")
    cyc = QVBoxLayout(cycle_group)

    top_button_layout = QHBoxLayout()
    w.load_button = QPushButton("LOAD POSITION")
    w.load_button.clicked.connect(w.load_position)
    w.load_button.setStyleSheet("font-size: 12px; min-height: 20px;")
    w.load_button.setProperty("role", "small")
    w.load_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    top_button_layout.addWidget(w.load_button)

    w.cancel_cycle_button = QPushButton("CANCEL CYCLE")
    w.cancel_cycle_button.clicked.connect(w.cancel_auto_cycle)
    w.cancel_cycle_button.setStyleSheet("background-color: #ef4444; font-size: 12px; min-height: 20px;")
    w.cancel_cycle_button.setProperty("role", "small")
    w.cancel_cycle_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    top_button_layout.addWidget(w.cancel_cycle_button)

    w.resume_on_reset_button = QPushButton("RESUME ON RESET")
    w.resume_on_reset_button.clicked.connect(w.resume_after_reset)
    w.resume_on_reset_button.setStyleSheet("background-color: #f59e0b; font-size: 12px; min-height: 20px;")
    w.resume_on_reset_button.setProperty("role", "small")
    w.resume_on_reset_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    top_button_layout.addWidget(w.resume_on_reset_button)
    top_button_layout.setSpacing(8)
    cyc.addLayout(top_button_layout)

    radio_layout = QVBoxLayout()
    radio_layout.setContentsMargins(0, 5, 0, 5)
    radio_layout.setSpacing(2)
    radio_style = "font-size: 15px; padding: 2px 0; color: #e2e8f0;"
    w.board_size_radios = []
    for i, (label, board_length, load_pos) in enumerate(w.board_load_options):
        text = label if load_pos is None else f'{label} ({load_pos:.2f}")'
        radio = QRadioButton(text)
        radio.setStyleSheet(radio_style)
        radio.setChecked(i == 0)
        radio.toggled.connect(w.update_cut_list_display)
        radio_layout.addWidget(radio)
        w.board_size_radios.append((radio, board_length, load_pos))
    cyc.addLayout(radio_layout)

    w.start_cycle_button = QPushButton("START CYCLE")
    w.start_cycle_button.setProperty("role", "touch")
    w.start_cycle_button.clicked.connect(w.start_auto_cycle)
    w.start_cycle_button.setStyleSheet("""
        QPushButton { background-color: #22c55e; color: white; font-weight: bold; font-size: 24px; min-height: 25px; max-height: 55px; }
        QPushButton:hover { background-color: #16a34a; }
        QPushButton:disabled { background-color: #166534; color: #4ade80; }
    """)
    cyc.addWidget(w.start_cycle_button)

    actions = QGridLayout()
    w.auto_home_button = QPushButton('Home')
    w.auto_home_button.clicked.connect(w.home_motor)
    w.auto_clear_error = QPushButton('Confirm / Clear Error')
    w.auto_clear_error.clicked.connect(w.dry_run.acknowledge)
    w.auto_cancel_button = QPushButton('Cancel Cycle')
    w.auto_cancel_button.clicked.connect(w.dry_run.cancel_cycle)
    w.auto_pause_button = QPushButton('Pause Cycle')
    w.auto_pause_button.clicked.connect(lambda: w.dry_run.intervention.pause())
    w.auto_resume_button = QPushButton('Resume Cycle')
    w.auto_resume_button.setToolTip(
        'Use the adjusted board position, with stock against the pusher. After Home, reacquire the board and retain the pending cut.'
    )
    w.auto_resume_button.clicked.connect(lambda: w.dry_run.intervention.resume())
    w.auto_release_clamps = QPushButton('Release retained clamps')
    w.auto_release_clamps.clicked.connect(lambda: w.dry_run.request('recover_release'))
    for index, button in enumerate((
        w.auto_home_button,
        w.auto_clear_error,
        w.auto_cancel_button,
        w.auto_pause_button,
        w.auto_resume_button,
        w.auto_release_clamps,
    )):
        button.setMinimumHeight(42)
        actions.addWidget(button, index // 2, index % 2)
    cyc.insertLayout(1, actions)

    w.repeat_pattern = QCheckBox('Repeat cut list on each new board')
    w.clear_between_boards = QCheckBox('Clear sensor zone between boards')
    w.clear_at_list_end = QCheckBox('Clear sensor zone at end of finite list')
    w.clear_at_list_end.setToolTip('Repeat mode uses the between-boards option at each pattern boundary.')
    for key, checkbox, default in (
        ('repeat_pattern', w.repeat_pattern, False),
        ('clear_between', w.clear_between_boards, True),
        ('clear_end', w.clear_at_list_end, False),
    ):
        checkbox.setChecked(w.settings.value('auto/' + key, default, type=bool))
        checkbox.toggled.connect(lambda checked, k=key: w.settings.setValue('auto/' + k, checked))
        cyc.addWidget(checkbox)
    w.repeat_pattern.toggled.connect(w.refresh_teensy_tabs)

    w.auto_mode_label = QLabel('AUTOMATIC — positions, clamps and cycles each cut.')
    w.auto_mode_label.setWordWrap(True)
    cyc.insertWidget(0, w.auto_mode_label)

    w.operator_cut_button = QPushButton('Wood secured / run cut')
    w.operator_cut_button.setMinimumHeight(66)
    w.operator_cut_button.setStyleSheet(
        'QPushButton { background:#f59e0b; color:#111827; font-size:19px; font-weight:bold; } '
        'QPushButton:disabled { background:#1e293b; color:#94a3b8; border:1px solid #475569; } '
        'QPushButton[earlyReturnAttention="true"]:disabled { background:#f59e0b; color:#111827; border:1px solid #fbbf24; }'
    )
    w.operator_cut_button.clicked.connect(w.approve_auto_cut)
    w.operator_cut_button.setEnabled(False)
    w.operator_cut_button.hide()
    cyc.insertWidget(1, w.operator_cut_button)
    right_col.addWidget(cycle_group)

    status_group = QGroupBox("Status")
    sv = QVBoxLayout(status_group)
    status_group.setMinimumHeight(90)
    status_group.setMaximumHeight(120)
    w.auto_status_label = QLabel("STATUS: Waiting to Start")
    w.auto_status_label.setWordWrap(True)
    w.auto_status_label.setStyleSheet("font-weight:bold; font-size:14px; color:#e2e8f0;")
    sv.addWidget(w.auto_status_label)
    right_col.addWidget(status_group)

    right_wrap = QWidget()
    right_wrap.setLayout(right_col)
    right_wrap.setObjectName('autoCycleColumn')
    right_wrap.setStyleSheet('QWidget#autoCycleColumn { background:#0b1222; }')
    right_scroll = QScrollArea()
    right_scroll.setWidgetResizable(True)
    w.auto_right_scroll = right_scroll
    right_scroll.setStyleSheet('QScrollArea { background:#0b1222; border:0; }')
    right_scroll.setWidget(right_wrap)
    top_row.addWidget(right_scroll)
    root.addLayout(top_row)

    w._auto_shared_panel = panel
    outer = QWidget()
    outer_layout = QVBoxLayout(outer)
    outer_layout.setContentsMargins(0, 0, 0, 0)
    w.auto_modes = QTabWidget()
    w.auto_mode_pages = []
    for name in ('Automatic', 'Semi-Auto / approve each cut'):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        w.auto_modes.addTab(page, name)
        w.auto_mode_pages.append(page)
    w.auto_mode_pages[0].layout().addWidget(panel)
    w.auto_modes.currentChanged.connect(w.change_auto_page)
    outer_layout.addWidget(w.auto_modes)
    return outer


def build_settings_tab(w):
    """Build the speed-first, low-clutter Settings tab and attach its widgets onto `w`."""
    tab = QWidget()
    outer = QVBoxLayout(tab)
    outer.setContentsMargins(6, 6, 6, 6)
    w.settings_scroll = QScrollArea()
    w.settings_scroll.setWidgetResizable(True)
    w.settings_scroll.setStyleSheet('QScrollArea { background:#0f172a; border:0; }')
    body = QWidget()
    body.setObjectName('settingsBody')
    body.setStyleSheet('QWidget#settingsBody { background:#0f172a; }')
    root = QVBoxLayout(body)
    root.setContentsMargins(6, 6, 6, 6)
    root.setSpacing(10)
    w.settings_scroll.setWidget(body)
    outer.addWidget(w.settings_scroll)

    # ── 1. TOP PRIORITY: Motion Speeds & Accelerations (3-card layout) ──────
    profiles = QGroupBox("Motion Speeds & Accelerations")
    profiles_layout = QVBoxLayout(profiles)
    profiles_layout.setContentsMargins(10, 10, 10, 10)
    profiles_layout.setSpacing(8)

    cards_row = QHBoxLayout()
    cards_row.setSpacing(10)

    def _profile_card(title, subtitle, accent, speed_val, accel_val):
        card = QFrame()
        card.setObjectName("profileCard")
        card.setStyleSheet(
            f"QFrame#profileCard {{ background:#0b1222; border:1px solid #334155; "
            f"border-top:3px solid {accent}; border-radius:10px; }}"
        )
        cl = QVBoxLayout(card)
        cl.setContentsMargins(12, 8, 12, 10)
        cl.setSpacing(6)
        hdr = QLabel(title)
        hdr.setStyleSheet(f"color:{accent}; font-size:15px; font-weight:800; border:none;")
        sub = QLabel(subtitle)
        sub.setStyleSheet("color:#94a3b8; font-size:12px; border:none;")
        cl.addWidget(hdr)
        cl.addWidget(sub)
        form = QFormLayout()
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(6)
        spd = QDoubleSpinBox()
        spd.setRange(1, 20000)
        spd.setDecimals(0)
        spd.setValue(speed_val)
        spd.setSuffix(" p/s")
        spd.setMinimumHeight(36)
        spd.setStyleSheet("font-size:16px; font-weight:600;")
        acc = QDoubleSpinBox()
        acc.setRange(1, 50000)
        acc.setDecimals(0)
        acc.setValue(accel_val)
        acc.setSuffix(" p/s²")
        acc.setMinimumHeight(36)
        acc.setStyleSheet("font-size:16px; font-weight:600;")
        form.addRow("Speed:", spd)
        form.addRow("Accel:", acc)
        cl.addLayout(form)
        return card, spd, acc

    gentle_card, w.gentle_speed, w.gentle_accel = _profile_card(
        "GENTLE", "Board approach & truing", "#38bdf8", 600, 600
    )
    norm_card, w.norm_speed, w.norm_accel = _profile_card(
        "NORMAL", "Production board feed", "#22c55e", 2500, 900
    )
    fast_card, w.fast_speed, w.fast_accel = _profile_card(
        "FAST", "Carriage return to Load", "#f59e0b", 3500, 2000
    )
    cards_row.addWidget(gentle_card, 1)
    cards_row.addWidget(norm_card, 1)
    cards_row.addWidget(fast_card, 1)
    profiles_layout.addLayout(cards_row)

    apply_row = QHBoxLayout()
    apply_row.setSpacing(10)
    apply_row.addWidget(QLabel("Profile to apply:"))
    w.settings_profile_combo = QComboBox()
    w.settings_profile_combo.setMinimumWidth(140)
    w.settings_profile_combo.setStyleSheet(
        "QComboBox { background:#0b1222; color:#e2e8f0; border:1px solid #334155; padding:6px 10px; }"
        "QComboBox QAbstractItemView { background:#0b1222; color:#e2e8f0; selection-background-color:#1e40af; }"
    )
    for name in ("NORMAL", "GENTLE", "FAST"):
        w.settings_profile_combo.addItem(name, name)
    w.settings_profile_combo.currentIndexChanged.connect(lambda: w.refresh_teensy_tabs())
    apply_row.addWidget(w.settings_profile_combo)
    w.apply_profile_btn = QPushButton("Apply Selected Profile Settings Now")
    w.apply_profile_btn.setProperty("class", "primary")
    w.apply_profile_btn.clicked.connect(w.apply_current_profile_params)
    apply_row.addWidget(w.apply_profile_btn)
    apply_row.addStretch()
    profiles_layout.addLayout(apply_row)

    w.settings_profile_feedback = QLabel()
    w.settings_profile_feedback.setWordWrap(True)
    w.settings_profile_feedback.setStyleSheet("color:#94a3b8; font-size:12px;")
    profiles_layout.addWidget(w.settings_profile_feedback)
    root.addWidget(profiles)

    # ── 2. SECOND ROW: Homing Approach | Cutting & Sensors (1:1 split) ──────
    mid_row = QHBoxLayout()
    mid_row.setSpacing(10)

    homing = QGroupBox('Homing Approach — Teensy')
    w.homing_group = homing
    hl = QVBoxLayout(homing)
    hl.setContentsMargins(10, 10, 10, 10)
    hl.setSpacing(6)
    hgrid = QGridLayout()
    hgrid.setHorizontalSpacing(10)
    hgrid.setVerticalSpacing(6)
    saved_rate, saved_accel = w.saved_homing_settings()
    w.homing_speed = QDoubleSpinBox()
    w.homing_speed.setDecimals(0)
    w.homing_speed.setRange(1, 20000)
    w.homing_speed.setValue(saved_rate)
    w.homing_speed.setSuffix(" p/s")
    w.homing_speed.setMinimumHeight(34)
    w.homing_accel = QDoubleSpinBox()
    w.homing_accel.setDecimals(0)
    w.homing_accel.setRange(1, 50000)
    w.homing_accel.setValue(saved_accel)
    w.homing_accel.setSuffix(" p/s²")
    w.homing_accel.setMinimumHeight(34)
    hgrid.addWidget(QLabel("Approach speed:"), 0, 0)
    hgrid.addWidget(w.homing_speed, 0, 1)
    hgrid.addWidget(QLabel("Acceleration:"), 0, 2)
    hgrid.addWidget(w.homing_accel, 0, 3)
    hl.addLayout(hgrid)

    h_actions = QHBoxLayout()
    w.save_homing_button = QPushButton('Save / Apply Homing')
    w.save_homing_button.setProperty("class", "primary")
    w.save_homing_button.clicked.connect(w.save_homing_settings)
    h_actions.addWidget(w.save_homing_button)
    h_actions.addStretch()
    hl.addLayout(h_actions)

    w.homing_feedback = QLabel(
        'Saved on this PC. Final latch stays 10 p/s; backoff stays 40 p/s.'
    )
    w.homing_feedback.setWordWrap(True)
    w.homing_feedback.setStyleSheet("color:#94a3b8; font-size:12px;")
    hl.addWidget(w.homing_feedback)
    w.homing_speed.valueChanged.connect(w.refresh_homing_settings)
    w.homing_accel.valueChanged.connect(w.refresh_homing_settings)
    mid_row.addWidget(homing, 1)

    cutting = QGroupBox("Cutting & Sensors")
    cl = QVBoxLayout(cutting)
    cl.setContentsMargins(10, 10, 10, 10)
    cl.setSpacing(6)
    cgrid = QGridLayout()
    cgrid.setHorizontalSpacing(10)
    cgrid.setVerticalSpacing(6)
    w.kerf_input = QDoubleSpinBox()
    w.kerf_input.setRange(0.0, 0.5)
    w.kerf_input.setDecimals(4)
    w.kerf_input.setValue(0.100)
    w.kerf_input.setSuffix(" in")
    w.kerf_input.setMinimumHeight(34)
    w.kerf_input.setToolTip("Blade cut width used in cut-list, optimizer, and stock calculations.")
    initial_sensor_distance = w.dry_run.supervision.sensor_distance()
    w.board_sensor_location_input = QDoubleSpinBox()
    w.board_sensor_location_input.setRange(0, 2000)
    w.board_sensor_location_input.setDecimals(4)
    w.board_sensor_location_input.setValue(initial_sensor_distance)
    w.board_sensor_location_input.setSuffix(" in")
    w.board_sensor_location_input.setMinimumHeight(34)
    w.board_sensor_location_input.setToolTip(
        "Distance from the saw blade to the laser board sensor. Used for truing motion, board tracking and sensor-zone clearing."
    )
    cgrid.addWidget(QLabel("Blade Kerf:"), 0, 0)
    cgrid.addWidget(w.kerf_input, 0, 1)
    cgrid.addWidget(QLabel("Sensor Distance:"), 0, 2)
    cgrid.addWidget(w.board_sensor_location_input, 0, 3)
    cl.addLayout(cgrid)

    w.auto_clamp_checkbox = QCheckBox('Automatic clamp/saw simulation (offline Simulator only)')
    w.auto_clamp_checkbox.setToolTip(
        'Simulator only. Live automatic clamp/saw operation uses Teensy controller sequencing.'
    )
    w.auto_clamp_checkbox.toggled.connect(w._on_auto_clamp_toggled)
    cl.addWidget(w.auto_clamp_checkbox)
    cl.addStretch()
    mid_row.addWidget(cutting, 1)

    root.addLayout(mid_row)

    # ── 3. BOTTOM SECTION: Organized Sub-Tabs for Set-Once & Diagnostics ────
    w.cylinder_timing = CylinderTimingPanel(w.settings)
    w.supervision_settings = w.dry_run.supervision.controls()
    w.board_sensor_location_input.valueChanged.connect(w.dry_run.supervision.sync_reference)
    w.kerf_input.valueChanged.connect(w.dry_run.supervision.sync_reference)

    w.settings_advanced_tabs = QTabWidget()

    timings_page = QWidget()
    tl = QVBoxLayout(timings_page)
    tl.setContentsMargins(6, 6, 6, 6)
    tl.addWidget(w.cylinder_timing)
    tl.addStretch()
    w.settings_advanced_tabs.addTab(timings_page, "Cylinder Timings")

    dims_page = QWidget()
    dl = QVBoxLayout(dims_page)
    dl.setContentsMargins(6, 6, 6, 6)
    dl.addWidget(w.supervision_settings)
    dl.addStretch()
    w.settings_advanced_tabs.addTab(dims_page, "Machine Dimensions")

    diag_page = QWidget()
    dgl = QVBoxLayout(diag_page)
    dgl.setContentsMargins(6, 6, 6, 6)
    dgl.setSpacing(8)

    updates_row = QHBoxLayout()
    w.version_label = QLabel(f"Software Version {APP_VERSION}")
    w.version_label.setStyleSheet("font-weight:700;")
    updates_row.addWidget(w.version_label)
    history_note = QLabel(f"•  Cut history CSV: {w.cut_history.path}")
    history_note.setStyleSheet("color:#94a3b8; font-size:12px;")
    history_note.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    updates_row.addSpacing(10)
    updates_row.addWidget(history_note, 1)
    w.check_updates_btn = QPushButton("Check for Updates")
    w.check_updates_btn.clicked.connect(w.check_updates_manual)
    updates_row.addWidget(w.check_updates_btn)
    dgl.addLayout(updates_row)

    serial_hint = QLabel("Serial Monitor — live inbound messages from the controller:")
    serial_hint.setStyleSheet("color:#94a3b8; font-size:12px;")
    dgl.addWidget(serial_hint)
    w.speed_serial_console = QTextBrowser()
    w.speed_serial_console.setMinimumHeight(180)
    w.speed_serial_console.document().setMaximumBlockCount(500)
    w.speed_serial_console.setOpenExternalLinks(False)
    dgl.addWidget(w.speed_serial_console, 1)
    w.settings_advanced_tabs.addTab(diag_page, "Serial Monitor & Software")

    root.addWidget(w.settings_advanced_tabs, 1)
    return tab


def build_legacy_full_auto_tab(w):
    """Build the two-clamp live Machine / live cycle page for Full Auto."""
    tab = QWidget()
    root_layout = QVBoxLayout(tab)
    root_layout.setSpacing(6)
    root_layout.setContentsMargins(6, 6, 6, 6)

    # Top: Live Status
    live_group = QGroupBox("Live Status")
    live_layout = QHBoxLayout(live_group)
    live_layout.setSpacing(14)

    pos_col = QVBoxLayout()
    pos_col.addWidget(QLabel("Position (in):"))
    w.fa_position_label = QLabel("0.0000")
    w.fa_position_label.setStyleSheet("font-size: 26px; font-weight: bold; color: #60a5fa;")
    pos_col.addWidget(w.fa_position_label)
    live_layout.addLayout(pos_col)
    live_layout.addStretch()

    pills_layout = QHBoxLayout()
    pills_layout.setSpacing(8)
    for caption, attr, initial, color in (
        ("Homing:", "fa_homing_sensor_label", "OFF", "#ef4444"),
        ("Board:", "fa_board_sensor_label", "OFF", "#ef4444"),
        ("Driver:", "fa_driver_label", "UNKNOWN", "#475569"),
        ("Saw Pos:", "fa_saw_position_label", "--", "#475569"),
        ("Guard door:", "fa_fence_closed_label", "--", "#475569"),
    ):
        pills_layout.addWidget(QLabel(caption))
        lbl = w.pill(initial, color)
        setattr(w, attr, lbl)
        pills_layout.addWidget(lbl)
    live_layout.addLayout(pills_layout)
    root_layout.addWidget(live_group)

    # Middle row: Cut List + Machine View
    middle_row = QHBoxLayout()
    middle_row.setSpacing(6)

    cut_list_group = QGroupBox("Cut List")
    vcl = QVBoxLayout(cut_list_group)
    w.fa_board_fill_label = QLabel("No cuts loaded")
    w.fa_board_fill_label.setStyleSheet("font-size: 13px; color: #94a3b8;")
    vcl.addWidget(w.fa_board_fill_label)
    w.fa_board_fill_bar = QProgressBar()
    w.fa_board_fill_bar.setRange(0, 1000)
    w.fa_board_fill_bar.setValue(0)
    w.fa_board_fill_bar.setTextVisible(False)
    w.fa_board_fill_bar.setFixedHeight(16)
    w.fa_board_fill_bar.setStyleSheet("""
        QProgressBar { background-color: #1e293b; border-radius: 8px; border: 1px solid #334155; }
        QProgressBar::chunk { background-color: #38bdf8; border-radius: 8px; }
    """)
    vcl.addWidget(w.fa_board_fill_bar)

    w.fa_cut_list_display = QTextEdit()
    w.fa_cut_list_display.setReadOnly(True)
    w.fa_cut_list_display.setStyleSheet("font-size: 18px;")
    w.fa_cut_list_display.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    w.fa_cut_list_display.setMinimumHeight(150)
    vcl.addWidget(w.fa_cut_list_display, 1)

    fa_list_btns = QHBoxLayout()
    fa_load_btn = QPushButton("Load from File")
    fa_load_btn.clicked.connect(w.load_list_from_file)
    fa_clear_btn = QPushButton("Clear List")
    fa_clear_btn.clicked.connect(w.clear_cut_list)
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

    io_and_cycle = QVBoxLayout()
    io_and_cycle.setSpacing(6)
    cylinders_group = QGroupBox("Clamps — commanded outputs")
    cyl_layout = QHBoxLayout(cylinders_group)
    cyl_layout.setSpacing(8)
    cyl_layout.setContentsMargins(10, 4, 10, 4)
    for cyl_name, pill_attr in (("Main Clamp", "fa_cyl1_status"), ("Outfeed Clamp", "fa_cyl2_status")):
        name_lbl = QLabel(cyl_name)
        name_lbl.setStyleSheet("font-weight: bold; font-size: 13px;")
        cyl_layout.addWidget(name_lbl)
        status_pill = w.pill("RETRACTED", "#475569")
        status_pill.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        status_pill.setMinimumWidth(160)
        setattr(w, pill_attr, status_pill)
        cyl_layout.addWidget(status_pill)
        cyl_layout.addSpacing(6)
    cyl_layout.addStretch()
    cylinders_group.setMaximumHeight(64)
    io_and_cycle.addWidget(cylinders_group)

    sim_group = QGroupBox("Machine view")
    sim_layout = QVBoxLayout(sim_group)
    sim_layout.setContentsMargins(8, 8, 8, 8)
    w.saw_sim = SawSimWidget(home_position=w.home_position)
    w.saw_sim.set_sensor_location(w.board_sensor_location_input.value())
    w.board_sensor_location_input.valueChanged.connect(w.saw_sim.set_sensor_location)
    sim_layout.addWidget(w.saw_sim)
    io_and_cycle.addWidget(sim_group, 1)

    middle_row.addLayout(io_and_cycle)
    root_layout.addLayout(middle_row, 1)

    # Bottom: Status + Operator Cut + Start + Stop
    bottom_row = QHBoxLayout()
    bottom_row.setSpacing(8)
    bottom_row.setContentsMargins(4, 4, 4, 4)
    w.fa_auto_status_label = QLabel("STATUS: Waiting to Start")
    w.fa_auto_status_label.setWordWrap(True)
    w.fa_auto_status_label.setStyleSheet("font-weight: bold; font-size: 15px; color: #e2e8f0;")
    bottom_row.addWidget(w.fa_auto_status_label, 1)

    w.fa_operator_cut_button = QPushButton('Clamp / Cut / Advance')
    w.fa_operator_cut_button.setMinimumHeight(54)
    w.fa_operator_cut_button.setStyleSheet(
        'QPushButton {background:#f59e0b;color:#0b1222;font-weight:bold;padding:8px;} '
        'QPushButton:disabled {background:#334155;color:#94a3b8;}'
    )
    w.fa_operator_cut_button.clicked.connect(w.operator_cut_button.click)
    bottom_row.addWidget(w.fa_operator_cut_button)

    w.fa_start_cycle_button = QPushButton("START CYCLE")
    w.fa_start_cycle_button.setFixedHeight(50)
    w.fa_start_cycle_button.setMinimumWidth(160)
    w.fa_start_cycle_button.setStyleSheet("""
        QPushButton { background-color: #22c55e; color: white; font-weight: bold; font-size: 17px; border-radius: 10px; padding: 0 16px; }
        QPushButton:hover { background-color: #16a34a; }
        QPushButton:disabled { background-color: #166534; color: #4ade80; }
    """)
    w.fa_start_cycle_button.clicked.connect(w.start_auto_cycle)
    bottom_row.addWidget(w.fa_start_cycle_button)

    w.fa_stop_button = QPushButton('STOP / INTERRUPT')
    w.fa_stop_button.setMinimumSize(190, 54)
    w.fa_stop_button.setStyleSheet(
        'QPushButton {background:#dc2626;color:white;font-size:17px;font-weight:bold;border-radius:10px;padding:10px;} '
        'QPushButton:hover {background:#ef4444;} QPushButton:disabled {background:#7f1d1d;color:#cbd5e1;}'
    )
    w.fa_stop_button.setToolTip(
        'Software interrupt: stop carriage and cycle, release trigger, retain engaged clamps. Use the independent hardware emergency stop for emergencies.'
    )
    w.fa_stop_button.clicked.connect(w.cancel_auto_cycle)
    bottom_row.addWidget(w.fa_stop_button)

    bottom_widget = QWidget()
    bottom_widget.setLayout(bottom_row)
    bottom_widget.setMinimumHeight(82)
    root_layout.addWidget(bottom_widget)
    return tab
