#pragma once
#include <stdint.h>

namespace carriage {
// One bounded, forward-only acquisition. Raw detection pauses pulses immediately;
// 20ms stable detection records the existing machine coordinate, never re-zeros it.
class EdgeSearch {
 public:
  enum class Stage { Idle, Seek, Found, Failed, Cancelled };
  Stage stage = Stage::Idle;
  uint16_t limit = 0, sent = 0;
  const char *error = "NONE";
  uint32_t started = 0, lastPulse = 0, assertedAt = 0;
  bool asserting = false;
  bool active() const { return stage == Stage::Seek; }
  void start(uint16_t count, uint32_t now) {
    limit = count; sent = 0; started = lastPulse = now;
    asserting = false; error = "NONE"; stage = Stage::Seek;
  }
  void cancel() { if (active()) stage = Stage::Cancelled; }
  void observe(bool detected, uint32_t now) {
    if (!active()) return;
    if (static_cast<uint32_t>(now - started) >= static_cast<uint32_t>(limit)*25 + 2000) {
      stage = Stage::Failed; error = "TIMEOUT"; return;
    }
    if (detected) {
      if (!asserting) { asserting = true; assertedAt = now; }
      if (static_cast<uint32_t>(now - assertedAt) >= 20) stage = Stage::Found;
    } else {
      asserting = false;
      // Allow the final pulse's sensor input to settle without another pulse.
      if (sent >= limit && static_cast<uint32_t>(now - lastPulse) >= 45) {
        stage = Stage::Failed; error = "NOT_FOUND";
      }
    }
  }
  bool wantsPulse(bool detected) const { return active() && !detected && sent < limit; }
  void pulsed(uint32_t now) { ++sent; lastPulse = now; }
  const char *name() const {
    switch (stage) {
      case Stage::Seek: return "SEEK";
      case Stage::Found: return "FOUND";
      case Stage::Failed: return "FAILED";
      case Stage::Cancelled: return "CANCELLED";
      default: return "IDLE";
    }
  }
};
}  // namespace carriage
