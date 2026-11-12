#include "controller_fixture.h"
void advanceDry(unsigned ms, bool heartbeat=true) {
  while (ms--) { ++fakeTime; if (heartbeat && fakeTime%200==0) command("KEEPALIVE"); else loop(); }
}
void configDry() {
  const unsigned values[] = {10,10,20,10,10,10,1000,20,10,1000,20,10,30,10,40};
  for (unsigned i=0;i<15;++i) command("DSET "+std::to_string(i)+" "+std::to_string(values[i]));
  command("DCOMMIT 23"); CHECK(dry.configId==23 && !dry.armed);
}
void clampDry() {
  configDry(); command("DARM 23"); CHECK(dry.armed && !dry.clamp && !dry.saw);
  command("DCLAMP 1"); advanceDry(60); CHECK(dry.phase==unloaded::DryRun::Clamped);
  CHECK(fakePins[32]==HIGH && fakePins[33]==LOW && fakePins[19]==LOW);
}
void descendDry() {
  command("DCYCLE"); advanceDry(15); CHECK(dry.saw && dry.clamp);
  fakePins[22]=HIGH; advanceDry(30); CHECK(!dry.failed());
}
int main() {
  restart(); CHECK(Serial.outgoing.find("DRY_RUN:UNLOADED_V5,BLADE_LOCK:UNPLUGGED_CYCLE,TRIGGER_TEST:HOLD_V1,CYCLE:CLAMP_TRIGGER_TRAVEL_V1")!=std::string::npos);
  command("DARM 23"); CHECK(!dry.armed);
  command("DSET 0 10"); command("DCOMMIT 23"); CHECK(!dry.configId);
  command("DSET 42949672960 0"); CHECK(!dry.configId);
  command("DSET 0 42949672960"); CHECK(!dry.configId);
  command("DSET -1 0"); command("DSET 6 0"); CHECK(!dry.configId);
  command("ARM 1"); command("OUT 2 1"); CHECK(fakePins[19]==LOW && !outputStates[2]); command("OFF");
  clampDry(); const unsigned id=dry.requestId;
  command("XARM 1"); command("XJOG 1 13"); command("XHOME 254"); command("OUT 1 0");
  CHECK(dry.clamp && dry.requestId==id && fakePulses==0 && xRemaining==0);
  command("DSET 0 0"); CHECK(dry.configId==23);
  descendDry(); command("DCLAMP 0"); CHECK(dry.clamp);
  fakePins[16]=LOW; advanceDry(25); CHECK(!dry.failed());
  advanceDry(40); CHECK(!dry.saw && dry.clamp && dry.phase==unloaded::DryRun::Returning);
  fakePins[16]=HIGH; fakePins[22]=LOW; advanceDry(55);
  CHECK(dry.phase==unloaded::DryRun::Clamped && dry.armed && dry.clamp && !dry.saw);
  command("DCLAMP 0"); advanceDry(30); CHECK(!dry.clamp && dry.phase==unloaded::DryRun::Ready);
  command("DOFF"); CHECK(!dry.active() && !dry.armed && fakePins[19]==LOW);
  restart(); clampDry(); descendDry(); command("DOFF");
  CHECK(!dry.armed && !dry.saw && dry.clamp && dry.phase==unloaded::DryRun::StopReturn);
  command("XARM 1"); CHECK(!outputsArmed && fakePulses==0);
  fakePins[22]=LOW; advanceDry(50); CHECK(dry.phase==unloaded::DryRun::Stopped && dry.clamp);
  command("DRELEASE"); CHECK(!dry.clamp && dry.phase==unloaded::DryRun::Off);
  restart(); clampDry(); descendDry(); advanceDry(1100);
  CHECK(dry.failed() && std::string(dry.fault)=="DRY_DOWN_TIMEOUT" && dry.clamp && !dry.saw);
  command("RESET"); CHECK(dry.failed());
  fakePins[22]=LOW; advanceDry(50); command("RESET"); CHECK(dry.failed() && dry.clamp);
  command("DRELEASE"); command("RESET"); CHECK(!dry.failed() && !dry.armed && !dry.clamp);
  restart(); clampDry(); descendDry(); fakePins[16]=LOW; advanceDry(70);
  CHECK(dry.phase==unloaded::DryRun::Returning);
  fakePins[16]=HIGH; advanceDry(1100);
  CHECK(dry.failed() && std::string(dry.fault)=="DRY_UP_TIMEOUT");
  for (unsigned event=0;event<4;++event) {
    restart(); clampDry(); descendDry();
    if (event==0) fakePins[29]=HIGH;
    if (event==1) fakePins[14]=LOW;
    if (event==2) { fakePins[22]=LOW; fakePins[16]=LOW; }
    if (event==3) { Serial.txRoom=0; advanceDry(1600,false); }
    loop(); CHECK(dry.failed() && !dry.armed && dry.clamp && !dry.saw);
    CHECK(fakePins[33]==LOW && fakePins[32]==HIGH && fakePins[19]==LOW);
    command("KEEPALIVE"); CHECK(!dry.armed);
  }
  restart(); clampDry(); advanceDry(60010); CHECK(dry.failed() && std::string(dry.fault)=="DRY_CLAMP_MAX_ON");
  restart(); clampDry(); command("DDOWN"); advanceDry(15); fakePins[22]=HIGH; fakePins[16]=LOW; advanceDry(30);
  CHECK(dry.phase==unloaded::DryRun::Down);
  fakePins[16]=HIGH; loop(); CHECK(dry.failed() && std::string(dry.fault)=="DRY_POSITION_LOST");
  restart(); configDry(); fakeTime=UINT32_MAX-30;
  command("DARM 23"); command("DCLAMP 1"); advanceDry(80);
  CHECK(dry.clamp && dry.phase==unloaded::DryRun::Clamped && !dry.failed());
  // Manual session permission is distinct from Auto arm; hold loss releases.
  restart(); command("DTPRESS"); command("DTHOLD"); CHECK(!dry.manualMode && fakePins[19]==LOW);
  configDry(); command("DARM 23"); command("DTPRESS"); CHECK(fakePins[19]==LOW && !dry.manualMode);
  command("DOFF"); command("DMANUAL 23"); CHECK(dry.manualMode && !dry.trigger && fakePins[19]==LOW);
  advanceDry(11000); CHECK(dry.armed && dry.manualMode && !dry.failed());
  command("DTPRESS"); CHECK(dry.trigger && fakePins[19]==HIGH && fakePins[33]==LOW && fakePins[32]==LOW);
  command("DCLAMP 1"); CHECK(!dry.clamp && dry.phase==unloaded::DryRun::Ready);
  command("XARM 1"); command("XJOG 1 13"); CHECK(xRemaining==0 && fakePulses==0);
  for (unsigned i=0;i<40;++i) { command("DTHOLD"); advanceDry(100); }
  CHECK(dry.trigger && fakePins[19]==HIGH && !dry.failed());
  advanceDry(360); CHECK(!dry.trigger && dry.manualMode && fakePins[19]==LOW && !dry.failed());
  command("DTHOLD"); CHECK(fakePins[19]==LOW); // a late hold cannot restart it
  command("DTPRESS"); CHECK(fakePins[19]==HIGH); // new deliberate press, no rearm
  command("DTRELEASE"); CHECK(fakePins[19]==LOW && dry.manualMode && dry.armed);
  command("DCLAMP 1"); advanceDry(60); CHECK(dry.clamp);
  command("DTPRESS"); command("DCYCLE"); command("DDOWN"); command("DCLAMP 0");
  CHECK(dry.phase==unloaded::DryRun::Clamped && !dry.saw && dry.clamp);
  command("DTRELEASE"); command("DCYCLE"); advanceDry(15); CHECK(dry.saw);
  command("DTPRESS"); CHECK(fakePins[19]==LOW);
  for (unsigned event=0;event<5;++event) {
    restart(); configDry(); command("DMANUAL 23"); command("DTPRESS");
    if (event==0) fakePins[29]=HIGH;
    if (event==1) fakePins[14]=LOW;
    if (event==2) fakePins[22]=HIGH;
    if (event==3) fakePins[16]=LOW;
    if (event==4) { Serial.txRoom=0; advanceDry(1510,false); }
    loop(); CHECK(dry.failed() && !dry.trigger && !dry.manualMode && fakePins[19]==LOW);
    command("KEEPALIVE"); command("DTPRESS"); CHECK(fakePins[19]==LOW && !dry.armed);
    command("DTRELEASE"); CHECK(fakePins[19]==LOW);
  }
  restart(); configDry(); fakeTime=UINT32_MAX-30;
  command("DMANUAL 23"); command("DTPRESS"); advanceDry(360);
  CHECK(!dry.trigger && dry.manualMode && !dry.failed() && fakePins[19]==LOW);
  command("DTPRESS"); command("OFF"); CHECK(!dry.manualMode && !dry.trigger && fakePins[19]==LOW);
  restart(); CHECK(!dry.manualMode && fakePins[19]==LOW);
  // Full firmware-owned clamp -> trigger -> travel -> brake -> release.
  restart(); configDry(); command("DARM 23"); command("DCUT");
  CHECK(dry.cycleRunning && !dry.clamp && !dry.trigger && dry.phase==unloaded::DryRun::ClampDelay);
  for (unsigned i=0;i<200 && dry.phase!=unloaded::DryRun::Spinup;++i) advanceDry(1);
  CHECK(dry.clamp && dry.trigger && !dry.saw);
  advanceDry(15); CHECK(!dry.saw && dry.trigger);
  for (unsigned i=0;i<100 && !dry.saw;++i) advanceDry(1);
  CHECK(dry.saw && dry.trigger && dry.clamp);
  fakePins[22]=HIGH; advanceDry(400); CHECK(dry.trigger && !dry.failed()); // not a manual hold lease
  fakePins[16]=LOW;
  for (unsigned i=0;i<200 && dry.saw;++i) advanceDry(1);
  CHECK(!dry.saw && dry.trigger && dry.clamp);
  fakePins[16]=HIGH; fakePins[22]=LOW;
  for (unsigned i=0;i<200 && dry.phase!=unloaded::DryRun::BrakeWait;++i) advanceDry(1);
  CHECK(!dry.trigger && dry.clamp && dry.cycleRunning);
  advanceDry(20); CHECK(dry.clamp); // brake wait precedes release
  for (unsigned i=0;i<200 && dry.cycleRunning;++i) advanceDry(1);
  CHECK(dry.completed==1 && dry.phase==unloaded::DryRun::Ready && !dry.clamp && !dry.trigger && dry.armed);
  command("DCUT"); advanceDry(60); CHECK(dry.clamp && dry.trigger);
  command("OFF"); CHECK(dry.clamp && !dry.trigger && !dry.cycleRunning && !dry.armed);
  command("DRELEASE"); CHECK(dry.clamp); // explicit release must also wait brake interval
  advanceDry(50); command("DRELEASE"); CHECK(!dry.clamp);
  // Stop/guard/watchdog at every triggered phase retains material and releases trigger.
  const unloaded::DryRun::Phase phases[]={unloaded::DryRun::Spinup,unloaded::DryRun::Descend,
      unloaded::DryRun::Dwell,unloaded::DryRun::Returning,unloaded::DryRun::BrakeWait};
  for (auto phase:phases) for (unsigned cause=0;cause<3;++cause) {
    restart(); configDry(); command("DARM 23"); command("DCUT");
    for (unsigned i=0;i<2000 && dry.phase!=phase;++i) {
      fakePins[22]=dry.saw ? HIGH:LOW; fakePins[16]=dry.saw ? LOW:HIGH; advanceDry(1);
    }
    CHECK(dry.phase==phase && dry.clamp);
    if (cause==0) command("OFF");
    if (cause==1) { fakePins[29]=HIGH; loop(); }
    if (cause==2) { fakeTime+=1510; loop(); }
    CHECK(dry.clamp && !dry.trigger && !dry.saw && !dry.armed && !dry.cycleRunning);
    CHECK(fakePins[32]==HIGH && fakePins[19]==LOW && fakePins[33]==LOW);
    command("KEEPALIVE"); command("DCUT"); CHECK(!dry.cycleRunning && fakePins[19]==LOW);
  }
  // Individual unplugged Manual travel does not energize an unrelated clamp.
  restart();configDry();command("DMANUAL 23");CHECK(dry.manualMode && !dry.clamp);
  command("DDOWN");advanceDry(20);CHECK(dry.saw && !dry.clamp && !dry.cycleRunning);
  fakePins[22]=HIGH;fakePins[16]=LOW;advanceDry(30);
  CHECK(dry.phase==unloaded::DryRun::Down && !dry.clamp);
  command("DUP");fakePins[16]=HIGH;fakePins[22]=LOW;advanceDry(60);
  CHECK(dry.phase==unloaded::DryRun::Ready && !dry.saw && !dry.clamp);
  command("DOFF");CHECK(!dry.armed);
  printf("Unloaded dry-run sketch: %u checks passed\n",checks);
}
