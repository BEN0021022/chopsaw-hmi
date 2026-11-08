// ==============================================================================
// Arduino Mega Firmware for Closed-Loop Stepper Motor Control
// ==============================================================================
// This sketch implements full closed-loop control with an encoder and PID feedback.
//
// Features:
// - Stepper motor control with AccelStepper library for smooth motion.
// - Quadrature encoder feedback for real-time position tracking.
// - PID control loop to correct for missed steps or external forces.
// - Homing, calibration, and serial communication with Python HMI.
// - (ADDED) Motion profiles selectable via 'Z#' with per-profile speed/accel.
// ==============================================================================

#include <AccelStepper.h>

// --- Pin Definitions ---
const int STEP_PIN = 2;   // Connect to STEP pin on stepper driver
const int DIR_PIN  = 3;   // Connect to DIR pin on stepper driver
const int EN_PIN   = 4;   // Connect to ENABLE pin on stepper driver (active low)

const int HOMING_SENSOR_PIN = 5; // Digital pin for homing limit switch/proximity sensor
const int BOARD_SENSOR_PIN  = 6; // Pin for the board detection sensor
const int CURRENT_SENSOR_PIN = A2; // ACS712 20A current sensor

// --- CLOSED-LOOP ENABLED: Encoder Pin Definitions ---
const int ENCODER_A_PIN = 20;
const int ENCODER_B_PIN = 21;

// ------------------------------------------------------------------
// Compile-time polarity configuration for the board sensor.
// ------------------------------------------------------------------
//#define BOARD_SENSOR_ACTIVE_LOW   // sensor reads LOW when tripped
#define BOARD_SENSOR_ACTIVE_HIGH    // sensor reads HIGH (5V) when tripped

// >>> ADDED: honor polarity define
inline bool boardDetected() {
#ifdef BOARD_SENSOR_ACTIVE_LOW
  return digitalRead(BOARD_SENSOR_PIN) == LOW;
#else
  return digitalRead(BOARD_SENSOR_PIN) == HIGH;
#endif
}

// --- Stepper Motor Configuration ---
const float STEPS_PER_REV = 200;
const int   MICROSTEPS   = 1; // Set to 1 for 200 steps/rev (no microstepping)
const float STEPPER_STEPS_PER_REV_TOTAL = STEPS_PER_REV * MICROSTEPS;
const float ENCODER_TICKS_PER_REV       = 4000.0;
const float STEPS_PER_INCH_DEFAULT      = 127.12; 
float stepperStepsPerInch = STEPS_PER_INCH_DEFAULT;
float revs_per_inch       = STEPS_PER_INCH_DEFAULT / STEPPER_STEPS_PER_REV_TOTAL;
float encoderTicksPerInch = ENCODER_TICKS_PER_REV * revs_per_inch;
float tick_to_step_ratio  = stepperStepsPerInch / encoderTicksPerInch;

// --- Global Motor Speed/Acceleration Defaults ---
float defaultMaxSpeedStepsPerSec      = 1000.0;
float defaultAccelerationStepsPerSecSq = 500.0;

// AccelStepper setup
AccelStepper stepper(AccelStepper::DRIVER, STEP_PIN, DIR_PIN);

// --- Closed-Loop Control Variables ---
volatile long encoderPosition = 0;
volatile byte encoderState    = 0;
long encoderTargetPosition    = 0;

// PID Constants
float Kp = 0.1;
float Ki = 0.0;
float Kd = 0.025;
float error = 0;
float previousError = 0;
float integralError = 0;
const long MAX_INTEGRAL_ERROR = 1000;
const int  CORRECTION_THRESHOLD = 40;

// --- Homing and Calibration Variables ---
bool isHomed = false;
unsigned long lastStatusSendTime = 0;
const unsigned long STATUS_SEND_INTERVAL_MS = 250;
const unsigned long MOVING_STATUS_SEND_INTERVAL_MS = 100;
bool pidEnabled = true;
bool currentMonitoringEnabled = false;
float currentLimitAmps = 2.5;
unsigned long currentTripDelayMs = 150;
float filteredMotorCurrentAmps = 0.0;
bool overcurrentTripped = false;
unsigned long overcurrentStartTime = 0;

