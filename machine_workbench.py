"""Full Auto read-only layout, scenario lab and commissioning observations."""
from dataclasses import asdict, replace
import time
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QDoubleSpinBox,
    QCheckBox, QPushButton, QTabWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QScrollArea, QFileDialog, QTextBrowser,
)
from automation_supervision import Material, Span, assess_main_clamp
from machine_preview import example_scenarios, evaluate, preview_cut_list


COLORS = {'PROCEED': '#22c55e', 'ADAPT': '#38bdf8',
          'OPERATOR_REQUIRED': '#fbbf24', 'BLOCK': '#f87171'}


def table(headers):
    widget = QTableWidget(0, len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    widget.horizontalHeader().setSectionResizeMode(len(headers)-1, QHeaderView.ResizeMode.Stretch)
    widget.verticalHeader().hide()
    widget.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    widget.setWordWrap(True)
    return widget


def fill_table(widget, rows):
    widget.setRowCount(len(rows))
    for i, row in enumerate(rows):
        for j, value in enumerate(row):
            item = QTableWidgetItem(str(value))
            item.setToolTip(str(value))
            widget.setItem(i, j, item)
    widget.resizeRowsToContents()


class MachineLayoutView(QWidget):
    """Measured spatial envelopes. Command states are not depicted as grip."""
    def __init__(self):
        super().__init__()
        self.context = None
        self.decision = None
        self.zoom = True
        self.setMinimumHeight(290)
        self.setMinimumWidth(450)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor('#0b1222'))
        if self.context is None:
            p.setPen(QColor('#94a3b8')); p.drawText(20, 30, 'No machine state available')
            return
        c = self.context; g = c.geometry
        # Local detail keeps a one-inch pad legible on a 160-inch machine.
        high, low = (40.0, -20.0) if self.zoom else (168.0, -60.0)
        width = self.width()-60
        def x(value): return 30+(high-value)/(high-low)*width
        def label(rect, text, color='#cbd5e1'):
            p.setPen(QColor(color)); p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        def span(s, y, h, color):
            left, right = x(s.far), x(s.near)
            p.fillRect(QRectF(left, y, max(2, right-left), h), QColor(color))
        p.setClipRect(self.rect().adjusted(16, 0, -16, 0))
        label(QRectF(20, 8, self.width()-40, 22),
              'HOME / INFEED  →  BLADE  →  OUTFEED     •     inches from blade', '#94a3b8')
        board_y = 148
        span(Span(0, g.cut_keepout), 43, 165, '#4c1d2a')
        p.setPen(QPen(QColor('#334155'), 2)); p.drawLine(25, board_y+33, self.width()-25, board_y+33)
        if c.material.located:
            span(c.material.stock, board_y, 28, '#9a754b')
            label(QRectF(20, 184, self.width()-40, 20),
                  f'Modeled stock: {c.material.stock.near:g} to {c.material.stock.far:g} in  |  '
                  f'{c.material.confidence}  |  pusher contact {"tracked" if c.material.contact else "LOST"}')
        else:
            label(QRectF(20, board_y, self.width()-40, 28), 'MATERIAL LOCATION UNKNOWN', '#fbbf24')
        for index, clamp in enumerate(g.clamps):
            d = assess_main_clamp(c, clamp)
            planned = not (clamp.installed and clamp.commissioned)
            color = '#64748b' if planned else '#22c55e' if d.proceeds else '#fbbf24'
            span(clamp.footprint, 84, 15, color)
            # Closing envelope projected to the pusher/stock lane.
            p.setPen(QPen(QColor(color), 1, Qt.PenStyle.DashLine))
            envelope = clamp.footprint.expanded(g.margin)
            p.drawRect(QRectF(x(envelope.far), 100, max(2, x(envelope.near)-x(envelope.far)), 78))
            center = x((clamp.footprint.near+clamp.footprint.far)/2)
            label(QRectF(center-105, 54 if index%2 == 0 else 30, 210, 27),
                  f'{clamp.key.upper()}  {"PLANNED" if planned else "eligible" if d.proceeds else "inhibited"}', color)
        if not g.clamps:
            label(QRectF(30, 65, self.width()-60, 24), 'Clamp footprints not commissioned', '#fbbf24')
        if c.position is not None and c.reference_known:
            push = g.pusher(c.position)
            span(push, board_y-6, 40, '#2563eb')
            px = x(push.near)
            p.setPen(QPen(QColor('#93c5fd'), 3)); p.drawLine(int(px), board_y-8, int(px), board_y+37)
            text = f'Pusher {c.position:.3f} in'
            if not low <= c.position <= high: text += ' (outside detail view)'
            center = max(120, min(self.width()-120, px))
            label(QRectF(center-110, 112, 220, 24), text, '#93c5fd')
        else:
            label(QRectF(20, 112, self.width()-40, 24), 'Pusher position UNKNOWN', '#fbbf24')
        span(g.sensor, 212, 8, '#38bdf8' if c.sensor_clear is False else '#64748b')
        sensor = 'UNKNOWN' if c.sensor_clear is None else 'clear' if c.sensor_clear else 'blocked'
        label(QRectF(20, 224, self.width()-40, 22),
              f'Detector {g.sensor.near:g}–{g.sensor.far:g} in: {sensor}   •   Blade keepout: {g.cut_keepout:g} in', '#94a3b8')
        p.setPen(QPen(QColor('#f87171'), 2)); p.drawLine(int(x(0)), 40, int(x(0)), 211)
        label(QRectF(x(0)-25, 40, 50, 20), '0', '#f87171')
        step = 10 if self.zoom else 40
        for tick in range(int(low), int(high)+1, step):
            px = x(tick)
            p.setPen(QColor('#475569')); p.drawLine(int(px), 253, int(px), 259)
            label(QRectF(px-24, 260, 48, 20), str(tick), '#94a3b8')


