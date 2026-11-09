#pragma once
#include <stdint.h>
#include <math.h>

namespace carriage {
struct MotionProfile {
  static constexpr uint16_t MaxRate = 20000, MaxAcceleration = 50000;
  uint16_t maxRate;
  uint16_t acceleration;
  static MotionProfile get(uint8_t id) {
    switch (id) {
      // Restored from the preserved MEGA V2.5 initProfiles(), not HMI limits.
      case 1: return {150, 200};   // Gentle: 1.18 in/s
      case 2: return {1000, 500};  // Normal: 7.87 in/s
      case 3: return {2500, 1500}; // Fast: 19.67 in/s
      default: return {40, 0};  // Proven commissioning rate, no ramp
    }
  }
};

// Discrete trapezoid: velocity-squared changes by at most 2*a per step.
// The pulse service schedules from actual time; it never catches up in bursts.
class MotionRamp {
 public:
  uint16_t total = 0, sent = 0;
  MotionProfile parameters = MotionProfile::get(0);
  void start(uint16_t count, uint8_t id) { start(count, MotionProfile::get(id)); }
  void start(uint16_t count, MotionProfile p) { total = count; sent = 0; parameters = p; }
  void pulsed() { if (sent < total) ++sent; }
  uint32_t __attribute__((noinline)) intervalUs() const {
    const MotionProfile p = parameters;
    if (!p.acceleration || !total) return 1000000u / p.maxRate;
    const uint16_t fromStart = sent + 1;
    const uint16_t toEnd = total > sent ? total - sent : 1;
    const uint16_t rampDistance = fromStart < toEnd ? fromStart : toEnd;
    float rate = sqrtf(2.0f * p.acceleration * rampDistance);
    if (rate > p.maxRate) rate = p.maxRate;
    return static_cast<uint32_t>(ceilf(1000000.0f / rate));
  }
};

// Pulse-generation diagnostics, not encoder velocity. Reset per jog/absolute
// move. Unsigned differences handle micros() rollover for bounded moves.
struct PulseTiming {
  uint16_t count = 0;
  uint32_t first = 0, last = 0, minGap = UINT32_MAX, maxLate = 0;
  void pulse(uint32_t now, uint32_t due) {
    if (count) {
      const uint32_t gap = now - last;
      if (gap < minGap) minGap = gap;
    } else first = now;
    last = now; ++count;
    const uint32_t late = now - due;
    if (late > maxLate) maxLate = late;
  }
  uint32_t peakPps() const { return count > 1 && minGap ? 1000000u/minGap : 0; }
  uint32_t elapsedUs() const { return count > 1 ? last-first : 0; }
};
}  // namespace carriage