enum MotorState { IDLE, MOVING_TO_TARGET, HOMING, CALIBRATING, DETECTING_BOARD, OVERCURRENT, ERROR };
MotorState currentMotorState = IDLE;

float currentZeroVoltage = 2.5;
float latestCurrentSensorVoltage = 2.5;
const float ACS712_VOLTS_PER_AMP = 0.100;
const float ADC_VOLTS_PER_COUNT = 5.0 / 1023.0;
const float CURRENT_FILTER_ALPHA = 0.18;

// >>> ADDED: Motion profile support
// 0 = NORMAL, 1 = GENTLE, 2 = FAST  (match HMI PROFILE_MAP)
volatile int activeProfile = 0;

struct MotionProfile {
  float speed; // steps/s
  float accel; // steps/s^2
};

MotionProfile profiles[3];

void initProfiles() {
  profiles[0] = {1000.0,  500.0};   // NORMAL
  profiles[1] = { 150.0,  200.0};   // GENTLE
  profiles[2] = {2500.0, 1500.0};   // FAST
}

// --- Function Prototypes ---
void encoderISR();
void updateClosedLoopControl();
void sendCurrentStatus();
void parseSerialCommand(String command);
void homeStepper();
void performTruingCycle(float sensor_offset);
void performNearCalibration(float sensor_offset);
void setTargetLength(float lengthInches);
void moveRelative(float deltaInches);
void performCalibration(float measuredLength);
void calibrateCurrentZero();
void updateMotorCurrent();
void updateOvercurrentProtection();
void sendAck(char cmdChar, String message);
void sendNack(char cmdChar, String errorMessage);
void sendStatusMessage(String message);
long  inchesToEncoderTicks(float inches);
long  inchesToStepperSteps(float inches);
float encoderTicksToInches(long steps);

// ==============================================================================
// Setup Function
// ==============================================================================
void setup() {
  Serial.begin(115200);
  pinMode(EN_PIN, OUTPUT);
  digitalWrite(EN_PIN, LOW);
  pinMode(HOMING_SENSOR_PIN, INPUT);
  pinMode(BOARD_SENSOR_PIN, INPUT);
  pinMode(CURRENT_SENSOR_PIN, INPUT);

  pinMode(ENCODER_A_PIN, INPUT_PULLUP);
  pinMode(ENCODER_B_PIN, INPUT_PULLUP);
  encoderState = (digitalRead(ENCODER_A_PIN) << 1) | digitalRead(ENCODER_B_PIN);
  attachInterrupt(digitalPinToInterrupt(ENCODER_A_PIN), encoderISR, CHANGE);
  attachInterrupt(digitalPinToInterrupt(ENCODER_B_PIN), encoderISR, CHANGE);

  delay(10);
  calibrateCurrentZero();

  // >>> ADDED: initialize profiles
  initProfiles();
  activeProfile = 0; // NORMAL

  stepper.setMaxSpeed(defaultMaxSpeedStepsPerSec);
  stepper.setAcceleration(defaultAccelerationStepsPerSecSq);
  stepper.setCurrentPosition(0);

  isHomed = false;
  currentMotorState = IDLE;
  sendStatusMessage("System initialized (CLOSED-LOOP). Awaiting commands.");
}

// ==============================================================================
// Main Loop Function
// ==============================================================================
void loop() {
  stepper.run();

  if (Serial.available()) {
    String command = Serial.readStringUntil('\n');
    command.trim();
    parseSerialCommand(command);
  }

  updateMotorCurrent();
  updateClosedLoopControl();
  updateOvercurrentProtection();

  unsigned long now = millis();

  if (currentMotorState == MOVING_TO_TARGET && stepper.distanceToGo() == 0) {
    currentMotorState = IDLE;
    sendCurrentStatus();
    lastStatusSendTime = now;
  } else if (currentMotorState == IDLE) {
    if (now - lastStatusSendTime >= STATUS_SEND_INTERVAL_MS) {
      sendCurrentStatus();
      lastStatusSendTime = now;
    }
  } else if (currentMonitoringEnabled && currentMotorState != OVERCURRENT && currentMotorState != ERROR) {
    if (now - lastStatusSendTime >= MOVING_STATUS_SEND_INTERVAL_MS) {
      sendCurrentStatus();
      lastStatusSendTime = now;
    }
  }
}

