#pragma once
#include <stdint.h>

namespace carriage {
// Integer machine-coordinate conversion: 127.12 pulses/in, 160.5 in Home datum.
struct Positioning {
  static constexpr int32_t HomeMilli = 160500;
  static constexpr int32_t MinOffset = -20402;  // smallest full step at or above 0 in
  static constexpr uint16_t MaxMove = 20594;

  static int32_t offsetForMilli(int32_t milli) {
    const int64_t scaled = static_cast<int64_t>(milli - HomeMilli) * 12712;
    return static_cast<int32_t>((scaled + (scaled >= 0 ? 50000 : -50000)) / 100000);
  }
  static int32_t milliForOffset(int32_t offset) {
    return static_cast<int32_t>((static_cast<int64_t>(HomeMilli) * 12712 +
                                 static_cast<int64_t>(offset) * 100000) / 12712);
  }
  static bool within(int32_t offset, int32_t maxOffset) {
    return offset >= MinOffset && offset <= maxOffset;
  }
  static bool target(int32_t milli, int32_t maxOffset, int32_t &result) {
    if (milli < 0 || milli > milliForOffset(maxOffset)) return false;
    result = offsetForMilli(milli);
    // Zero inches may lie between full steps; choose the first nonnegative one.
    if (result < MinOffset) result = MinOffset;
    return within(result, maxOffset);
  }
};
}  // namespace carriage
