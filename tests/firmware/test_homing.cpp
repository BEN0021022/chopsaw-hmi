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

int main() {
  homeStart();
  CHECK(fakePulses == 0 && fakePins[3] == HIGH);
  for (int i = 0; i < 190; ++i) stepHome();
  CHECK(fakePulses == 0);  // enable settling precedes Home pulses
  runHome();
  CHECK(xHoming.done() && xPositionKnown && !outputsArmed);
  CHECK(physicalPosition == 86 && xHomeOffset == -14 && xCommandedSteps == 86);
  CHECK(fakePins[20] == HIGH && fakePins[2] == LOW && fakePins[40] == LOW);
  CHECK(fakeMinGapUs >= 25000 && fakePulseWidth == 5 && xMoveId == 1);
  CHECK(Serial.outgoing.find("HOME_STATE:DONE") != std::string::npos);
  CHECK(Serial.outgoing.find("POS_KNOWN:1") != std::string::npos);
  const unsigned completed = fakePulses;
  fakeTime += 1000; command("KEEPALIVE"); CHECK(fakePulses == completed && !outputsArmed);
  command("XARM 1"); fakeTime += 200; command("XJOG -1 13"); finishJog();
  CHECK(xPositionKnown && xHomeOffset == -27);
  command("OFF"); CHECK(xPositionKnown);  // normal stop retains counted reference
  command("XDISABLE"); CHECK(!xPositionKnown);

  // Starting already on Home must release it safely before latching again.
  homeStart(110);
  CHECK(xHoming.stage == carriage::Homing::Stage::Release && fakePins[3] == LOW);
  runHome(); CHECK(xPositionKnown && xHoming.done() && physicalPosition == 86);
  CHECK(xCommandedSteps == -24 && xHomeOffset == -14);

  homeStart(0, 1); runHome();
  CHECK(!xPositionKnown && !outputsArmed && interlocks.fault == bench::Fault::HomingFailed);
  CHECK(std::string(xHoming.error) == "NOT_FOUND" && fakePulses == 254);
  homeStart(110, 2); runHome();
  CHECK(!xPositionKnown && !outputsArmed && std::string(xHoming.error) == "STUCK_ACTIVE");
  CHECK(fakePulses == 127);

  homeStart();
  while (xHoming.active() && xHoming.stage != carriage::Homing::Stage::Latch) stepHome();
  sensorMode = 1; sensor(); runHome();
  CHECK(!xPositionKnown && std::string(xHoming.error) == "LATCH_NOT_FOUND");
  homeStart();
  while (xHoming.active() && xHoming.stage != carriage::Homing::Stage::PullRelease) stepHome();
  sensorMode = 2; sensor(); runHome();
  CHECK(!xPositionKnown && std::string(xHoming.error) == "STUCK_ACTIVE");

  // Cancel/fault every phase; no queued pulse or saved reference may survive.
  for (int target = 1; target <= 6; ++target) {
    for (int cause = 0; cause < 5; ++cause) {
      homeStart();
      for (unsigned tick = 0; xHoming.active() && static_cast<int>(xHoming.stage) != target && tick < 20000; ++tick) stepHome();
      CHECK(static_cast<int>(xHoming.stage) == target);
      if (cause == 0) command("OFF");
      if (cause == 1) { fakePins[29] = HIGH; loop(); }
      if (cause == 2) { fakePins[14] = LOW; loop(); }
      if (cause == 3) { fakeTime += bench::Interlocks::WatchdogMs; loop(); }
      if (cause == 4) { fakePins[22] = HIGH; loop(); }
      const unsigned stopped = fakePulses;
      fakeTime += 1000; command("KEEPALIVE");
      CHECK(!outputsArmed && !xHoming.active() && !xPositionKnown && fakePulses == stopped);
      CHECK(fakePins[2] == LOW && !outputStates[0] && !outputStates[1] && !outputStates[2]);
    }
  }
  homeStart(); command("XJOG 1 13"); command("OUT 0 1");
  CHECK(xRemaining == 0 && !outputStates[0] && xHoming.active());
  command("XHOME 254"); CHECK(xMoveId == 1);  // repeated request cannot restart/bump limits
  command("XDISABLE"); CHECK(!xHoming.active() && !xPositionKnown && fakePins[40] == HIGH);
  const char *bad[] = {"XHOME 0", "XHOME -1", "XHOME 20595", "XHOME 254 EXTRA"};
  for (const char *request : bad) {
    restart(); command("XCONFIG 0 1"); command(request);
    CHECK(!outputsArmed && !xHoming.active() && !xPositionKnown && fakePulses == 0);
  }
  restart(); command("XHOME 254"); CHECK(!outputsArmed && !xHoming.active());

  carriage::Homing policy;
  CHECK(!policy.start(0, false, 0) && !policy.start(20595, false, 0));
  CHECK(policy.start(254, false, 0));
  policy.observe(false, 9000); CHECK(policy.failed() && std::string(policy.error) == "TIMEOUT");
  CHECK(policy.start(254, false, 0));
  policy.observe(true, 1); CHECK(!policy.wantsPulse(true));
  policy.observe(false, 10); CHECK(policy.stage == carriage::Homing::Stage::Seek);
  policy.observe(true, 20); policy.observe(true, 40);
  CHECK(policy.stage == carriage::Homing::Stage::Release);
  policy.observe(false, 41); policy.observe(false, 61);
  CHECK(policy.stage == carriage::Homing::Stage::Backoff);
  policy.observe(true, 62); CHECK(policy.failed() && std::string(policy.error) == "RETRIGGERED");
  printf("Homing policy and sketch integration: %u checks passed\n", checks);
}