class MachineWorkbench(QWidget):
    def __init__(self, owner, legacy):
        super().__init__()
        self.owner = owner
        self.setStyleSheet('''
            QScrollArea, QScrollArea > QWidget > QWidget { background:#0b1222; border:none; }
            QComboBox, QLineEdit { background:#111c2e; color:#e2e8f0; border:1px solid #334155; padding:6px; border-radius:6px; }
            QComboBox QAbstractItemView { background:#111c2e; color:#e2e8f0; selection-background-color:#1d4ed8; }
            QTableWidget { background:#0b1222; alternate-background-color:#111c2e; color:#e2e8f0; gridline-color:#334155; border:1px solid #334155; }
            QHeaderView::section { background:#1e293b; color:#cbd5e1; padding:7px; border:1px solid #334155; }
            QTabBar::tab { min-width:100px; }
        ''')
        self.scenarios = example_scenarios()
        self.current_context = None
        self.current_decision = None
        self._diag_key = None
        self._forecast_input = None
        root = QVBoxLayout(self)
        heading = QLabel('Full Auto — machine view')
        heading.setStyleSheet('font-size:22px;font-weight:600;color:#e2e8f0')
        root.addWidget(heading)
        self.pages = QTabWidget(); root.addWidget(self.pages)
        self.pages.addTab(legacy, 'Machine / live cycle')
        layout_page = QWidget(); layout = QVBoxLayout(layout_page)
        bar = QHBoxLayout()
        self.source = QComboBox(); self.source.addItems(('Live machine readback', 'Offline scenarios'))
        self.source.setMinimumHeight(40); self.source.setCurrentIndex(1)
        self.scenario = QComboBox()
        for scenario in self.scenarios: self.scenario.addItem(scenario.title)
        self.scenario.setMinimumHeight(40)
        self.position = QDoubleSpinBox(); self.position.setRange(0, 162); self.position.setDecimals(3)
        self.position.setSuffix(' in'); self.position.setMinimumHeight(40)
        self.zoom = QCheckBox('Detail near blade'); self.zoom.setChecked(True)
        self.position_caption = QLabel('Pusher:')
        bar.addWidget(self.source); bar.addWidget(self.scenario, 1); bar.addWidget(self.position_caption)
        bar.addWidget(self.position); bar.addWidget(self.zoom)
        layout.addLayout(bar)
        self.source_note = QLabel(); self.source_note.setWordWrap(True); layout.addWidget(self.source_note)
        self.machine_state = QLabel(); self.machine_state.setWordWrap(True)
        self.machine_state.setStyleSheet('color:#93c5fd;padding:5px 0;'); layout.addWidget(self.machine_state)
        self.view = MachineLayoutView(); layout.addWidget(self.view)
        self.decision_label = QLabel(); self.decision_label.setWordWrap(True)
        self.decision_label.setMinimumHeight(58); layout.addWidget(self.decision_label)
        self.clamp_label = QLabel(); self.clamp_label.setWordWrap(True); layout.addWidget(self.clamp_label)
        buttons = QHBoxLayout()
        forecast = QPushButton('Preview whole cut list from this stock state')
        forecast.setMinimumHeight(40); forecast.clicked.connect(self.forecast)
        settings = QPushButton('Open measured geometry settings'); settings.clicked.connect(self.show_settings)
        buttons.addWidget(forecast); buttons.addWidget(settings); layout.addLayout(buttons)
        self.forecast_note = QLabel('Lookahead assumes the displayed stock is already trued and contacting the pusher. It does not run acquisition or move anything.')
        self.forecast_note.setWordWrap(True); layout.addWidget(self.forecast_note)
        self.lookahead = table(('Next action', 'Position (in)', 'Coordinator assessment'))
        self.lookahead.setMinimumHeight(135); layout.addWidget(self.lookahead, 1)
        self.pages.addTab(self.scrolled(layout_page), 'Layout / scenarios')
        self.build_diagnostics()
        self.source.currentIndexChanged.connect(self.refresh)
        self.scenario.currentIndexChanged.connect(self.load_scenario)
        self.position.valueChanged.connect(self.refresh)
        self.zoom.toggled.connect(self.refresh)
        self.pages.currentChanged.connect(self.refresh)
        self.load_scenario()

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()

    @staticmethod
    def scrolled(widget):
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(widget)
        return scroll

    def load_scenario(self, *_):
        self.position.blockSignals(True)
        self.position.setValue(self.scenarios[self.scenario.currentIndex()].context.position or 0)
        self.position.blockSignals(False)
        self.refresh()

    def refresh(self, *_):
        offline = self.source.currentIndex() == 1
        self.scenario.setVisible(offline); self.position.setVisible(offline); self.position_caption.setVisible(offline)
        if offline:
            s = self.scenarios[self.scenario.currentIndex()]
            c = s.context
            if c.position is not None:
                delta = self.position.value()-c.position
                material = c.material
                if material.located and delta:
                    material = replace(material, stock=Span(material.stock.near, self.position.value()),
                                       source='offline pusher/stock example')
                c = replace(c, position=self.position.value(), material=material)
            action = s.action
            self.source_note.setText('OFFLINE EXAMPLE — illustrative dimensions only. Pusher changes resize the contacting example stock; '
                                     'nothing is saved to machine settings or sent to hardware. Planned devices remain unavailable.')
        elif hasattr(self.owner, 'carriage_tab'):
            dry = self.owner.dry_run
            c = dry.supervision.context()
            if not c.fresh:
                c = replace(c, position=None, reference_known=False, sensor_clear=None)
            stage = dry.sequence.stage if dry.sequence else None
            action = 'clear_sensor' if stage in ('PNEU_OFF','CLEARANCE_REQUIRED','CLEAR_PROFILE',
                      'CLEAR_ARM','CLEAR_MOVE','CLEAR_VERIFY','LOAD_ARM','LOAD_WAIT','DONE') else 'cut'
            self.source_note.setText('LIVE READBACK — measured geometry and modeled material. Unknown/stale state stays unknown. '
                                     'Next-action eligibility can show busy during motion; it is not a current-cycle fault. '
                                     'This preview sends no commands; eligibility does not confirm grip.')
        else:
            return
        decision = evaluate(c, action)
        if offline or c.fresh:
            status = (f'Guard: {"closed" if c.door_closed else "open"}   |   '
                      f'Reference: {"known" if c.reference_known else "unknown"}   |   '
                      f'Saw UP: {"confirmed" if c.saw_up else "not confirmed"}   |   '
                      f'Fault state: {"clear" if c.fault_free else "fault / unknown"}')
            if not offline:
                data = self.owner.dry_run.data
                status += '   |   Commanded: ' + ', '.join(f'{name.lower()} {"ON" if data.get(name)=="1" else "OFF"}'
                            for name in ('CLAMP','SAW','TRIGGER'))
                status += '   |   second clamp '+('disabled' if data.get('SECOND_ENABLED')!='1' else
                                                  'ON commanded' if data.get('SECOND_CLAMP')=='1' else 'OFF commanded')
        else:
            status = 'No fresh machine readback — guard, saw position and output states UNKNOWN.'
        self.machine_state.setText(status)
        forecast_input = (c, decision, self.source.currentIndex(),
                          tuple(self.owner.cut_list), self.owner.kerf_input.value())
        changed = forecast_input != self._forecast_input
        self._forecast_input = forecast_input
        self.current_context, self.current_decision = c, decision
        self.view.context = c; self.view.decision = decision; self.view.zoom = self.zoom.isChecked(); self.view.update()
        color = COLORS[decision.outcome.name]
        self.decision_label.setText(f'{decision.outcome.name.replace("_", " ")}  •  {decision.code}\n{decision.reason}' +
                                   (f'  Target: {decision.target:.3f} in' if decision.target is not None else ''))
        self.decision_label.setStyleSheet(f'background:#111c2e;border-left:4px solid {color};padding:10px;color:{color};font-size:15px;')
        self.clamp_label.setText('  |  '.join(f'{clamp.key}: {assess_main_clamp(c, clamp).reason}' for clamp in c.geometry.clamps)
                                 or 'No measured clamp footprints are available.')
        if changed:
            self.lookahead.setRowCount(0)
            self.forecast_note.setText('Lookahead assumes the displayed stock is already trued and contacting the pusher. '
                                       'Preview again after state changes; no acquisition or motion is performed.')
        if hasattr(self.owner, 'carriage_tab'): self.refresh_diagnostics()

    def forecast(self):
        if self.current_context is None: return
        lengths = [float(length) for _, length, _ in self.owner.cut_list]
        if not lengths:
            self.forecast_note.setText('Add lengths to the cut list in Auto, then preview here. No stock or carriage state is changed.')
            self.lookahead.setRowCount(0); return
        steps = preview_cut_list(self.current_context, lengths, self.owner.kerf_input.value())
        fill_table(self.lookahead, [(s.label, '—' if s.position is None else f'{s.position:.3f}',
                   f'{s.decision.outcome.name}: {s.decision.reason}' +
                   (f' Target {s.decision.target:.3f} in.' if s.decision.target is not None else '')) for s in steps])
        source = 'OFFLINE EXAMPLE' if self.source.currentIndex() else 'LIVE-STATE FORECAST'
        self.forecast_note.setText(f'{source}: entire list from entry 1, using this already-trued stock. Stops at the first unsupported step. '
                                  'Final detector state is predicted and must be verified by real feedback during execution.')

    def show_settings(self):
        self.owner.tabs.setCurrentWidget(self.owner.speed_tab)
        # Settings itself owns verification/saving; preview has no save shortcut.
        self.owner.supervision_settings.setFocus()
        parent = self.owner.supervision_settings.parentWidget()
        while parent is not None:
            if isinstance(parent, QScrollArea):
                parent.ensureWidgetVisible(self.owner.supervision_settings); break
            parent = parent.parentWidget()

    def build_diagnostics(self):
        page = QWidget(); layout = QVBoxLayout(page)
        self.live_phase = QLabel('No fresh native telemetry'); self.live_phase.setWordWrap(True)
        self.live_phase.setStyleSheet('font-size:18px;color:#60a5fa;'); layout.addWidget(self.live_phase)
        note = QLabel('Observed host intervals may include telemetry latency or missed short phases. '
                      'Travel limits are limits, not target durations. Commanded outputs do not confirm clamp grip or blade standstill.')
        note.setWordWrap(True); layout.addWidget(note)
        self.follow_trace = QCheckBox('Follow latest phase'); self.follow_trace.setChecked(True)
        layout.addWidget(self.follow_trace)
        self.phase_table = table(('Sequence / controller phase', 'Observed (ms)', 'Configured (ms)', 'Source / interpretation'))
        layout.addWidget(self.phase_table, 1)
        self.event_log = QTextBrowser(); self.event_log.setMaximumHeight(155); layout.addWidget(self.event_log)
        export = QPushButton('Export commissioning report (JSON)'); export.setMinimumHeight(42)
        export.clicked.connect(self.export_report); layout.addWidget(export)
        self.export_feedback = QLabel(); self.export_feedback.setWordWrap(True); layout.addWidget(self.export_feedback)
        self.pages.addTab(page, 'Cycle diagnostics')

    def refresh_diagnostics(self):
        # Recording is independent; don't rebuild a hidden table during motion.
        if not self.isVisible() or self.pages.tabText(self.pages.currentIndex()) != 'Cycle diagnostics': return
        d = self.owner.dry_run
        seq = str(d.sequence.stage) if d.sequence else 'IDLE'
        phase = d.data.get('STATE', 'UNKNOWN') if d.fresh() else 'UNKNOWN / STALE'
        self.live_phase.setText(f'{seq}  /  {phase}\n{d.message}')
        # Render at most once per observed half second; recording is independent.
        key = (len(d.diagnostics.phases), len(d.diagnostics.events), int(time.monotonic()*2), d.fresh())
        if key == self._diag_key: return
        self._diag_key = key
        rows = d.diagnostics.phase_rows(time.monotonic())[-100:]
        scroll = self.phase_table.verticalScrollBar().value()
        event_scroll = self.event_log.verticalScrollBar().value()
        fill_table(self.phase_table, [(r['sequence']+' / '+r['controller'], str(r['observed_ms']) +
                   (' (active)' if r.get('active') else ' (feedback interrupted)' if r.get('interrupted') else ''),
                   '—' if r['expected_ms'] is None else r['expected_ms'], r['timing_source']+' / '+r['timing_kind']) for r in rows])
        if rows and self.follow_trace.isChecked(): self.phase_table.scrollToBottom()
        else: self.phase_table.verticalScrollBar().setValue(scroll)
        self.event_log.setPlainText('\n'.join(f'{e["event"]}: {e["reason"]}' for e in list(d.diagnostics.events)[-30:]))
        event_bar = self.event_log.verticalScrollBar()
        event_bar.setValue(event_bar.maximum() if self.follow_trace.isChecked() else event_scroll)

    def export_report(self, *_args, path=None):
        if path is None:
            path, _ = QFileDialog.getSaveFileName(self, 'Save commissioning report',
                                                'chopsaw-commissioning.json', 'JSON files (*.json)')
        if not path: return False
        try:
            c = self.owner.dry_run.supervision.context()
            self.owner.dry_run.diagnostics.write_report(path, time.monotonic(), {
                'geometry': asdict(c.geometry), 'material': asdict(c.material),
                'geometry_revision': c.config_revision,
                'configured_timings_ms': self.owner.cylinder_timing.snapshot(),
                'requested_timing_values_ms': self.owner.dry_run.loaded,
                'cut_lengths_in': [float(length) for _, length, _ in self.owner.cut_list],
                'checklist': {},
                'session_notes': '',
                'preview_source': 'offline example' if self.source.currentIndex() else 'live readback',
                'preview': {'context': asdict(self.current_context), 'decision': asdict(self.current_decision)}
                           if self.current_context else None,
            })
        except (OSError, ValueError, TypeError) as error:
            message = 'Report could not be saved: '+str(error)
            self.export_feedback.setText(message); return False
        message = 'Report saved: '+str(path)
        self.export_feedback.setText(message); return True
