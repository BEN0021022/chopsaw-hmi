"""Replay real C++ sketch output into the real Qt panel; no hardware access.

Called by test_bench_interlocks.py after compiling the mock controller emitter.
"""
import os
import sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication
from teensy_carriage import TeensyCarriagePanel


def main():
    app = QApplication.instance() or QApplication([])
    writes = []
    panel = TeensyCarriagePanel(lambda line: writes.append(line) or True, lambda line: None)
    panel.timer.stop()
    panel.session(True)
    panel.consent.setChecked(True)
    count = 0
    saw_capture = False
    for line in sys.stdin:
        panel.handle_line(line)
        assert not panel.local_fault, (panel.local_fault, line)
        if line.startswith("BENCH_X,"):
            count += 1
            saw_capture |= panel.x.get("EDGE_VALID") == "1"
    assert panel.compatible and panel.ready_link()
    assert count > 10 and saw_capture
    assert panel.x["PROFILE_ID"] == "2" and panel.x["POS_KNOWN"] == "1"
    assert panel.x["MOVE_KIND"] == "ABSOLUTE" and panel.x["EDGE_VALID"] == "0"
    assert not writes, "Read-only replay cannot generate motion commands"
    panel.session(False)
    panel.close()
    print(f"Real sketch -> Qt protocol replay: {count} motion records passed")


if __name__ == "__main__":
    main()
