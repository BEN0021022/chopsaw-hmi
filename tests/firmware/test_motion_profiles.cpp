#include "homing_fixture.h"

void profileMove() {
  for (unsigned tick=0; xRemaining && tick<40000; ++tick) {
    ++fakeTime;
    if (tick%200==0) command("KEEPALIVE"); else loop();
  }
  CHECK(!xRemaining);
}

void advanceUs(unsigned delta) {
  fakeUs += delta; fakeTime += fakeUs/1000; fakeUs %= 1000;
}

int main() {
  for (uint8_t profile=0; profile<4; ++profile) {
    const carriage::MotionProfile parameters = carriage::MotionProfile::get(profile);
    carriage::MotionRamp ramp;
    ramp.start(200,profile);
    uint32_t intervals[200];
    for (unsigned i=0;i<200;++i) {
      intervals[i]=ramp.intervalUs();
      CHECK(intervals[i]>=static_cast<uint32_t>(ceilf(1000000.0f/parameters.maxRate)));
      ramp.pulsed();
    }
    CHECK(intervals[0]==intervals[199]);
    for (unsigned i=1;i<100;++i) CHECK(intervals[i]<=intervals[i-1]);
    for (unsigned i=101;i<200;++i) CHECK(intervals[i]>=intervals[i-1]);
    if (profile) CHECK(intervals[0]>intervals[99]);
    else CHECK(intervals[0]==25000 && intervals[99]==25000);
    restart(); command("XPROFILE "+std::to_string(profile));
    CHECK(xProfile==profile && !outputsArmed && fakePulses==0 && fakePins[40]==HIGH);
    command("XCONFIG 0 1"); command("XARM 1"); fakeTime+=200;
    command("XJOG 1 254");
    if (profile) { fakeTime+=1; loop(); CHECK(fakePulses==0); }
    profileMove();
    CHECK(fakePulses==254 && outputsArmed && xCommandedSteps==254);
    CHECK(fakeMinGapUs>=static_cast<uint32_t>(ceilf(1000000.0f/parameters.maxRate)));
    const unsigned before=fakePulses;
    command("XPROFILE "+std::to_string((profile+1)%4));
    CHECK(xProfile==profile && fakePulses==before); // can't change timing while armed
    command("XJOG -1 254"); profileMove(); CHECK(xCommandedSteps==0 && fakePulses==508);
    command("XJOG 1 254"); fakeTime+=150; loop(); command("OFF");
    const unsigned stopped=fakePulses;
    fakeTime+=500; command("KEEPALIVE"); CHECK(!outputsArmed && !xRemaining && fakePulses==stopped);
  }
  restart(); command("XPROFILE 4"); CHECK(interlocks.fault==bench::Fault::Command && fakePulses==0);
  restart(); command("XPROFILE 3"); command("XCONFIG 0 1"); command("XARM 1");
  fakeTime+=200; command("XJOG 1 254"); fakeTime+=1000; loop();
  const unsigned once=fakePulses; loop(); CHECK(fakePulses==once); // no catch-up burst

  // User-edited parameters are atomic, RAM-only, disarmed-only, and selected
  // rates are captured by the ramp at command acceptance.
  restart(); command("XPROFILE 3 1700 2200");
  CHECK(xProfile==3 && xProfiles[3].maxRate==1700 && xProfiles[3].acceleration==2200);
  CHECK(!outputsArmed && !fakePulses && fakePins[40]==HIGH);
  command("XPROFILE 1"); command("XPROFILE 3"); CHECK(xProfiles[3].maxRate==1700);
  command("XCONFIG 0 1"); command("XARM 1");
  command("XPROFILE 3 2000 3000"); CHECK(xProfiles[3].maxRate==1700);
  const char *bad[] = {"XPROFILE 0 1000 1000", "XPROFILE 3 0 1000", "XPROFILE 3 20001 1000",
                      "XPROFILE 3 1000 0", "XPROFILE 3 1000 50001", "XPROFILE 3 TEXT",
                      "XPROFILE 3 1000", "XPROFILE 3 1000 1000 EXTRA"};
  for(const char *c:bad) { restart(); command(c);
    CHECK(interlocks.fault==bench::Fault::Command && !outputsArmed && !fakePulses);
    CHECK(xProfiles[3].maxRate==2500); }
  restart(); CHECK(xProfile==0 && xProfiles[3].maxRate==2500);

  // Microsecond simulation verifies the actual sketch scheduler at the full
  // editable 20kpps cap, rather than a millisecond mock that caps near 1kpps.
  restart(); command("XPROFILE 3 20000 50000"); command("XCONFIG 0 1"); command("XARM 1");
  fakeTime+=200; xPositionKnown=true; xHomeOffset=xSoftMaxOffset=-14;
  xHoming.stage=carriage::Homing::Stage::Done;
  command("XMOVE 63000"); const unsigned expected=xRemaining;
  for(unsigned t=0; xRemaining && t<4000000; ++t) {
    advanceUs(1); interlocks.keepalive(millis()); serviceXJog();
  }
  CHECK(!xRemaining && fakePulses==expected && xTiming.count==expected);
  CHECK(xTiming.peakPps()==20000 && fakeMinGapUs==50 && fakePulseWidth==5);
  CHECK(xTiming.elapsedUs()<1500000 && outputsArmed && xPositionKnown);
  CHECK(xHomeOffset==carriage::Positioning::offsetForMilli(63000));
  // Record still fits its reserved USB capacity at maximum-size fields.
  xTiming.maxLate=UINT32_MAX; publishX();
  const auto record=Serial.outgoing.rfind("BENCH_X,");
  CHECK(record!=std::string::npos && Serial.outgoing.size()-record<1024);

  // A full host TX buffer skips armed telemetry, not pulse servicing. Loss of
  // keepalive still cancels via the existing watchdog independently.
  command("XJOG -1 254"); Serial.txRoom=0;
  const std::string beforeOutput=Serial.outgoing;
  publishHello(); publishPinMap(); publishX(); publishInputs(); publishSafety(); publishOutputs();
  CHECK(Serial.outgoing==beforeOutput);
  advanceUs(10000); serviceXJog(); CHECK(xTiming.count==1);
  const unsigned beforeStop=fakePulses;
  fakeTime+=1500; loop(); CHECK(!outputsArmed && !xRemaining && fakePulses==beforeStop);
  CHECK(interlocks.fault==bench::Fault::Watchdog);

  carriage::PulseTiming timing;
  timing.pulse(UINT32_MAX-19,UINT32_MAX-21); timing.pulse(30,28);
  CHECK(timing.count==2 && timing.elapsedUs()==50 && timing.peakPps()==20000 && timing.maxLate==2);
  printf("Motion profile/ramp checks: %u passed\n",checks);
}
