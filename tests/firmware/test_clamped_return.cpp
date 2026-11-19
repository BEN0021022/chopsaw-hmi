#include "controller_fixture.h"
void waitReturn(unsigned ms,bool beat=true,bool endpoints=true) {
  while(ms--) {
    ++fakeTime;
    if(endpoints) {fakePins[22]=dry.saw ? HIGH:LOW;fakePins[16]=dry.saw ? LOW:HIGH;}
    if(beat && fakeTime%200==0)command("KEEPALIVE");else loop();
  }
}
void readyReturn(bool second=true) {
  restart();command("XCONFIG 0 1");xPositionKnown=true;xHomeOffset=-19000;xSoftMaxOffset=-14;
  const unsigned values[]={10,10,20,10,10,10,1500,1000,10,1500,20,10,30,10,40,second ? 1u:0u,80,90,70,60};
  for(unsigned i=0;i<20;++i)command("DSET "+std::to_string(i)+" "+std::to_string(values[i]));
  command("DCOMMIT 26");command("DARM 26");CHECK(dry.armed && !outputsArmed);
}
void automaticReturn(unsigned mask,int32_t target=-14) {
  command("DCUTRET 26 "+std::to_string(dry.requestId+1)+" "+std::to_string(mask)+" "+
          std::to_string(carriage::Positioning::milliForOffset(target))+" 10500");
}
int main() {
  for(unsigned mask=1;mask<=3;++mask) for(unsigned order=0;order<2;++order) {
    readyReturn();const unsigned pulses=fakePulses;automaticReturn(mask,order ? -18980:-14);
    CHECK(xReturnPending && dry.cycleRunning && !outputsArmed && fakePulses==pulses);
    waitReturn(20);CHECK(fakePulses==pulses);
    unsigned overlap=0;bool cutFirst=false,returnFirst=false;
    for(unsigned i=0;i<25000 && (dry.cycleRunning || xReturnPending || outputsArmed);++i) {
      const unsigned before=fakePulses;waitReturn(1);
      CHECK(!dry.failed() && interlocks.fault==bench::Fault::None);
      if(fakePulses>before && dry.saw) {++overlap;CHECK(dry.heldMask==mask && !xReturnPending && xDirection==1);}
      if(dry.completed && xRemaining)cutFirst=true;
      if(!xReturnPending && !xRemaining && dry.cycleRunning)returnFirst=true;
      CHECK((mask&1) || !fakePins[32]);CHECK((mask&2) || !fakePins[18]);
    }
    CHECK(overlap>0 && dry.completed==1 && !xRemaining && !outputsArmed && !dry.clamp);
    CHECK(order ? returnFirst:cutFirst);
    const unsigned done=dry.completed;automaticReturn(mask);CHECK(dry.completed==done && !dry.cycleRunning);
  }
  // Binding, target direction, disabled mask and boundary rejection.
  readyReturn(false);automaticReturn(2);CHECK(!xReturnPermit && !dry.cycleRunning);
  const std::string next=std::to_string(dry.requestId+1);
  command("DCUTRET 25 "+next+" 1 160389 10500");CHECK(!xReturnPermit && !dry.cycleRunning);
  command("DCUTRET 26 0 1 160389 10500");CHECK(!xReturnPermit && !dry.cycleRunning);
  command("DCUTRET 26 "+next+" 1 10000 10500");CHECK(!xReturnPermit && !dry.cycleRunning);
  command("DCUTRET 26 "+next+" 1 160389 12000");CHECK(!xReturnPermit && !dry.cycleRunning);
  fakePins[20]=LOW;automaticReturn(1);CHECK(!xReturnPermit && !dry.cycleRunning);
  for(unsigned event=0;event<8;++event) {
    readyReturn();automaticReturn(2);waitReturn(500);CHECK(xRemaining && dry.cycleRunning);
    if(event==0)command("OFF");
    if(event==1)fakePins[29]=HIGH;
    if(event==2)fakePins[14]=LOW;
    if(event==3)fakeTime+=1600;
    if(event==4) {fakePins[22]=LOW;fakePins[16]=LOW;}
    if(event==5) {dry.heldMask=0;dry.clamp=false;}
    if(event==6) {fakePins[22]=HIGH;fakePins[16]=HIGH;waitReturn(1600,true,false);}
    if(event==7)command("DTRELEASE");
    loop();const unsigned stopped=fakePulses;waitReturn(50);
    CHECK(!xReturnPermit && !xReturnPending && !outputsArmed && !xRemaining && !dry.cycleRunning && !fakePins[19]);
    CHECK(stopped==fakePulses);
    if(event==1 || event==4) CHECK(xPositionKnown);  // controlled door/endpoint stop
    if(event==2 || event==3 || event==5) CHECK(!xPositionKnown);  // drive, watchdog, holding loss
  }
  readyReturn();automaticReturn(2);command("OFF");waitReturn(400);
  CHECK(!xReturnPermit && !xReturnPending && !xRemaining && !fakePulses);
  readyReturn();automaticReturn(2);command("DTRELEASE");waitReturn(400);
  CHECK(!xReturnPermit && !xReturnPending && !xRemaining && !fakePulses);
  printf("Clamped last-cut return: %u checks passed\n",checks);
}