void calibrateCurrentZero() {
  const int sampleCount = 200;
  unsigned long total = 0;
  for (int i = 0; i < sampleCount; ++i) {
    total += analogRead(CURRENT_SENSOR_PIN);
    delay(2);
  }
  float averageRaw = (float)total / (float)sampleCount;
  currentZeroVoltage = averageRaw * ADC_VOLTS_PER_COUNT;
  latestCurrentSensorVoltage = currentZeroVoltage;
  filteredMotorCurrentAmps = 0.0;
}

// ==============================================================================
// Encoder Interrupt Service Routine (ISR) - ROBUST VERSION
// ==============================================================================
void encoderISR() {
  static const int8_t lookup_table[] = {0, -1, 1, 0, 1, 0, 0, -1, -1, 0, 0, 1, 0, 1, -1, 0};
  byte currentState = (digitalRead(ENCODER_A_PIN) << 1) | digitalRead(ENCODER_B_PIN);
  byte index = (encoderState << 2) | currentState;
  encoderPosition += lookup_table[index];
  encoderState = currentState;
}

// ==============================================================================
// Closed-Loop Position Control
// ==============================================================================
void updateClosedLoopControl() {
  if (pidEnabled) {
    if (currentMotorState == IDLE && isHomed) {
      error = (float)encoderTargetPosition - (float)encoderPosition;
      if (abs(error) > CORRECTION_THRESHOLD) {
        integralError += error;
        if (integralError > MAX_INTEGRAL_ERROR) integralError = MAX_INTEGRAL_ERROR;
        if (integralError < -MAX_INTEGRAL_ERROR) integralError = -MAX_INTEGRAL_ERROR;
        float derivativeError = error - previousError;
        previousError = error;
        long correction_ticks = (long)(Kp * error + Ki * integralError + Kd * derivativeError);
        long correction_steps = (long)(correction_ticks * tick_to_step_ratio);
        stepper.move(correction_steps);
        sendStatusMessage("Correcting position error...");
      } else {
        integralError = 0;
      }
    } else {
      integralError = 0;
      previousError = 0;
    }
  }
}

