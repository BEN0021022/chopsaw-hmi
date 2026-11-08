#pragma once
#include "controller_fixture.h"

// Simulated motor position drives the real sketch's Home input. No actual GPIO.
int physicalPosition = 0;
int sensorMode = 0;  // 0=normal at position 100; 1=stuck inactive; 2=stuck active
void sensor() {
  const bool active = sensorMode == 2 || (sensorMode == 0 && physicalPosition >= 100);
  fakePins[20] = active ? LOW : HIGH;
}
void homeStart(int position = 0, int mode = 0, int search = 254) {
  restart(); physicalPosition = position; sensorMode = mode; sensor();
  command("XCONFIG 0 1");
  CHECK(xConfigured);
  command("XHOME " + std::to_string(search));
  CHECK(testMode == TestMode::Homing && outputsArmed && !xPositionKnown);
}
void stepHome() {
  const int32_t before = xCommandedSteps;
  ++fakeTime;
  if (fakeTime % 200 == 0) command("KEEPALIVE"); else loop();
  physicalPosition += xCommandedSteps - before;
  sensor();
}
void runHome() {
  for (unsigned tick = 0; xHoming.active() && tick < 30000; ++tick) stepHome();
  CHECK(!xHoming.active());
}
