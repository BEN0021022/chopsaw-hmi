#pragma once
#include <stdint.h>
#include "bench_interlocks.h"

// Saw-unplugged commissioning. Controller-owned combined timing, real endpoints,
// explicit recovery and retained clamp on stop/fault. Not powered-cut approval.
namespace unloaded {
class DryRun {
 public:
  static constexpr unsigned Count = 15;
  enum Phase { Off, Ready, ClampDelay, ClampSettle, Clamped, ReleaseDelay,
               ReleaseClear, DownDelay, Descend, Down, Dwell, UpDelay,
               Returning, UpSettle, StopReturn, Failed, TriggerDelay, Spinup,
               TriggerReleaseDelay, BrakeWait, Stopped };
  Phase phase = Off;
  bool armed = false, clamp = false, saw = false;
  bool manualMode = false, trigger = false;
  bool cycleRunning = false;
  uint32_t completed = 0;
  uint32_t configId = 0, requestId = 0, timingHash = 0;
  const char *fault = "NONE";
  bench::StableAssertion door, up, down;
  bool rawDoor = false, rawUp = false, rawDown = false, alarm = false;

  bool active() const { return armed || clamp || saw || phase == StopReturn; }
  bool failed() const { return phase == Failed; }
  bool configEditable() const { return !active() && !failed() && phase == Off && up.stable && door.stable && alarm; }
  bool configure(unsigned index, uint32_t value) {
    if (!configEditable() || index >= Count || value > 5000 ||
        ((index == 6 || index == 9) && value < 100)) return false;
    if (index == 0) { staged = 0; configId = 0; }
    draft[index] = value; staged |= static_cast<uint16_t>(1u << index);
    return true;
  }
  bool commit(uint32_t id) {
    if (!configEditable() || !id || staged != (1u << Count)-1) return false;
    for (unsigned i=0;i<Count;++i) timing[i] = draft[i];
    timingHash=2166136261u;
    for (unsigned i=0;i<Count;++i) for (unsigned byte=0;byte<4;++byte)
      timingHash=(timingHash ^ ((timing[i]>>(byte*8))&255u))*16777619u;
    configId = id; staged = 0; return true;
  }
  bool arm(uint32_t id, uint32_t now, bool manual = false) {
    if (!configEditable() || !configId || configId != id || rawDown) return false;
    armed = true; manualMode = manual; heartbeat = now; enter(Ready, now); ++requestId; return true;
  }
  bool commandClamp(bool on, uint32_t now) {
    if (!armed || failed() || !up.stable || rawDown || saw || trigger || cycleRunning) return false;
    if (on ? phase != Ready : phase != Clamped) return false;
    enter(on ? ClampDelay : ReleaseDelay, now); ++requestId; return true;
  }
  bool stroke(bool cycle, uint32_t now) {
    const bool supported = (phase==Clamped && clamp) || (manualMode && phase==Ready && !clamp);
    if (!armed || !supported || !up.stable || rawDown || trigger || cycleRunning) return false;
    automaticReturn = cycle; enter(DownDelay, now); ++requestId; return true;
  }
  bool combinedCycle(uint32_t now) {
    if (!armed || failed() || cycleRunning || trigger || saw || !up.stable || !rawUp ||
        rawDown || !rawDoor || !alarm || !(phase==Ready || phase==Clamped)) return false;
    cycleRunning=true; automaticReturn=true;
    enter(phase==Ready ? ClampDelay : TriggerDelay,now); ++requestId; return true;
  }
  bool returnUp(uint32_t now) {
    if (!armed || (!clamp && !manualMode) || !(phase == DownDelay || phase == Descend || phase == Down ||
                              phase == Dwell || phase == UpDelay)) return false;
    saw = false; enter(Returning, now); ++requestId; return true;
  }
  void keepalive(uint32_t now) { if (armed) heartbeat = now; }
  bool pressTrigger(uint32_t now) {
    if (!armed || !manualMode || trigger || failed() || saw || cycleRunning ||
        !(phase == Ready || phase == Clamped) || !rawDoor || !rawUp || rawDown || !alarm) return false;
    trigger = true; triggerHoldAt = now; ++requestId; return true;
  }
  bool holdTrigger(uint32_t now) {
    if (!armed || !manualMode || !trigger || failed() || saw || cycleRunning ||
        !(phase == Ready || phase == Clamped) || !rawDoor || !rawUp || rawDown || !alarm) return false;
    triggerHoldAt = now; return true;
  }
  void releaseTrigger() { trigger = false; ++requestId; }
  void stop(uint32_t now) {
    if (armed || cycleRunning || trigger) stoppedAt=now;
    armed = saw = trigger = manualMode = cycleRunning = false; automaticReturn = false;
    if (!failed()) enter(up.stable && !rawDown ? (clamp ? Stopped : Off) : StopReturn, now);
    ++requestId;
  }
  bool releaseReady(uint32_t now) const {
    return !armed && clamp && !saw && !trigger && (phase==Stopped || failed()) &&
        door.stable && rawDoor && up.stable && rawUp && !rawDown && alarm &&
        static_cast<uint32_t>(now-stoppedAt)>=timing[14];
  }
  bool releaseStopped(uint32_t now) {
    if (!releaseReady(now)) return false;
    clamp=false; if (!failed()) enter(Off,now); ++requestId; return true;
  }
  bool reset(uint32_t now) {
    if (active() || !door.stable || !up.stable || rawDown || !alarm) return false;
    trigger = manualMode = cycleRunning = false; fault = "NONE"; enter(Off,now); return true;
  }
  void trip(const char *reason, uint32_t now) {
    if (!failed()) { fault = reason; stoppedAt=now; }
    armed = saw = trigger = manualMode = cycleRunning = false; automaticReturn = false; enter(Failed,now);
  }
  void tick(bool d, bool u, bool n, bool a, uint32_t now) {
    rawDoor=d; rawUp=u; rawDown=n; alarm=a;
    door.update(d,now); up.update(u,now); down.update(n,now);
    // Hold-to-test: only live DTHOLD messages renew a press. Generic keepalive
    // cannot keep the trigger on after mouse release/UI loss. Never auto-press.
    if (trigger && !cycleRunning && static_cast<uint32_t>(now-triggerHoldAt) >= 350) trigger = false;
    if (armed) {
      if (!d) trip("DRY_DOOR_OPEN",now);
      else if (!a) trip("DRY_DRIVER_ALARM",now);
      else if (u && n) trip("DRY_POSITION_CONFLICT",now);
      else if (static_cast<uint32_t>(now-heartbeat) >= 1500) trip("DRY_WATCHDOG",now);
      else if (clamp && static_cast<uint32_t>(now-clampAt) >= 60000) trip("DRY_CLAMP_MAX_ON",now);
      else if (saw && static_cast<uint32_t>(now-sawAt) >= 15000) trip("DRY_SAW_MAX_ON",now);
      else if (trigger && cycleRunning && static_cast<uint32_t>(now-triggerAt) >= 30000) trip("DRY_TRIGGER_MAX_ON",now);
      else if ((phase == Down || phase == Dwell || phase == UpDelay) && (!n || u)) trip("DRY_POSITION_LOST",now);
      else if ((phase == Ready || phase == ClampDelay || phase == ClampSettle || phase == Clamped ||
                phase == ReleaseDelay || phase == ReleaseClear || phase == TriggerDelay || phase == Spinup ||
                phase == TriggerReleaseDelay || phase == BrakeWait) && (!u || n)) trip("DRY_POSITION_LOST",now);
    }
    const uint32_t elapsed = static_cast<uint32_t>(now-at);
    switch (phase) {
      case ClampDelay:
        if (elapsed >= timing[0]+timing[1]) { clamp=true; clampAt=now; enter(ClampSettle,now); } break;
      case ClampSettle: if (elapsed >= timing[2]) enter(cycleRunning ? TriggerDelay : Clamped,now); break;
      case ReleaseDelay: if (elapsed >= timing[3]) { clamp=false; enter(ReleaseClear,now); } break;
      case ReleaseClear:
        if (elapsed >= timing[4]) { if (cycleRunning) { cycleRunning=false; ++completed; } enter(Ready,now); } break;
      case TriggerDelay:
        if (elapsed >= timing[11]) { trigger=true; triggerAt=now; enter(Spinup,now); } break;
      case Spinup: if (elapsed >= timing[12]) enter(DownDelay,now); break;
      case TriggerReleaseDelay:
        if (elapsed >= timing[13]) { trigger=false; enter(BrakeWait,now); } break;
      case BrakeWait: if (elapsed >= timing[14]) enter(ReleaseDelay,now); break;
      case DownDelay:
        if (elapsed >= timing[5]) { saw=true; sawAt=now; enter(Descend,now); } break;
      case Descend:
        if (down.stable && !u) enter(automaticReturn ? Dwell : Down,now);
        else if (elapsed >= timing[6]) trip("DRY_DOWN_TIMEOUT",now);
        break;
      case Dwell: if (elapsed >= timing[7]) enter(UpDelay,now); break;
      case UpDelay: if (elapsed >= timing[8]) { saw=false; enter(Returning,now); } break;
      case Returning:
        if (up.stable && !n) enter(UpSettle,now);
        else if (elapsed >= timing[9]) trip("DRY_UP_TIMEOUT",now);
        break;
      case UpSettle:
        if (!u || n) trip("DRY_POSITION_LOST",now);
        else if (elapsed >= timing[10]) { automaticReturn=false; enter(cycleRunning ? TriggerReleaseDelay : clamp ? Clamped : Ready,now); }
        break;
      case StopReturn:
        if (up.stable && !n) enter(clamp ? Stopped : Off,now);
        else if (elapsed >= 5000) trip("DRY_STOP_RETURN_TIMEOUT",now);
        break;
      default: break;
    }
  }
  const char *name() const {
    switch (phase) {
      case Off:return "OFF"; case Ready:return "READY"; case ClampDelay:return "CLAMP_DELAY";
      case ClampSettle:return "CLAMP_SETTLE"; case Clamped:return "CLAMPED";
      case ReleaseDelay:return "RELEASE_DELAY"; case ReleaseClear:return "RELEASE_CLEAR";
      case DownDelay:return "DOWN_DELAY"; case Descend:return "DESCEND"; case Down:return "DOWN";
      case Dwell:return "DWELL"; case UpDelay:return "UP_DELAY"; case Returning:return "RETURN";
      case UpSettle:return "UP_SETTLE"; case StopReturn:return "STOP_RETURN"; case Failed:return "FAULT";
      case TriggerDelay:return "TRIGGER_DELAY"; case Spinup:return "SPINUP";
      case TriggerReleaseDelay:return "TRIGGER_RELEASE_DELAY"; case BrakeWait:return "BRAKE_WAIT"; case Stopped:return "STOPPED";
    }
    return "FAULT";
  }
 private:
  uint32_t draft[Count] = {}, timing[Count] = {};
  uint16_t staged = 0;
  uint32_t at=0, heartbeat=0, clampAt=0, sawAt=0;
  uint32_t triggerHoldAt=0, triggerAt=0, stoppedAt=0;
  bool automaticReturn=false;
  void enter(Phase value, uint32_t now) { phase=value; at=now; }
};
}
