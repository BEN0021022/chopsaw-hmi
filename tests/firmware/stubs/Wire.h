#pragma once
#include <stdint.h>
struct FakeWire {
  void begin() {}
  void setClock(uint32_t) {}
  void beginTransmission(uint8_t) {}
  void write(uint8_t) {}
  int endTransmission(bool = true) { return 4; }
  int requestFrom(uint8_t, uint8_t) { return 0; }
  int read() { return 0; }
};
extern FakeWire Wire2;
