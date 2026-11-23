"""Offline Simulator / Legacy Mega cycle, current monitor, and motion prediction mixin."""
from datetime import datetime
from math import sqrt
import os
import time

from PyQt6.QtCore import QTimer

from controller_backends import TEENSY_CARRIAGE
from pneumatic_timing import CLAMPS, simulation_clamps
from sim_view import PIECE_COLORS, SCRAP_COLOR, TRIM_COLOR
from simulator import TRUING_TRIM, VirtualController


class SimulatorCycleMixin:
    """Keeps offline VirtualController / Legacy Mega simulation logic out of main.py."""

    def cylinder_extend(self, cyl_id):
        if cyl_id not in (1, 2):
            return False
        if not self.send_backend_commands(
            self.active_controller().clamp_extend(cyl_id),
            f"extend cylinder {cyl_id}",
        ):
            return False
        if cyl_id == 1:
            self.clamp_left_engaged = True
        elif cyl_id == 2:
            self.clamp_right_engaged = True
        self._update_cylinder_ui(cyl_id)
        return True

    def cylinder_retract(self, cyl_id):
        if cyl_id not in (1, 2):
            return False
        if not self.send_backend_commands(
            self.active_controller().clamp_retract(cyl_id),
            f"retract cylinder {cyl_id}",
        ):
            return False
        if cyl_id == 1:
            self.clamp_left_engaged = False
        elif cyl_id == 2:
            self.clamp_right_engaged = False
        self._update_cylinder_ui(cyl_id)
        return True

    def _update_cylinder_ui(self, cyl_id):
        engaged_map = {1: self.clamp_left_engaged, 2: self.clamp_right_engaged}
        pill_map = {1: "fa_cyl1_status", 2: "fa_cyl2_status"}
        engaged = engaged_map[cyl_id]
        pill_attr = pill_map[cyl_id]
        if hasattr(self, pill_attr):
            pill_widget = getattr(self, pill_attr)
            if engaged:
                self.set_pill(pill_widget, "EXTENDED", "#2563eb")
            else:
                self.set_pill(pill_widget, "RETRACTED", "#475569", fg="#e2e8f0")
        if hasattr(self, 'saw_sim'):
            self.saw_sim.set_clamps(self.clamp_left_engaged, self.clamp_right_engaged)

    def _update_saw_sensor_pill(self, text, color):
        if hasattr(self, 'fa_saw_position_label'):
            self.set_pill(self.fa_saw_position_label, text, color)
        if hasattr(self, 'saw_sim'):
            self.saw_sim.set_saw_state(text)

    def update_saw_position_sensor_status(self, status):
        """Virtual SSEN:1 confirms UP; SSEN:0 means not UP. Simulator only."""
        rising = status == 1 and self._last_saw_sensor == 0
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
        """Start the virtual saw cycle with this cut's timing snapshot."""
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
        if is_truing:
            self.sim_active_piece = {"truing": True}
        elif self.current_cut_index < len(self.cut_list):
            _, length, _ = self.cut_list[self.current_cut_index]
            self.sim_active_piece = {
                "truing": False,
                "early": early_return,
                "length": length,
                "color": PIECE_COLORS[self.current_cut_index % len(PIECE_COLORS)],
            }

    def _sync_sim_index(self):
        self.sim_next_piece_index = self.current_cut_index

    def _sim_track_carriage(self, pos):
        if not hasattr(self, 'saw_sim'):
            return
        if self.sim_board_remaining is not None:
            back = self.sim_edge_pos + self.sim_board_remaining
            if pos < back - 1e-9:
                self.sim_edge_pos = pos - self.sim_board_remaining
                self.saw_sim.set_board_edge(self.sim_edge_pos)
        self.saw_sim.set_carriage(pos)

    def _refresh_sim_board(self):
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
            self.sim_next_piece_index = self.current_cut_index
        else:
            self.sim_next_piece_index = self.current_cut_index + 1
        if hasattr(self, 'saw_sim'):
            if piece.get("truing"):
                self.saw_sim.eject_piece(TRUING_TRIM, TRIM_COLOR, "trim")
            else:
                self.saw_sim.eject_piece(piece["length"], piece["color"], f'{piece["length"]:g}"')
        self._refresh_sim_board()

    def _schedule_simulation_phase(self, delay_ms, callback):
        generation, port = self.cycle_generation, self.ser

        def run():
            if (
                generation == self.cycle_generation
                and self.ser is port
                and isinstance(port, VirtualController)
                and port.is_open
                and self.auto_clamp_enabled
            ):
                callback()

        QTimer.singleShot(int(delay_ms), run)

    def _engage_clamps_for_cut(self, early_return=False):
        if not isinstance(self.ser, VirtualController) or not self.auto_clamp_enabled:
            return False
        position = self.current_position
        is_truing = (not early_return) and self.auto_cycle_state == "WAITING_FOR_TRUING_CUT"
        clamps = simulation_clamps(position, is_truing)
        timing = self.cylinder_timing.snapshot()
        self._cycle_clamps = clamps
        self._cycle_cylinder_timings = timing
        self._simulation_pneumatic_pending = True
        self._set_cut_complete_enabled(False)
        self._set_cycle_status('STATUS: Board in position — settling before simulated clamping...')
        self._record_sim_piece(early_return, is_truing)

        def _do_clamp():
            self._run_simulation_clamps(clamps, timing, 'engage', self._actuate_saw)

        self._schedule_simulation_phase(timing['board.settle'], _do_clamp)
        return True

    def _run_simulation_clamps(self, clamps, timing, phase, complete):
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
            self.set_pill(self.auto_clamp_status_label, "UNKNOWN", "#475569")
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

    def resume_after_reset(self):
        if self.manual_pneumatics.motion_locked():
            return False
        if getattr(self, '_simulation_pneumatic_pending', False):
            return False
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
        if self.current_cut_index >= len(self.cut_list):
            self.current_cut_index = max(0, len(self.cut_list) - 1)
        self.perform_early_return = False
        self.is_early_returning = False
        self.clamps_engaged_cutting = False
        self.sim_active_piece = None
        self._sync_sim_index()
        cut_num, cut_length, _ = self.cut_list[self.current_cut_index]
        self._set_cycle_status(f'STATUS: Resuming after reset at cut {cut_num} ({cut_length:.2f}")')
        self.update_cut_list_display()
        self.switch_profile("GENTLE", True)
        self.auto_cycle_state = "DETECTING"
        self._set_start_enabled(False)
        self._set_cut_complete_enabled(False)
        self.advance_auto_cycle()

    def cut_complete_pressed(self):
        if not isinstance(self.ser, VirtualController):
            return False
        if getattr(self, '_simulation_pneumatic_pending', False):
            return False
        if self.clamps_engaged_cutting:
            return False
        if self.sim_active_piece is not None:
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

    def advance_auto_cycle(self):
        if not self.active_controller().capabilities.automatic_cycle_ready:
            return False
        self.perform_early_return = False
        if self.auto_cycle_state == "DETECTING":
            self._set_cycle_status("STATUS: Detecting board edge...")
            sensor_offset = self.board_sensor_location_input.value()
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
                self.auto_cycle_state = "FINISHED"
                self.advance_auto_cycle()
                return
            current_pos = self.current_position
            cut_num, cut_length, _ = self.cut_list[self.current_cut_index]
            kerf = self.kerf_input.value()
            total_material_needed = cut_length + kerf
            if current_pos < total_material_needed:
                self.auto_cycle_state = "WAITING_FOR_NEW_BOARD"
                self._set_cycle_status("STATUS: Board empty. Load new board.")
                self._set_start_enabled(True)
                self._set_cut_complete_enabled(False)
                self.load_position()
                return
            self._set_cycle_status(f'STATUS: Advancing for cut {cut_num} ({cut_length:.2f}")')
            new_pos = current_pos - total_material_needed
            next_cut_index = self.current_cut_index + 1
            if next_cut_index < len(self.cut_list):
                needed_for_next = self.cut_list[next_cut_index][1] + kerf
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

    # ---------- Current monitor (Simulator) ----------
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

    def update_motor_state(self, state):
        if isinstance(self.ser, VirtualController):
            self.enable_chk.blockSignals(True)
            self.enable_chk.setChecked(self.ser.motor_enabled)
            self.enable_chk.blockSignals(False)
        self.current_motor_state = state
        previous_motor_state = self.state_label.text()
        self.state_label.setText(state)
        color = {
            "IDLE": "#22c55e",
            "MOVING": "#60a5fa",
            "HOMING": "#60a5fa",
            "DETECTING": "#60a5fa",
            "OVERCURRENT": "#ef4444",
        }.get(state, "#a78bfa")
        self.state_label.setStyleSheet(f"color: {color}; font-weight: bold;")
        if state == "OVERCURRENT":
            self.update_overcurrent_status(1)
        if state != "MOVING":
            self.pred_active = False

        if state == "IDLE" and previous_motor_state in ["MOVING", "DETECTING"]:
            if self.perform_early_return:
                self.perform_early_return = False
                self.is_early_returning = True
                if self.auto_clamp_enabled:
                    self._engage_clamps_for_cut(early_return=True)
                else:
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
                    is_truing = self.auto_cycle_state == "WAITING_FOR_TRUING_CUT"
                    self._record_sim_piece(early_return=False, is_truing=is_truing)
                    self._set_cycle_status("STATUS: Simulation in position; awaiting simulated completion.")

    def update_sensor_status(self, status):
        text = "ON" if status == 1 else "OFF"
        bg = "#22c55e" if status == 1 else "#ef4444"
        for widget in (
            self.sensor_label,
            self.auto_homing_sensor_label,
            getattr(self, 'fa_homing_sensor_label', None),
        ):
            if widget is not None:
                self.set_pill(widget, text, bg)

    def update_board_sensor_status(self, status):
        text = "ON" if status == 1 else "OFF"
        bg = "#22c55e" if status == 1 else "#ef4444"
        self.board_sensor_tripped = status == 1
        for widget in (
            self.board_sensor_label,
            self.auto_board_sensor_label,
            getattr(self, 'fa_board_sensor_label', None),
        ):
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
        self.overcurrent_tripped = status == 1
        if hasattr(self, 'current_status_label'):
            if self.overcurrent_tripped:
                self.set_pill(self.current_status_label, "Overcurrent Tripped", "#ef4444")
                if hasattr(self, 'auto_status_label'):
                    self._set_cycle_status("STATUS: Overcurrent protection tripped.")
            else:
                self.set_pill(self.current_status_label, "Current OK", "#22c55e", fg="#0f172a")

    def update_calibration_factors(self, new_encoder_tpi, new_stepper_spi):
        self.encoder_ticks_per_inch = new_encoder_tpi
        self.stepper_steps_per_inch = new_stepper_spi
        self.log.append("HMI calibration factors updated.")

    def update_home_position(self, pos):
        self.home_position = pos
        self.log.append(f'Max travel distance set to: {pos}"')
        try:
            if hasattr(self, 'board_sensor_location_input') and self.board_sensor_location_input is not None:
                self.board_sensor_location_input.setRange(0, pos)
            if hasattr(self, 'load_button') and self.load_button is not None:
                self.load_button.setText(f'LOAD POSITION ({pos:.2f}")')
            if hasattr(self, 'saw_sim'):
                self.saw_sim.set_home_position(pos)
        except Exception as e:
            print("update_home_position guarded:", e)

    # ---------- Prediction model (Simulator) ----------
    def prepare_prediction(self, target_in):
        start_in = self.current_position
        self.pred_start_pos = start_in
        self.pred_target_pos = target_in
        self.pred_dir = 1.0 if (target_in - start_in) >= 0 else -1.0
        if self.active_profile_name == "NORMAL":
            spd_steps, acc_steps = self.norm_speed.value(), self.norm_accel.value()
        elif self.active_profile_name == "GENTLE":
            spd_steps, acc_steps = self.gentle_speed.value(), self.gentle_accel.value()
        else:
            spd_steps, acc_steps = self.fast_speed.value(), self.fast_accel.value()
        if self.stepper_steps_per_inch <= 0:
            self.pred_vmax_in = 0.0
            self.pred_acc_in = 0.0
        else:
            self.pred_vmax_in = float(spd_steps) / self.stepper_steps_per_inch
            self.pred_acc_in = float(acc_steps) / self.stepper_steps_per_inch
        self.pred_start_time = time.monotonic()
        self.pred_active = True
        if not self.pred_timer.isActive():
            self.pred_timer.start()

    def tick_predict(self):
        if not self.pred_active:
            return
        now = time.monotonic()
        t = now - self.pred_start_time
        s0 = self.pred_start_pos
        sf = self.pred_target_pos
        dist = abs(sf - s0)
        if dist < 1e-6 or self.pred_vmax_in <= 0 or self.pred_acc_in <= 0:
            self.pred_active = False
            return
        a = self.pred_acc_in
        v = self.pred_vmax_in
        t_acc = v / a
        d_acc = 0.5 * a * t_acc * t_acc
        if 2 * d_acc < dist:
            d_cruise = dist - 2 * d_acc
            t_cruise = d_cruise / v
            if t <= t_acc:
                s = 0.5 * a * t * t
            elif t <= t_acc + t_cruise:
                s = d_acc + v * (t - t_acc)
            else:
                td = t - (t_acc + t_cruise)
                if td >= t_acc:
                    s = dist
                    self.pred_active = False
                else:
                    s = d_acc + d_cruise + (v * td - 0.5 * a * td * td)
        else:
            t_acc_tri = sqrt(dist / a)
            if t <= t_acc_tri:
                s = 0.5 * a * t * t
            else:
                td = t - t_acc_tri
                if td >= t_acc_tri:
                    s = dist
                    self.pred_active = False
                else:
                    v_peak = a * t_acc_tri
                    s = 0.5 * a * t_acc_tri * t_acc_tri + (v_peak * td - 0.5 * a * td * td)
        pos = s0 + self.pred_dir * s
        if (self.pred_dir > 0 and pos > sf) or (self.pred_dir < 0 and pos < sf):
            pos = sf
            self.pred_active = False
        self.position_label.setText(f"{pos:.4f}")
        self.auto_position_label.setText(f"{pos:.4f}")
        if hasattr(self, 'fa_position_label'):
            self.fa_position_label.setText(f"{pos:.4f}")
        self._sim_track_carriage(pos)
