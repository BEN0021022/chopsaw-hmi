#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include "../../firmware/chopsaw_sensor_bench/bench_interlocks.h"

using bench::Fault;
using bench::Inputs;
using bench::Interlocks;
const Inputs Safe = {true, true, false};
static unsigned checks = 0;
#define CHECK(value) do { ++checks; if (!(value)) { \
  fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #value); exit(1); } } while (0)

void ready(Interlocks &p, uint32_t base = 0) {
  p.tick(Safe, base);
  p.tick(Safe, base + 20);
  CHECK(p.readyToArm());
  CHECK(p.arm(base + 20));
}

void keep(Interlocks &p, Inputs sample, uint32_t at) {
  p.tick(sample, at);  // production order: faults are checked before heartbeat
  p.keepalive(at);
}

int main() {
  {
    Interlocks p;
    CHECK(!p.armed && !p.outputs[0] && !p.outputs[1] && !p.outputs[2]);
    p.tick(Safe, 0);
    CHECK(!p.arm(0));
    p.tick(Safe, 19);
    CHECK(!p.arm(19));
    p.tick(Safe, 20);
    CHECK(p.arm(20));
    CHECK(!p.arm(21));
    CHECK(p.requestOutput(0, true, 21) == nullptr);
    CHECK(p.requestOutput(1, true, 22) != nullptr);
    CHECK(p.outputs[0] && !p.outputs[1]);
    p.off(23);
    CHECK(!p.armed && !p.outputs[0]);
  }
  for (uint8_t output = 0; output < 3; ++output) {
    Interlocks p;
    ready(p);
    CHECK(p.requestOutput(output, true, 21) == nullptr);
    p.tick({false, true, false}, 22);
    CHECK(p.fault == Fault::DoorOpen && !p.armed);
    CHECK(!p.outputs[0] && !p.outputs[1] && !p.outputs[2]);
    p.tick(Safe, 23);
    p.tick(Safe, 43);
    CHECK(!p.armed && !p.arm(43));
    p.off(44);
    CHECK(p.fault == Fault::DoorOpen);  // OFF cannot acknowledge a fault
    CHECK(p.reset());
    CHECK(!p.armed && !p.outputs[output]);
    CHECK(p.arm(45));
  }
  {
    Interlocks p;
    ready(p);
    p.requestOutput(2, true, 21);
    p.tick({true, true, true}, 22);
    CHECK(p.fault == Fault::PositionConflict && !p.outputs[2]);
    CHECK(!p.reset());
  }
  for (uint8_t output = 1; output < 3; ++output) {
    Interlocks p;
    ready(p);
    p.requestOutput(output, true, 21);
    p.tick({true, false, false}, 22);
    CHECK(p.fault == Fault::PositionLost && !p.outputs[output]);
  }
  {
    Interlocks p;
    ready(p);
    p.requestOutput(0, true, 21);
    p.tick({true, false, false}, 50);
    CHECK(p.armed && p.outputs[0]);  // neither endpoint is valid during travel
    p.tick({true, false, true}, 100);
    p.tick({true, false, true}, 120);
    CHECK(p.fault == Fault::None);
    p.requestOutput(0, false, 130);
    CHECK(p.travel == bench::Travel::Return && !p.outputs[0]);
    CHECK(p.requestOutput(1, true, 131) != nullptr);
    p.tick(Safe, 200);
    p.tick(Safe, 220);
    CHECK(p.travel == bench::Travel::Idle);
    CHECK(p.requestOutput(1, true, 221) == nullptr);
  }
  {
    Interlocks p;
    ready(p);
    p.requestOutput(0, true, 20);
    for (uint32_t t = 1000; t <= 5000; t += 1000) keep(p, {true, false, false}, t);
    p.tick({true, false, false}, 5020);
    CHECK(p.fault == Fault::DownTimeout && !p.outputs[0]);
  }
  {
    Interlocks p;
    ready(p);
    p.requestOutput(0, true, 20);
    p.tick({true, false, false}, 50);
    p.requestOutput(0, false, 100);
    for (uint32_t t = 1000; t <= 5000; t += 1000) keep(p, {true, false, false}, t);
    p.tick({true, false, false}, 5100);
    CHECK(p.fault == Fault::ReturnTimeout && !p.armed);
  }
  {
    Interlocks p;
    ready(p);
    p.requestOutput(2, true, 20);
    for (uint32_t t = 1000; t <= 5000; t += 1000) {
      keep(p, Safe, t);
      CHECK(p.requestOutput(2, true, t) == nullptr);
    }
    p.tick(Safe, 5020);
    CHECK(p.fault == Fault::MaxOn && !p.outputs[2]);
  }
  {
    Interlocks p;
    ready(p);
    p.requestOutput(1, true, 21);
    p.tick(Safe, 1520);
    p.keepalive(1520);  // late traffic cannot revive an expired permit
    CHECK(p.fault == Fault::Watchdog && !p.armed && !p.outputs[1]);
    CHECK(!p.arm(1520));
    CHECK(p.requestOutput(1, false, 1521) == nullptr);
  }
  {
    Interlocks p;
    const uint32_t base = UINT32_MAX - 100;
    ready(p, base);
    p.requestOutput(1, true, base + 21);
    p.tick(Safe, 30);  // millis() rollover must not cause an early timeout
    CHECK(p.armed && p.outputs[1]);
    p.tick(Safe, 1419);
    CHECK(p.fault == Fault::Watchdog && !p.outputs[1]);
  }
  {
    Interlocks p;
    p.tick({false, true, false}, 0);
    p.tick({false, true, false}, 20);
    CHECK(!p.arm(20));
    p.tick({true, false, false}, 30);
    p.tick({true, false, false}, 50);
    CHECK(!p.arm(50));
    p.trip(Fault::Command, 51);
    CHECK(!p.reset());
  }
  printf("Firmware interlock policy: %u checks passed\n", checks);
}
