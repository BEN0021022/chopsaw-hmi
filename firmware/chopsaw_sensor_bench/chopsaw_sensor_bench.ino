/*
  Chop Saw Sensor Bench - Teensy 4.1 / T41U5XBB V2.20

  Input commissioning firmware plus three guarded, momentary pneumatic outputs.
  X diagnostics emit bounded, interruptible pulse jogs. Pneumatic outputs boot OFF, require an explicit arm and
  host keepalive, and shut off on communications or maximum-on timeout.

  I2C header: Wire2, SDA D25, SCL D24, 3.3 V logic.
*/

#include <Arduino.h>
#include <Wire.h>
#include "bench_interlocks.h"

namespace {

constexpr char FIRMWARE_VERSION[] = "0.6.0";
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
bool &outputsArmed = interlocks.armed;
bool (&outputStates)[OUTPUT_COUNT] = interlocks.outputs;
enum class TestMode { None, Pneumatic, Stepper };
TestMode testMode = TestMode::None;
bool xConfigured = false;
bool xHomeSeenActive = false;
bool xHomeVerified = false;
bench::StableAssertion xHomeActive, xHomeInactive;
uint8_t xEnableLevel = LOW;
uint8_t xAlarmNormal = HIGH;
uint16_t xBudget = 0;
uint16_t xRemaining = 0;
uint32_t xNextPulseUs = 0;
constexpr uint16_t X_ARM_BUDGET = 254;  // ~2 inches total, calibration provisional
constexpr uint32_t X_PULSE_INTERVAL_US = 25000;  // 40 pulses/s, no catch-up bursts
uint32_t xArmAt = 0;
uint32_t xLastStepAt = 0;

void publishOutputs();
void publishSafety();
void publishX();

void stopTests() {
  xRemaining = 0;
  interlocks.off(millis());
  testMode = TestMode::None;
  digitalWrite(X_STEP_PIN, LOW);
  // Retain ENA level/holding torque. ENA is not a safety-rated power disconnect.
}

bool xReady() {
  return xConfigured && xHomeVerified && digitalRead(HOME_PIN) == HIGH &&
         digitalRead(CL57T_ALARM_PIN) == xAlarmNormal && interlocks.readyToArm();
}

void applyOutputs() {
  for (uint8_t index = 0; index < OUTPUT_COUNT; ++index) {
    digitalWrite(OUTPUT_PINS[index], outputStates[index] ? HIGH : LOW);
  }
}

void commandFault() {
  xRemaining = 0;
  interlocks.trip(bench::Fault::Command, millis());
  applyOutputs();
  testMode = TestMode::None;
  digitalWrite(X_STEP_PIN, LOW);
}

void updateSafety() {
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
  if (testMode == TestMode::Stepper && outputsArmed) {
    if (digitalRead(CL57T_ALARM_PIN) != xAlarmNormal)
      interlocks.trip(bench::Fault::DriverAlarm, millis());
    else if (digitalRead(HOME_PIN) == LOW)
      interlocks.trip(bench::Fault::HomeLimit, millis());
  }
  if (!outputsArmed) { testMode = TestMode::None; xRemaining = 0; }
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
  Serial.print("BENCH_HELLO,PROTO:");
  Serial.print(PROTOCOL_VERSION);
  Serial.print(",FW:");
  Serial.print(FIRMWARE_VERSION);
  Serial.println(",BOARD:TEENSY41,MAP:T41U5XBB_V2_20,MOTION:1,TEST_OUTPUTS:3,OUTPUT_MAP:AUX2_AUX1_FLOOD,INPUT_MAP:DOOR29_UP22_DOWN16,INTERLOCKS:DOOR_POSITION_V1,COMMISSIONING:VALVES_ISOLATED,X_TEST:BOUNDED_JOG_V1,X_MAP:STEP2_DIR3_EN40");
}

void publishPinMap() {
  Serial.println(
      "BENCH_PINMAP,HOME:D20/LIMIT_X,BOARD_EDGE:D21/LIMIT_Y,"
      "FENCE_DOOR:D29/DOOR,CL57T_ALM:D14/HALT,SAW_UP:D22/LIMIT_Z,"
      "SAW_DOWN:D16/FD_HLD,FENCE_CLOSED:D34/ST2,OUTFEED:D35/ST3,"
      "SAW_CYLINDER:D33/AUX2_TTL,MAIN_CLAMP:D32/AUX1_TTL,BLADE_TRIGGER:D19/FLOOD_TTL,"
      "X_STEP:D2/AXIS_X_STP,X_DIR:D3/AXIS_X_DIR,X_ENA:D40/AXIS_Y_EN");
}

void publishOutputs() {
  Serial.print("BENCH_OUTPUTS,ARMED:");
  Serial.print(outputsArmed && testMode == TestMode::Pneumatic ? 1 : 0);
  for (uint8_t index = 0; index < OUTPUT_COUNT; ++index) {
    Serial.print(",CLAMP");
    Serial.print(index + 1);
    Serial.print(':');
    Serial.print(outputStates[index] ? 1 : 0);
  }
  Serial.print(",FAULT:");
  Serial.println(interlocks.faultName());
}

void publishSafety() {
  Serial.print("BENCH_SAFETY,DOOR_CLOSED:");
  Serial.print(interlocks.door.stable ? 1 : 0);
  Serial.print(",SAW_POSITION:");
  Serial.print(interlocks.position());
  Serial.print(",READY:");
  Serial.print(interlocks.readyToArm() ? 1 : 0);
  Serial.print(",RESET_READY:");
  Serial.print(interlocks.readyToReset() ? 1 : 0);
  Serial.print(",FAULT:");
  Serial.print(interlocks.faultName());
  Serial.print(",BLOCKER:");
  Serial.println(interlocks.blocker());
}

void publishX() {
  Serial.print("BENCH_X,ARMED:");
  Serial.print(outputsArmed && testMode == TestMode::Stepper ? 1 : 0);
  Serial.print(",CONFIGURED:"); Serial.print(xConfigured ? 1 : 0);
  Serial.print(",READY:"); Serial.print(xReady() ? 1 : 0);
  Serial.print(",HOME_VERIFIED:"); Serial.print(xHomeVerified ? 1 : 0);
  Serial.print(",HOME_RAW:"); Serial.print(digitalRead(HOME_PIN));
  Serial.print(",ALARM_RAW:"); Serial.print(digitalRead(CL57T_ALARM_PIN));
  Serial.print(",STEP:"); Serial.print(digitalRead(X_STEP_PIN));
  Serial.print(",DIR:"); Serial.print(digitalRead(X_DIR_PIN));
  Serial.print(",ENA:"); Serial.print(digitalRead(X_ENABLE_PIN));
  Serial.print(",BUDGET:"); Serial.print(xBudget);
  Serial.print(",REMAINING:"); Serial.print(xRemaining);
  Serial.print(",FAULT:"); Serial.println(interlocks.faultName());
}

void publishInputs() {
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
  if (!outputsArmed && interlocks.travel == bench::Travel::Idle) publishHealth();
  publishInputs();
  if (!outputsArmed && interlocks.travel == bench::Travel::Idle) publishMcp();
  publishOutputs();
  publishSafety();
  publishX();
}

bool startsWith(const char *text, const char *prefix) {
  return strncmp(text, prefix, strlen(prefix)) == 0;
}

void handleCommand(char *command) {
  // An overdue heartbeat or open door must trip before a new command can refresh it.
  updateSafety();
  for (char *cursor = command; *cursor; ++cursor) {
    *cursor = toupper(*cursor);
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
    if (!interlocks.reset()) Serial.println("BENCH_ERROR,CODE:RESET_NOT_READY");
    applyOutputs();
    publishOutputs();
    publishSafety();
  } else if (strcmp(command, "ARM 0") == 0 || strcmp(command, "OFF") == 0) {
    stopTests();
    applyOutputs();
    publishOutputs();
    publishSafety();
    publishX();
  } else if (strcmp(command, "KEEPALIVE") == 0) {
    interlocks.keepalive(millis());
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
    const char *error = state == 1 && testMode == TestMode::Stepper ? "STEPPER_MODE_ACTIVE" :
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
      if (!xHomeVerified || digitalRead(HOME_PIN) != HIGH ||
          digitalRead(CL57T_ALARM_PIN) != second || !interlocks.readyToArm()) {
        Serial.println("BENCH_ERROR,CODE:X_CONFIG_NOT_READY");
      } else { xEnableLevel = first; xAlarmNormal = second; xConfigured = true; }
    } else {
      digitalWrite(X_STEP_PIN, LOW);
      digitalWrite(X_DIR_PIN, first);
      digitalWrite(X_ENABLE_PIN, second);
      xConfigured = false;
    }
    publishX();
  } else if (strcmp(command, "XARM 1") == 0) {
    if (!xReady() || !interlocks.arm(millis())) {
      Serial.println("BENCH_ERROR,CODE:X_NOT_READY");
    } else {
      testMode = TestMode::Stepper;
      xBudget = X_ARM_BUDGET;
      xRemaining = 0;
      xArmAt = xLastStepAt = millis();
      digitalWrite(X_STEP_PIN, LOW);
      digitalWrite(X_ENABLE_PIN, xEnableLevel);
    }
    publishOutputs(); publishSafety(); publishX();
  } else if (strcmp(command, "XARM 0") == 0) {
    stopTests(); applyOutputs(); publishOutputs(); publishSafety(); publishX();
  } else if (startsWith(command, "XJOG ")) {
    int direction = 0, pulses = 0; char extra = '\0';
    if (sscanf(command + 5, "%d %d %c", &direction, &pulses, &extra) != 2 ||
        (direction != -1 && direction != 1) ||
        (pulses != 13 && pulses != 64 && pulses != 127)) {
      commandFault(); Serial.println("BENCH_ERROR,CODE:BAD_X_JOG");
    } else if (!outputsArmed || testMode != TestMode::Stepper || !xConfigured) {
      Serial.println("BENCH_ERROR,CODE:X_NOT_ARMED");
    } else if (xRemaining) {
      Serial.println("BENCH_ERROR,CODE:X_BUSY");
    } else if (pulses > xBudget) {
      Serial.println("BENCH_ERROR,CODE:X_BUDGET_EXCEEDED");
    } else if (static_cast<uint32_t>(millis() - xArmAt) < 200 ||
               static_cast<uint32_t>(millis() - xLastStepAt) < 200) {
      Serial.println("BENCH_ERROR,CODE:X_RATE_LIMIT");
    } else {
      digitalWrite(X_DIR_PIN, direction == 1 ? HIGH : LOW);
      xRemaining = static_cast<uint16_t>(pulses);
      xNextPulseUs = micros() + 10;  // direction setup; no pulse in command handler
    }
    publishX();
  } else if (startsWith(command, "XSTEP ")) {
    int direction = 0; char extra = '\0';
    if (sscanf(command + 6, "%d %c", &direction, &extra) != 1 ||
        (direction != -1 && direction != 1)) {
      commandFault(); Serial.println("BENCH_ERROR,CODE:BAD_X_STEP");
    } else if (!outputsArmed || testMode != TestMode::Stepper || !xConfigured || !xBudget) {
      Serial.println("BENCH_ERROR,CODE:X_NOT_ARMED");
    } else if (xRemaining) {
      Serial.println("BENCH_ERROR,CODE:X_BUSY");
    } else if (static_cast<uint32_t>(millis() - xArmAt) < 200 ||
               static_cast<uint32_t>(millis() - xLastStepAt) < 200) {
      Serial.println("BENCH_ERROR,CODE:X_RATE_LIMIT");
    } else {
      digitalWrite(X_DIR_PIN, direction == 1 ? HIGH : LOW);
      delayMicroseconds(10);  // driver requires >=2us direction setup
      updateSafety();
      if (outputsArmed && testMode == TestMode::Stepper) {
        digitalWrite(X_STEP_PIN, HIGH);
        delayMicroseconds(5);  // driver requires >=1us pulse width
        digitalWrite(X_STEP_PIN, LOW);
        --xBudget;
        xLastStepAt = millis();
        if (!xBudget) stopTests();
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
  digitalWrite(X_STEP_PIN, HIGH);
  delayMicroseconds(5);
  digitalWrite(X_STEP_PIN, LOW);
  --xRemaining;
  --xBudget;
  xLastStepAt = millis();
  xNextPulseUs = micros() + X_PULSE_INTERVAL_US;
  if (!xBudget) stopTests();
  if (!xRemaining) { publishOutputs(); publishSafety(); publishX(); }
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
  const uint32_t now = millis();
  updateSafety();
  if (now - lastInputAt >= INPUT_INTERVAL_MS) {
    lastInputAt = now;
    publishInputs();
    publishSafety();
    publishX();
    if (!outputsArmed && interlocks.travel == bench::Travel::Idle) publishMcp();
  }
  if (now - lastHealthAt >= HEALTH_INTERVAL_MS) {
    lastHealthAt = now;
    if (!outputsArmed && interlocks.travel == bench::Travel::Idle) publishHealth();
  }
}
