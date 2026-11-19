#pragma once
// Real manual-controller sketch; only GPIO, serial and time are mocked.
#include "stubs/Arduino.h"
#include "stubs/Wire.h"
#include <stdlib.h>
uint32_t fakeTime = 0;
int fakePins[64], fakeModes[64], fakeLatches[64];
unsigned fakePulses = 0, fakeUs = 0, fakeDirAt = 0, fakeHighAt = 0, fakePulseWidth = 0, fakeSetupUs = 0;
uint32_t fakeMinGapUs = UINT32_MAX, fakeLastPulseUs = 0;
FakeSerial Serial;
FakeWire Wire2;
#include "../../firmware/chopsaw_controller/chopsaw_controller.ino"
static unsigned checks = 0;
#define CHECK(value) do { ++checks; if (!(value)) { \
  fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #value); exit(1); } } while (0)

void command(const std::string &line) {
  Serial.incoming += line + '\n';
  while (Serial.available()) { ++fakeTime; loop(); }
}
void restart() {
  interlocks = bench::Interlocks{};
  dry = unloaded::DryRun{};
  commandLength = 0; discardCommand = false; testMode = TestMode::None;
  xConfigured = xHomeSeenActive = xHomeVerified = false;
  xHomeActive = bench::StableAssertion{}; xHomeInactive = bench::StableAssertion{};
  xHoming = carriage::Homing{}; xPositionKnown = false; xHomeOffset = 0; xSoftMaxOffset = 0; xTargetOffset = 0; xAbsoluteMove = false; xProfile = 0; xRamp = carriage::MotionRamp{};
  xEdge = carriage::EdgeSearch{}; xEdgeValid = false;
  xContinuousAcquire=xReturnPermit=xReturnCutUsed=false;
  xReturnAutomatic=xReturnPending=false;xReturnHoldMask=0;
  xAcquisitionEnd=xCandidateOffset=xReturnStart=xReturnMinimum=0;
  xEdgeMilli = xTruingMilli = 0; xSensorOffsetMilli = 10800; xTrimMilli = 250;
  xTiming = carriage::PulseTiming{}; Serial.txRoom = 8192;
  for (unsigned id=0; id<4; ++id) xProfiles[id] = carriage::MotionProfile::get(id);
  xRemaining = 0; xCommandedSteps = 0; xMoveId = 0; xDirection = 1;
  xNextPulseUs = xArmAt = xLastStepAt = 0;
  Serial.incoming.clear(); Serial.outgoing.clear();
  fakeTime = lastInputAt = lastHealthAt = 0;
  for (int &pin : fakePins) pin = HIGH;
  for (int &mode : fakeModes) mode = 0;
  for (int &latch : fakeLatches) latch = 0;
  fakePulses = fakeUs = fakeDirAt = fakeHighAt = fakePulseWidth = fakeSetupUs = 0;
  fakeMinGapUs = UINT32_MAX; fakeLastPulseUs = 0;
  fakePins[29] = LOW; fakePins[22] = LOW;
  setup(); loop(); fakeTime += 20; loop();
}
void prepareManual(uint32_t armBase = 0) {
  restart();
  command("XCONFIG 0 1");
  if (armBase) fakeTime = armBase;
  command("XARM 1"); fakeTime += 200;
}
void finishJog() {
  for (unsigned tick = 0; xRemaining && tick < 400; ++tick) {
    fakeTime += 25;
    if (tick % 10 == 0) command("KEEPALIVE"); else loop();
  }
  CHECK(xRemaining == 0);
}
