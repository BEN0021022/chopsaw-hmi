/*
  Chop Saw Controller - Teensy 4.1 / T41U5XBB V2.20

  Input commissioning firmware plus three guarded, momentary pneumatic outputs.
  X diagnostics emit bounded, interruptible pulse jogs. Pneumatic outputs boot OFF, require an explicit arm and
  host keepalive, and shut off on communications or maximum-on timeout.

  I2C header: Wire2, SDA D25, SCL D24, 3.3 V logic.
*/

#include <Arduino.h>
#include <Wire.h>
#include "bench_interlocks.h"
#include "homing.h"
#include "positioning.h"
#include "motion_profile.h"
#include "edge_search.h"
#include "dry_run.h"

namespace {

constexpr char FIRMWARE_VERSION[] = "0.17.0";
constexpr uint8_t PROTOCOL_VERSION = 2;
constexpr uint8_t MCP_ADDRESS = 0x27;
constexpr uint8_t INA_ADDRESS = 0x40;

constexpr uint8_t HOME_PIN = 20;          // Limit X
constexpr uint8_t BOARD_EDGE_PIN = 21;    // Limit Y (Probe D15 intentionally unused)
constexpr uint8_t FENCE_DOOR_PIN = 29;    // Door
constexpr uint8_t CL57T_ALARM_PIN = 14;   // Halt
constexpr uint8_t SAW_UP_PIN = 22;        // Limit Z opto input; Cyc/St and ST0 deferred
constexpr uint8_t SAW_DOWN_PIN = 16;      // Fd/Hld opto input; ST1 path unverified
constexpr uint8_t FENCE_CLOSED_PIN = 34;  // ST2
constexpr uint8_t OUTFEED_PIN = 35;       // ST3
constexpr uint8_t X_STEP_PIN = 2;
constexpr uint8_t X_DIR_PIN = 3;
constexpr uint8_t X_ENABLE_PIN = 40;  // Axis Y En; suspect Axis X En/D10 unused

// Commissioning map: AUX2=saw travel, AUX1=main left clamp, Flood=blade-trigger
// valve. AUX0/D31 is retired pending investigation. Use JP10 TTL Sig/Gnd rows,
// not the open-collector screw terminals. Test with valve power disconnected.
constexpr uint8_t OUTPUT_PINS[] = {33, 32, 19};  // AUX2, AUX1, Flood TTL signals
constexpr uint8_t OUTPUT_COUNT = sizeof(OUTPUT_PINS) / sizeof(OUTPUT_PINS[0]);

constexpr uint32_t INPUT_INTERVAL_MS = 200;
constexpr uint32_t HEALTH_INTERVAL_MS = 1000;

constexpr uint8_t MCP_IODIRA = 0x00;
constexpr uint8_t MCP_IODIRB = 0x01;
constexpr uint8_t MCP_GPPUA = 0x0C;
constexpr uint8_t MCP_GPPUB = 0x0D;
constexpr uint8_t MCP_GPIOA = 0x12;
constexpr uint8_t INA_MANUFACTURER_ID = 0x3E;
constexpr uint8_t INA_DEVICE_ID = 0x3F;

uint32_t sequenceNumber = 0;
uint32_t lastInputAt = 0;
uint32_t lastHealthAt = 0;
char commandBuffer[64];
size_t commandLength = 0;
bool discardCommand = false;
bench::Interlocks interlocks;
unloaded::DryRun dry;
bool &outputsArmed = interlocks.armed;
bool (&outputStates)[OUTPUT_COUNT] = interlocks.outputs;
enum class TestMode { None, Pneumatic, Stepper, Homing, Edge };
TestMode testMode = TestMode::None;
bool xConfigured = false;
bool xHomeSeenActive = false;
bool xHomeVerified = false;
bench::StableAssertion xHomeActive, xHomeInactive;
uint8_t xEnableLevel = LOW;
uint8_t xAlarmNormal = HIGH;
uint16_t xRemaining = 0;
carriage::Homing xHoming;
bool xPositionKnown = false;
int32_t xHomeOffset = 0;
int32_t xSoftMaxOffset = 0;
int32_t xTargetOffset = 0;
bool xAbsoluteMove = false;
uint8_t xProfile = 0;
carriage::MotionProfile xProfiles[4] = {carriage::MotionProfile::get(0), carriage::MotionProfile::get(1),
                                      carriage::MotionProfile::get(2), carriage::MotionProfile::get(3)};
carriage::MotionRamp xRamp;
carriage::PulseTiming xTiming;
carriage::EdgeSearch xEdge;
bool xEdgeValid = false;
int32_t xEdgeMilli = 0, xTruingMilli = 0;
int32_t xSensorOffsetMilli = 10800, xTrimMilli = 250;
int32_t xCommandedSteps = 0;  // pulse-count displacement since boot, not encoder position
int8_t xDirection = 1;
uint32_t xMoveId = 0;
constexpr float X_STEPS_PER_INCH = 127.12f;
uint32_t xNextPulseUs = 0;
constexpr uint16_t X_MAX_JOG_PULSES = 254;  // ~2 inches per click at recovered 127.12 pulses/in
constexpr uint32_t X_PULSE_INTERVAL_US = 25000;  // 40 pulses/s, no catch-up bursts
uint32_t xArmAt = 0;
uint32_t xLastStepAt = 0;

void publishOutputs();
void publishSafety();
void publishX();
void publishDry();

// Teensy USB writes can wait when the host stops reading. During armed motion,
// reserve enough room for a whole record rather than blocking the pulse loop.
// See teensy4/usb_serial.h availableForWrite() timing guidance.
bool telemetryRoom(unsigned bytes) {
  return !(outputsArmed || dry.armed) || Serial.availableForWrite() >= static_cast<int>(bytes);
}

void stopTests() {
  if (dry.active()) dry.stop(millis());
  if (xHoming.active()) { xPositionKnown = false; xHoming.cancel(); }
  xEdge.cancel(); xEdgeValid = false;
  xRemaining = 0; xAbsoluteMove = false;
  interlocks.off(millis());
  testMode = TestMode::None;
  digitalWrite(X_STEP_PIN, LOW);
  // Retain ENA level/holding torque. ENA is not a safety-rated power disconnect.
}

bool xReady() {
  return !dry.active() && !dry.failed() && xConfigured && digitalRead(HOME_PIN) == HIGH &&
         digitalRead(CL57T_ALARM_PIN) == xAlarmNormal && interlocks.readyToArm();
}

void applyOutputs() {
  for (uint8_t index = 0; index < OUTPUT_COUNT; ++index) {
    const bool on = index == 2 ? (dry.armed && dry.triggerArmed && dry.trigger && !dry.failed()) :
        dry.active() ? (index == 0 ? dry.saw : dry.clamp) : outputStates[index];
    digitalWrite(OUTPUT_PINS[index], on ? HIGH : LOW);
  }
}

void commandFault() {
  if (dry.active()) dry.trip("DRY_COMMAND",millis());
  xPositionKnown = false; xHoming.cancel();
  xEdge.cancel(); xEdgeValid = false;
  xRemaining = 0; xAbsoluteMove = false;
  interlocks.trip(bench::Fault::Command, millis());
  applyOutputs();
  testMode = TestMode::None;
  digitalWrite(X_STEP_PIN, LOW);
}

void updateSafety() {
  dry.tick(digitalRead(FENCE_DOOR_PIN)==LOW, digitalRead(SAW_UP_PIN)==LOW,
           digitalRead(SAW_DOWN_PIN)==LOW, digitalRead(CL57T_ALARM_PIN)==HIGH, millis());
  const bool wasArmed = outputsArmed;
  const bench::Fault previousFault = interlocks.fault;
  const bench::Travel previousTravel = interlocks.travel;
  interlocks.tick({digitalRead(FENCE_DOOR_PIN) == LOW,
                   digitalRead(SAW_UP_PIN) == LOW,
                   digitalRead(SAW_DOWN_PIN) == LOW}, millis());
  xHomeActive.update(digitalRead(HOME_PIN) == LOW, millis());
  xHomeInactive.update(digitalRead(HOME_PIN) == HIGH, millis());
  if (!outputsArmed && xHomeActive.stable) xHomeSeenActive = true;
  if (xHomeSeenActive && xHomeInactive.stable) xHomeVerified = true;
  if ((testMode == TestMode::Stepper || testMode == TestMode::Homing || testMode == TestMode::Edge) && outputsArmed) {
    if (digitalRead(CL57T_ALARM_PIN) != xAlarmNormal)
      interlocks.trip(bench::Fault::DriverAlarm, millis());
    else if (testMode != TestMode::Homing && digitalRead(HOME_PIN) == LOW)
      interlocks.trip(bench::Fault::HomeLimit, millis());
  }
  if (interlocks.fault != bench::Fault::None || dry.failed()) xPositionKnown = false;
  if (!xPositionKnown || digitalRead(BOARD_EDGE_PIN) == HIGH) xEdgeValid = false;
  if (!outputsArmed) xEdge.cancel();
  if (!outputsArmed) { xHoming.cancel(); testMode = TestMode::None; xRemaining = 0; xAbsoluteMove = false; }
  applyOutputs();
  if (wasArmed != outputsArmed || previousFault != interlocks.fault ||
      previousTravel != interlocks.travel) {
    publishOutputs();
    publishSafety();
    publishX();
  }
}

bool i2cProbe(uint8_t address) {
  Wire2.beginTransmission(address);
  return Wire2.endTransmission() == 0;
}

bool mcpWrite8(uint8_t reg, uint8_t value) {
  Wire2.beginTransmission(MCP_ADDRESS);
  Wire2.write(reg);
  Wire2.write(value);
  return Wire2.endTransmission() == 0;
}

bool mcpReadPair(uint8_t reg, uint8_t &first, uint8_t &second) {
  Wire2.beginTransmission(MCP_ADDRESS);
  Wire2.write(reg);
  if (Wire2.endTransmission(false) != 0) {
    return false;
  }
  if (Wire2.requestFrom(MCP_ADDRESS, static_cast<uint8_t>(2)) != 2) {
    return false;
  }
  first = Wire2.read();
  second = Wire2.read();
  return true;
}

bool inaRead16(uint8_t reg, uint16_t &value) {
  Wire2.beginTransmission(INA_ADDRESS);
  Wire2.write(reg);
  if (Wire2.endTransmission(false) != 0) {
    return false;
  }
  if (Wire2.requestFrom(INA_ADDRESS, static_cast<uint8_t>(2)) != 2) {
    return false;
  }
  value = (static_cast<uint16_t>(Wire2.read()) << 8) | Wire2.read();
  return true;
}

bool configureMcpInputs() {
  // Every channel remains an input. Pull-ups make an unconnected channel read
  // HIGH and permit later active-low dry-contact/NPN bench testing.
  return mcpWrite8(MCP_IODIRA, 0xFF) &&
         mcpWrite8(MCP_IODIRB, 0xFF) &&
         mcpWrite8(MCP_GPPUA, 0xFF) &&
         mcpWrite8(MCP_GPPUB, 0xFF);
}

void printHex8(uint8_t value) {
  Serial.print("0x");
  if (value < 0x10) Serial.print('0');
  Serial.print(value, HEX);
}

void printHex16(uint16_t value) {
  Serial.print("0x");
  if (value < 0x1000) Serial.print('0');
  if (value < 0x0100) Serial.print('0');
  if (value < 0x0010) Serial.print('0');
  Serial.print(value, HEX);
}

void publishHello() {
  if (!telemetryRoom(1024)) return;
  Serial.print("BENCH_HELLO,PROTO:");
  Serial.print(PROTOCOL_VERSION);
  Serial.print(",FW:");
  Serial.print(FIRMWARE_VERSION);
  Serial.println(",BOARD:TEENSY41,MAP:T41U5XBB_V2_20,MOTION:1,TEST_OUTPUTS:3,OUTPUT_MAP:AUX2_AUX1_FLOOD,INPUT_MAP:DOOR29_UP22_DOWN16,INTERLOCKS:DOOR_POSITION_V1,COMMISSIONING:UNLOADED_DRY_RUN,X_TEST:MANUAL_JOG_V1,X_MAP:STEP2_DIR3_EN40,X_APP:CARRIAGE_V11,CAL_SPI:127.12,MAX_JOG:254,BASE_RATE:40,MAX_RATE:20000,MAX_ACCEL:50000,PROFILES:EDITABLE_V1,HOME_CHECK:LEVEL_ONLY,HOMING:BOUNDED_V1,HOME_MAX:20594,HOME_REF:160.5,ABSOLUTE:REFERENCED_V1,MAX_MOVE:20594,EDGE_SEARCH:BOUNDED_V1,LOAD:FAST_V1,DRY_RUN:UNLOADED_V2,BLADE_LOCK:TEST_ONLY,TRIGGER_TEST:BOUNDED_V1");
}

void publishPinMap() {
  if (!telemetryRoom(768)) return;
  Serial.println(
      "BENCH_PINMAP,HOME:D20/LIMIT_X,BOARD_EDGE:D21/LIMIT_Y,"
      "FENCE_DOOR:D29/DOOR,CL57T_ALM:D14/HALT,SAW_UP:D22/LIMIT_Z,"
      "SAW_DOWN:D16/FD_HLD,FENCE_CLOSED:D34/ST2,OUTFEED:D35/ST3,"
      "SAW_CYLINDER:D33/AUX2_TTL,MAIN_CLAMP:D32/AUX1_TTL,BLADE_TRIGGER:D19/FLOOD_TTL,"
      "X_STEP:D2/AXIS_X_STP,X_DIR:D3/AXIS_X_DIR,X_ENA:D40/AXIS_Y_EN");
}

void publishOutputs() {
  if (!telemetryRoom(256)) return;
  Serial.print("BENCH_OUTPUTS,ARMED:");
  Serial.print(dry.armed || (outputsArmed && testMode == TestMode::Pneumatic) ? 1 : 0);
  for (uint8_t index = 0; index < OUTPUT_COUNT; ++index) {
    Serial.print(",CLAMP");
    Serial.print(index + 1);
    Serial.print(':');
    Serial.print(digitalRead(OUTPUT_PINS[index]) == HIGH ? 1 : 0);
  }
  Serial.print(",FAULT:");
  Serial.println(dry.failed() ? dry.fault : interlocks.faultName());
}

void publishDry() {
  if (!telemetryRoom(256)) return;
  Serial.print("BENCH_DRY,PROTO:2,CFG:"); Serial.print(dry.configId);
  Serial.print(",HASH:"); Serial.print(dry.timingHash);
  Serial.print(",REQ:"); Serial.print(dry.requestId);
  Serial.print(",ARMED:"); Serial.print(dry.armed ? 1 : 0);
  Serial.print(",STATE:"); Serial.print(dry.name());
  Serial.print(",CLAMP:"); Serial.print(dry.clamp ? 1 : 0);
  Serial.print(",SAW:"); Serial.print(dry.saw ? 1 : 0);
  Serial.print(",TRIGGER:"); Serial.print(digitalRead(OUTPUT_PINS[2]) == HIGH ? 1 : 0);
  Serial.print(",LOCK:"); Serial.print(dry.triggerArmed ? 0 : 1);
  Serial.print(",FAULT:"); Serial.print(dry.fault);
  Serial.print(",UP_MS:"); Serial.println(millis());
}

void publishSafety() {
  if (!telemetryRoom(256)) return;
  Serial.print("BENCH_SAFETY,DOOR_CLOSED:");
  Serial.print(interlocks.door.stable ? 1 : 0);
  Serial.print(",SAW_POSITION:");
  Serial.print(interlocks.position());
  Serial.print(",READY:");
  Serial.print(!dry.active() && !dry.failed() && interlocks.readyToArm() ? 1 : 0);
  Serial.print(",RESET_READY:");
  Serial.print(!dry.active() && interlocks.readyToReset() ? 1 : 0);
  Serial.print(",FAULT:");
  Serial.print(dry.failed() ? dry.fault : interlocks.faultName());
  Serial.print(",BLOCKER:");
  Serial.println(dry.failed() ? dry.fault : dry.active() ? "DRY_RUN_ACTIVE" : interlocks.blocker());
}

void publishX() {
  if (!telemetryRoom(1024)) return;
  Serial.print("BENCH_X,ARMED:");
  Serial.print(outputsArmed && (testMode == TestMode::Stepper || testMode == TestMode::Homing || testMode == TestMode::Edge) ? 1 : 0);
  Serial.print(",CONFIGURED:"); Serial.print(xConfigured ? 1 : 0);
  Serial.print(",READY:"); Serial.print(xReady() ? 1 : 0);
  Serial.print(",HOME_VERIFIED:"); Serial.print(xHomeVerified ? 1 : 0);
  Serial.print(",HOME_RAW:"); Serial.print(digitalRead(HOME_PIN));
  Serial.print(",ALARM_RAW:"); Serial.print(digitalRead(CL57T_ALARM_PIN));
  Serial.print(",STEP:"); Serial.print(digitalRead(X_STEP_PIN));
  Serial.print(",DIR:"); Serial.print(digitalRead(X_DIR_PIN));
  Serial.print(",ENA:"); Serial.print(digitalRead(X_ENABLE_PIN));
  Serial.print(",MAX_JOG:"); Serial.print(X_MAX_JOG_PULSES);
  Serial.print(",PROFILE_ID:"); Serial.print(xProfile);
  Serial.print(",RATE_PPS:"); Serial.print(xProfiles[xProfile].maxRate);
  Serial.print(",ACCEL_PPS2:"); Serial.print(xProfiles[xProfile].acceleration);
  for (unsigned id=0; id<4; ++id) {
    Serial.print(",PROFILE_RATE"); Serial.print(id); Serial.print(':'); Serial.print(xProfiles[id].maxRate);
    Serial.print(",PROFILE_ACCEL"); Serial.print(id); Serial.print(':'); Serial.print(xProfiles[id].acceleration);
  }
  Serial.print(",JOG_PULSES:"); Serial.print(xTiming.count);
  Serial.print(",JOG_TIME_US:"); Serial.print(xTiming.elapsedUs());
  Serial.print(",JOG_PEAK_PPS:"); Serial.print(xTiming.peakPps());
  Serial.print(",JOG_LATE_US:"); Serial.print(xTiming.maxLate);
  Serial.print(",JOG_READY:");
  Serial.print(outputsArmed && testMode == TestMode::Stepper &&
               static_cast<uint32_t>(millis() - xArmAt) >= 200 ? 1 : 0);
  Serial.print(",REMAINING:"); Serial.print(xRemaining);
  Serial.print(",POS_STEPS:"); Serial.print(xCommandedSteps);
  Serial.print(",POS_KNOWN:"); Serial.print(xPositionKnown ? 1 : 0);
  Serial.print(",HOME_OFFSET:"); Serial.print(xHomeOffset);
  Serial.print(",HOME_REF:160.5,HOME_STATE:"); Serial.print(xHoming.name());
  Serial.print(",HOME_ERROR:"); Serial.print(xHoming.error);
  Serial.print(",SOFT_MIN_OFFSET:"); Serial.print(carriage::Positioning::MinOffset);
  Serial.print(",SOFT_MAX_OFFSET:"); Serial.print(xSoftMaxOffset);
  Serial.print(",SOFT_MAX_MILLI:"); Serial.print(carriage::Positioning::milliForOffset(xSoftMaxOffset));
  Serial.print(",TARGET_OFFSET:"); Serial.print(xTargetOffset);
  Serial.print(",MAX_MOVE:20594,MOVE_KIND:"); Serial.print(testMode == TestMode::Edge ? "EDGE" : xAbsoluteMove ? "ABSOLUTE" : xRemaining ? "JOG" : "IDLE");
  Serial.print(",EDGE_STATE:"); Serial.print(xEdge.name());
  Serial.print(",EDGE_ERROR:"); Serial.print(xEdge.error);
  Serial.print(",EDGE_VALID:"); Serial.print(xEdgeValid ? 1 : 0);
  Serial.print(",EDGE_MILLI:"); Serial.print(xEdgeMilli);
  Serial.print(",TRUING_MILLI:"); Serial.print(xTruingMilli);
  Serial.print(",SENSOR_OFFSET_MILLI:"); Serial.print(xSensorOffsetMilli);
  Serial.print(",TRIM_MILLI:"); Serial.print(xTrimMilli);
  Serial.print(",CAL_SPI:127.12,MOVE_ID:"); Serial.print(xMoveId);
  Serial.print(",UP_MS:"); Serial.print(millis());
  Serial.print(",FAULT:"); Serial.println(dry.failed() ? dry.fault : interlocks.faultName());
}

void publishInputs() {
  if (!telemetryRoom(256)) return;
  ++sequenceNumber;
  Serial.print("BENCH_INPUTS,SEQ:");
  Serial.print(sequenceNumber);
  Serial.print(",HOME:");
  Serial.print(digitalRead(HOME_PIN));
  Serial.print(",BOARD_EDGE:");
  Serial.print(digitalRead(BOARD_EDGE_PIN));
  Serial.print(",FENCE_DOOR:");
  Serial.print(digitalRead(FENCE_DOOR_PIN));
  Serial.print(",CL57T_ALM:");
  Serial.print(digitalRead(CL57T_ALARM_PIN));
  Serial.print(",SAW_UP:");
  Serial.print(digitalRead(SAW_UP_PIN));
  Serial.print(",SAW_DOWN:");
  Serial.print(digitalRead(SAW_DOWN_PIN));
  Serial.print(",FENCE_CLOSED:");
  Serial.print(digitalRead(FENCE_CLOSED_PIN));
  Serial.print(",OUTFEED:");
  Serial.println(digitalRead(OUTFEED_PIN));
}

void publishMcp() {
  uint8_t gpioA = 0;
  uint8_t gpioB = 0;
  const bool ok = mcpReadPair(MCP_GPIOA, gpioA, gpioB);
  Serial.print("BENCH_MCP,SEQ:");
  Serial.print(sequenceNumber);
  Serial.print(",OK:");
  Serial.print(ok ? 1 : 0);
  if (ok) {
    Serial.print(",GPIOA:");
    printHex8(gpioA);
    Serial.print(",GPIOB:");
    printHex8(gpioB);
  }
  Serial.println();
}

void publishHealth() {
  const bool mcpAck = i2cProbe(MCP_ADDRESS);
  uint8_t gpioA = 0;
  uint8_t gpioB = 0;
  const bool mcpIo = mcpAck && mcpReadPair(MCP_GPIOA, gpioA, gpioB);

  const bool inaAck = i2cProbe(INA_ADDRESS);
  uint16_t manufacturer = 0;
  uint16_t deviceRaw = 0;
  const bool inaRegisters = inaAck &&
                            inaRead16(INA_MANUFACTURER_ID, manufacturer) &&
                            inaRead16(INA_DEVICE_ID, deviceRaw);
  const uint16_t deviceId = deviceRaw >> 4;
  const bool inaIdentity = inaRegisters && manufacturer == 0x5449 && deviceId == 0x0228;

  Serial.print("BENCH_HEALTH,SEQ:");
  Serial.print(sequenceNumber);
  Serial.print(",UP_MS:");
  Serial.print(millis());
  Serial.print(",MCP_ACK:");
  Serial.print(mcpAck ? 1 : 0);
  Serial.print(",MCP_IO:");
  Serial.print(mcpIo ? 1 : 0);
  Serial.print(",INA_ACK:");
  Serial.print(inaAck ? 1 : 0);
  Serial.print(",INA_ID:");
  Serial.print(inaIdentity ? 1 : 0);
  if (inaRegisters) {
    Serial.print(",INA_MFG:");
    printHex16(manufacturer);
    Serial.print(",INA_DEV:0x");
    Serial.print(deviceId, HEX);
    Serial.print(",INA_REV:");
    Serial.print(deviceRaw & 0x0F);
  }
  Serial.println();
}

void publishI2cScan() {
  uint8_t addresses[16];
  uint8_t count = 0;
  for (uint8_t address = 1; address < 127; ++address) {
    if (i2cProbe(address) && count < sizeof(addresses)) {
      addresses[count++] = address;
    }
  }
  Serial.print("BENCH_I2C,COUNT:");
  Serial.print(count);
  Serial.print(",ADDRS:");
  for (uint8_t index = 0; index < count; ++index) {
    if (index) Serial.print('|');
    printHex8(addresses[index]);
  }
  Serial.println();
}

void publishStatus() {
  publishHello();
  if (!outputsArmed && !dry.active() && interlocks.travel == bench::Travel::Idle) publishHealth();
  publishInputs();
  if (!outputsArmed && !dry.active() && interlocks.travel == bench::Travel::Idle) publishMcp();
  publishOutputs();
  publishSafety();
  publishX();
  publishDry();
}

bool startsWith(const char *text, const char *prefix) {
  return strncmp(text, prefix, strlen(prefix)) == 0;
}

bool unsignedArgs(const char *text, const char *prefix, unsigned count, uint32_t *values) {
  if (!startsWith(text,prefix)) return false;
  const char *p=text+strlen(prefix);
  for (unsigned i=0;i<count;++i) {
    if (i && *p++ != ' ') return false;
    if (*p<'0' || *p>'9') return false;
    uint32_t value=0;
    while (*p>='0' && *p<='9') {
      const unsigned digit=static_cast<unsigned>(*p-'0');
      if (value > (UINT32_MAX-digit)/10u) return false;
      value=value*10+digit; ++p;
    }
    values[i]=value;
  }
  return *p=='\0';
}

bool __attribute__((noinline)) handleDryCommand(const char *command) {
  const bool dryCommand = startsWith(command,"DSET ") || startsWith(command,"DCOMMIT ") ||
      startsWith(command,"DARM ") || startsWith(command,"DCLAMP ") || strcmp(command,"DCYCLE")==0 ||
      strcmp(command,"DDOWN")==0 || strcmp(command,"DUP")==0 || strcmp(command,"DOFF")==0 ||
      strcmp(command,"DTARM")==0 || strcmp(command,"DTPRESS")==0 || strcmp(command,"DTRELEASE")==0;
  if (!dryCommand) return false;
  bool accepted=false;
  uint32_t args[2]={0,0};
  if (strcmp(command,"DOFF")==0) { stopTests(); accepted=true; }
  else if (strcmp(command,"DTRELEASE")==0) { dry.releaseTrigger(); accepted=true; }
  else if (outputsArmed || xRemaining || interlocks.travel != bench::Travel::Idle || interlocks.fault != bench::Fault::None) {}
  else if (startsWith(command,"DSET ")) accepted=unsignedArgs(command,"DSET ",2,args) && dry.configure(args[0],args[1]);
  else if (startsWith(command,"DCOMMIT ")) accepted=unsignedArgs(command,"DCOMMIT ",1,args) && dry.commit(args[0]);
  else if (startsWith(command,"DARM ")) accepted=unsignedArgs(command,"DARM ",1,args) && dry.arm(args[0],millis());
  else if (startsWith(command,"DCLAMP ")) accepted=unsignedArgs(command,"DCLAMP ",1,args) && args[0]<=1 && dry.commandClamp(args[0]==1,millis());
  else if (strcmp(command,"DCYCLE")==0 || strcmp(command,"DDOWN")==0) accepted=dry.stroke(strcmp(command,"DCYCLE")==0,millis());
  else if (strcmp(command,"DUP")==0) accepted=dry.returnUp(millis());
  else if (strcmp(command,"DTARM")==0) accepted=dry.armTrigger(millis());
  else if (strcmp(command,"DTPRESS")==0) accepted=dry.pressTrigger(millis());
  if (!accepted) Serial.println("BENCH_ERROR,CODE:DRY_REQUEST_REJECTED");
  applyOutputs(); publishDry(); publishSafety(); publishX();
  return true;
}

void __attribute__((noinline)) handleCommand(char *command) {
  // An overdue heartbeat or open door must trip before a new command can refresh it.
  updateSafety();
  for (char *cursor = command; *cursor; ++cursor) {
    *cursor = toupper(*cursor);
  }
  if (handleDryCommand(command)) return;
  if ((dry.active() || dry.failed()) && strcmp(command,"HELLO") && strcmp(command,"PINMAP") &&
      strcmp(command,"STATUS") && strcmp(command,"PING") && strcmp(command,"KEEPALIVE") &&
      strcmp(command,"OFF") && strcmp(command,"RESET") && strcmp(command,"XARM 0") && strcmp(command,"ARM 0")) {
    Serial.println("BENCH_ERROR,CODE:DRY_MODE_ACTIVE"); publishDry(); return;
  }
  if (strcmp(command, "HELLO") == 0) {
    publishHello();
  } else if (strcmp(command, "PING") == 0) {
    Serial.print("BENCH_PONG,UP_MS:");
    Serial.println(millis());
  } else if (strcmp(command, "PINMAP") == 0) {
    publishPinMap();
  } else if (strcmp(command, "I2C") == 0) {
    if (outputsArmed || interlocks.travel != bench::Travel::Idle) {
      Serial.println("BENCH_ERROR,CODE:I2C_BLOCKED_DURING_TEST");
      return;
    }
    publishI2cScan();
    configureMcpInputs();
    publishHealth();
  } else if (strcmp(command, "STATUS") == 0) {
    publishStatus();
  } else if (strcmp(command, "ARM 1") == 0) {
    if (!interlocks.arm(millis())) {
      Serial.print("BENCH_ERROR,CODE:");
      Serial.println(interlocks.blocker());
    } else testMode = TestMode::Pneumatic;
    applyOutputs();
    publishOutputs();
    publishSafety();
  } else if (strcmp(command, "RESET") == 0) {
    if ((dry.failed() || dry.active()) && !dry.reset(millis())) {
      Serial.println("BENCH_ERROR,CODE:DRY_RESET_NOT_READY"); publishDry(); return;
    }
    if (!interlocks.reset()) Serial.println("BENCH_ERROR,CODE:RESET_NOT_READY");
    applyOutputs();
    publishOutputs();
    publishSafety();
    publishDry();
  } else if (strcmp(command, "ARM 0") == 0 || strcmp(command, "OFF") == 0) {
    stopTests();
    applyOutputs();
    publishOutputs();
    publishSafety();
    publishX();
    publishDry();
  } else if (strcmp(command, "KEEPALIVE") == 0) {
    interlocks.keepalive(millis());
    dry.keepalive(millis());
  } else if (startsWith(command, "OUT ")) {
    int output = -1;
    int state = -1;
    char extra = '\0';
    if (sscanf(command, "OUT %d %d %c", &output, &state, &extra) != 2 ||
        output < 0 || output >= OUTPUT_COUNT || (state != 0 && state != 1)) {
      commandFault();
      Serial.println("BENCH_ERROR,CODE:BAD_OUTPUT_COMMAND");
      publishOutputs();
      return;
    }
    if (output == 2 && state == 1) { Serial.println("BENCH_ERROR,CODE:BLADE_LOCKED"); applyOutputs(); return; }
    const char *error = state == 1 && (testMode == TestMode::Stepper || testMode == TestMode::Homing || testMode == TestMode::Edge) ? "STEPPER_MODE_ACTIVE" :
      interlocks.requestOutput(static_cast<uint8_t>(output), state == 1, millis());
    applyOutputs();
    if (error) {
      Serial.print("BENCH_ERROR,CODE:");
      Serial.println(error);
    }
    publishOutputs();
    publishSafety();
  } else if (startsWith(command, "XLEVEL ") || startsWith(command, "XCONFIG ")) {
    int first = -1, second = -1; char extra = '\0';
    const bool configure = startsWith(command, "XCONFIG ");
    const char *arguments = command + (configure ? 8 : 7);
    if (sscanf(arguments, "%d %d %c", &first, &second, &extra) != 2 ||
        first < 0 || first > 1 || second < 0 || second > 1) {
      commandFault(); Serial.println("BENCH_ERROR,CODE:BAD_X_CONFIG");
    } else if (outputsArmed || testMode != TestMode::None) {
      Serial.println("BENCH_ERROR,CODE:DISARM_FIRST");
    } else if (configure) {
      if (digitalRead(CL57T_ALARM_PIN) != second || !interlocks.readyToArm()) {
        Serial.println("BENCH_ERROR,CODE:X_CONFIG_NOT_READY");
      } else { xEnableLevel = first; xAlarmNormal = second; xConfigured = true; }
    } else {
      digitalWrite(X_STEP_PIN, LOW);
      digitalWrite(X_DIR_PIN, first);
      digitalWrite(X_ENABLE_PIN, second);
      xConfigured = false; xPositionKnown = false;
    }
    publishX();
    publishDry();
  } else if (strcmp(command, "XARM 1") == 0) {
    if (!xReady() || !interlocks.arm(millis())) {
      Serial.println("BENCH_ERROR,CODE:X_NOT_READY");
    } else {
      testMode = TestMode::Stepper;
      xRemaining = 0;
      xArmAt = xLastStepAt = millis();
      xNextPulseUs = micros();
      digitalWrite(X_STEP_PIN, LOW);
      digitalWrite(X_ENABLE_PIN, xEnableLevel);
    }
    publishOutputs(); publishSafety(); publishX();
  } else if (strcmp(command, "XARM 0") == 0) {
    stopTests(); applyOutputs(); publishOutputs(); publishSafety(); publishX();
  } else if (strcmp(command, "XDISABLE") == 0) {
    stopTests(); applyOutputs();
    digitalWrite(X_ENABLE_PIN, HIGH);  // confirmed active LOW driver
    xConfigured = false; xPositionKnown = false;
    xHomeVerified = xHomeSeenActive = false;
    xHomeActive = bench::StableAssertion{};
    xHomeInactive = bench::StableAssertion{};
    publishOutputs(); publishSafety(); publishX();
  } else if (startsWith(command, "XPROFILE ")) {
    int id = -1, rate = -1, acceleration = -1; char extra = '\0';
    const int fields = sscanf(command + 9, "%d %d %d %c", &id, &rate, &acceleration, &extra);
    const bool selectOnly = sscanf(command + 9, "%d %c", &id, &extra) == 1;
    if ((!selectOnly && fields != 3) || id < 0 || id > 3 ||
        (fields == 3 && (id == 0 || rate < 1 || rate > carriage::MotionProfile::MaxRate ||
                        acceleration < 1 || acceleration > carriage::MotionProfile::MaxAcceleration))) {
      commandFault(); Serial.println("BENCH_ERROR,CODE:BAD_PROFILE");
    } else if (outputsArmed || testMode != TestMode::None) {
      Serial.println("BENCH_ERROR,CODE:DISARM_FIRST");
    } else {
      if (fields == 3) xProfiles[id] = {static_cast<uint16_t>(rate), static_cast<uint16_t>(acceleration)};
      xProfile = id;  // RAM only; selecting a profile never enables or moves
    }
    publishX();
  } else if (startsWith(command, "XHOME ")) {
    int pulses = 0; char extra = '\0';
    if (sscanf(command + 6, "%d %c", &pulses, &extra) != 1 || pulses < 1 || pulses > carriage::Homing::MaxSearch) {
      commandFault(); Serial.println("BENCH_ERROR,CODE:BAD_HOME_LIMIT");
    } else if (outputsArmed || testMode != TestMode::None || !xConfigured ||
               digitalRead(CL57T_ALARM_PIN) != xAlarmNormal || !interlocks.readyToArm()) {
      Serial.println("BENCH_ERROR,CODE:HOME_NOT_READY");
    } else if (interlocks.arm(millis()) && xHoming.start(pulses, digitalRead(HOME_PIN) == LOW, millis())) {
      xEdgeValid = false;
      xPositionKnown = false; xHomeOffset = 0; xRemaining = 0;
      testMode = TestMode::Homing; ++xMoveId;
      xArmAt = xLastStepAt = millis();
      digitalWrite(X_ENABLE_PIN, xEnableLevel);
      digitalWrite(X_DIR_PIN, xHoming.direction() == 1 ? HIGH : LOW);
      xNextPulseUs = micros() + 200000;
    }
    publishOutputs(); publishSafety(); publishX();
  } else if (startsWith(command, "XEDGE ")) {
    int pulses = 0; long offset = -1, trim = -1; char extra = '\0';
    if (sscanf(command + 6, "%d %ld %ld %c", &pulses, &offset, &trim, &extra) != 3 ||
        pulses < 1 || pulses > carriage::Positioning::MaxMove ||
        offset < 0 || offset > 160500 || trim < 0 || trim > 160500) {
      commandFault(); Serial.println("BENCH_ERROR,CODE:BAD_EDGE_COMMAND");
    } else if (!xPositionKnown) {
      Serial.println("BENCH_ERROR,CODE:HOME_REQUIRED");
    } else if (!outputsArmed || testMode != TestMode::Stepper || !xConfigured) {
      Serial.println("BENCH_ERROR,CODE:X_NOT_ARMED");
    } else if (xRemaining) {
      Serial.println("BENCH_ERROR,CODE:X_BUSY");
    } else if (static_cast<uint32_t>(millis() - xArmAt) < 200) {
      Serial.println("BENCH_ERROR,CODE:X_RATE_LIMIT");
    } else if (digitalRead(BOARD_EDGE_PIN) == LOW) {
      Serial.println("BENCH_ERROR,CODE:EDGE_ALREADY_ACTIVE");
    } else if (!carriage::Positioning::within(xHomeOffset - pulses, xSoftMaxOffset)) {
      Serial.println("BENCH_ERROR,CODE:X_SOFT_LIMIT");
    } else {
      xEdgeValid = false; xSensorOffsetMilli = offset; xTrimMilli = trim;
      xEdge.start(pulses, millis()); testMode = TestMode::Edge; ++xMoveId;
      xRemaining = pulses; xAbsoluteMove = false; xDirection = -1;
      digitalWrite(X_DIR_PIN, LOW);
      // Search is fixed 40pps regardless of the selected jog profile.
      xNextPulseUs = micros() + X_PULSE_INTERVAL_US;
    }
    publishX();
  } else if (startsWith(command, "XTRUING ")) {
    unsigned long capture = 0; char extra = '\0';
    if (sscanf(command + 8, "%lu %c", &capture, &extra) != 1 || command[8] == '-' || capture > UINT32_MAX) {
      commandFault(); Serial.println("BENCH_ERROR,CODE:BAD_TRUING_COMMAND");
    } else if (!xEdgeValid || capture != xMoveId || digitalRead(BOARD_EDGE_PIN) != LOW) {
      Serial.println("BENCH_ERROR,CODE:EDGE_CAPTURE_EXPIRED"); publishX();
    } else {
      // Reuse the normal absolute-move guards, not a second motion path.
      char move[24]; snprintf(move, sizeof(move), "XMOVE %ld", static_cast<long>(xTruingMilli));
      handleCommand(move);
    }
  } else if (startsWith(command, "XMOVE ") || startsWith(command, "XLOAD ")) {
    const bool loadMove = startsWith(command, "XLOAD ");
    long milli = -1; char extra = '\0'; int32_t target = 0;
    if (sscanf(command + 6, "%ld %c", &milli, &extra) != 1 || milli < 0 || milli > carriage::Positioning::HomeMilli) {
      commandFault(); Serial.println("BENCH_ERROR,CODE:BAD_ABSOLUTE_TARGET");
    } else if (!xPositionKnown) {
      Serial.println("BENCH_ERROR,CODE:HOME_REQUIRED");
    } else if (!outputsArmed || testMode != TestMode::Stepper || !xConfigured) {
      Serial.println("BENCH_ERROR,CODE:X_NOT_ARMED");
    } else if (xRemaining) {
      Serial.println("BENCH_ERROR,CODE:X_BUSY");
    } else if (static_cast<uint32_t>(millis() - xArmAt) < 200) {
      Serial.println("BENCH_ERROR,CODE:X_RATE_LIMIT");
    } else if (!carriage::Positioning::target(milli, xSoftMaxOffset, target)) {
      Serial.println("BENCH_ERROR,CODE:X_SOFT_LIMIT");
    } else {
      xEdgeValid = false;
      if (loadMove) xProfile = 3; // explicit accepted Load move selects stored FAST atomically
      const int32_t delta = target - xHomeOffset;
      xTargetOffset = target; ++xMoveId;
      xDirection = delta >= 0 ? 1 : -1;
      xRemaining = static_cast<uint16_t>(delta >= 0 ? delta : -delta);
      xAbsoluteMove = xRemaining != 0;
      xRamp.start(xRemaining, xProfiles[xProfile]);
      xTiming = carriage::PulseTiming{};
      digitalWrite(X_DIR_PIN, xDirection == 1 ? HIGH : LOW);
      const uint32_t directionReady = micros() + (xProfile ? xRamp.intervalUs() : 10);
      if (static_cast<uint32_t>(millis() - xLastStepAt) >= 26 ||
          static_cast<int32_t>(xNextPulseUs - directionReady) < 0) xNextPulseUs = directionReady;
    }
    publishX();
  } else if (startsWith(command, "XJOG ")) {
    int direction = 0, pulses = 0; char extra = '\0';
    if (sscanf(command + 5, "%d %d %c", &direction, &pulses, &extra) != 2 ||
        (direction != -1 && direction != 1) ||
        pulses < 1 || pulses > X_MAX_JOG_PULSES) {
      commandFault(); Serial.println("BENCH_ERROR,CODE:BAD_X_JOG");
    } else if (!outputsArmed || testMode != TestMode::Stepper || !xConfigured) {
      Serial.println("BENCH_ERROR,CODE:X_NOT_ARMED");
    } else if (xRemaining) {
      Serial.println("BENCH_ERROR,CODE:X_BUSY");
    } else if (static_cast<uint32_t>(millis() - xArmAt) < 200) {
      Serial.println("BENCH_ERROR,CODE:X_RATE_LIMIT");
    } else if (xPositionKnown && !carriage::Positioning::within(xHomeOffset + direction * pulses, xSoftMaxOffset)) {
      Serial.println("BENCH_ERROR,CODE:X_SOFT_LIMIT");
    } else {
      xEdgeValid = false;
      xAbsoluteMove = false;
      xTargetOffset = xHomeOffset + direction * pulses;
      digitalWrite(X_DIR_PIN, direction == 1 ? HIGH : LOW);
      xDirection = direction;
      ++xMoveId;
      xRemaining = static_cast<uint16_t>(pulses);
      xRamp.start(xRemaining, xProfiles[xProfile]);
      xTiming = carriage::PulseTiming{};
      const uint32_t directionReady = micros() + (xProfile ? xRamp.intervalUs() : 10);
      // Keep the previous pulse deadline across jogs. Rapid clicks cannot
      // bypass the 40 pulses/s limit or create a catch-up burst.
      if (static_cast<uint32_t>(millis() - xLastStepAt) >= 26 ||
          static_cast<int32_t>(xNextPulseUs - directionReady) < 0)
        xNextPulseUs = directionReady;
    }
    publishX();
  } else if (startsWith(command, "XSTEP ")) {
    int direction = 0; char extra = '\0';
    if (sscanf(command + 6, "%d %c", &direction, &extra) != 1 ||
        (direction != -1 && direction != 1)) {
      commandFault(); Serial.println("BENCH_ERROR,CODE:BAD_X_STEP");
    } else if (!outputsArmed || testMode != TestMode::Stepper || !xConfigured) {
      Serial.println("BENCH_ERROR,CODE:X_NOT_ARMED");
    } else if (xRemaining) {
      Serial.println("BENCH_ERROR,CODE:X_BUSY");
    } else if (static_cast<uint32_t>(millis() - xArmAt) < 200 ||
               static_cast<uint32_t>(millis() - xLastStepAt) < 200) {
      Serial.println("BENCH_ERROR,CODE:X_RATE_LIMIT");
    } else if (xPositionKnown && !carriage::Positioning::within(xHomeOffset + direction, xSoftMaxOffset)) {
      Serial.println("BENCH_ERROR,CODE:X_SOFT_LIMIT");
    } else {
      digitalWrite(X_DIR_PIN, direction == 1 ? HIGH : LOW);
      delayMicroseconds(10);  // driver requires >=2us direction setup
      updateSafety();
      if (outputsArmed && testMode == TestMode::Stepper) {
        xEdgeValid = false;
        digitalWrite(X_STEP_PIN, HIGH);
        delayMicroseconds(5);  // driver requires >=1us pulse width
        digitalWrite(X_STEP_PIN, LOW);
        xCommandedSteps += direction;
        if (xPositionKnown) xHomeOffset += direction;
        ++xMoveId;
        xLastStepAt = millis();
        xNextPulseUs = micros() + X_PULSE_INTERVAL_US;
      }
    }
    publishOutputs(); publishSafety(); publishX();
  } else if (startsWith(command, "EN") || startsWith(command, "G") ||
             startsWith(command, "$")) {
    commandFault();
    Serial.println("BENCH_ERROR,CODE:COMMAND_BLOCKED");
    publishOutputs();
  } else if (*command) {
    commandFault();
    Serial.println("BENCH_ERROR,CODE:UNKNOWN_COMMAND");
    publishOutputs();
    publishSafety();
  }
}

// Keep this scheduler separate from loop(); avoids a Teensy GCC optimizer ICE.
void __attribute__((noinline)) serviceXJog() {
  if (!xRemaining) return;
  updateSafety();
  if (!xRemaining || !outputsArmed || testMode != TestMode::Stepper) return;
  if (static_cast<int32_t>(micros() - xNextPulseUs) < 0) return;
  if (xPositionKnown && !carriage::Positioning::within(xHomeOffset + xDirection, xSoftMaxOffset)) {
    interlocks.trip(bench::Fault::SoftLimit, millis());
    updateSafety(); publishOutputs(); publishSafety(); publishX(); return;
  }
  const uint32_t pulseAt = micros();
  xTiming.pulse(pulseAt, xNextPulseUs);
  digitalWrite(X_STEP_PIN, HIGH);
  delayMicroseconds(5);
  digitalWrite(X_STEP_PIN, LOW);
  xCommandedSteps += xDirection;
  if (xPositionKnown) xHomeOffset += xDirection;
  --xRemaining; xRamp.pulsed();
  xLastStepAt = millis();
  // Rate is rising-edge to rising-edge; the 5us HIGH time is inside the period.
  // Rebase on the actual edge, never the overdue deadline: no catch-up burst.
  xNextPulseUs = pulseAt + xRamp.intervalUs();
  if (!xRemaining) { xAbsoluteMove = false; publishOutputs(); publishSafety(); publishX(); }
}

void __attribute__((noinline)) serviceXEdge() {
  if (testMode != TestMode::Edge || !outputsArmed) return;
  updateSafety();
  if (testMode != TestMode::Edge || !outputsArmed) return;
  const bool detected = digitalRead(BOARD_EDGE_PIN) == LOW;
  xEdge.observe(detected, millis());
  if (xEdge.stage == carriage::EdgeSearch::Stage::Failed) {
    interlocks.trip(bench::Fault::EdgeFailed, millis());
    updateSafety(); publishOutputs(); publishSafety(); publishX(); return;
  }
  if (xEdge.stage == carriage::EdgeSearch::Stage::Found) {
    xEdgeMilli = carriage::Positioning::milliForOffset(xHomeOffset);
    xTruingMilli = xEdgeMilli - xSensorOffsetMilli + xTrimMilli;
    int32_t proposed = 0;
    const bool valid = carriage::Positioning::target(xTruingMilli, xSoftMaxOffset, proposed);
    stopTests();  // finish disarmed, holding torque retained; no automatic advance
    xEdgeValid = valid;
    if (!valid) xEdge.error = "TARGET_OUT_OF_RANGE";
    publishOutputs(); publishSafety(); publishX(); return;
  }
  if (!xEdge.wantsPulse(detected) || static_cast<int32_t>(micros() - xNextPulseUs) < 0) return;
  if (!carriage::Positioning::within(xHomeOffset - 1, xSoftMaxOffset)) {
    interlocks.trip(bench::Fault::SoftLimit, millis());
    updateSafety(); publishOutputs(); publishSafety(); publishX(); return;
  }
  digitalWrite(X_STEP_PIN, HIGH); delayMicroseconds(5); digitalWrite(X_STEP_PIN, LOW);
  --xCommandedSteps; --xHomeOffset; --xRemaining;
  xEdge.pulsed(millis()); xLastStepAt = millis();
  xNextPulseUs = micros() + X_PULSE_INTERVAL_US;
}

void __attribute__((noinline)) serviceXHome() {
  if (testMode != TestMode::Homing || !outputsArmed) return;
  updateSafety();
  if (testMode != TestMode::Homing || !outputsArmed) return;
  const auto previousStage = xHoming.stage;
  const bool wasLatched = xHoming.referenceLatched;
  xHoming.observe(digitalRead(HOME_PIN) == LOW, millis());
  if (!wasLatched && xHoming.referenceLatched) xHomeOffset = 0;
  if (xHoming.failed()) {
    xPositionKnown = false;
    interlocks.trip(bench::Fault::HomingFailed, millis());
    updateSafety(); publishOutputs(); publishSafety(); publishX(); return;
  }
  if (xHoming.done()) {
    xPositionKnown = true; xSoftMaxOffset = xHomeOffset;
    stopTests(); publishOutputs(); publishSafety(); publishX(); return;
  }
  if (previousStage != xHoming.stage) {
    digitalWrite(X_DIR_PIN, xHoming.direction() == 1 ? HIGH : LOW);
    const uint32_t directionReady = micros() + 10;
    if (static_cast<int32_t>(xNextPulseUs - directionReady) < 0) xNextPulseUs = directionReady;
    publishX();
  }
  if (static_cast<uint32_t>(millis() - xArmAt) < 200 ||
      !xHoming.wantsPulse(digitalRead(HOME_PIN) == LOW) ||
      static_cast<int32_t>(micros() - xNextPulseUs) < 0) return;
  digitalWrite(X_STEP_PIN, HIGH); delayMicroseconds(5); digitalWrite(X_STEP_PIN, LOW);
  xCommandedSteps += xHoming.direction();
  if (xHoming.referenceLatched) xHomeOffset += xHoming.direction();
  xHoming.pulsed(millis()); xLastStepAt = millis();
  xNextPulseUs = micros() + xHoming.intervalUs();
}

void readSerialCommands() {
  uint8_t processed = 0;
  while (Serial.available() && processed++ < 64) {
    const char incoming = static_cast<char>(Serial.read());
    if (incoming == '\r') continue;
    if (discardCommand) {
      if (incoming == '\n') discardCommand = false;
      continue;
    }
    if (incoming == '\n') {
      commandBuffer[commandLength] = '\0';
      handleCommand(commandBuffer);
      commandLength = 0;
    } else if (commandLength + 1 < sizeof(commandBuffer)) {
      commandBuffer[commandLength++] = incoming;
    } else {
      commandLength = 0;
      discardCommand = true;
      commandFault();
      Serial.println("BENCH_ERROR,CODE:COMMAND_TOO_LONG");
      publishOutputs();
      publishSafety();
    }
  }
}

}  // namespace

