# Controller Protocol

Status: Sensor Bench Protocol v2 is implemented. It adds three tightly guarded
clamp-test outputs to the Protocol v1 input telemetry. Motion and production
machine commands remain undefined and blocked.

## Transport

- USB serial, 115200 baud, 8 data bits, no parity, 1 stop bit.
- UTF-8/ASCII text records terminated by LF; CR before LF is accepted.
- Maximum firmware command length is 63 characters.
- Record fields are comma separated. The first field is the record type; later
  fields use `NAME:value` format.
- Parsers must ignore unknown fields and record types.

## Identity and capabilities

```text
BENCH_HELLO,PROTO:2,FW:0.2.0,BOARD:TEENSY41,MAP:T41U5XBB_V2_20,MOTION:0,TEST_OUTPUTS:3
```

`MOTION:0` means no motion command is available. `TEST_OUTPUTS:3` means only the
three clamp commissioning outputs are available. It does not imply that valve
loads, air pressure, or automatic clamping are approved.

## Accepted commands

Commands are case-insensitive. Repeated read commands are safe.

| Command | Response/purpose |
|---|---|
| `HELLO` | `BENCH_HELLO` identity |
| `PING` | `BENCH_PONG` with controller uptime |
| `PINMAP` | `BENCH_PINMAP` input and clamp-test assignments |
| `I2C` | `BENCH_I2C`, MCP input reconfiguration, then health |
| `STATUS` | Current hello, health, inputs, MCP state, and output state |
| `ARM 1` | Turn every clamp output OFF, clear the output fault, arm testing, and publish `BENCH_OUTPUTS` |
| `ARM 0` | Turn every clamp output OFF, disarm, and publish state |
| `KEEPALIVE` | Refresh the 1.5-second output watchdog while armed |
| `OUT n 1` | Energize clamp output `n` (0-2) only while armed |
| `OUT n 0` | De-energize output `n`; accepted even while disarmed |
| `OFF` | Turn all outputs OFF and disarm |

The Python transport accepts only these exact forms. Firmware blocks enable,
g-code, and grbl commands with `BENCH_ERROR,CODE:COMMAND_BLOCKED`. A malformed
output command disarms everything and reports `BAD_OUTPUT_COMMAND`. An ON
command while disarmed reports `NOT_ARMED`.

## Telemetry

Direct and MCP input records are emitted every 200 ms; health records are
emitted every 1000 ms. Output state is published on status and every output,
arm, disarm, or output-safety transition.

```text
BENCH_HEALTH,SEQ:42,UP_MS:8400,MCP_ACK:1,MCP_IO:1,INA_ACK:1,INA_ID:1,INA_MFG:0x5449,INA_DEV:0x228,INA_REV:1
BENCH_INPUTS,SEQ:42,HOME:1,BOARD_EDGE:0,FENCE_DOOR:1,CL57T_ALM:1,SAW_UP:1,SAW_DOWN:1,FENCE_CLOSED:1,OUTFEED:1
BENCH_MCP,SEQ:42,OK:1,GPIOA:0xFF,GPIOB:0xFF
BENCH_OUTPUTS,ARMED:1,CLAMP1:0,CLAMP2:0,CLAMP3:0,FAULT:NONE
BENCH_I2C,COUNT:2,ADDRS:0x27|0x40
```

- Direct and MCP values are raw electrical levels.
- `MCP_ACK`/`INA_ACK` prove address acknowledgment only.
- `MCP_IO` proves a GPIO register read completed.
- `INA_ID` proves the manufacturer and device IDs match an INA228.
- `FAULT` is `NONE`, `WATCHDOG`, `MAX_ON`, or `COMMAND`.
- INA228 measurement values are deferred until the shunt range and measured
  branch are final.

## Output safety state

D31-D33 are latched LOW before firmware changes them to output mode. All are OFF
and disarmed after boot. Arming never energizes an output. While armed, the HMI
sends `KEEPALIVE` every 500 ms. Firmware turns every output OFF and disarms if:

- no keepalive arrives for 1.5 seconds;
- one output stays energized for more than 5 seconds;
- `OFF` or `ARM 0` is received; or
- a malformed or blocked control command is received.

The HMI also sends `OFF` before an intentional disconnect, on window close, and
when telemetry becomes stale. Firmware timing is authoritative if the HMI or USB
connection fails. These protections do not replace a hardwired E-stop, safety
relay/contactor, pneumatic dump, guarding, branch fuse, or valve-coil flyback
suppression.

## Compatibility input

The Python parser still accepts the original Protocol v1 records and the prior
validation sketch's `KLF_IO` and `I2C: found 0xNN` display records. Old firmware
does not announce `TEST_OUTPUTS:3`, so the HMI keeps every output control disabled.

## Deferred production protocol

Position, acknowledged motion queues, production clamp sequencing, saw control,
actuator commands, normalized current telemetry, and grblHAL status remain
deferred. They require a separate reviewed production protocol and independent
machine-safety layers.
