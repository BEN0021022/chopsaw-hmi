#include "homing_fixture.h"
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
  // Configuration is motion-free, bounded, immutable during Home, and retained
  // independently of Gentle/Normal/Fast. Approach ramps; precision stays slow.
  restart();physicalPosition=-1000;sensorMode=0;sensor();command("XCONFIG 0 1");
  command("XHOMEPROFILE 1200 1500");
  CHECK(xHoming.approach.maxRate==1200 && xHoming.approach.acceleration==1500 && !outputsArmed && fakePulses==0);
  CHECK(Serial.outgoing.find("HOME_RATE_PPS:1200,HOME_ACCEL_PPS2:1500")!=std::string::npos);
  command("XHOME 20594");
  const uint32_t seekAt=fakeTime;
  command("XHOMEPROFILE 2000 3000");CHECK(xHoming.approach.maxRate==1200 && xHoming.active());
  while (xHoming.stage==carriage::Homing::Stage::Seek && fakeTime-seekAt<5000) stepHome();
  CHECK(xHoming.stage==carriage::Homing::Stage::Release && fakeTime-seekAt<5000);
  CHECK(xHoming.ramp.parameters.maxRate==40);
  while (xHoming.active() && xHoming.stage!=carriage::Homing::Stage::Latch) stepHome();
  CHECK(xHoming.ramp.parameters.maxRate==10);
  runHome();CHECK(xHoming.done() && xPositionKnown && xHomeOffset==-14 && physicalPosition==86);
  CHECK(xProfiles[1].maxRate==150 && xProfiles[2].maxRate==1000 && xProfiles[3].maxRate==2500);
  carriage::Homing tuned;
  CHECK(tuned.configure(1200,1000));CHECK(tuned.start(20594,false,0));
  const uint32_t firstInterval=tuned.intervalUs();tuned.pulsed(25);
  CHECK(firstInterval>tuned.intervalUs() && tuned.intervalUs()>1000000u/1200);
  CHECK(!tuned.configure(2000,1500));tuned.cancel();
  CHECK(tuned.configure(20000,1) && tuned.start(20594,false,0));
  tuned.observe(false,100000);CHECK(tuned.active()); // acceleration-aware fixed deadline
  tuned.observe(false,600001);CHECK(tuned.failed());
  const char *badProfiles[]={"XHOMEPROFILE 0 1","XHOMEPROFILE 20001 1","XHOMEPROFILE 1 0", "XHOMEPROFILE 1 50001",
                             "XHOMEPROFILE -1 100", "XHOMEPROFILE 40 200 EXTRA","XHOMEPROFILE 42949672960 200"};
  for (const char *request:badProfiles) {
    restart();command(request);
    CHECK(!outputsArmed && fakePulses==0 && xHoming.approach.maxRate==40 && xHoming.approach.acceleration==200);
  }
  printf("Homing policy and sketch integration: %u checks passed\n", checks);
}
