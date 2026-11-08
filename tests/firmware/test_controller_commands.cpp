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
  commandLength = 0; discardCommand = false; testMode = TestMode::None;
  xConfigured = xHomeSeenActive = xHomeVerified = false;
  xHomeActive = bench::StableAssertion{}; xHomeInactive = bench::StableAssertion{};
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
int main() {
  restart();
  CHECK(Serial.outgoing.find("FW:0.9.0") != std::string::npos);
  CHECK(Serial.outgoing.find("X_APP:CARRIAGE_V3") != std::string::npos);
  CHECK(Serial.outgoing.find("X_TEST:MANUAL_JOG_V1") != std::string::npos);
  CHECK(Serial.outgoing.find("MAX_JOG:254,RATE_PPS:40") != std::string::npos);
  CHECK(Serial.outgoing.find("BUDGET:") == std::string::npos);
  CHECK(Serial.outgoing.find("HOME_CHECK:LEVEL_ONLY") != std::string::npos);
  CHECK(Serial.outgoing.find("X_ENA:D40/AXIS_Y_EN") != std::string::npos);
  CHECK(!outputsArmed && !xConfigured && !xHomeVerified && fakePulses == 0);
  CHECK(fakePins[2] == LOW && fakePins[3] == LOW && fakePins[40] == HIGH);
  CHECK(fakeModes[10] != OUTPUT && fakeModes[40] == OUTPUT);
  CHECK(!outputStates[0] && !outputStates[1] && !outputStates[2]);
  command("XARM 1"); command("XJOG 1 13"); command("XCONFIG 0 1");
  CHECK(!outputsArmed && xConfigured && !xHomeVerified && fakePulses == 0);
  command("XARM 1"); fakeTime += 200;
  command("XJOG 1 13"); finishJog();
  CHECK(outputsArmed && fakePulses == 13 && !xHomeVerified);
  restart();
  fakePins[20] = LOW; command("XCONFIG 0 1");
  CHECK(!xConfigured && !outputsArmed);  // active limit still blocks setup
  fakePins[20] = HIGH; loop();
  fakePins[20] = LOW; loop(); fakeTime += 20; loop();
  fakePins[20] = HIGH; loop(); fakeTime += 20; loop(); CHECK(xHomeVerified);
  fakePins[14] = LOW; command("XCONFIG 0 1"); CHECK(!xConfigured);
  fakePins[14] = HIGH; command("XCONFIG 0 1"); CHECK(xConfigured && fakePulses == 0);
  command("XARM 1"); CHECK(outputsArmed && fakePins[40] == LOW && fakePulses == 0);
  CHECK(Serial.outgoing.find("JOG_READY:0") != std::string::npos);
  command("XJOG 1 13"); CHECK(!xRemaining && fakePulses == 0);
  fakeTime += 200; command("STATUS"); CHECK(Serial.outgoing.find("JOG_READY:1") != std::string::npos);
  // Total commanded travel exceeds the old per-arm allowance repeatedly.
  prepareManual();
  for (int move = 0; move < 6; ++move) {
    const unsigned before = fakePulses;
    command(move % 2 ? "XJOG -1 254" : "XJOG 1 254"); CHECK(xRemaining == 254);
    finishJog(); CHECK(outputsArmed && testMode == TestMode::Stepper && fakePulses == before + 254);
    fakeTime += 100; command("KEEPALIVE"); CHECK(fakePulses == before + 254);
  }
  CHECK(fakePulses == 1524 && xCommandedSteps == 0 && xMoveId == 6);
  CHECK(fakePulseWidth == 5 && fakeSetupUs >= 10 && fakeMinGapUs >= 25000);
  command("XJOG -1 32"); finishJog(); CHECK(xCommandedSteps == -32);
  command("XJOG 1 64"); finishJog(); CHECK(xCommandedSteps == 32);
  // Rapid reversal between tiny jogs must still honor the pulse interval.
  prepareManual(); command("XJOG 1 1"); fakeTime += 1; loop(); CHECK(fakePulses == 1);
  command("XJOG -1 1"); CHECK(fakePulses == 1 && xRemaining == 1);
  fakeTime += 23; loop(); CHECK(fakePulses == 1);
  ++fakeTime; loop(); CHECK(fakePulses == 2 && !xRemaining && outputsArmed);
  CHECK(fakeMinGapUs >= 25000 && xCommandedSteps == 0);
  prepareManual(); command("XJOG 1 127"); command("XJOG -1 13"); command("XSTEP -1");
  CHECK(xMoveId == 1 && fakePins[3] == HIGH);
  CHECK(Serial.outgoing.find("CODE:X_BUSY") != std::string::npos);
  command("XARM 1"); CHECK(xMoveId == 1 && xRemaining <= 127);
  command("OUT 0 1"); CHECK(!outputStates[0]);
  command("I2C"); CHECK(Serial.outgoing.find("CODE:I2C_BLOCKED_DURING_TEST") != std::string::npos);
  finishJog(); CHECK(fakePulses == 127 && outputsArmed);
  for (int cause = 0; cause < 8; ++cause) {
    prepareManual(); command("XJOG 1 127"); fakeTime += 1; loop(); CHECK(fakePulses == 1 && xRemaining == 126);
    if (cause == 0) command("OFF");
    if (cause == 1) { fakePins[29] = HIGH; loop(); }
    if (cause == 2) { fakePins[20] = LOW; loop(); }
    if (cause == 3) { fakePins[14] = LOW; loop(); }
    if (cause == 4) { fakeTime += bench::Interlocks::WatchdogMs; loop(); }
    if (cause == 5) { fakePins[22] = HIGH; loop(); }
    if (cause == 6) { fakePins[16] = LOW; loop(); }
    if (cause == 7) command("XARM 0");
    const unsigned stoppedAt = fakePulses;
    fakeTime += 200; command("KEEPALIVE");
    CHECK(!outputsArmed && !xRemaining && fakePins[2] == LOW && fakePulses == stoppedAt);
    CHECK(fakePins[40] == LOW);
    command("XJOG -1 13"); CHECK(fakePulses == stoppedAt && !xRemaining);
  }
  const char *bad[] = {"XJOG 1 0", "XJOG 1 255", "XJOG 1 -1", "XJOG 0 13", "XJOG 1 13 EXTRA"};
  for (const char *request : bad) {
    prepareManual(); command(request);
    CHECK(!outputsArmed && !xRemaining && fakePulses == 0 && interlocks.fault == bench::Fault::Command);
  }
  prepareManual(); command("XJOG 1 127"); fakeTime += 1000; loop();
  CHECK(fakePulses == 1); loop(); CHECK(fakePulses == 1);
  prepareManual(4294700u); command("XJOG -1 13"); finishJog();
  CHECK(fakePulses == 13 && xCommandedSteps == -13 && outputsArmed);
  command("XDISABLE"); CHECK(!outputsArmed && !xConfigured && !xHomeVerified && fakePins[40] == HIGH);
  command("XARM 1"); CHECK(!outputsArmed && xCommandedSteps == -13);
  prepareManual(); command("XJOG 1 254"); finishJog(); command("XDISABLE");
  CHECK(fakePulses == 254 && !outputsArmed);
  prepareManual(); command("XJOG 1 1"); finishJog();
  fakeTime += 2200000u;  // armed idle longer than the signed micros half-period
  interlocks.keepalive(fakeTime);  // healthy host heartbeats throughout idle
  command("XJOG -1 1"); fakeTime += 1; loop();
  CHECK(fakePulses == 2 && !xRemaining && outputsArmed && xCommandedSteps == 0);
  printf("Manual controller integration: %u checks passed\n", checks);
}
