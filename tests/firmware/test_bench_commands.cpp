#include "stubs/Arduino.h"
#include "stubs/Wire.h"
#include <stdlib.h>
uint32_t fakeTime = 0;
int fakePins[64];
int fakeModes[64], fakeLatches[64];
unsigned fakePulses = 0, fakeUs = 0, fakeDirAt = 0, fakeHighAt = 0, fakePulseWidth = 0, fakeSetupUs = 0;
uint32_t fakeMinGapUs = UINT32_MAX, fakeLastPulseUs = 0;
FakeSerial Serial;
FakeWire Wire2;
#include "../../firmware/chopsaw_sensor_bench/chopsaw_sensor_bench.ino"

static unsigned checks = 0;
#define CHECK(value) do { ++checks; if (!(value)) { \
  fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #value); exit(1); } } while (0)

void command(const std::string &line) {
  Serial.incoming += line + '\n';
  while (Serial.available()) { ++fakeTime; loop(); }
}

void restart() {
  interlocks = bench::Interlocks{};
  commandLength = 0;
  discardCommand = false;
  testMode = TestMode::None;
  xConfigured = xHomeSeenActive = xHomeVerified = false;
  xHomeActive = bench::StableAssertion{};
  xHomeInactive = bench::StableAssertion{};
  xBudget = xRemaining = 0;
  Serial.incoming.clear();
  Serial.outgoing.clear();
  fakeTime = lastInputAt = lastHealthAt = 0;
  for (int &pin : fakePins) pin = HIGH;
  for (int &mode : fakeModes) mode = 0;
  for (int &latch : fakeLatches) latch = 0;
  fakePulses = fakeUs = fakeDirAt = fakeHighAt = fakePulseWidth = fakeSetupUs = 0;
  fakeMinGapUs = UINT32_MAX; fakeLastPulseUs = 0;
  fakePins[29] = LOW;  // closed door
  fakePins[22] = LOW;  // saw fully up on Limit Z; retired Cyc/St stays HIGH
  setup();
  loop();
  fakeTime += 20;
  loop();
}

void prepareJog() {
  restart();
  fakePins[20] = LOW; loop(); fakeTime += 20; loop();
  fakePins[20] = HIGH; loop(); fakeTime += 20; loop();
  command("XCONFIG 0 1"); command("XARM 1");
  fakeTime += 200;
}

void finishJog() {
  for (unsigned tick = 0; xRemaining && tick < 300; ++tick) {
    fakeTime += 25;
    if (tick % 20 == 0) command("KEEPALIVE"); else loop();
  }
}

