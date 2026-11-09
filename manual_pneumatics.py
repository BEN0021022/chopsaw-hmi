"""Manual actuator UI and virtual commissioning behavior; no native output fallback."""
import time
from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import QGroupBox, QGridLayout, QLabel, QPushButton
from simulator import VirtualController


class ManualPneumatics(QGroupBox):
    state_changed = pyqtSignal()

    def __init__(self, owner):
        super().__init__('Manual Machine Controls')
        disabled = 'QPushButton:disabled { background:#111827; color:#64748b; border-color:#1e293b; }'
        self.setStyleSheet(disabled)
        self.owner = owner
        self.phase = ''
        self.token = 0
        self.session = None
        self.clamp_settled = False
        self.last_view = None
        self.notice = ''
        layout = QGridLayout(self)
        self.status = QLabel('Teensy manual pneumatics require controller sequencing and commissioning.')
        self.status.setWordWrap(True)
        self.status.setStyleSheet('color:#fbbf24; font-size:14px;')
        layout.addWidget(self.status, 0, 0, 1, 4)
        self.native_controls = owner.dry_run.controls()
        layout.addWidget(self.native_controls, 1, 0, 1, 4)
        self.labels = {}
        self.buttons = {}
        rows = (
            ('clamp', 'Main clamp', ('engage','Clamp'), ('release','Release')),
            ('travel', 'Saw travel', ('lower','Lower'), ('up','Return UP')),
            ('trigger', 'Blade trigger', ('press','Press trigger'), ('unpress','Release trigger')),
        )
        for row, (key, title, first, second) in enumerate(rows, 2):
            layout.addWidget(QLabel(title), row, 0)
            self.labels[key] = QLabel('UNKNOWN')
            self.labels[key].setStyleSheet('font-size:13px; color:#94a3b8;')
            layout.addWidget(self.labels[key], row, 1)
            for column, (action, text) in enumerate((first, second), 2):
                button = QPushButton(text)
                button.setMinimumHeight(40)
                button.setEnabled(False)
                button.clicked.connect(lambda _checked=False, a=action: self.request(a))
                self.buttons[action] = button
                layout.addWidget(button, row, column)
        self.cycle_button = QPushButton('Manual Saw Cycle')
        self.cycle_button.setMinimumHeight(48)
        self.cycle_button.setStyleSheet('QPushButton { background:#166534; color:#e2e8f0; font-size:17px; }' + disabled)
        self.cycle_button.setEnabled(False)
        self.cycle_button.clicked.connect(lambda: self.request('cycle'))
        layout.addWidget(self.cycle_button, 5, 0, 1, 3)
        self.stop_button = QPushButton('STOP')
        self.stop_button.setMinimumHeight(48)
        self.stop_button.setStyleSheet('QPushButton { background:#b91c1c; color:white; font-weight:bold; }' + disabled)
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop)
        layout.addWidget(self.stop_button, 5, 3)
        self.note = QLabel('Normal saw cycle keeps the main clamp engaged. Release it explicitly after the cut.')
        self.note.setWordWrap(True); self.note.setStyleSheet('color:#94a3b8; font-size:13px;')
        layout.addWidget(self.note, 6, 0, 1, 4)
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()

    def simulator(self):
        port = self.owner.ser
        return port if isinstance(port, VirtualController) and port.is_open else None

    def available(self):
        sim = self.simulator()
        return bool(sim and sim.state in ('IDLE','DISABLED')
                    and self.owner.auto_cycle_state in ('IDLE','FINISHED','WAITING_FOR_NEW_BOARD')
                    and not getattr(self.owner, '_simulation_pneumatic_pending', False)
                    and self.owner._sim_health_received is not None
                    and time.monotonic()-self.owner._sim_health_received <= 2
                    and self.owner.auto_live_status.property('healthState') == 'healthy')

    def motion_locked(self):
        sim = self.simulator()
        if not sim: return self.owner.dry_run.motion_locked()
        return bool(sim and (self.phase or self.owner.clamp_left_engaged or sim.blade_pressed or not sim.saw_up))

    def wait(self, ms, callback):
        token, generation, port = self.token, self.owner.cycle_generation, self.owner.ser
        def run():
            if (token == self.token and generation == self.owner.cycle_generation
                    and port is self.owner.ser and self.available()):
                callback()
        QTimer.singleShot(int(ms), run)

    def finish(self, notice=''):
        self.phase = ''
        self.notice = notice
        self.refresh()

    def request(self, action):
        self.refresh()
        if not self.simulator():
            return self.owner.dry_run.request(action) if action not in ('press','unpress') else False
        if not self.available() or self.phase:
            return False
        sim = self.simulator()
        timing = self.owner.cylinder_timing.snapshot()
        clamp = self.owner.clamp_left_engaged and self.clamp_settled
        if action in ('lower','press','cycle') and (not clamp or not sim.saw_up or sim._saw_busy):
            return False
        if action in ('engage','release') and (not sim.saw_up or sim.blade_pressed or sim._saw_busy):
            return False
        if action == 'release' and not self.owner.clamp_left_engaged:
            return False
        if action == 'engage' and self.owner.clamp_left_engaged:
            return False
        if action == 'up' and (sim.saw_up or sim._saw_busy):
            return False
        if action == 'unpress' and not sim.blade_pressed:
            return False
        if action == 'press' and sim.blade_pressed:
            return False
        self.token += 1
        self.notice = ''
        self.phase = action
        if action in ('engage','release'):
            self.clamp_settled = False
            def command_clamp():
                method = self.owner.cylinder_extend if action == 'engage' else self.owner.cylinder_retract
                if not method(1):
                    self.stop(); return
                def done():
                    self.clamp_settled = action == 'engage'
                    self.finish()
                settle = 'engage_settle' if action == 'engage' else 'release_clearance'
                self.wait(timing[f'main.{settle}'], done)
            self.wait(timing[f'main.{"engage_delay" if action == "engage" else "release_delay"}'], command_clamp)
        elif action in ('press','unpress'):
            delay = timing['trigger.press_delay' if action == 'press' else 'trigger.release_delay']
            def trigger():
                sim.set_manual_blade(action == 'press')
                self.wait(timing['trigger.spinup' if action == 'press' else 'trigger.brake_wait'], self.finish)
            self.wait(delay, trigger)
        elif action in ('lower','up'):
            delay = timing['saw.down_delay' if action == 'lower' else 'saw.up_delay']
            def travel():
                if not sim.manual_saw_travel(action == 'lower'):
                    self.stop(); return
                self.poll_travel(sim, up=action == 'up', settle=timing['saw.up_settle'] if action == 'up' else 0)
            self.wait(delay, travel)
        elif action == 'cycle':
            # Full virtual cycle, independent of Auto cut lists and clamp selection.
            def start():
                sim.set_manual_blade(True)
                stroke_timing = dict(timing, **{'trigger.press_delay':0, 'trigger.spinup':0})
                sim.configure_saw_timing(stroke_timing)
                if not self.owner.send_backend_commands(self.owner.active_controller().saw_actuate(), 'run manual simulated saw cycle'):
                    self.stop(); return
                def after_up():
                    def release_trigger():
                        sim.set_manual_blade(False)
                        self.wait(timing['trigger.brake_wait'], lambda: self.finish('Manual cycle complete; clamp retained.'))
                    self.wait(timing['saw.up_settle'] + timing['trigger.release_delay'], release_trigger)
                self.poll_travel(sim, up=True, complete=after_up)
            self.wait(timing['trigger.press_delay'] + timing['trigger.spinup'], start)
        else:
            self.phase = ''; return False
        self.refresh()
        return True

    def poll_travel(self, sim, *, up, settle=0, complete=None):
        if not sim._saw_busy and (sim.saw_up if up else sim.saw_down):
            self.wait(settle, complete or self.finish)
        else:
            self.wait(50, lambda: self.poll_travel(sim, up=up, settle=settle, complete=complete))

    def stop(self):
        sim = self.simulator()
        if not sim:
            if not self.owner.dry_run.native() or not self.owner.dry_run.compatible: return False
            self.owner.dry_run.stop(); return True
        if (not sim or getattr(self.owner, '_simulation_pneumatic_pending', False)
                or self.owner.auto_cycle_state not in ('IDLE','FINISHED','WAITING_FOR_NEW_BOARD')):
            return False
        self.token += 1
        sim.cancel_saw_cycle()
        self.phase = ''
        self.notice = 'Stopped in Simulator; clamp retained.'
        self.refresh()
        return True

    def refresh(self):
        sim = self.simulator()
        self.native_controls.setVisible(not bool(sim))
        if not sim:
            # Revoke delayed simulator callbacks on disconnect/mode change too.
            if self.session is not None or self.phase:
                self.token += 1; self.session = None; self.phase = ''; self.clamp_settled = False
            native=self.owner.dry_run
            commands={'engage':'DCLAMP 1','release':'DCLAMP 0','lower':'DDOWN','up':'DUP'}
            for action,button in self.buttons.items(): button.setEnabled(native.allowed(commands.get(action,'')))
            self.cycle_button.setText('Unloaded Saw Cycle')
            self.cycle_button.setEnabled(native.allowed('DCYCLE'))
            self.stop_button.setText('Stop / release')
            self.stop_button.setEnabled(native.native() and native.compatible)
            fresh=native.fresh()
            self.labels['clamp'].setText(('ON commanded' if native.data.get('CLAMP')=='1' else 'OFF commanded') if fresh else 'UNKNOWN')
            self.labels['travel'].setText(self.owner.carriage_tab.safety.get('SAW_POSITION','UNKNOWN') if fresh else 'UNKNOWN')
            self.labels['trigger'].setText('LOCKED OFF' if native.compatible else 'UNKNOWN')
            self.status.setText(native.message if native.compatible else 'Requires matching unloaded-test firmware 0.16.0. No hardware outputs are enabled here.')
            self.note.setText('Unloaded tests only: saw mains unplugged, no stock. Trigger output stays OFF. Stop/fault releases the clamp; a normal stroke retains it.')
            self.state_changed.emit()
            return
        self.cycle_button.setText('Manual Saw Cycle'); self.stop_button.setText('STOP')
        self.note.setText('Normal saw cycle keeps the main clamp engaged. Release it explicitly after the cut.')
        session = (self.owner.ser, self.owner.cycle_generation)
        if session != self.session:
            self.session = session
            self.token += 1
            self.phase = ''
            self.clamp_settled = False
            self.notice = ''
        available = self.available()
        if sim and not available and (self.phase or sim.blade_pressed) and not getattr(self.owner, '_simulation_pneumatic_pending', False):
            self.token += 1; sim.cancel_saw_cycle(); self.phase = ''
            self.notice = 'Manual simulation stopped: feedback or operating state changed.'
        idle = available and not self.phase
        held = bool(sim and self.owner.clamp_left_engaged)
        up = bool(sim and sim.saw_up)
        blade = bool(sim and sim.blade_pressed)
        busy = bool(sim and sim._saw_busy)
        for name, allowed in {
            'engage':idle and up and not held and not blade and not busy,
            'release':idle and up and held and not blade and not busy,
            'lower':idle and held and self.clamp_settled and up and not busy,
            'up':idle and not up and not busy,
            'press':idle and held and self.clamp_settled and up and not blade and not busy,
            'unpress':idle and blade,
        }.items(): self.buttons[name].setEnabled(allowed)
        self.cycle_button.setEnabled(idle and held and self.clamp_settled and up and not busy)
        self.stop_button.setEnabled(bool(sim and (self.phase or blade or not up)
                                         and not getattr(self.owner, '_simulation_pneumatic_pending', False)
                                         and self.owner.auto_cycle_state in ('IDLE','FINISHED','WAITING_FOR_NEW_BOARD')))
        if sim:
            self.labels['clamp'].setText('HELD (sim)' if held and self.clamp_settled else 'HELD / UNVERIFIED' if held else 'RELEASED (sim)')
            self.labels['travel'].setText('MOVING (sim)' if busy else 'UP (sim)' if up else 'DOWN (sim)')
            self.labels['trigger'].setText('PRESSED (sim)' if blade else 'RELEASED (sim)')
            prompt = ('Return the saw UP before releasing the clamp.' if not up else
                      'Main clamp engaged. Ready for Manual Saw Cycle.' if held and self.clamp_settled else
                      'Clamp the material, then run Manual Saw Cycle.')
            detail = (self.phase.replace('_',' ') + ' in progress' if self.phase else self.notice or
                      (prompt if available else 'Waiting for fresh feedback / idle machine.'))
            text = 'Simulator only — ' + detail
        else:
            for label in self.labels.values(): label.setText('UNKNOWN')
            text = 'Teensy manual pneumatics require controller sequencing and commissioning. No hardware outputs are enabled here.'
        self.status.setText(text)
        view = (session, available, self.phase, held, up, blade, busy, self.clamp_settled)
        if view != self.last_view:
            self.last_view = view
            self.state_changed.emit()
