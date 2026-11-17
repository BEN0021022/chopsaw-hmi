#include "homing_fixture.h"
void tick(unsigned count=1) {
  while(count--) {++fakeTime;if(fakeTime%200==0)command("KEEPALIVE");else loop();}
}
void acquireReady() {
  homeStart();runHome();command("XPROFILE 1 600 600");command("XARM 1");tick(210);
  command("XACQUIRE 1000 10800 120");CHECK(testMode==TestMode::Acquisition);
  for(unsigned i=0;xEdge.sent<400 && i<10000;++i)tick();
  CHECK(xEdge.sent>=400);
}
void returnReady() {
  restart();command("XCONFIG 0 1");xPositionKnown=true;xSoftMaxOffset=-14;xHomeOffset=-19000;
  const unsigned values[]={10,10,20,10,10,10,1000,20,10,1000,20,10,30,10,40};
  for(unsigned i=0;i<15;++i)command("DSET "+std::to_string(i)+" "+std::to_string(values[i]));
  command("DCOMMIT 25");command("XARM 1");tick(210);command("XRETURN 160389 1000");
  CHECK(xReturnPermit && xRemaining && xDirection==1 && xProfile==3);
}
void beginReturnCut() {
  command("DRETURN 25 "+std::to_string(dry.requestId+1)+" "+std::to_string(xMoveId));
  CHECK(dry.operatorCycle && dry.cycleRunning && xReturnCutUsed && outputsArmed);
}
int main() {
  acquireReady();const int32_t first=xHomeOffset;fakePins[21]=LOW;
  command("OUT 1 1");CHECK(!fakePins[32]);
  const unsigned before=fakePulses;tick(25);
  CHECK(fakePulses>before && xEdgeValid && outputsArmed && xRemaining);
  CHECK(xEdgeMilli==carriage::Positioning::milliForOffset(first));
  CHECK(xTruingMilli==xEdgeMilli-10920);
  CHECK(xTiming.maxLate<6000); // no 20ms qualification pause/re-enable
  int32_t target=0;CHECK(carriage::Positioning::target(xTruingMilli,xSoftMaxOffset,target));
  for(unsigned i=0;outputsArmed && i<10000;++i) {tick();CHECK(!fakePins[32] && !fakePins[18] && !fakePins[33] && !fakePins[19]);}
  CHECK(!outputsArmed && !xRemaining && xHomeOffset==target && xEdgeValid && xContinuousAcquire);
  // Bounce continues motion, then captures the final qualified raw edge.
  acquireReady();fakePins[21]=LOW;tick(5);const unsigned moving=fakePulses;
  fakePins[21]=HIGH;tick(10);CHECK(fakePulses>moving && !xEdgeValid);
  const int32_t second=xHomeOffset;fakePins[21]=LOW;tick(25);
  CHECK(xEdgeValid && xEdgeMilli==carriage::Positioning::milliForOffset(second));
  command("OFF");CHECK(!xContinuousAcquire && !xRemaining);
  // Positive return can overlap exactly one explicit clamp-inhibited cut.
  returnReady();const uint32_t req=dry.requestId;
  command("DRETURN 25 "+std::to_string(req+1)+" "+std::to_string(xMoveId+1));CHECK(!dry.cycleRunning);
  beginReturnCut();unsigned overlap=0;
  const int32_t returnTarget=xTargetOffset;
  command("XMOVE 1000");command("DCLAMP 1");
  CHECK(xDirection==1 && xTargetOffset==returnTarget && !dry.clamp);
  for(unsigned i=0;(outputsArmed || dry.cycleRunning) && i<25000;++i) {
    const int32_t old=xCommandedSteps;fakePins[22]=dry.saw ? HIGH:LOW;fakePins[16]=dry.saw ? LOW:HIGH;tick();
    CHECK(!dry.failed() && interlocks.fault==bench::Fault::None && !fakePins[32] && !fakePins[18]);
    if (fakePins[19] && xCommandedSteps>old)++overlap;
  }
  CHECK(overlap>0 && !outputsArmed && xHomeOffset==-14 && dry.completed==1 && !dry.cycleRunning);
  command("DRETURN 25 "+std::to_string(dry.requestId+1)+" "+std::to_string(xMoveId));CHECK(dry.completed==1 && !dry.cycleRunning);
  for(unsigned cause=0;cause<7;++cause) {
    returnReady();beginReturnCut();tick(15);
    if(cause==0)command("OFF");
    if(cause==1)fakePins[29]=HIGH;
    if(cause==2)fakePins[14]=LOW;
    if(cause==3)fakeTime+=1600;
    if(cause==4)fakePins[21]=LOW;
    if(cause==5) {fakePins[22]=LOW;fakePins[16]=LOW;}
    if(cause==6) {tick(80);fakePins[22]=HIGH;fakePins[16]=HIGH;tick(1100);}
    loop();const unsigned stopped=fakePulses;tick(100);
    CHECK(!xRemaining && !outputsArmed && !dry.cycleRunning && !fakePins[19] && !fakePins[33]);
    CHECK(!xReturnPermit && fakePulses==stopped);
  }
  printf("Continuous acquisition / return-cut sketch: %u checks passed\n",checks);
}
