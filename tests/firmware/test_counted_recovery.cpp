#include "homing_fixture.h"
void idleTicks(unsigned ms) {while(ms--) {++fakeTime;loop();}}
int main() {
  for(unsigned cause=0;cause<3;++cause) {
    homeStart();runHome();command("XARM 1");idleTicks(210);command("XMOVE 63000");idleTicks(500);
    CHECK(xPositionKnown && xRemaining);
    if(cause==0)fakePins[29]=HIGH;
    if(cause==1)fakePins[22]=HIGH;
    if(cause==2)fakePins[16]=LOW;
    loop();const int32_t stopped=xHomeOffset;const unsigned pulses=fakePulses;
    CHECK(xPositionKnown && !outputsArmed && !xRemaining);
    idleTicks(100);CHECK(fakePulses==pulses && xHomeOffset==stopped && xPositionKnown);
    fakePins[29]=LOW;fakePins[22]=LOW;fakePins[16]=HIGH;idleTicks(40);command("RESET");
    CHECK(interlocks.fault==bench::Fault::None && xPositionKnown && xHomeOffset==stopped);
    command("XARM 1");idleTicks(210);command("XJOG 1 10");
    for(unsigned i=0;i<500 && xRemaining;++i) {++fakeTime;if(fakeTime%200==0)command("KEEPALIVE");else loop();}
    CHECK(xPositionKnown && xHomeOffset==stopped+10);
  }
  homeStart();runHome();fakePins[29]=HIGH;command("XARM 1");
  // A driver error after a door stop must still revoke confidence.
  fakePins[14]=LOW;loop();CHECK(!xPositionKnown);
  restart();CHECK(!xPositionKnown);
  printf("Counted fault recovery: %u checks passed\n",checks);
}
