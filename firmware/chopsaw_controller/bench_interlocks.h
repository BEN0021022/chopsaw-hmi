#pragma once

#include <stdint.h>

// Manual, blade-unplugged commissioning policy. This is not an automatic cut
// controller or a safety-rated guard system. Tests use the exact same policy.
namespace bench {

struct Inputs {
  bool doorClosed;
  bool sawUp;
  bool sawDown;
};

enum class Fault { None, DoorOpen, PositionConflict, PositionLost, Watchdog, MaxOn,
                   DownTimeout, ReturnTimeout, DriverAlarm, HomeLimit, HomingFailed, SoftLimit, Command };
enum class Travel { Idle, Down, Return };

struct StableAssertion {
  bool initialized = false;
  bool raw = false;
  bool stable = false;
  uint32_t since = 0;

  void update(bool value, uint32_t now) {
    if (!initialized || value != raw) {
      initialized = true;
      raw = value;
      since = now;
    }
    // Assertion requires 20ms; loss revokes confirmation immediately.
    stable = raw && static_cast<uint32_t>(now - since) >= 20;
  }
};

class Interlocks {
 public:
  static constexpr uint32_t WatchdogMs = 1500;
  static constexpr uint32_t MaxOnMs = 5000;
  static constexpr uint32_t TravelTimeoutMs = 5000;  // provisional, not a cycle time
  bool armed = false;
  bool outputs[3] = {false, false, false};
  Fault fault = Fault::None;
  Travel travel = Travel::Idle;
  Inputs inputs = {false, false, false};
  StableAssertion door, up, down;

  void tick(Inputs sample, uint32_t now) {
    inputs = sample;
    door.update(sample.doorClosed, now);
    up.update(sample.sawUp, now);
    down.update(sample.sawDown, now);
    if (armed) {
      if (!sample.doorClosed) trip(Fault::DoorOpen, now);
      else if (sample.sawUp && sample.sawDown) trip(Fault::PositionConflict, now);
      else if (travel == Travel::Idle && (!sample.sawUp || sample.sawDown))
        trip(Fault::PositionLost, now);
      else if (static_cast<uint32_t>(now - lastKeepalive) >= WatchdogMs)
        trip(Fault::Watchdog, now);
    }
    if (travel == Travel::Down && outputs[0]) {
      if (down.stable && !sample.sawUp) reachedDown = true;
      if (!reachedDown && static_cast<uint32_t>(now - travelAt) >= TravelTimeoutMs)
        trip(Fault::DownTimeout, now);
    }
    for (uint8_t index = 0; index < 3; ++index) {
      if (outputs[index] && static_cast<uint32_t>(now - outputAt[index]) >= MaxOnMs)
        trip(Fault::MaxOn, now);
    }
    if (travel == Travel::Return) {
      if (up.stable && !sample.sawDown) travel = Travel::Idle;
      else if (static_cast<uint32_t>(now - travelAt) >= TravelTimeoutMs)
        trip(Fault::ReturnTimeout, now);
    }
  }

  bool readyToReset() const {
    return !armed && !anyOutput() && door.stable && up.stable &&
           !inputs.sawDown && travel == Travel::Idle;
  }

  bool readyToArm() const { return fault == Fault::None && readyToReset(); }

  const char *blocker() const {
    if (fault != Fault::None) return faultName();
    if (!door.stable) return "DOOR_OPEN";
    if (inputs.sawUp && inputs.sawDown) return "POSITION_CONFLICT";
    if (travel == Travel::Return) return "RETURN_PENDING";
    if (!up.stable || inputs.sawDown) return "SAW_NOT_UP";
    if (armed) return "ALREADY_ARMED";
    return "NONE";
  }

  bool arm(uint32_t now) {
    if (!readyToArm()) return false;
    armed = true;
    lastKeepalive = now;
    return true;
  }

  bool reset() {
    if (!readyToReset()) return false;
    fault = Fault::None;
    return true;  // deliberately does not arm or energize anything
  }

  void keepalive(uint32_t now) { if (armed) lastKeepalive = now; }

  void off(uint32_t now) {
    setOff(0, now);
    outputs[1] = outputs[2] = false;
    armed = false;  // preserves a latched fault
  }

  void trip(Fault reason, uint32_t now) {
    if (fault == Fault::None) fault = reason;  // preserve the first cause
    off(now);
  }

  const char *requestOutput(uint8_t index, bool on, uint32_t now) {
    if (index >= 3) { trip(Fault::Command, now); return "BAD_OUTPUT_COMMAND"; }
    if (!on) { setOff(index, now); return nullptr; }  // OFF always available
    if (fault != Fault::None) return faultName();
    if (!armed) return "NOT_ARMED";
    if (!door.stable || !inputs.doorClosed) {
      trip(Fault::DoorOpen, now);
      return faultName();
    }
    if (outputs[index]) return nullptr;  // repeats cannot extend the ON timer
    if (anyOutput()) return "OUTPUT_BUSY";  // manual tests, never combined motion
    if (!up.stable || inputs.sawDown || travel != Travel::Idle) return "SAW_NOT_UP";
    outputs[index] = true;
    outputAt[index] = now;
    if (index == 0) {
      travel = Travel::Down;
      travelAt = now;
      reachedDown = false;
    }
    return nullptr;
  }

  const char *faultName() const {
    switch (fault) {
      case Fault::DoorOpen: return "DOOR_OPEN";
      case Fault::PositionConflict: return "POSITION_CONFLICT";
      case Fault::PositionLost: return "POSITION_LOST";
      case Fault::Watchdog: return "WATCHDOG";
      case Fault::MaxOn: return "MAX_ON";
      case Fault::DownTimeout: return "DOWN_TIMEOUT";
      case Fault::ReturnTimeout: return "RETURN_TIMEOUT";
      case Fault::DriverAlarm: return "DRIVER_ALARM";
      case Fault::HomeLimit: return "HOME_LIMIT";
      case Fault::HomingFailed: return "HOME_FAILED";
      case Fault::SoftLimit: return "SOFT_LIMIT";
      case Fault::Command: return "COMMAND";
      default: return "NONE";
    }
  }

  const char *position() const {
    if (inputs.sawUp && inputs.sawDown) return "CONFLICT";
    if (up.stable && !inputs.sawDown) return "UP";
    if (down.stable && !inputs.sawUp) return "DOWN";
    return "BETWEEN";
  }

 private:
  uint32_t outputAt[3] = {0, 0, 0};
  uint32_t lastKeepalive = 0;
  uint32_t travelAt = 0;
  bool reachedDown = false;

  bool anyOutput() const { return outputs[0] || outputs[1] || outputs[2]; }

  void setOff(uint8_t index, uint32_t now) {
    const bool wasOn = outputs[index];
    outputs[index] = false;
    if (index == 0 && wasOn) {
      if (up.stable && !inputs.sawDown) travel = Travel::Idle;
      else { travel = Travel::Return; travelAt = now; }
    }
  }
};

}  // namespace bench
