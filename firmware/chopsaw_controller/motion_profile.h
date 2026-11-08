#pragma once
#include <stdint.h>
#include <math.h>

namespace carriage {
struct MotionProfile {
  uint16_t maxRate;
  uint16_t acceleration;
  static MotionProfile get(uint8_t id) {
    switch (id) {
      case 1: return {40, 40};   // Gentle
      case 2: return {80, 160};  // Normal
      case 3: return {127, 254}; // Fast: initial acceptance cap ~1 in/s
      default: return {40, 0};  // Proven commissioning rate, no ramp
    }
  }
};

// Discrete trapezoid: velocity-squared changes by at most 2*a per step.
// The pulse service schedules from actual time; it never catches up in bursts.
class MotionRamp {
 public:
  uint16_t total = 0, sent = 0;
  uint8_t profile = 0;
  void start(uint16_t count, uint8_t id) { total = count; sent = 0; profile = id; }
  void pulsed() { if (sent < total) ++sent; }
  uint32_t __attribute__((noinline)) intervalUs() const {
    const MotionProfile p = MotionProfile::get(profile);
    if (!p.acceleration || !total) return 1000000u / p.maxRate;
    const uint16_t fromStart = sent + 1;
    const uint16_t toEnd = total > sent ? total - sent : 1;
    const uint16_t rampDistance = fromStart < toEnd ? fromStart : toEnd;
    float rate = sqrtf(2.0f * p.acceleration * rampDistance);
    if (rate > p.maxRate) rate = p.maxRate;
    return static_cast<uint32_t>(ceilf(1000000.0f / rate));
  }
};
}  // namespace carriage
