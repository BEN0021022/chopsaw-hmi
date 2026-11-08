"""Compile and run the firmware's actual C++ interlock policy on the host.

Uses g++, clang++, or a locally supplied Zig toolchain. The optional portable
Zig installation in tmp/native-compiler is not an application dependency.
"""
import os
from pathlib import Path
import shutil
import subprocess


def main():
    root = Path(__file__).resolve().parent
    output_dir = root / "tmp" / "firmware-tests"
    output_dir.mkdir(parents=True, exist_ok=True)
    compiler = shutil.which("g++") or shutil.which("clang++")
    if compiler:
        command = [compiler]
    else:
        zig = root / "tmp" / "native-compiler" / "ziglang" / "zig.exe"
        if not zig.exists():
            raise SystemExit("Install a C++ compiler, or pip install --target tmp/native-compiler ziglang==0.14.1")
        command = [str(zig), "c++", "-target", "x86_64-windows-gnu"]
    for name in ("test_bench_interlocks", "test_bench_commands", "test_controller_commands", "test_homing", "test_positioning", "test_motion_profiles"):
        exe = output_dir / (name + (".exe" if os.name == "nt" else ""))
        subprocess.run(command + ["-std=c++11", "-Wall", "-Wextra", "-Werror",
                       "-I", str(root / "tests" / "firmware" / "stubs"),
                       str(root / "tests" / "firmware" / (name + ".cpp")),
                       "-o", str(exe)], check=True, cwd=root)
        subprocess.run([str(exe)], check=True, cwd=root)


if __name__ == "__main__":
    main()
