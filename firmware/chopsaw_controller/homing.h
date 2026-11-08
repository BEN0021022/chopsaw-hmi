#pragma once
#include <stdint.h>

namespace carriage {
// Nonblocking homing policy. Caller owns GPIO, pulse timing and global interlocks.
class Homing {
 public:
  enum class Stage { Idle, Seek, Release, Backoff, Latch, PullRelease, PullOff, Done, Cancelled, Failed };
  Stage stage = Stage::Idle;
  bool referenceLatched = false;
  const char *error = "NONE";
  uint16_t pulses = 0;
  static constexpr uint16_t MaxSearch = 20594;  // ~162 in at 127.12 pulses/in
  static constexpr uint16_t ReleaseLimit = 127;
  static constexpr uint16_t BackoffPulses = 32;
  static constexpr uint16_t PullOffPulses = 13;

  bool active() const {
    return stage >= Stage::Seek && stage <= Stage::PullOff;
  }
  bool failed() const { return stage == Stage::Failed; }
  bool done() const { return stage == Stage::Done; }
  int direction() const { return stage == Stage::Seek || stage == Stage::Latch ? 1 : -1; }
  uint32_t intervalUs() const { return stage == Stage::Latch ? 100000 : 25000; }
  uint16_t limit() const {
    if (stage == Stage::Seek) return searchLimit;
    if (stage == Stage::Backoff) return BackoffPulses;
    if (stage == Stage::PullOff) return PullOffPulses;
    return ReleaseLimit;
  }
  const char *name() const {
    switch (stage) {
      case Stage::Idle: return "IDLE";
      case Stage::Seek: return "SEEK";
      case Stage::Release: return "RELEASE";
      case Stage::Backoff: return "BACKOFF";
      case Stage::Latch: return "LATCH";
      case Stage::PullRelease: return "PULL_RELEASE";
      case Stage::PullOff: return "PULL_OFF";
      case Stage::Done: return "DONE";
      case Stage::Cancelled: return "CANCELLED";
      case Stage::Failed: return "FAILED";
    }
    return "FAILED";
  }
  bool start(uint16_t maxSearch, bool activeInput, uint32_t now) {
    if (active() || !maxSearch || maxSearch > MaxSearch) return false;
    searchLimit = maxSearch;
    raw = activeInput; rawSince = startedAt = now;
    referenceLatched = false; error = "NONE";
    enter(activeInput ? Stage::Release : Stage::Seek, now);
    return true;
  }
  void cancel() {
    if (active()) { stage = Stage::Cancelled; error = "CANCELLED"; }
  }
  void observe(bool activeInput, uint32_t now) {
    if (!active()) return;
    if (raw != activeInput) { raw = activeInput; rawSince = now; }
    const bool stable = static_cast<uint32_t>(now - rawSince) >= 20;
    const uint32_t phaseTimeout = static_cast<uint32_t>(limit()) * (intervalUs() / 1000) + 2000;
    if (static_cast<uint32_t>(now - startedAt) >= 600000 ||
        static_cast<uint32_t>(now - phaseAt) >= phaseTimeout) { fail("TIMEOUT"); return; }
    switch (stage) {
      case Stage::Seek:
        if (raw && stable) enter(Stage::Release, now);
        else if (!raw && exhausted(now)) fail("NOT_FOUND");
        break;
      case Stage::Release:
        if (!raw && stable) enter(Stage::Backoff, now);
        else if (raw && exhausted(now)) fail("STUCK_ACTIVE");
        break;
      case Stage::Backoff:
        if (raw) fail("RETRIGGERED");
        else if (pulses >= limit()) enter(Stage::Latch, now);
        break;
      case Stage::Latch:
        if (raw && stable) { referenceLatched = true; enter(Stage::PullRelease, now); }
        else if (!raw && exhausted(now)) fail("LATCH_NOT_FOUND");
        break;
      case Stage::PullRelease:
        if (!raw && stable) enter(Stage::PullOff, now);
        else if (raw && exhausted(now)) fail("STUCK_ACTIVE");
        break;
      case Stage::PullOff:
        if (raw) fail("RETRIGGERED");
        else if (pulses >= limit()) enter(Stage::Done, now);
        break;
      default: break;
    }
  }
  bool wantsPulse(bool activeInput) const {
    if (!active() || pulses >= limit()) return false;
    if (stage == Stage::Release || stage == Stage::PullRelease) return activeInput;
    return !activeInput;
  }
  void pulsed(uint32_t now) { if (active()) { ++pulses; lastPulseAt = now; } }

 private:
  uint16_t searchLimit = 0;
  bool raw = false;
  uint32_t rawSince = 0, startedAt = 0, phaseAt = 0, lastPulseAt = 0;
  bool exhausted(uint32_t now) const {
    return pulses >= limit() && static_cast<uint32_t>(now - lastPulseAt) >= intervalUs() / 1000 + 20;
  }
  void enter(Stage next, uint32_t now) { stage = next; phaseAt = now; pulses = 0; }
  void fail(const char *reason) { stage = Stage::Failed; error = reason; }
};
}  // namespace carriage