// ==============================================================================
// Serial Command Parser
// ==============================================================================
void parseSerialCommand(String command) {
  if (command.length() == 0) return;
  char cmdChar = command.charAt(0);
  String valueStr = command.substring(1);

  switch (cmdChar) {
    case 'S': { float l = valueStr.toFloat(); if (l >= 0.0) { setTargetLength(l); sendAck(cmdChar, "Target set."); } else { sendNack(cmdChar, "Invalid length."); } break; }
    case 'M': { float d = valueStr.toFloat(); moveRelative(d); sendAck(cmdChar, "Relative move."); break; }
    case 'H': homeStepper(); break;
    case 'C': { float m = valueStr.toFloat(); if (m > 0.0) { performCalibration(m); sendAck(cmdChar, "Calibrated."); } else { sendNack(cmdChar, "Invalid length."); } break; }
    case 'P': {
      int c1 = valueStr.indexOf(','), c2 = valueStr.indexOf(',', c1 + 1);
      if (c1 != -1 && c2 != -1) {
        Kp = valueStr.substring(0, c1).toFloat(); Ki = valueStr.substring(c1 + 1, c2).toFloat(); Kd = valueStr.substring(c2 + 1).toFloat();
        sendAck(cmdChar, "PID updated."); sendStatusMessage("New PID: Kp=" + String(Kp) + ", Ki=" + String(Ki) + ", Kd=" + String(Kd));
      } else { sendNack(cmdChar, "Invalid PID format."); } break;
    }
    case 'A': {
      int c = valueStr.indexOf(',');
      if (c != -1) {
        float s = valueStr.substring(0, c).toFloat(), a = valueStr.substring(c + 1).toFloat();
        if (s >= 0 && a >= 0) {
          defaultMaxSpeedStepsPerSec = s; defaultAccelerationStepsPerSecSq = a;
          stepper.setMaxSpeed(s); stepper.setAcceleration(a);
          // >>> ADDED: keep current profile store in sync
          if (activeProfile >= 0 && activeProfile <= 2) {
            profiles[activeProfile].speed = s;
            profiles[activeProfile].accel = a;
          }
          sendAck(cmdChar, "Motor params updated.");
        } else { sendNack(cmdChar, "Invalid speed/accel."); }
      } else { sendNack(cmdChar, "Invalid 'A' format."); } break;
    }
    case 'K': {
      pidEnabled = (valueStr.toInt() == 1);
      sendAck(cmdChar, pidEnabled ? "PID Enabled." : "PID Disabled.");
      break;
    }
    case 'J': {
      float sensor_offset = valueStr.toFloat();
      performTruingCycle(sensor_offset);
      break;
    }
    case 'N': {
      float sensor_offset = valueStr.toFloat();
      if (sensor_offset > 0.0) {
        performNearCalibration(sensor_offset);
      } else {
        sendNack(cmdChar, "Invalid near calibration offset.");
      }
      break;
    }
    case 'T': {
      stepperStepsPerInch = valueStr.toFloat();
      if (encoderTicksPerInch > 0) { tick_to_step_ratio = stepperStepsPerInch / encoderTicksPerInch; }
      sendAck(cmdChar, "Stepper steps/inch updated.");
      break;
    }
    case 'W': {
      if (valueStr == "1") {
        currentMonitoringEnabled = true;
        calibrateCurrentZero();
        overcurrentTripped = false;
        overcurrentStartTime = 0;
        sendAck(cmdChar, "Current monitoring enabled.");
      } else if (valueStr == "0") {
        currentMonitoringEnabled = false;
        filteredMotorCurrentAmps = 0.0;
        latestCurrentSensorVoltage = 0.0;
        overcurrentTripped = false;
        overcurrentStartTime = 0;
        sendAck(cmdChar, "Current monitoring disabled.");
      } else {
        sendNack(cmdChar, "Invalid monitoring toggle.");
      }
      sendCurrentStatus();
      break;
    }
    case 'O': {
      int c = valueStr.indexOf(',');
      if (c != -1) {
        float limitAmps = valueStr.substring(0, c).toFloat();
        unsigned long tripDelay = (unsigned long)valueStr.substring(c + 1).toInt();
        if (limitAmps > 0.0 && tripDelay >= 10) {
          currentLimitAmps = limitAmps;
          currentTripDelayMs = tripDelay;
          overcurrentTripped = false;
          overcurrentStartTime = 0;
          sendAck(cmdChar, "Current protection updated.");
        } else {
          sendNack(cmdChar, "Invalid current protection settings.");
        }
      } else {
        sendNack(cmdChar, "Invalid 'O' format.");
      }
      break;
    }
    case 'R': {
      overcurrentTripped = false;
      overcurrentStartTime = 0;
      digitalWrite(EN_PIN, LOW);
      if (currentMotorState == OVERCURRENT) {
        currentMotorState = IDLE;
      }
      sendAck(cmdChar, "Overcurrent reset.");
      sendCurrentStatus();
      break;
    }
    case 'G': sendCurrentStatus(); break;
    case 'X': stepper.stop(); digitalWrite(EN_PIN, HIGH); currentMotorState = IDLE; overcurrentTripped = false; sendAck(cmdChar, "Motor Disabled."); break;
    case 'E': digitalWrite(EN_PIN, LOW); isHomed = false; overcurrentTripped = false; currentMotorState = IDLE; sendAck(cmdChar, "Motor Enabled."); sendCurrentStatus(); break;

    // >>> ADDED: Z# profile select
    case 'Z': {
      int p = valueStr.toInt();  // 0..2 expected
      if (p >= 0 && p <= 2) {
        activeProfile = p;
        sendAck(cmdChar, "Active profile changed.");
        // Optional: immediately apply stored params for this profile.
        // The HMI also sends A<speed,accel> right after Z, so either way is fine.
        stepper.setMaxSpeed(profiles[p].speed);
        stepper.setAcceleration(profiles[p].accel);
      } else {
        sendNack(cmdChar, "Invalid profile index.");
      }
      break;
    }

    default: sendNack('?', "Unknown command."); break;
  }
}