void setup() {
  digitalWriteFast(X_STEP_PIN, LOW); pinMode(X_STEP_PIN, OUTPUT);
  digitalWrite(X_STEP_PIN, LOW);
  digitalWriteFast(X_DIR_PIN, LOW); pinMode(X_DIR_PIN, OUTPUT);
  digitalWrite(X_DIR_PIN, LOW);
  // HIGH is an electrical level only; the actual ENA polarity must be verified.
  digitalWriteFast(X_ENABLE_PIN, HIGH); pinMode(X_ENABLE_PIN, OUTPUT);
  digitalWrite(X_ENABLE_PIN, HIGH);
  // Latch every pneumatic signal LOW before changing its pin to output. This keeps
  // all three MOSFET triggers off during startup.
  for (uint8_t index = 0; index < OUTPUT_COUNT; ++index) {
    digitalWrite(OUTPUT_PINS[index], LOW);
    pinMode(OUTPUT_PINS[index], OUTPUT);
  }
  pinMode(HOME_PIN, INPUT_PULLUP);
  pinMode(BOARD_EDGE_PIN, INPUT_PULLUP);
  pinMode(FENCE_DOOR_PIN, INPUT_PULLUP);
  pinMode(CL57T_ALARM_PIN, INPUT_PULLUP);
  pinMode(SAW_UP_PIN, INPUT_PULLUP);
  pinMode(SAW_DOWN_PIN, INPUT_PULLUP);
  pinMode(FENCE_CLOSED_PIN, INPUT_PULLUP);
  pinMode(OUTFEED_PIN, INPUT_PULLUP);

  Serial.begin(115200);
  Wire2.begin();
  Wire2.setClock(100000);
  delay(100);
  configureMcpInputs();
  publishHello();
  publishPinMap();
  publishI2cScan();
  publishStatus();
}

void loop() {
  updateSafety();
  readSerialCommands();
  serviceXJog();
  serviceXEdge();
  serviceXHome();
  const uint32_t now = millis();
  updateSafety();
  if (now - lastInputAt >= INPUT_INTERVAL_MS) {
    lastInputAt = now;
    publishInputs();
    publishSafety();
    publishX();
    publishDry();
    if (!outputsArmed && !dry.active() && interlocks.travel == bench::Travel::Idle) publishMcp();
  }
  if (now - lastHealthAt >= HEALTH_INTERVAL_MS) {
    lastHealthAt = now;
    if (!outputsArmed && !dry.active() && interlocks.travel == bench::Travel::Idle) publishHealth();
  }
}
