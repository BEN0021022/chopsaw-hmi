"""Command-line entry point for the sensor bench."""

import argparse
import sys

from PyQt6.QtWidgets import QApplication

from .window import SensorBenchWindow


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Chop Saw sensor bench")
    parser.add_argument("--demo", action="store_true", help="run without hardware using simulated telemetry")
    args = parser.parse_args()

    app = QApplication(sys.argv[:1])
    app.setApplicationName("Chop Saw Sensor Bench")
    window = SensorBenchWindow()
    window.show()
    if args.demo:
        window.start_demo()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