// ==============================================================================
// Stepper Movement Functions
// ==============================================================================
void updateMotorCurrent() {
  if (!currentMonitoringEnabled) {
    latestCurrentSensorVoltage = 0.0;
    filteredMotorCurrentAmps = 0.0;
    return;
  }
  int raw = analogRead(CURRENT_SENSOR_PIN);
  float sensedVoltage = raw * ADC_VOLTS_PER_COUNT;
  latestCurrentSensorVoltage = sensedVoltage;
  float instantCurrent = abs(sensedVoltage - currentZeroVoltage) / ACS712_VOLTS_PER_AMP;
  if (instantCurrent < 0.03) instantCurrent = 0.0;
  filteredMotorCurrentAmps += (instantCurrent - filteredMotorCurrentAmps) * CURRENT_FILTER_ALPHA;
}

void updateOvercurrentProtection() {
  if (!currentMonitoringEnabled) {
    overcurrentStartTime = 0;
    overcurrentTripped = false;
    return;
  }
  bool motorMoving = (currentMotorState == MOVING_TO_TARGET || currentMotorState == HOMING || currentMotorState == DETECTING_BOARD || currentMotorState == CALIBRATING);
  if (!motorMoving || overcurrentTripped) {
    overcurrentStartTime = 0;
    return;
  }

  if (filteredMotorCurrentAmps > currentLimitAmps) {
    if (overcurrentStartTime == 0) {
      overcurrentStartTime = millis();
    } else if ((millis() - overcurrentStartTime) >= currentTripDelayMs) {
      stepper.stop();
      digitalWrite(EN_PIN, HIGH);
      currentMotorState = OVERCURRENT;
      overcurrentTripped = true;
      sendStatusMessage("OVERCURRENT trip. Motor shut down.");
      sendCurrentStatus();
    }
  } else {
    overcurrentStartTime = 0;
  }
}

void setTargetLength(float lengthInches) {
  if (!isHomed) { sendStatusMessage("ERROR: Not homed!"); sendNack('S', "Not homed."); return; }
  encoderTargetPosition = inchesToEncoderTicks(lengthInches);
  stepper.moveTo(inchesToStepperSteps(lengthInches));
  currentMotorState = MOVING_TO_TARGET;
  sendCurrentStatus(); 
}

void moveRelative(float deltaInches) {
  if (!isHomed) { sendStatusMessage("ERROR: Not homed!"); sendNack('M', "Not homed."); return; }
  encoderTargetPosition = encoderPosition + inchesToEncoderTicks(deltaInches);
  stepper.move(inchesToStepperSteps(deltaInches));
  currentMotorState = MOVING_TO_TARGET;
  sendCurrentStatus();
}

void performTruingCycle(float sensor_offset) {
  if (!isHomed) { sendStatusMessage("ERROR: Must home before starting cycle."); return; }
  
  sendAck('J', "Starting truing cycle...");
  currentMotorState = DETECTING_BOARD;
  sendCurrentStatus();
  
  stepper.moveTo(0);
  while (!boardDetected() && stepper.distanceToGo() != 0) {
    stepper.run();
  }

  float truing_cut_overlap = 0.25;
  float detected_pos_inches = encoderTicksToInches(encoderPosition);
  float final_truing_pos = detected_pos_inches - sensor_offset + truing_cut_overlap;
  
  setTargetLength(final_truing_pos);
}

