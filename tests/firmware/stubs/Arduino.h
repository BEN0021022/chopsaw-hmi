#pragma once
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <ctype.h>
#include <stdio.h>
#include <string>

constexpr int HIGH = 1, LOW = 0, OUTPUT = 1, INPUT_PULLUP = 2, HEX = 16;
extern uint32_t fakeTime;
extern int fakePins[64];
extern int fakeModes[64], fakeLatches[64];
extern unsigned fakePulses, fakeUs, fakeDirAt, fakeHighAt, fakePulseWidth, fakeSetupUs;
extern uint32_t fakeMinGapUs, fakeLastPulseUs;
inline uint32_t millis() { return fakeTime; }
inline uint32_t micros() { return fakeTime * 1000u + fakeUs; }
inline void delay(uint32_t duration) { fakeTime += duration; }
inline int digitalRead(uint8_t pin) { return fakePins[pin]; }
inline void delayMicroseconds(unsigned value) { fakeUs += value; }
inline void digitalWrite(uint8_t pin, int state) {
  // Teensy digitalWrite on an input changes bias, not the output latch.
  if (fakeModes[pin] != OUTPUT) return;
  if (pin == 3) fakeDirAt = micros();
  if (pin == 2 && state == HIGH && fakePins[pin] == LOW) {
    if (fakePulses && micros() - fakeLastPulseUs < fakeMinGapUs) fakeMinGapUs = micros() - fakeLastPulseUs;
    fakeLastPulseUs = micros();
    ++fakePulses; fakeHighAt = micros(); fakeSetupUs = micros() - fakeDirAt;
  }
  if (pin == 2 && state == LOW && fakePins[pin] == HIGH) fakePulseWidth = micros() - fakeHighAt;
  fakePins[pin] = state;
  fakeLatches[pin] = state;
}
inline void digitalWriteFast(uint8_t pin, int state) {
  fakeLatches[pin] = state;
  if (fakeModes[pin] == OUTPUT) digitalWrite(pin, state);
}
inline void pinMode(uint8_t pin, int mode) {
  fakeModes[pin] = mode;
  if (mode == OUTPUT) digitalWrite(pin, fakeLatches[pin]);
}

struct FakeSerial {
  std::string incoming, outgoing;
  int txRoom = 8192;
  int availableForWrite() const { return txRoom; }
  void begin(int) {}
  int available() const { return static_cast<int>(incoming.size()); }
  int read() { const char ch = incoming[0]; incoming.erase(0, 1); return ch; }
  void print(const char *s) { outgoing += s; }
  void print(char c) { outgoing += c; }
  template<class T> void print(T value) { outgoing += std::to_string(value); }
  template<class T> void print(T value, int base) {
    char buffer[32];
    snprintf(buffer, sizeof(buffer), base == HEX ? "%lx" : "%lu", static_cast<unsigned long>(value));
    outgoing += buffer;
  }
  void println() { outgoing += '\n'; }
  template<class T> void println(T value) { print(value); println(); }
};
extern FakeSerial Serial;
