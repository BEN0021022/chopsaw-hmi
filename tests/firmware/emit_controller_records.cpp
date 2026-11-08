#include "homing_fixture.h"

// Emit actual sketch serial records for the Python panel contract test.
int main() {
  homeStart(); runHome(); command("XPROFILE 2"); command("XARM 1"); fakeTime+=200;
  command("XEDGE 254 10800 250");
  for(unsigned n=0;n<400;++n) stepHome();
  fakePins[21]=LOW;
  for(unsigned n=0;n<25;++n) stepHome();
  CHECK(xEdgeValid && xPositionKnown && !outputsArmed);
  command("XARM 1"); fakeTime+=200;
  command("XTRUING "+std::to_string(xMoveId));
  CHECK(xAbsoluteMove && !xEdgeValid);
  printf("%s",Serial.outgoing.c_str());
}