void performNearCalibration(float sensor_offset) {
  if (!isHomed) { sendStatusMessage("ERROR: Must home before near calibration."); sendNack('N', "Not homed."); return; }

  sendAck('N', "Near calibration started.");
  currentMotorState = DETECTING_BOARD;
  sendCurrentStatus();

  float savedSpeed = profiles[activeProfile].speed;
  float savedAccel = profiles[activeProfile].accel;
  const float nearBounceBackInches = 1.0;
  const float nearFinalApproachInches = 1.5;

  // Mirror the standard homing sequence: fast approach, back off, slow approach.
  stepper.setMaxSpeed(300.0);
  stepper.setAcceleration(1200.0);
  stepper.moveTo(0);
  while (!boardDetected() && stepper.distanceToGo() != 0) {
    stepper.run();
  }
  stepper.stop();

  if (!boardDetected()) {
    currentMotorState = ERROR;
    sendNack('N', "Board sensor not detected.");
    sendCurrentStatus();
  } else {
    stepper.move(nearBounceBackInches * stepperStepsPerInch);
    while (boardDetected() && stepper.distanceToGo() != 0) {
      stepper.run();
    }
    stepper.stop();

    if (boardDetected()) {
      currentMotorState = ERROR;
      sendNack('N', "Board sensor did not clear after bounce back.");
      sendCurrentStatus();
      stepper.setMaxSpeed(savedSpeed);
      stepper.setAcceleration(savedAccel);
      return;
    }

    stepper.setMaxSpeed(100.0);
    stepper.setAcceleration(50.0);
    stepper.move(-nearFinalApproachInches * stepperStepsPerInch);
    while (!boardDetected() && stepper.distanceToGo() != 0) {
      stepper.run();
    }
    stepper.stop();

    if (!boardDetected()) {
      currentMotorState = ERROR;
      sendNack('N', "Board sensor lost on final approach.");
      sendCurrentStatus();
      stepper.setMaxSpeed(savedSpeed);
      stepper.setAcceleration(savedAccel);
      return;
    }

    long near_ticks = inchesToEncoderTicks(sensor_offset);
    long near_steps = inchesToStepperSteps(sensor_offset);
    stepper.setCurrentPosition(near_steps);
    encoderPosition = near_ticks;
    encoderTargetPosition = near_ticks;
    currentMotorState = IDLE;
    sendStatusMessage("Near calibration complete.");
    sendAck('N', "Near calibration completed successfully.");
    sendCurrentStatus();
  }

  stepper.setMaxSpeed(savedSpeed);
  stepper.setAcceleration(savedAccel);
}

// ==============================================================================
// Homing Sequence
// ==============================================================================
void homeStepper() {
  const float HOME_POSITION_INCHES = 160.5;
  sendAck('H', "Homing started.");
  currentMotorState = HOMING;
  sendCurrentStatus();

  // Use a conservative homing profile
  stepper.setMaxSpeed(300);
  stepper.setAcceleration(1200);
  stepper.move(stepperStepsPerInch * 200);
  while (digitalRead(HOMING_SENSOR_PIN) == LOW && stepper.distanceToGo() != 0) { stepper.run(); }
  stepper.stop();

  stepper.move(-stepperStepsPerInch * 0.5); 
  while (stepper.distanceToGo() != 0) { stepper.run(); }
  stepper.stop();

  stepper.setMaxSpeed(100);
  stepper.setAcceleration(50);
  stepper.move(stepperStepsPerInch * 1);
  while (digitalRead(HOMING_SENSOR_PIN) == LOW && stepper.distanceToGo() != 0) { stepper.run(); }
  stepper.stop();
  
  long home_position_ticks = inchesToEncoderTicks(HOME_POSITION_INCHES);
  long home_position_steps = inchesToStepperSteps(HOME_POSITION_INCHES);
  stepper.setCurrentPosition(home_position_steps);
  encoderPosition = home_position_ticks;
  encoderTargetPosition = home_position_ticks;
  
  isHomed = true;
  currentMotorState = IDLE;
  
  // Send the configured home position to the HMI
  sendStatusMessage("HOME_POS:" + String(HOME_POSITION_INCHES));
  
  sendAck('H', "Homing completed successfully.");
  sendCurrentStatus();

  // Restore whatever profile params were last active
  stepper.setMaxSpeed(profiles[activeProfile].speed);
  stepper.setAcceleration(profiles[activeProfile].accel);
}

