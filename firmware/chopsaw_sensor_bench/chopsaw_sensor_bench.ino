/*
  Chop Saw Sensor Bench - Teensy 4.1 / T41U5XBB V2.20

  Input commissioning firmware plus three guarded, momentary clamp outputs.
  It never issues motion. Clamp outputs boot OFF, require an explicit arm and
  host keepalive, and shut off on communications or maximum-on timeout.

  I2C header: Wire2, SDA D25, SCL D24, 3.3 V logic.
*/

#include <Arduino.h>
#include <Wire.h>

namespace {

constexpr char FIRMWARE_VERSION[] = "0.2.0";
constexpr uint8_t PROTOCOL_VERSION = 2;
constexpr uint8_t MCP_ADDRESS = 0x27;
constexpr uint8_t INA_ADDRESS = 0x40;

constexpr uint8_t HOME_PIN = 20;          // Limit X
constexpr uint8_t BOARD_EDGE_PIN = 21;    // Limit Y (Probe D15 intentionally unused)
constexpr uint8_t FENCE_DOOR_PIN = 29;    // Door
constexpr uint8_t CL57T_ALARM_PIN = 14;   // Halt
constexpr uint8_t SAW_UP_PIN = 36;        // ST0
constexpr uint8_t SAW_DOWN_PIN = 30;      // ST1
constexpr uint8_t FENCE_CLOSED_PIN = 34;  // ST2
constexpr uint8_t OUTFEED_PIN = 35;       // ST3

constexpr uint8_t CLAMP_PINS[] = {31, 32, 33};  // AUX0, AUX1, AUX2 TTL/SSR signals
constexpr uint8_t CLAMP_COUNT = sizeof(CLAMP_PINS) / sizeof(CLAMP_PINS[0]);

constexpr uint32_t INPUT_INTERVAL_MS = 200;
constexpr uint32_t HEALTH_INTERVAL_MS = 1000;
constexpr uint32_t OUTPUT_WATCHDOG_MS = 1500;
constexpr uint32_t OUTPUT_MAX_ON_MS = 5000;

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
bool outputsArmed = false;
bool clampStates[CLAMP_COUNT] = {false, false, false};
uint32_t clampOnAt[CLAMP_COUNT] = {0, 0, 0};
uint32_t lastKeepaliveAt = 0;
const char *outputFault = "NONE";

void publishOutputs();

void allOutputsOff() {
  for (uint8_t index = 0; index < CLAMP_COUNT; ++index) {
    digitalWrite(CLAMP_PINS[index], LOW);
    clampStates[index] = false;
    clampOnAt[index] = 0;
  }
}

void disarmOutputs(const char *fault) {
  allOutputsOff();
  outputsArmed = false;
  outputFault = fault;
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
  Serial.println(",BOARD:TEENSY41,MAP:T41U5XBB_V2_20,MOTION:0,TEST_OUTPUTS:3");
}

void publishPinMap() {
  Serial.println(
      "BENCH_PINMAP,HOME:D20/LIMIT_X,BOARD_EDGE:D21/LIMIT_Y,"
      "FENCE_DOOR:D29/DOOR,CL57T_ALM:D14/HALT,SAW_UP:D36/ST0,"
      "SAW_DOWN:D30/ST1,FENCE_CLOSED:D34/ST2,OUTFEED:D35/ST3,"
      "CLAMP1:D31/AUX0_TTL,CLAMP2:D32/AUX1_TTL,CLAMP3:D33/AUX2_TTL");
}

void publishOutputs() {
  Serial.print("BENCH_OUTPUTS,ARMED:");
  Serial.print(outputsArmed ? 1 : 0);
  for (uint8_t index = 0; index < CLAMP_COUNT; ++index) {
    Serial.print(",CLAMP");
    Serial.print(index + 1);
    Serial.print(':');
    Serial.print(clampStates[index] ? 1 : 0);
  }
  Serial.print(",FAULT:");
  Serial.println(outputFault);
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
  publishHealth();
  publishInputs();
  publishMcp();
  publishOutputs();
}

bool startsWith(const char *text, const char *prefix) {
  return strncmp(text, prefix, strlen(prefix)) == 0;
}

void handleCommand(char *command) {
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
    publishI2cScan();
    configureMcpInputs();
    publishHealth();
  } else if (strcmp(command, "STATUS") == 0) {
    publishStatus();
  } else if (strcmp(command, "ARM 1") == 0) {
    allOutputsOff();
    outputsArmed = true;
    lastKeepaliveAt = millis();
    outputFault = "NONE";
    publishOutputs();
  } else if (strcmp(command, "ARM 0") == 0 || strcmp(command, "OFF") == 0) {
    disarmOutputs("NONE");
    publishOutputs();
  } else if (strcmp(command, "KEEPALIVE") == 0) {
    if (outputsArmed) lastKeepaliveAt = millis();
  } else if (startsWith(command, "OUT ")) {
    int output = -1;
    int state = -1;
    char extra = '\0';
    if (sscanf(command, "OUT %d %d %c", &output, &state, &extra) != 2 ||
        output < 0 || output >= CLAMP_COUNT || (state != 0 && state != 1)) {
      disarmOutputs("COMMAND");
      Serial.println("BENCH_ERROR,CODE:BAD_OUTPUT_COMMAND");
      publishOutputs();
      return;
    }
    if (state == 0) {
      digitalWrite(CLAMP_PINS[output], LOW);
      clampStates[output] = false;
      clampOnAt[output] = 0;
      publishOutputs();
    } else if (!outputsArmed) {
      Serial.println("BENCH_ERROR,CODE:NOT_ARMED");
      publishOutputs();
    } else if (!clampStates[output]) {
      digitalWrite(CLAMP_PINS[output], HIGH);
      clampStates[output] = true;
      clampOnAt[output] = millis();
      publishOutputs();
    }
  } else if (startsWith(command, "EN") || startsWith(command, "G") ||
             startsWith(command, "$")) {
    disarmOutputs("COMMAND");
    Serial.println("BENCH_ERROR,CODE:COMMAND_BLOCKED");
    publishOutputs();
  } else if (*command) {
    Serial.println("BENCH_ERROR,CODE:UNKNOWN_COMMAND");
  }
}

