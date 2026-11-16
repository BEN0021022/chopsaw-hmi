#pragma once
#include <stdint.h>
#include "bench_interlocks.h"

// Saw-unplugged commissioning. Controller-owned combined timing, real endpoints,
// explicit recovery and retained clamp on stop/fault. Not powered-cut approval.
namespace unloaded {
class DryRun {
 public:
  static constexpr unsigned Count = 20;  // legacy 15 + second enable and four independent delays
  enum Phase { Off, Ready, ClampDelay, ClampSettle, Clamped, ReleaseDelay,
               ReleaseClear, DownDelay, Descend, Down, Dwell, UpDelay,
               Returning, UpSettle, StopReturn, Failed, TriggerDelay, Spinup,
               TriggerReleaseDelay, BrakeWait, Stopped };
  Phase phase = Off;
  bool armed = false, clamp = false, saw = false;
  bool manualMode = false, trigger = false;
  bool cycleRunning = false, operatorCycle = false;
  uint8_t heldMask = 0, selectedMask = 1;
  bool mainClamp() const { return (heldMask & 1)!=0; }
  bool secondClamp() const { return (heldMask & 2)!=0; }
  bool secondEnabled() const { return timing[15]==1; }
  uint32_t completed = 0;
  uint32_t configId = 0, requestId = 0, timingHash = 0;
  const char *fault = "NONE";
  bench::StableAssertion door, up, down;
  bool rawDoor = false, rawUp = false, rawDown = false, alarm = false;

