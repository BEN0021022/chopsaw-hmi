"""Parser for the sensor-bench firmware and the earlier validation sketch."""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class ParsedMessage:
    kind: str
    fields: dict[str, str]
    raw: str


def _fields(parts: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for part in parts:
        if ":" not in part:
            continue
        key, value = part.split(":", 1)
        values[key.strip().upper()] = value.strip()
    return values


def parse_line(line: str) -> ParsedMessage | None:
    """Parse one line without raising on malformed or future protocol fields."""
    raw = line.strip()
    if not raw:
        return None

    parts = [part.strip() for part in raw.split(",")]
    tag = parts[0].upper()
    if tag.startswith("BENCH_"):
        return ParsedMessage(tag, _fields(parts[1:]), raw)

    # Compatibility with the temporary validation firmware used during initial
    # board bring-up. This lets the HMI prove the connection before the current
    # guarded-output sketch is flashed.
    match = re.fullmatch(r"I2C:\s*FOUND\s+(0X[0-9A-F]+)", raw.upper())
    if match:
        return ParsedMessage("LEGACY_I2C_FOUND", {"ADDRESS": match.group(1)}, raw)

    if raw.startswith("KLF_IO,"):
        values: dict[str, str] = {}
        for item in raw.split(",")[1:]:
            if ":" not in item:
                continue
            name, value = item.split(":", 1)
            name = name.split("[", 1)[0].strip().upper()
            values[name] = value.strip()
        return ParsedMessage("LEGACY_INPUTS", values, raw)

    return ParsedMessage("TEXT", {}, raw)


def parse_int(value: str | None, default: int | None = None) -> int | None:
    if value is None:
        return default
    try:
        return int(value, 0)
    except (TypeError, ValueError):
        return default
