// Interactive actual-sketch harness for Qt end-to-end tests. Never uses a port.
#include "controller_fixture.h"
#include <iostream>

int world = -50;
bool valve = false;
uint32_t valveAt = 0;
unsigned strokes = 0;
bool automaticSensor=false, materialContact=false;
double materialRear=0, detectorPosition=10.8;

void physics() {
  fakePins[20] = world >= 0 ? LOW : HIGH;
  const bool on = fakePins[33] == HIGH;
  if (on != valve) { valve = on; valveAt = fakeTime; if (on) ++strokes; }
  const uint32_t elapsed = fakeTime - valveAt;
  fakePins[22] = !valve && elapsed >= 200 ? LOW : HIGH;
  fakePins[16] = valve && elapsed >= 200 ? LOW : HIGH;
  if (automaticSensor) fakePins[21]=materialRear>=detectorPosition ? LOW:HIGH;
}

void step() {
  const int32_t before = xCommandedSteps;
  ++fakeTime; physics(); loop();
  world += xCommandedSteps - before;
  if (automaticSensor && materialContact) {
    const int delta=xCommandedSteps-before;
    if (delta>0) materialContact=false;
    else materialRear+=delta/127.12;
  }
  CHECK(!fakePins[19] || (dry.armed && dry.trigger && (dry.cycleRunning || dry.manualMode) &&
                        fakePins[29]==LOW && fakePins[14]==HIGH));
  CHECK(!dry.cycleRunning || !fakePins[19] || fakePins[32]);
  CHECK(!fakePins[19] || xCommandedSteps == before);
  CHECK(!fakePins[33] || fakePins[32]);
  CHECK(!fakePins[32] || xCommandedSteps == before);
}

int main() {
  restart(); valveAt = 0; physics();
  for (unsigned i=0;i<220;++i) step();
  publishStatus();
  std::cout << Serial.outgoing << "@END\n" << std::flush;
  Serial.outgoing.clear();
  std::string line;
  while (std::getline(std::cin,line)) {
    if (line.rfind("@TICK ",0)==0) {
      unsigned count=static_cast<unsigned>(std::stoul(line.substr(6)));
      for (unsigned i=0;i<count;++i) step();
    } else if (line.rfind("@SENSOR_ZONE ",0)==0) {
      detectorPosition=std::stod(line.substr(13)); physics(); publishStatus();
    } else if (line=="@AUTO_SENSOR 1") {
      automaticSensor=materialContact=true;
      materialRear=carriage::Positioning::milliForOffset(xHomeOffset)/1000.0;
      physics(); publishStatus();
    } else if (line=="@AUTO_SENSOR 0") {
      automaticSensor=materialContact=false; fakePins[21]=HIGH; publishStatus();
    } else if (line.rfind("@PIN ",0)==0) {
      int pin=0,value=0;
      if (sscanf(line.c_str(),"@PIN %d %d",&pin,&value)==2 && pin>=0 && pin<64) fakePins[pin]=value;
      loop(); publishStatus();
    } else {
      Serial.incoming += line + '\n';
      step();
    }
    std::cout << Serial.outgoing;
    Serial.outgoing.clear();
    std::cout << "@WORLD," << world << ',' << strokes << ',' << fakePulses << ',' << fakeTime << '\n';
    std::cout << "@END\n" << std::flush;
  }
}
