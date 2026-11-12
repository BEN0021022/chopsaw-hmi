#include "homing_fixture.h"

void edgeReady() {
  homeStart(); runHome(); command("XARM 1"); fakeTime += 200;
  CHECK(xPositionKnown && outputsArmed && xHomeOffset == -14);
}
void edgeTick() { stepHome(); }
void seekUntil(unsigned additional) {
  const unsigned begin = fakePulses;
  for (unsigned t=0; fakePulses-begin<additional && t<30000; ++t) edgeTick();
  CHECK(fakePulses-begin==additional);
}
void detect() {
  fakePins[21] = LOW;
  const unsigned begin = fakePulses;
  for (unsigned t=0;t<25;++t) edgeTick();
  CHECK(fakePulses==begin);
}

int main() {
  using carriage::EdgeSearch;
  EdgeSearch policy;
  policy.start(1,UINT32_MAX-10); policy.pulsed(UINT32_MAX-5);
  policy.observe(true,UINT32_MAX-1); CHECK(policy.active());
  policy.observe(true,19); CHECK(policy.stage==EdgeSearch::Stage::Found);
  policy.start(1,0); policy.pulsed(25); policy.observe(false,69); CHECK(policy.active());
  policy.observe(false,70); CHECK(policy.stage==EdgeSearch::Stage::Failed);
  policy.start(10,0); policy.observe(true,2249); CHECK(policy.active());
  policy.observe(true,2250); CHECK(std::string(policy.error)=="TIMEOUT");

  prepareManual(); command("XEDGE 254 10800 250");
  CHECK(testMode==TestMode::Stepper && !xRemaining && !xEdgeValid);
  edgeReady(); fakePins[21]=LOW; const unsigned initial=fakePulses;
  command("XEDGE 254 10800 250");
  CHECK(testMode==TestMode::Stepper && !xRemaining && fakePulses==initial);
  CHECK(Serial.outgoing.find("CODE:EDGE_ALREADY_ACTIVE")!=std::string::npos);
  fakePins[21]=HIGH; command("XPROFILE 3"); // must not alter while armed
  command("XEDGE 254 10800 250");
  CHECK(testMode==TestMode::Edge && xRemaining==254 && fakePins[3]==LOW);
  CHECK(xProfile==1 && xRamp.parameters.maxRate==xProfiles[1].maxRate && xRamp.parameters.acceleration==xProfiles[1].acceleration);
  CHECK(!xEdgeValid && xMoveId==2);
  seekUntil(13); CHECK(xHomeOffset==-27);
  // A bouncing edge pauses immediately, but does not publish a false capture.
  fakePins[21]=LOW; for(unsigned t=0;t<10;++t) edgeTick();
  const unsigned paused=fakePulses;
  CHECK(xEdge.active() && !xEdgeValid);
  fakePins[21]=HIGH; seekUntil(1); CHECK(fakePulses==paused+1);
  const int32_t capturedOffset=xHomeOffset;
  detect();
  CHECK(xEdge.stage==EdgeSearch::Stage::Found && xEdgeValid && !outputsArmed && !xRemaining);
  CHECK(xPositionKnown && xHomeOffset==capturedOffset && fakePins[40]==LOW);
  CHECK(xEdgeMilli==carriage::Positioning::milliForOffset(capturedOffset));
  CHECK(xTruingMilli==xEdgeMilli-10800-250 && xTruingMilli>0);
  CHECK(Serial.outgoing.find("EDGE_VALID:1")!=std::string::npos);
  for(unsigned t=0;t<1000;++t) edgeTick();
  CHECK(fakePulses==paused+1 && !outputsArmed); // never auto-advance or operate valves
  for(unsigned i=0;i<3;++i) CHECK(!outputStates[i]);
  command("XARM 1"); fakeTime+=200;
  CHECK(xEdgeValid);
  command("XTRUING "+std::to_string(xMoveId-1));
  CHECK(xEdgeValid && !xRemaining);
  command("XTRUING "+std::to_string(xMoveId));
  CHECK(xAbsoluteMove && !xEdgeValid);
  command("OFF");

  // Any count/position invalidation, stop, sensor clearance or intervening move
  // prevents the previous capture from remaining a fresh truing proposal.
  for (int cause=0;cause<4;++cause) {
    edgeReady(); command("XEDGE 13 10800 250"); seekUntil(1); detect(); CHECK(xEdgeValid);
    if(cause==0) { fakePins[21]=HIGH; loop(); }
    if(cause==1) command("OFF");
    if(cause==2) command("XDISABLE");
    if(cause==3) { command("XARM 1"); fakeTime+=200; command("XJOG -1 1"); }
    CHECK(!xEdgeValid);
  }
  // The final allowed pulse may cause detection; no extra pulse is needed.
  edgeReady(); command("XEDGE 1 10800 250"); seekUntil(1); detect();
  CHECK(xEdgeValid && !outputsArmed && xEdge.sent==1);
  edgeReady(); command("XEDGE 1 10800 250"); seekUntil(1);
  for(unsigned t=0;t<60;++t) edgeTick();
  CHECK(interlocks.fault==bench::Fault::EdgeFailed && !outputsArmed && !xPositionKnown);
  CHECK(std::string(xEdge.error)=="NOT_FOUND");
  edgeReady(); command("XEDGE 13 160500 0"); seekUntil(1); detect();
  CHECK(xEdge.stage==EdgeSearch::Stage::Found && !xEdgeValid && xPositionKnown && !outputsArmed);
  CHECK(std::string(xEdge.error)=="TARGET_OUT_OF_RANGE");

  for (int cause=0;cause<6;++cause) {
    edgeReady(); command("XEDGE 254 10800 250"); seekUntil(1);
    if(cause==0) command("OFF");
    if(cause==1) { fakePins[29]=HIGH; loop(); }
    if(cause==2) { fakePins[14]=LOW; loop(); }
    if(cause==3) { fakeTime+=1500; loop(); }
    if(cause==4) { fakePins[20]=LOW; loop(); }
    if(cause==5) { fakePins[22]=HIGH; loop(); }
    const unsigned stopped=fakePulses;
    for(unsigned t=0;t<200;++t) edgeTick();
    CHECK(!outputsArmed && !xRemaining && !xEdge.active() && !xEdgeValid && fakePulses==stopped);
    CHECK(cause==0 ? xPositionKnown : !xPositionKnown);
  }
  edgeReady(); command("XEDGE 254 10800 250");
  const uint32_t id=xMoveId;
  command("XJOG -1 13"); command("XMOVE 135000"); command("OUT 1 1");
  CHECK(testMode==TestMode::Edge && xMoveId==id && !outputStates[1]);
  xHomeOffset=carriage::Positioning::MinOffset; fakeTime+=100; loop();
  CHECK(interlocks.fault==bench::Fault::SoftLimit && !outputsArmed && !xPositionKnown);

  edgeReady(); xHomeOffset=carriage::Positioning::MinOffset+10;
  command("XEDGE 11 10800 250"); CHECK(!xRemaining && xPositionKnown);
  const char *bad[]={"XEDGE 0 10800 250", "XEDGE 20595 10800 250", "XEDGE 13 -1 250",
                     "XEDGE 13 10800 -1", "XEDGE 13 10800 250 EXTRA"};
  for(const char *c:bad) { edgeReady(); const unsigned n=fakePulses; command(c);
    CHECK(!outputsArmed && !xRemaining && !xPositionKnown && fakePulses==n); }
  printf("Board-edge search and truing proposal: %u checks passed\n",checks);
}
