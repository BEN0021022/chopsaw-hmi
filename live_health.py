"""Read-only display health policies, separate from motion authorization."""
from dataclasses import dataclass
import math

STALE_SECONDS = 2.0
RECORD_NAMES = {"X": "Controller", "SAFETY": "Safety", "INPUTS": "Sensor"}


def record_name(name):
    return RECORD_NAMES.get(name, name.replace('_', ' ').title())


@dataclass(frozen=True)
class SensorRule:
    key: str
    label: str
    record: str = "INPUTS"
    required: bool = True
    values: tuple = ("0", "1")
    healthy_value: str | None = None
    fault_text: str = ""


# Commission new feedback here when its telemetry is available. Deferred inputs
# are explicit, so a future UNKNOWN clamp does not mask faults or block green.
NATIVE_SENSORS = (
    SensorRule("HOME", "Home sensor"),
    SensorRule("BOARD_EDGE", "Board sensor"),
    SensorRule("FENCE_DOOR", "Guard door", healthy_value="0", fault_text="Guard open"),
    SensorRule("SAW_UP", "Saw UP sensor"),
    SensorRule("SAW_DOWN", "Saw DOWN sensor"),
    SensorRule("CL57T_ALM", "Driver alarm", healthy_value="1", fault_text="Driver alarm"),
    SensorRule("ALARM_RAW", "Driver alarm readback", record="X", healthy_value="1", fault_text="Driver alarm"),
    SensorRule("CLAMP", "Clamp feedback", required=False),
)


@dataclass(frozen=True)
class HealthState:
    level: str  # healthy / fault / neutral
    text: str
    details: tuple = ()


def fault(issues):
    return HealthState("fault", issues[0] + (f" (+{len(issues)-1} more)" if len(issues) > 1 else ""), tuple(issues))


def native_health(*, connected, compatible, records, received, started, now,
                  local_fault="", sensors=NATIVE_SENSORS, stale_seconds=STALE_SECONDS):
    if not connected:
        return HealthState("neutral", "Disconnected")
    if local_fault:
        return fault([local_fault])
    if not compatible:
        if "HELLO" in received:
            return fault(["Incompatible controller identity"])
        if now - started > stale_seconds:
            return fault(["Controller identity not received"])
        return HealthState("neutral", "Waiting for controller identity")
    required_records = {"X", "SAFETY"} | {rule.record for rule in sensors if rule.required}
    missing = sorted(name for name in required_records if name not in received)
    if missing and now - started <= stale_seconds:
        return HealthState("neutral", "Waiting for sensor data", tuple(missing))
    issues = [f"{record_name(name)} data missing" for name in missing]
    issues += [f"{record_name(name)} data stale" for name in sorted(required_records)
               if name in received and now - received[name] > stale_seconds]
    if issues:
        return fault(issues)
    for name in ("X", "SAFETY"):
        code = records.get(name, {}).get("FAULT")
        if code != "NONE":
            issues.append(f"{record_name(name)} fault: {code or 'UNKNOWN'}")
    for rule in sensors:
        if not rule.required:
            continue
        value = records.get(rule.record, {}).get(rule.key)
        if value not in rule.values:
            issues.append(f"{rule.label} data missing or invalid")
        elif rule.healthy_value is not None and value != rule.healthy_value:
            issues.append(rule.fault_text or f"{rule.label} fault")
    inputs = records.get("INPUTS", {})
    safety = records.get("SAFETY", {})
    if inputs.get("SAW_UP") == inputs.get("SAW_DOWN") == "0":
        issues.append("Saw position signals conflict")
    elif inputs.get("SAW_UP") == "1" or inputs.get("SAW_DOWN") == "0":
        issues.append("Saw not fully UP")  # current carriage-only commissioning policy
    if safety.get("DOOR_CLOSED") not in ("0", "1"):
        issues.append("Guard safety data invalid")
    elif safety["DOOR_CLOSED"] != "1":
        issues.append("Guard open")
    if safety.get("SAW_POSITION") != "UP":
        issues.append("Saw safety position: " + safety.get("SAW_POSITION", "UNKNOWN"))
    blocker = safety.get("BLOCKER")
    if blocker != "NONE":
        issues.append("Interlock: " + (blocker or "UNKNOWN"))
    issues = list(dict.fromkeys(issues))
    return fault(issues) if issues else HealthState("healthy", "System healthy")


def simulator_data_valid(fields):
    try:
        position_ok = math.isfinite(float(fields.get("POS", "")))
    except (TypeError, ValueError):
        position_ok = False
    return (position_ok and fields.get("STATE") in
            {"IDLE", "MOVING", "HOMING", "DETECTING", "DISABLED", "OVERCURRENT"}
            and all(fields.get(key) in ("0", "1") for key in ("SEN", "BSEN", "SSEN", "OCT")))


def simulator_health(*, connected, fields, received, started, now):
    if not connected:
        return HealthState("neutral", "Disconnected")
    if received is None:
        return (HealthState("neutral", "Waiting for simulator data") if now-started <= STALE_SECONDS
                else fault(["Simulator data missing"]))
    if now - received > STALE_SECONDS:
        return fault(["Simulator data stale"])
    if not simulator_data_valid(fields):
        return fault(["Simulator sensor data missing or invalid"])
    if fields["STATE"] == "OVERCURRENT" or fields["OCT"] == "1":
        return fault(["Simulator overcurrent"])
    return HealthState("healthy", "System healthy", ("Virtual feedback only; physical guard, driver and clamp are not monitored in Simulator mode.",))


class TelemetryActivity:
    """Five-second breathing brightness, gated by fresh telemetry."""
    def __init__(self):
        self.started = None

    def update(self, receipt, now):
        if receipt is None or now-receipt > STALE_SECONDS:
            self.started = None
            return 0.0
        if self.started is None:
            self.started = now
        phase = (now-self.started) % 5.0
        if phase < 1.5:
            return .5 - .5 * math.cos(math.pi * phase / 1.5)
        if phase < 3.5:
            return 1.0  # two seconds fully illuminated
        return .5 + .5 * math.cos(math.pi * (phase-3.5) / 1.5)