int main() {
  restart();
  CHECK(!outputsArmed && fakePins[33] == LOW && fakePins[32] == LOW && fakePins[19] == LOW);
  CHECK(Serial.outgoing.find("FW:0.6.0") != std::string::npos);
  CHECK(Serial.outgoing.find("INPUT_MAP:DOOR29_UP22_DOWN16") != std::string::npos);
  CHECK(Serial.outgoing.find("INTERLOCKS:DOOR_POSITION_V1") != std::string::npos);
  CHECK(Serial.outgoing.find("X_MAP:STEP2_DIR3_EN40") != std::string::npos);
  CHECK(Serial.outgoing.find("X_ENA:D40/AXIS_Y_EN") != std::string::npos);
  CHECK(fakeModes[10] != OUTPUT && fakeModes[40] == OUTPUT);
  command("ARM 1");
  CHECK(outputsArmed);
  command("OUT 0 1");
  CHECK(fakePins[33] == HIGH && fakePins[32] == LOW && fakePins[19] == LOW);
  command("OUT 1 1");
  CHECK(fakePins[32] == LOW && Serial.outgoing.find("CODE:OUTPUT_BUSY") != std::string::npos);
  fakePins[29] = HIGH;
  loop();
  CHECK(!outputsArmed && fakePins[33] == LOW);
  CHECK(interlocks.fault == bench::Fault::DoorOpen);
  fakePins[29] = LOW;
  loop();
  fakeTime += 20;
  loop();
  command("ARM 1");
  CHECK(!outputsArmed);
  command("OFF");
  CHECK(interlocks.fault == bench::Fault::DoorOpen);
  command("RESET");
  CHECK(interlocks.fault == bench::Fault::None && !outputsArmed);
  command("ARM 1");
  command("OUT 2 1");
  CHECK(fakePins[19] == HIGH && fakePins[33] == LOW && fakePins[32] == LOW);
  command("I2C");
  CHECK(Serial.outgoing.find("CODE:I2C_BLOCKED_DURING_TEST") != std::string::npos);
  command("OUT 2 0");
  CHECK(fakePins[19] == LOW);
  command("OUT 0 1 EXTRA");
  CHECK(!outputsArmed && interlocks.fault == bench::Fault::Command);

  restart();
  command("ARM 1");
  command(std::string(70, 'X') + "OUT 2 1");
  CHECK(interlocks.fault == bench::Fault::Command && fakePins[19] == LOW);
  CHECK(Serial.outgoing.find("COMMAND_TOO_LONG") != std::string::npos);
  command("RESET");
  command("ARM 1");
  command("OUT 1 1");
  CHECK(fakePins[32] == HIGH);
  fakeTime += bench::Interlocks::WatchdogMs;
  command("KEEPALIVE");
  CHECK(!outputsArmed && fakePins[32] == LOW && interlocks.fault == bench::Fault::Watchdog);
  restart();
  fakePins[22] = HIGH;
  fakePins[17] = LOW;  // a false assertion on the retired pin must not permit arm
  loop();
  command("ARM 1");
  CHECK(!outputsArmed);
  CHECK(fakePulses == 0);

  restart();
  CHECK(fakePins[2] == LOW && fakePins[3] == LOW && fakePins[40] == HIGH && fakePulses == 0);
  command("XLEVEL 1 0");
  CHECK(fakePins[3] == HIGH && fakePins[40] == LOW && fakePulses == 0);
  command("XSTEP 1");
  command("XCONFIG 0 1");
  CHECK(!xConfigured && fakePulses == 0);
  fakePins[20] = LOW; loop(); fakeTime += 20; loop();
  fakePins[20] = HIGH; loop(); fakeTime += 20; loop();
  CHECK(xHomeVerified);
  fakePins[14] = LOW;
  command("XCONFIG 0 1");
  CHECK(!xConfigured);
  fakePins[14] = HIGH;
  command("XCONFIG 0 1");
  CHECK(xConfigured && fakePulses == 0);
  command("XARM 1");
  CHECK(outputsArmed && testMode == TestMode::Stepper && xBudget == X_ARM_BUDGET);
  command("XSTEP 1");
  CHECK(fakePulses == 0);  // enable setup interval is enforced
  fakeTime += 200; command("XSTEP 1");
  CHECK(fakePulses == 1 && fakePins[2] == LOW && fakePulseWidth == 5 && fakeSetupUs >= 10);
  command("OUT 0 1");
  CHECK(!outputStates[0]);  // pneumatic and stepper modes cannot overlap
  for (unsigned i = 0; i < 4; ++i) { fakeTime += 200; command("XSTEP -1"); }
  CHECK(fakePulses == 5 && outputsArmed && xBudget == X_ARM_BUDGET - 5);
  xBudget = 0; stopTests();
  command("XSTEP 1");
  CHECK(fakePulses == 5);
  command("XARM 1");
  fakePins[14] = LOW; loop();
  CHECK(!outputsArmed && interlocks.fault == bench::Fault::DriverAlarm && fakePins[2] == LOW);
  command("XSTEP 1");
  CHECK(fakePulses == 5);
  fakePins[14] = HIGH; command("RESET"); command("XARM 1");
  fakePins[20] = LOW; loop();
  CHECK(!outputsArmed && interlocks.fault == bench::Fault::HomeLimit);
  CHECK(fakePulses == 5);
  fakePins[20] = HIGH; command("RESET"); command("XARM 1");
  fakePins[29] = HIGH; command("XSTEP 1");
  CHECK(!outputsArmed && interlocks.fault == bench::Fault::DoorOpen && fakePulses == 5);
  fakePins[29] = LOW; loop(); fakeTime += 20; loop();
  command("RESET"); command("XARM 1");
  fakeTime += bench::Interlocks::WatchdogMs; command("KEEPALIVE");
  CHECK(!outputsArmed && interlocks.fault == bench::Fault::Watchdog && fakePulses == 5);
  prepareJog();
  command("XJOG 1 13");
  CHECK(xRemaining == 13 && fakePulses == 0);
  command("XJOG -1 127");
  CHECK(xRemaining <= 13 && fakePins[3] == HIGH);
  CHECK(Serial.outgoing.find("CODE:X_BUSY") != std::string::npos);
  command("XSTEP -1");
  CHECK(fakePins[3] == HIGH);
  finishJog();
  CHECK(fakePulses == 13 && !xRemaining && xBudget == 241 && outputsArmed);
  CHECK(fakePulseWidth == 5 && fakeSetupUs >= 10);

  prepareJog();
  command("XJOG -1 127"); finishJog();
  CHECK(fakePulses == 127 && xBudget == 127 && outputsArmed);
  fakeTime += 200; command("XJOG 1 127"); finishJog();
  CHECK(fakePulses == 254 && !outputsArmed && !xRemaining && !xBudget);
  command("XJOG 1 13"); fakeTime += 100; loop();
  CHECK(fakePulses == 254);

  prepareJog();
  command("XJOG 1 64"); finishJog();
  CHECK(fakePulses == 64 && xBudget == 190);
  fakeTime += 200; command("XJOG 1 127"); finishJog();
  CHECK(fakePulses == 191 && xBudget == 63);
  fakeTime += 200; command("XJOG 1 64");
  CHECK(!xRemaining && Serial.outgoing.find("CODE:X_BUDGET_EXCEEDED") != std::string::npos);

  for (int cause = 0; cause < 7; ++cause) {
    prepareJog(); command("XJOG 1 127");
    fakeTime += 1; loop();
    CHECK(fakePulses == 1 && xRemaining == 126);
    if (cause == 0) command("OFF");
    if (cause == 1) { fakePins[29] = HIGH; loop(); }
    if (cause == 2) { fakePins[20] = LOW; loop(); }
    if (cause == 3) { fakePins[14] = LOW; loop(); }
    if (cause == 4) { fakeTime += bench::Interlocks::WatchdogMs; loop(); }
    if (cause == 5) { fakePins[22] = HIGH; loop(); }
    if (cause == 6) { fakePins[16] = LOW; loop(); }
    const unsigned stoppedAt = fakePulses;
    fakeTime += 200; loop();
    CHECK(!outputsArmed && !xRemaining && fakePins[2] == LOW && fakePulses == stoppedAt);
    CHECK(fakePins[40] == LOW);  // cancellation retains holding level
    command("KEEPALIVE");
    CHECK(!outputsArmed && !xRemaining);
  }
  prepareJog(); command("XJOG 1 127"); fakeTime += 1000; loop();
  CHECK(fakePulses == 1);  // missed deadlines never create a catch-up burst
  loop(); CHECK(fakePulses == 1);
  command("XJOG 1 255");
  CHECK(!outputsArmed && !xRemaining && interlocks.fault == bench::Fault::Command);
  prepareJog(); fakeTime = 4294967u; xArmAt = xLastStepAt = fakeTime - 200;
  interlocks.keepalive(fakeTime); command("XJOG -1 13"); finishJog();
  CHECK(fakePulses == 13);  // microsecond counter rollover
  printf("Bench serial integration: %u checks passed\n", checks);
}
