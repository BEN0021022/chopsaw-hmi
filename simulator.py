# simulator.py

import math
import random
import threading
import time
from collections import deque

STEPS_PER_INCH = 127.0
TRUING_TRIM = 1.0  # inches removed by the truing cut (shared with the HMI sim view)


class VirtualController:
    """
    Drop-in stand-in for serial.Serial that emulates the chop saw firmware.

    Exposes the same surface the HMI uses (is_open, in_waiting, readline,
    write, close) so listen_for_data and send_command work unchanged. An
    internal thread runs a trapezoidal motion model and a simple board model,
    and streams the same POS:... status lines the real controller sends,
    plus an SSEN field for the saw position sensor.
    """

    def __init__(self, home_position=160.5):  # matches firmware HOME_POSITION_INCHES
        self.is_open = True
        self.home_position = home_position
        self.board_length = 145.5  # set by the HMI: usable length + truing trim
        self._rx = deque()
        self._lock = threading.Lock()

        # Motion
        self.pos = 0.0
        self.vel = 0.0
        self.target = 0.0
        self.vmax = 3000.0 / STEPS_PER_INCH
        self.acc = 1000.0 / STEPS_PER_INCH
        self.state = "IDLE"
        self.homed = 0
        self.motor_enabled = True
        self._homing = False
        self.profiles = {0: (2500.0, 900.0), 1: (600.0, 600.0), 2: (3500.0, 2500.0)}
        self.active_profile = 0

        # Board (drives the board sensor)
        self.board_remaining = None   # inches of board between edge and back
        self.board_edge = 0.0         # leading edge, inches from blade (negative = past it)
        self.sensor_loc = 10.8

        # Saw
        self.saw_up = 1
        self.saw_down = False
        self.blade_pressed = False
        self._saw_busy = False
        self._saw_timing = {}

        # Current sensing
        self.monitoring = False
        self.current_limit = 2.5
        self.trip_delay_ms = 150
        self.oct = 0
        self._over_since = None

        self._events = []  # [(due_monotonic, fn)]
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    # ---------- serial.Serial interface ----------
    @property
    def in_waiting(self):
        return len(self._rx)

    def readline(self):
        try:
            return self._rx.popleft()
        except IndexError:
            return b""

    def write(self, data):
        line = data.decode("utf-8", errors="ignore").strip()
        if line:
            with self._lock:
                self._handle_command(line)
        return len(data)

    def close(self):
        self.is_open = False
        if self._thread.is_alive() and threading.current_thread() is not self._thread:
            self._thread.join(timeout=1.0)

    # ---------- internals ----------
    def _send(self, text):
        self._rx.append((text + "\n").encode("utf-8"))

    def _schedule(self, delay_s, fn):
        self._events.append((time.monotonic() + delay_s, fn))

    def _handle_command(self, line):
        cmd, payload = line[0], line[1:]
        if cmd == "X":
            self.motor_enabled = False
            self.target = self.pos
            self.vel = 0.0
            self.homed = 0
            self._homing = False
            self.state = "DISABLED"
            return
        if cmd == "E":
            self.motor_enabled = True
            if self.state == "DISABLED":
                self.state = "IDLE"
            return
        if cmd in ("H", "S", "J") and not self.motor_enabled:
            return
        if cmd == "H":
            self.state = "HOMING"
            self._homing = True
            self.target = self.home_position
        elif cmd == "S":
            try:
                val = float(payload)
            except ValueError:
                return
            self.target = min(max(val, 0.0), self.home_position)
            self.state = "MOVING"
        elif cmd == "J":
            # Detect board edge: spawn a fresh board against the carriage and
            # advance until the leading edge sits TRUING_TRIM past the blade.
            try:
                self.sensor_loc = float(payload)
            except ValueError:
                pass
            self.board_remaining = self.board_length
            self.board_edge = self.pos - self.board_remaining
            self.target = max(0.0, self.board_remaining - TRUING_TRIM)
            self.state = "DETECTING"
        elif cmd == "A":
            try:
                spd, acc = (float(x) for x in payload.split(","))
            except ValueError:
                return
            self.vmax = spd / STEPS_PER_INCH
            self.acc = acc / STEPS_PER_INCH
            self.profiles[self.active_profile] = (spd, acc)
        elif cmd == "Z":
            try:
                idx = int(payload)
            except ValueError:
                return
            if idx in self.profiles:
                self.active_profile = idx
                spd, acc = self.profiles[idx]
                self.vmax = spd / STEPS_PER_INCH
                self.acc = acc / STEPS_PER_INCH
        elif cmd == "M":
            self.target = self.pos
        elif cmd == "V":
            self._start_saw_stroke()
        elif cmd == "C":
            # C1..C3 are cylinder extends; anything else is a calibration request
            if payload not in ("1", "2", "3"):
                self._send(f"CAL_SUCCESS:{STEPS_PER_INCH * 20.0:.1f},{STEPS_PER_INCH:.1f}")
        elif cmd == "W":
            self.monitoring = payload.strip() == "1"
        elif cmd == "O":
            try:
                lim, delay = payload.split(",")
                self.current_limit = float(lim)
                self.trip_delay_ms = int(float(delay))
            except ValueError:
                pass
        elif cmd == "R":
            self.oct = 0
            self._over_since = None
            if self.state == "OVERCURRENT":
                self.state = "IDLE"
        # D/K/L/U/N: accepted silently; the ideal motion model has no PID toggle.

    def configure_saw_timing(self, timing):
        """Simulation-only plan; never sent through a physical serial port."""
        with self._lock:
            self._saw_timing = dict(timing)

    def cancel_saw_cycle(self):
        with self._lock:
            self._events.clear()
            self._saw_busy = False
            self.saw_up = 1
            self.saw_down = False
            self.blade_pressed = False

    def set_manual_blade(self, pressed):
        with self._lock:
            self.blade_pressed = bool(pressed)

    def manual_saw_travel(self, down):
        with self._lock:
            if self._saw_busy:
                return False
            self._saw_busy = True
            self.saw_down = False
            def arrive():
                self.saw_up = 0 if down else 1
                self.saw_down = bool(down)
                self._saw_busy = False
            if down:
                self._schedule(.4, lambda: setattr(self, 'saw_up', 0))
            self._schedule(1.6 if down else 1.0, arrive)
            return True

    def _start_saw_stroke(self):
        if self._saw_busy:
            return
        self._saw_busy = True

        def down():
            self.saw_up = 0

        def cut():
            self.saw_down = True
            if self.board_remaining is not None:
                # Everything past the blade is removed; remaining edge sits at the blade
                back = self.board_edge + self.board_remaining
                self.board_remaining = back if back > 0.01 else None
                self.board_edge = 0.0

        def up():
            self.saw_up = 1
            self.saw_down = False
            self._saw_busy = False

        timing = self._saw_timing
        start = sum(timing.get(key, 0) for key in
                    ('trigger.press_delay', 'trigger.spinup', 'saw.down_delay')) / 1000
        dwell = (timing.get('saw.bottom_dwell', 0) + timing.get('saw.up_delay', 0)) / 1000
        # Physical travel is a fixed virtual model, not a prediction of real air hardware.
        self._schedule(start + 0.4, down)
        self._schedule(start + 1.6, cut)
        self._schedule(start + 2.6 + dwell, up)

    def _step_motion(self, dt):
        if not self.motor_enabled:
            return
        err = self.target - self.pos
        if abs(err) < 1e-4 and abs(self.vel) < 0.05:
            if self.state in ("MOVING", "HOMING", "DETECTING"):
                self.pos = self.target
                self.vel = 0.0
                if self._homing:
                    self._homing = False
                    self.homed = 1
                    self._send(f"STATUS:HOME_POS:{self.home_position:.4f}")
                self.state = "IDLE"
            return
        # Velocity command limited by accel and braking distance
        v_brake = math.sqrt(2.0 * self.acc * abs(err))
        v_des = math.copysign(min(self.vmax, v_brake), err)
        dv = v_des - self.vel
        max_dv = self.acc * dt
        self.vel += max(-max_dv, min(max_dv, dv))
        new_pos = self.pos + self.vel * dt
        if (err > 0 and new_pos > self.target) or (err < 0 and new_pos < self.target):
            new_pos = self.target
            self.vel = 0.0
        self.pos = new_pos
        # The carriage pushes the board toward the blade; retracting leaves it
        if self.board_remaining is not None:
            back = self.board_edge + self.board_remaining
            if self.pos < back:
                self.board_edge = self.pos - self.board_remaining

    def _current_draw(self):
        if self.saw_up == 0:
            amps = 1.7 + random.uniform(-0.2, 0.5)
        elif self.state in ("MOVING", "HOMING", "DETECTING"):
            amps = 0.9 + random.uniform(-0.1, 0.25)
        else:
            amps = 0.25 + random.uniform(-0.05, 0.1)
        return max(0.0, amps)

    def _run(self):
        dt = 0.02
        last_status = 0.0
        while self.is_open:
            now = time.monotonic()
            with self._lock:
                due = [e for e in self._events if e[0] <= now]
                self._events = [e for e in self._events if e[0] > now]
                for _, fn in due:
                    fn()
                self._step_motion(dt)
                if now - last_status >= 0.06:
                    last_status = now
                    amps = self._current_draw()
                    if self.monitoring and amps > self.current_limit:
                        if self._over_since is None:
                            self._over_since = now
                        elif (now - self._over_since) * 1000.0 >= self.trip_delay_ms:
                            self.oct = 1
                            self.state = "OVERCURRENT"
                            self.target = self.pos
                    else:
                        self._over_since = None
                    sen = 1 if self.pos >= self.home_position - 0.3 else 0
                    if self.board_remaining is not None:
                        back = self.board_edge + self.board_remaining
                        bsen = 1 if self.board_edge <= self.sensor_loc <= back else 0
                    else:
                        bsen = 0
                    cv = 2.5 + amps * 0.185
                    self._send(
                        f"POS:{self.pos:.4f},HOMED:{self.homed},STATE:{self.state},"
                        f"SEN:{sen},BSEN:{bsen},SSEN:{self.saw_up},"
                        f"CV:{cv:.3f},CUR:{amps:.3f},OCT:{self.oct}"
                    )
            time.sleep(dt)