// ==============================================================================
// Calibration Routine
// ==============================================================================
void performCalibration(float measuredLength) {
  if (!isHomed) { sendStatusMessage("ERROR: Cannot calibrate, not homed!"); sendNack('C', "Not homed."); return; }
  if (measuredLength > 0 && encoderPosition != 0) {
    long current_stepper_pos = abs(stepper.currentPosition());
    long current_encoder_pos = abs(encoderPosition);
    encoderTicksPerInch = (float)current_encoder_pos / measuredLength;
    stepperStepsPerInch = (float)current_stepper_pos / measuredLength;
    if (current_encoder_pos > 0) {
      tick_to_step_ratio = (float)current_stepper_pos / (float)current_encoder_pos;
    }
    sendStatusMessage("CAL_SUCCESS:" + String(encoderTicksPerInch, 4) + "," + String(stepperStepsPerInch, 4));
    currentMotorState = IDLE;
  } else {
    sendNack('C', "Invalid length or position for calibration.");
  }
}

// ==============================================================================
// Serial Communication Helper Functions
// ==============================================================================
void sendCurrentStatus() {
  error = (float)encoderTargetPosition - (float)encoderPosition;
  float currentPositionInches = encoderTicksToInches(encoderPosition);
  float currentSpeed = abs(stepper.speed());

  Serial.print("POS:"); Serial.print(currentPositionInches, 4);
  Serial.print(",HOMED:"); Serial.print(isHomed ? "1" : "0");
  Serial.print(",SEN:"); Serial.print(digitalRead(HOMING_SENSOR_PIN));
  Serial.print(",BSEN:"); Serial.print(boardDetected() ? 1 : 0);
  if (currentMonitoringEnabled) {
    Serial.print(",CV:"); Serial.print(latestCurrentSensorVoltage, 3);
    Serial.print(",CUR:"); Serial.print(filteredMotorCurrentAmps, 2);
    Serial.print(",OCT:"); Serial.print(overcurrentTripped ? "1" : "0");
  }
  Serial.print(",ERR:"); Serial.print(error, 2);
  Serial.print(",SPD:"); Serial.print(currentSpeed, 0);
  // >>> ADDED: expose active profile to HMI
  Serial.print(",PROF:"); Serial.print(activeProfile);
  Serial.print(",STATE:");
  switch(currentMotorState) {
    case IDLE: Serial.print("IDLE"); break;
    case MOVING_TO_TARGET: Serial.print("MOVING"); break;
    case HOMING: Serial.print("HOMING"); break;
    case CALIBRATING: Serial.print("CALIBRATING"); break;
    case DETECTING_BOARD: Serial.print("DETECTING"); break;
    case OVERCURRENT: Serial.print("OVERCURRENT"); break;
    case ERROR: Serial.print("ERROR"); break;
  }
  Serial.println();
}

void sendAck(char cmdChar, String message)   { Serial.print("ACK:");  Serial.print(cmdChar); Serial.print(":"); Serial.println(message); }
void sendNack(char cmdChar, String errorMessage) { Serial.print("NACK:"); Serial.print(cmdChar); Serial.print(":"); Serial.println(errorMessage); }
void sendStatusMessage(String message)       { Serial.print("STATUS:"); Serial.println(message); }

// ==============================================================================
// Unit Conversion Functions
// ==============================================================================
long  inchesToEncoderTicks(float inches) { return (long)(inches * encoderTicksPerInch); }
long  inchesToStepperSteps(float inches) { return (long)(inches * stepperStepsPerInch); }
float encoderTicksToInches(long steps)   { if (encoderTicksPerInch == 0) return 0.0; return (float)steps / encoderTicksPerInch; }