  bool active() const { return armed || clamp || saw || phase == StopReturn; }
  bool failed() const { return phase == Failed; }
  bool configEditable() const { return !active() && !failed() && phase == Off && up.stable && door.stable && alarm; }
  bool configure(unsigned index, uint32_t value) {
    if (!configEditable() || index >= Count || value > 5000 || (index==15 && value>1) ||
        ((index == 6 || index == 9) && value < 100)) return false;
    if (index == 0) { staged = 0; configId = 0; }
    draft[index] = value; staged |= (1u << index);
    return true;
  }
  bool commit(uint32_t id) {
    const unsigned loaded=staged==((1u<<15)-1) ? 15:Count;
    if (!configEditable() || !id || staged != (1u << loaded)-1) return false;
    for (unsigned i=0;i<Count;++i) timing[i] = i<loaded ? draft[i]:0;
    selectedMask=1;
    timingHash=2166136261u;
    for (unsigned i=0;i<loaded;++i) for (unsigned byte=0;byte<4;++byte)
      timingHash=(timingHash ^ ((timing[i]>>(byte*8))&255u))*16777619u;
    configId = id; staged = 0; return true;
  }
  bool arm(uint32_t id, uint32_t now, bool manual = false) {
    if (!configEditable() || !configId || configId != id || rawDown) return false;
    armed = true; manualMode = manual; heartbeat = now; enter(Ready, now); ++requestId; return true;
  }
  bool commandClamp(bool on, uint32_t now, uint8_t mask=1) {
    if (!(mask==1 || mask==2) || (mask==2 && (!secondEnabled() || !manualMode))) return false;
    if (!armed || failed() || !up.stable || rawDown || saw || trigger || cycleRunning) return false;
    if (!(phase==Ready || phase==Clamped) || (on ? (heldMask & mask)!=0 : (heldMask & mask)==0)) return false;
    beginClamps(mask,on,now); ++requestId; return true;
  }
  bool stroke(bool cycle, uint32_t now) {
    const bool supported = (phase==Clamped && clamp) || (manualMode && phase==Ready && !clamp);
    if (!armed || !supported || !up.stable || rawDown || trigger || cycleRunning) return false;
    automaticReturn = cycle; enter(DownDelay, now); ++requestId; return true;
  }
  bool combinedCycle(uint32_t now, uint8_t mask=1) {
    if (!mask || mask>3 || ((mask & 2) && !secondEnabled()) || (heldMask & ~mask)) return false;
    if (!armed || failed() || cycleRunning || trigger || saw || !up.stable || !rawUp ||
        rawDown || !rawDoor || !alarm || !(phase==Ready || phase==Clamped)) return false;
    operatorCycle=false; cycleRunning=true; automaticReturn=true;
    selectedMask=mask;
    if (mask & ~heldMask) beginClamps(mask & ~heldMask,true,now);
    else enter(TriggerDelay,now);
    ++requestId; return true;
  }
  bool maskedCycle(uint32_t id, uint32_t expected, uint8_t mask, uint32_t now) {
    return id==configId && expected==static_cast<uint32_t>(requestId+1) && combinedCycle(now,mask);
  }
  // One explicit unplugged operator stroke, main clamp inhibited throughout.
  // Config/request binding rejects stale or repeated commands after any action.
  bool operatorCut(uint32_t id, uint32_t expectedRequest, uint32_t now) {
    if (!armed || manualMode || phase!=Ready || clamp || id!=configId ||
        expectedRequest!=static_cast<uint32_t>(requestId+1)) return false;
    if (!combinedCycle(now)) return false;
    operatorCycle=true; selectedMask=0; enter(TriggerDelay,now); return true;
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
    armed = saw = trigger = manualMode = cycleRunning = operatorCycle = false; automaticReturn = false;
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
    setHeld(0,now); if (!failed()) enter(Off,now); ++requestId; return true;
  }
  bool reset(uint32_t now) {
    if (active() || !door.stable || !up.stable || rawDown || !alarm) return false;
    trigger = manualMode = cycleRunning = operatorCycle = false; fault = "NONE"; enter(Off,now); return true;
  }
  void trip(const char *reason, uint32_t now) {
    if (!failed()) { fault = reason; stoppedAt=now; }
    armed = saw = trigger = manualMode = cycleRunning = operatorCycle = false; automaticReturn = false; enter(Failed,now);
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
      case ClampSettle: stepClamps(true,now); break;
      case ReleaseDelay:
      case ReleaseClear:
        stepClamps(false,now); break;
      case TriggerDelay:
        if (elapsed >= timing[11]) { trigger=true; triggerAt=now; enter(Spinup,now); } break;
      case Spinup: if (elapsed >= timing[12]) enter(DownDelay,now); break;
      case TriggerReleaseDelay:
        if (elapsed >= timing[13]) { trigger=false; enter(BrakeWait,now); } break;
      case BrakeWait:
        if (elapsed >= timing[14]) {
          if (operatorCycle) { cycleRunning=operatorCycle=false; ++completed; enter(Ready,now); }
          else beginClamps(heldMask,false,now);
        }
        break;
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
  uint32_t staged = 0;
  uint32_t at=0, heartbeat=0, clampAt=0, sawAt=0;
  uint32_t triggerHoldAt=0, triggerAt=0, stoppedAt=0;
  bool automaticReturn=false;
  uint8_t changingMask=0;
  uint32_t clampTransitionAt=0;
  void setHeld(uint8_t mask,uint32_t now) {
    if (!heldMask && mask) clampAt=now;
    heldMask=mask; clamp=mask!=0;
  }
  void beginClamps(uint8_t mask,bool on,uint32_t now) {
    changingMask=mask; clampTransitionAt=now; enter(on ? ClampDelay:ReleaseDelay,now);
  }
  void stepClamps(bool on,uint32_t now) {
    const uint32_t elapsed=static_cast<uint32_t>(now-clampTransitionAt);
    bool settled=true,changed=false;
    for (unsigned bit=0;bit<2;++bit) {
      const uint8_t mask=static_cast<uint8_t>(1u<<bit);
      if (!(changingMask & mask)) continue;
      const unsigned delayIndex=bit ? (on ? 16:18):(on ? 1:3);
      const unsigned settleIndex=bit ? (on ? 17:19):(on ? 2:4);
      const uint32_t delay=timing[delayIndex]+(on ? timing[0]:0);
      if (elapsed>=delay) {
        setHeld(on ? heldMask|mask:heldMask & ~mask,now); changed=true;
      }
      if (elapsed<delay+timing[settleIndex]) settled=false;
    }
    if (settled) {
      if (on) enter(cycleRunning ? TriggerDelay:Clamped,now);
      else { if (cycleRunning) { cycleRunning=false; ++completed; } enter(clamp ? Clamped:Ready,now); }
    } else if (changed) phase=on ? ClampSettle:ReleaseClear;
  }
  void enter(Phase value, uint32_t now) { phase=value; at=now; }
};
}
