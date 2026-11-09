#include "homing_fixture.h"

void positionReady() {
  homeStart(); runHome();
  CHECK(xPositionKnown && xSoftMaxOffset == -14);
  command("XARM 1"); fakeTime += 200;
}
void runMove() {
  for (unsigned tick = 0; xRemaining && tick < 600000; ++tick) stepHome();
  CHECK(!xRemaining);
}

int main() {
  using carriage::Positioning;
  int32_t result = 0;
  CHECK(Positioning::MinOffset == -20402);
  CHECK(Positioning::milliForOffset(-14) == 160389);
  CHECK(Positioning::target(0, -14, result) && result == -20402);
  CHECK(Positioning::target(135000, -14, result) && result == -3242);
  CHECK(!Positioning::target(-1, -14, result));
  CHECK(!Positioning::target(160390, -14, result));
  CHECK(!Positioning::target(160500, -14, result));

  prepareManual(); command("XMOVE 100000");
  CHECK(xRemaining == 0 && Serial.outgoing.find("CODE:HOME_REQUIRED") != std::string::npos);
  positionReady();
  const unsigned initial = fakePulses;
  command("XMOVE 159390");
  CHECK(xAbsoluteMove && xRemaining == 127 && fakePins[3] == LOW);
  CHECK(xMoveId == 2 && Serial.outgoing.find("MOVE_KIND:ABSOLUTE") != std::string::npos);
  runMove();
  CHECK(xHomeOffset == -141 && fakePulses == initial + 127 && outputsArmed && xPositionKnown);
  command("XMOVE 160389"); runMove();
  CHECK(xHomeOffset == -14 && physicalPosition == 86 && fakePins[20] == HIGH);
  const unsigned returned = fakePulses;
  command("XMOVE 160389"); CHECK(!xRemaining && fakePulses == returned);
  command("XMOVE 160390"); CHECK(!xRemaining && xPositionKnown);
  CHECK(Serial.outgoing.find("CODE:X_SOFT_LIMIT") != std::string::npos);
  command("XJOG 1 1"); command("XSTEP 1");
  CHECK(fakePulses == returned && xHomeOffset == -14 && xPositionKnown);

  // Existing load targets, including long moves beyond the manual jog limit.
  const int32_t loads[] = {135000, 111000, 87000, 63000};
  for (int32_t target : loads) {
    command("XMOVE " + std::to_string(target));
    CHECK(xRemaining > 254 && xAbsoluteMove);
    runMove();
    CHECK(xHomeOffset == Positioning::offsetForMilli(target) && xPositionKnown && outputsArmed);
  }
  command("XMOVE 0"); runMove();
  CHECK(xHomeOffset == Positioning::MinOffset && xPositionKnown);
  const unsigned low = fakePulses;
  command("XJOG -1 1"); command("XSTEP -1");
  CHECK(!xRemaining && fakePulses == low && xPositionKnown);
  command("XMOVE 160389"); CHECK(xRemaining > 20000);
  runMove(); CHECK(xHomeOffset == -14 && xPositionKnown && fakeMinGapUs >= 25000);

  // No queued replacement; all stop/fault paths must cancel the target.
  for (int cause = 0; cause < 6; ++cause) {
    positionReady(); command("XMOVE 63000"); stepHome();
    CHECK(xRemaining > 10000);
    const uint32_t id = xMoveId;
    const uint16_t left = xRemaining;
    command("XMOVE 135000"); command("XJOG -1 13");
    CHECK(xMoveId == id && xRemaining <= left);
    if (cause == 0) command("OFF");
    if (cause == 1) { fakePins[29] = HIGH; loop(); }
    if (cause == 2) { fakePins[14] = LOW; loop(); }
    if (cause == 3) { fakeTime += bench::Interlocks::WatchdogMs; loop(); }
    if (cause == 4) { fakePins[22] = HIGH; loop(); }
    if (cause == 5) command("XDISABLE");
    const unsigned stopped = fakePulses;
    fakeTime += 500; command("KEEPALIVE");
    CHECK(!outputsArmed && !xRemaining && !xAbsoluteMove && fakePulses == stopped);
    CHECK(cause == 0 ? xPositionKnown : !xPositionKnown);
  }
  // Per-pulse enforcement catches an unexpectedly changed counted position.
  positionReady(); command("XMOVE 159390");
  xHomeOffset = Positioning::MinOffset;
  fakeTime += 1; loop();
  CHECK(!outputsArmed && !xPositionKnown && !xRemaining && interlocks.fault == bench::Fault::SoftLimit);
  const char *bad[] = {"XMOVE -1", "XMOVE 160501", "XMOVE nan", "XMOVE 1000 EXTRA"};
  for (const char *target : bad) {
    positionReady(); const unsigned before = fakePulses; command(target);
    CHECK(!outputsArmed && !xPositionKnown && !xRemaining && fakePulses == before);
  }
  // Explicit Load uses the same guarded move path, selecting stored FAST only
  // after acceptance. It does not arm, change limits or rewrite profile values.
  prepareManual(); command("XLOAD 135000"); CHECK(!xRemaining && xProfile==0);
  positionReady(); command("OFF"); command("XPROFILE 3 3000 1500"); command("XPROFILE 2");
  command("XLOAD 135000"); CHECK(!xRemaining && xProfile==2 && !outputsArmed);
  command("XARM 1"); fakeTime+=200;
  command("XLOAD 160390"); CHECK(!xRemaining && xProfile==2 && xPositionKnown);
  command("XLOAD 135000");
  CHECK(xAbsoluteMove && xProfile==3 && xRamp.parameters.maxRate==3000 && xRamp.parameters.acceleration==1500);
  const uint32_t loadId=xMoveId;
  command("XLOAD 111000"); CHECK(xMoveId==loadId); // no queued replacement
  runMove(); CHECK(xHomeOffset==Positioning::offsetForMilli(135000) && outputsArmed && xPositionKnown);
  command("XLOAD 160389"); runMove(); CHECK(xHomeOffset==-14);
  command("XLOAD 63000"); xHomeOffset=Positioning::MinOffset;
  fakeTime+=25; loop(); CHECK(interlocks.fault==bench::Fault::SoftLimit && !outputsArmed && !xPositionKnown);
  printf("Referenced positioning and soft limits: %u checks passed\n", checks);
}
