#include "homing_fixture.h"

void profileMove() {
  for (unsigned tick=0; xRemaining && tick<40000; ++tick) {
    ++fakeTime;
    if (tick%200==0) command("KEEPALIVE"); else loop();
  }
  CHECK(!xRemaining);
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
  printf("Motion profile/ramp checks: %u passed\n",checks);
}