void enforceOutputSafety(uint32_t now) {
  if (outputsArmed && now - lastKeepaliveAt > OUTPUT_WATCHDOG_MS) {
    disarmOutputs("WATCHDOG");
    publishOutputs();
    return;
  }
  for (uint8_t index = 0; index < CLAMP_COUNT; ++index) {
    if (clampStates[index] && now - clampOnAt[index] > OUTPUT_MAX_ON_MS) {
      disarmOutputs("MAX_ON");
      publishOutputs();
      return;
    }
  }
}

void readSerialCommands() {
  while (Serial.available()) {
    const char incoming = static_cast<char>(Serial.read());
    if (incoming == '\r') continue;
    if (incoming == '\n') {
      commandBuffer[commandLength] = '\0';
      handleCommand(commandBuffer);
      commandLength = 0;
    } else if (commandLength + 1 < sizeof(commandBuffer)) {
      commandBuffer[commandLength++] = incoming;
    } else {
      commandLength = 0;
      Serial.println("BENCH_ERROR,CODE:COMMAND_TOO_LONG");
    }
  }
}

}  // namespace

void setup() {
  // Latch every clamp signal LOW before changing its pin to output. This keeps
  // all three MOSFET triggers off during startup.
  for (uint8_t index = 0; index < CLAMP_COUNT; ++index) {
    digitalWrite(CLAMP_PINS[index], LOW);
    pinMode(CLAMP_PINS[index], OUTPUT);
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
  readSerialCommands();
  const uint32_t now = millis();
  enforceOutputSafety(now);
  if (now - lastInputAt >= INPUT_INTERVAL_MS) {
    lastInputAt = now;
    publishInputs();
    publishMcp();
  }
  if (now - lastHealthAt >= HEALTH_INTERVAL_MS) {
    lastHealthAt = now;
    publishHealth();
  }
}
