#include "controller_fixture.h"
void waitDry(unsigned ms,bool heartbeat=true) {
  while(ms--) { ++fakeTime;if(heartbeat && fakeTime%200==0)command("KEEPALIVE");else loop(); }
}
void configureSecond(bool enabled=true) {
  const unsigned values[]={10,10,20,10,10,10,1000,20,10,1000,20,10,30,10,40,enabled ? 1u:0u,80,90,70,60};
  for(unsigned i=0;i<20;++i)command("DSET "+std::to_string(i)+" "+std::to_string(values[i]));
  command("DCOMMIT 24");CHECK(dry.configId==24 && !dry.armed && fakePins[18]==LOW);
}
void cut(unsigned mask) {
  command("DCUTM 24 "+std::to_string(dry.requestId+1)+" "+std::to_string(mask));
}
void finishStroke() {
  CHECK(dry.saw);fakePins[22]=HIGH;waitDry(30);fakePins[16]=LOW;waitDry(80);
  CHECK(!dry.saw && dry.clamp);fakePins[16]=HIGH;fakePins[22]=LOW;waitDry(250);
  CHECK(dry.phase==unloaded::DryRun::Ready && dry.completed==1 && !dry.clamp);
  CHECK(!fakePins[32] && !fakePins[18] && !fakePins[19]);
}
int main() {
  restart();CHECK(!dry.secondEnabled() && fakeModes[18]==OUTPUT && fakePins[18]==LOW);
  CHECK(Serial.outgoing.find("SECOND_CLAMP:D18_MASK_V1")!=std::string::npos);
  command("ARM 1");command("OUT 3 1");CHECK(fakePins[18]==LOW);command("OFF");command("RESET");
  configureSecond(false);command("DMANUAL 24");command("DCLAMP2 1");CHECK(!dry.clamp && !fakePins[18]);
  cut(2);CHECK(!dry.cycleRunning && !fakePins[32] && !fakePins[18]);
  command("DOFF");configureSecond();command("DMANUAL 24");
  command("DCLAMP 1");waitDry(50);CHECK(dry.mainClamp() && !dry.secondClamp());
  command("DCLAMP2 1");waitDry(60);CHECK(dry.mainClamp() && !dry.secondClamp());
  waitDry(40);CHECK(dry.secondClamp() && dry.phase==unloaded::DryRun::ClampSettle);
  command("DCLAMP 0");CHECK(dry.mainClamp()); // no mutation during settle
  waitDry(90);CHECK(dry.phase==unloaded::DryRun::Clamped && dry.heldMask==3);
  command("DCLAMP2 0");waitDry(50);CHECK(dry.heldMask==3);
  waitDry(30);CHECK(dry.heldMask==1);waitDry(60);CHECK(dry.phase==unloaded::DryRun::Clamped);
  command("DCLAMP 0");waitDry(30);CHECK(!dry.clamp && dry.phase==unloaded::DryRun::Ready);
  command("DOFF");command("DARM 24");
  const uint32_t req=dry.requestId;
  command("DCUTM 25 "+std::to_string(req+1)+" 2");command("DCUTM 24 "+std::to_string(req)+" 2");
  command("DCUTM 24 "+std::to_string(req+1)+" 258");
  CHECK(dry.requestId==req && !dry.cycleRunning && !fakePins[18]);
  cut(3);waitDry(30);CHECK(dry.mainClamp() && !dry.secondClamp() && !dry.trigger);
  waitDry(80);CHECK(dry.secondClamp() && !dry.trigger);
  waitDry(140);CHECK(dry.trigger && dry.saw && dry.heldMask==3);finishStroke();
  // Outfeed-only holding must never energize the main clamp.
  command("DOFF");command("DARM 24");cut(2);
  for(unsigned i=0;i<260;++i) {waitDry(1);CHECK(fakePins[32]==LOW);}
  CHECK(dry.secondClamp() && dry.saw && !dry.mainClamp());
  command("DSET 15 0");CHECK(dry.secondEnabled() && dry.secondClamp());
  fakePins[22]=HIGH;waitDry(30);fakePins[16]=LOW;waitDry(80);fakePins[16]=HIGH;fakePins[22]=LOW;waitDry(250);
  CHECK(dry.completed==2 && !dry.clamp && !fakePins[18] && !fakePins[32]);
  // Stop/fault/watchdog retain either engaged clamp until guarded release.
  for(unsigned mask=2;mask<=3;++mask) for(unsigned event=0;event<4;++event) {
    restart();configureSecond();command("DMANUAL 24");
    if(mask==3) {command("DCLAMP 1");waitDry(50);}
    command("DCLAMP2 1");waitDry(200);
    CHECK(dry.heldMask==mask && fakePins[18]==HIGH);
    command("XCONFIG 0 1");command("XARM 1");CHECK(!outputsArmed && fakePulses==0);
    if(event==0)command("DOFF");
    if(event==1) {fakePins[29]=HIGH;loop();}
    if(event==2) {fakePins[14]=LOW;loop();}
    if(event==3)waitDry(1600,false);
    CHECK(!dry.armed && dry.heldMask==mask && fakePins[18]==HIGH && fakePins[32]==static_cast<int>(mask&1) && !fakePins[19]);
    fakePins[29]=LOW;fakePins[14]=HIGH;waitDry(70);command("DRELEASE");
    CHECK(!dry.clamp && !fakePins[18]);command("RESET");CHECK(!dry.failed());
  }
  restart();configureSecond();fakeTime=UINT32_MAX-30;command("DMANUAL 24");command("DCLAMP2 1");waitDry(200);
  CHECK(dry.secondClamp() && !dry.failed());waitDry(60010);
  CHECK(dry.failed() && std::string(dry.fault)=="DRY_CLAMP_MAX_ON" && fakePins[18]==HIGH);
  restart();CHECK(!dry.secondEnabled() && !fakePins[18]);
  command("DSET 0 0");command("DSET 15 2");command("DCOMMIT 88");CHECK(!dry.configId);
  printf("Second clamp actual sketch: %u checks passed\n",checks);
}
