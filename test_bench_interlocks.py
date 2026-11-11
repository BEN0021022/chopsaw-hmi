"""Compile and run the firmware's actual C++ interlock policy on the host.

Uses g++, clang++, or a locally supplied Zig toolchain. The optional portable
Zig installation in tmp/native-compiler is not an application dependency.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parent
    output_dir = root / "tmp" / "firmware-tests"
    output_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable,str(root/'test_automation_supervision.py')],check=True,cwd=root)
    subprocess.run([sys.executable,str(root/'test_machine_preview.py')],check=True,cwd=root)
    subprocess.run([sys.executable,str(root/'test_cut_history.py')],check=True,cwd=root)
    subprocess.run([sys.executable,str(root/'test_machine_workbench.py')],check=True,cwd=root)
    compiler = shutil.which("g++") or shutil.which("clang++")
    if compiler:
        command = [compiler]
    else:
        zig = root / "tmp" / "native-compiler" / "ziglang" / "zig.exe"
        if not zig.exists():
            raise SystemExit("Install a C++ compiler, or pip install --target tmp/native-compiler ziglang==0.14.1")
        command = [str(zig), "c++", "-target", "x86_64-windows-gnu"]
    for name in ("test_bench_interlocks", "test_bench_commands", "test_controller_commands", "test_homing", "test_positioning", "test_motion_profiles", "test_edge_search", "test_dry_run"):
        exe = output_dir / (name + (".exe" if os.name == "nt" else ""))
        subprocess.run(command + ["-std=c++11", "-Wall", "-Wextra", "-Werror",
                       "-I", str(root / "tests" / "firmware" / "stubs"),
                       str(root / "tests" / "firmware" / (name + ".cpp")),
                       "-o", str(exe)], check=True, cwd=root)
        subprocess.run([str(exe)], check=True, cwd=root)
    emitter = output_dir / ("emit_controller_records.exe" if os.name == "nt" else "emit_controller_records")
    subprocess.run(command + ["-std=c++11", "-Wall", "-Wextra", "-Werror",
                   "-I", str(root / "tests" / "firmware" / "stubs"),
                   str(root / "tests" / "firmware" / "emit_controller_records.cpp"),
                   "-o", str(emitter)], check=True, cwd=root)
    records = subprocess.run([str(emitter)], check=True, cwd=root, capture_output=True, text=True)
    subprocess.run([sys.executable, str(root / "test_teensy_protocol_records.py")],
                   input=records.stdout, text=True, check=True, cwd=root)
    server = output_dir / ("dry_run_server.exe" if os.name == "nt" else "dry_run_server")
    subprocess.run(command + ["-std=c++11", "-Wall", "-Wextra", "-Werror",
                   "-I", str(root / "tests" / "firmware" / "stubs"),
                   str(root / "tests" / "firmware" / "dry_run_server.cpp"),
                   "-o", str(server)], check=True, cwd=root)
    subprocess.run([sys.executable, str(root / "test_native_dry_run.py"), str(server)], check=True, cwd=root)


if __name__ == "__main__":
    main()
