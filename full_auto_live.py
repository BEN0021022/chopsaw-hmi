"""Display-only projection of the shared Auto controls and native machine model."""
from controller_backends import TEENSY_CARRIAGE
from sim_view import PIECE_COLORS, SCRAP_COLOR


def refresh_full_auto(w):
    if not hasattr(w, 'dry_run') or not hasattr(w, 'fa_stop_button'):
        return
    native = w.active_controller().key == TEENSY_CARRIAGE
    view = w.saw_sim
    if view.live != native:
        view.live = native
        view._eject = None
        view._eject_timer.stop()
        view.material_note = ''
        view.clamp_enabled = (True, True)
    w.fa_start_cycle_button.setEnabled(w.start_cycle_button.isEnabled())
    w.fa_start_cycle_button.setText(w.start_cycle_button.text().replace('Start Auto', 'Start Cycle'))
    w.fa_stop_button.setEnabled(w.is_connected())
    w.fa_operator_cut_button.setVisible(native and not w.operator_cut_button.isHidden()
                                        and not (w.dry_run.sequence or {}).get('automatic_cut_return'))
    w.fa_operator_cut_button.setEnabled(native and w.operator_cut_button.isEnabled())
    w.fa_operator_cut_button.setText(w.operator_cut_button.text())
    w.fa_operator_cut_button.setToolTip(w.operator_cut_button.toolTip())
    if not native:
        return
    p, d = w.carriage_tab, w.dry_run
    c = d.supervision.context()
    position = c.position if c.fresh and c.reference_known else None
    view.set_home_position(160.5)
    view.set_sensor_location(c.geometry.sensor.near)
    view.set_carriage(position)
    w.fa_position_label.setText('UNKNOWN' if position is None else f'{position:.4f}')
    inputs_fresh = p.fresh('INPUTS') and p.ready_link()
    raw = p.inputs if inputs_fresh else {}
    view.set_board_sensor(None if raw.get('BOARD_EDGE') not in ('0', '1') else raw['BOARD_EDGE'] == '0')
    for name, label, on, off in (
            ('HOME', w.fa_homing_sensor_label, 'ON', 'OFF'),
            ('BOARD_EDGE', w.fa_board_sensor_label, 'ON', 'OFF'),
            ('FENCE_DOOR', w.fa_fence_closed_label, 'CLOSED', 'OPEN')):
        value = raw.get(name)
        w.set_pill(label, 'UNKNOWN' if value not in ('0', '1') else on if value == '0' else off,
                   '#475569' if value not in ('0', '1') else '#22c55e' if value == '0' else '#ef4444')
    alarm = raw.get('CL57T_ALM')
    w.set_pill(w.fa_driver_label, 'UNKNOWN' if alarm not in ('0', '1') else 'NORMAL' if alarm == '1' else 'ALARM',
               '#475569' if alarm not in ('0', '1') else '#22c55e' if alarm == '1' else '#ef4444')
    fresh = d.fresh() and p.ready_link()
    states = tuple(d.data.get(key) == '1' if fresh and d.data.get(key) in ('0', '1') else None
                   for key in ('MAIN_CLAMP', 'SECOND_CLAMP'))
    second_enabled = d.supervision.second_requested()
    view.clamp_enabled = (True, second_enabled)
    for label, state, enabled in zip((w.fa_cyl1_status, w.fa_cyl2_status), states, view.clamp_enabled):
        text = ('DISABLED' if not enabled else 'UNKNOWN' if state is None else
                'ON COMMANDED' if state else 'OFF COMMANDED')
        w.set_pill(label, text, '#2563eb' if state is True and enabled else '#475569')
    view.set_clamps(*states)
    pads = {clamp.key: clamp.footprint for clamp in c.geometry.clamps}
    view.clamp_positions = tuple((pads[key].near + pads[key].far)/2 if key in pads else default
                                 for key, default in (('main', 9.25), ('outfeed', -10.875)))
    up, down = raw.get('SAW_UP'), raw.get('SAW_DOWN')
    saw = ('UNKNOWN' if up not in ('0', '1') or down not in ('0', '1') else
           'CONFLICT' if up == down == '0' else 'UP' if up == '0' else 'DOWN' if down == '0' else
           'MOVING DOWN' if fresh and d.data.get('SAW') == '1' else
           'RETURNING UP' if fresh and d.data.get('STATE') in ('RETURN', 'STOP_RETURN') else 'BETWEEN LIMITS')
    w.set_pill(w.fa_saw_position_label, saw, '#22c55e' if saw == 'UP' else '#ef4444' if saw == 'CONFLICT' else '#475569')
    view.set_saw_state(saw)
    if c.fresh and c.material.located:
        stock = c.material.stock
        remaining = stock.far-stock.near
        index = max(0, d.sequence['index'] if d.sequence else d.progress_index)
        cuts = d.sequence['cuts'][index:] if d.sequence else [float(length) for _, length, _ in w.cut_list[index:]]
        segments = []
        for offset, length in enumerate(cuts):
            if remaining <= 0: break
            take = min(remaining, length)
            segments.append((take, PIECE_COLORS[(index+offset) % len(PIECE_COLORS)], f'{length:g}"'))
            remaining -= take
            kerf = min(remaining, w.kerf_input.value())
            if kerf > 0: segments.append((kerf, None, '')); remaining -= kerf
        if remaining > 0: segments.append((remaining, SCRAP_COLOR, 'remainder'))
        view.set_board(True, stock.near, segments)
        material = 'Stock extent is modeled from detector capture; cut pieces/removal are not sensed.'
    else:
        view.set_board(False, 0, [])
        material = 'Stock location unknown — acquire a board to display its modeled extent.'
    view.material_note = material
    phase = d.sequence['stage'].replace('_', ' ') if d.sequence else 'IDLE'
    output = ('TRIGGER ON commanded' if d.data.get('TRIGGER') == '1' else 'trigger OFF commanded') if fresh else 'outputs UNKNOWN'
    w.fa_auto_status_label.setText(f'{phase} / {d.data.get("STATE", "UNKNOWN") if fresh else "STALE"} — {output}\n{d.message}')
    view.update()
