# updater.py
#
# GitHub-Releases auto-updater for the Chop Saw HMI.
#
# Unlike a OneDrive/local-file updater, the new EXE is not already on disk. The
# flow is:
#   1. check_for_update()  -> read the latest GitHub Release over HTTPS, compare
#                             its tag to the running version.
#   2. download_update()   -> download the EXE asset into a local cache folder
#                             and (if a .sha256 asset is published) verify it.
#   3. schedule_update()   -> write _update.bat beside the running EXE, which
#                             waits for the app to exit, swaps the EXE, restarts.
#
# Stdlib only (urllib/json/hashlib) so nothing extra is bundled by PyInstaller.
# All network/parse errors are swallowed and reported as "no update" so a
# missing internet connection never disrupts startup.

import hashlib
import json
import os
import ssl
import subprocess
import sys
import urllib.request
from pathlib import Path

# ---- Per-project constants ------------------------------------------------
GITHUB_OWNER = "BEN0021022"
GITHUB_REPO = "chopsaw-hmi"
APP_EXE_NAME = "ChopSawHMI.exe"
# ---------------------------------------------------------------------------

API_LATEST = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
USER_AGENT = f"{APP_EXE_NAME}-updater"
DEFAULT_TIMEOUT = 8.0


def _ssl_context():
    """
    Build an SSL context with a CA bundle that works inside a frozen
    PyInstaller .exe. The bundled app has no system cert store, so verifying
    GitHub's HTTPS cert fails with CERTIFICATE_VERIFY_FAILED unless we point
    at certifi's bundled CA file. Falls back to the system default when running
    from source. Verification is always ON (never disabled).
    """
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _current_version():
    """Running app version from _version.py; '0.0.0' if it can't be read."""
    try:
        from _version import __version__
        return str(__version__)
    except Exception:
        return "0.0.0"


def _parse_version(v):
    """'v1.2.50' or '1.2.50' -> (1, 2, 50). Non-numeric parts -> (0,)."""
    try:
        text = str(v).strip().lstrip("vV")
        parts = text.split(".")
        return tuple(int(p) for p in parts)
    except (TypeError, ValueError):
        return (0,)


def update_cache_dir():
    """Per-user folder for downloaded installers (writable, survives restarts)."""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP") or os.getcwd()
    path = Path(base) / "ChopSawHMI" / "updates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _http_get(url, timeout, accept="application/vnd.github+json"):
    """GET a URL with the headers GitHub requires; returns raw bytes."""
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": accept,
    })
    context = _ssl_context()
    with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
        return resp.read()


def check_for_update(timeout=DEFAULT_TIMEOUT):
    """
    Read the latest published GitHub Release and decide whether it is newer.

    Returns a dict when a newer version with a downloadable EXE exists:
        {
          "version": "1.0.1",
          "download_url": "https://github.com/.../ChopSawHMI.exe",
          "sha256_url": "https://github.com/.../ChopSawHMI.exe.sha256" or None,
          "size": 36700160,
          "notes": "Release notes body",
        }
    Returns None when up to date, offline, or anything goes wrong.
    """
    try:
        data = json.loads(_http_get(API_LATEST, timeout).decode("utf-8"))
    except Exception:
        return None

    if data.get("draft") or data.get("prerelease"):
        return None

    latest = data.get("tag_name") or data.get("name") or "0.0.0"
    if _parse_version(latest) <= _parse_version(_current_version()):
        return None

    assets = data.get("assets") or []
    exe_asset = next(
        (a for a in assets if str(a.get("name", "")).lower().endswith(".exe")), None
    )
    if not exe_asset or not exe_asset.get("browser_download_url"):
        return None

    sha_asset = next(
        (a for a in assets if str(a.get("name", "")).lower().endswith(".sha256")), None
    )

    return {
        "version": str(latest).lstrip("vV"),
        "download_url": exe_asset["browser_download_url"],
        "sha256_url": sha_asset.get("browser_download_url") if sha_asset else None,
        "size": int(exe_asset.get("size", 0)),
        "notes": (data.get("body") or "").strip(),
    }


def _expected_sha(sha256_url, timeout):
    """Fetch and parse a published .sha256 file ('<hex>  filename' or '<hex>')."""
    if not sha256_url:
        return None
    try:
        text = _http_get(sha256_url, timeout, accept="text/plain").decode("utf-8")
        token = text.strip().split()[0].lower()
        return token if len(token) == 64 else None
    except Exception:
        return None


def download_update(info, progress_cb=None, timeout=60.0):
    """
    Download the release EXE into the update cache, verifying the published
    SHA-256 if one is available. progress_cb(downloaded, total) is called as
    bytes arrive. Returns the local Path on success, or None on failure /
    checksum mismatch (a mismatched partial file is deleted).
    """
    url = info.get("download_url")
    if not url:
        return None
    dest = update_cache_dir() / APP_EXE_NAME
    expected = _expected_sha(info.get("sha256_url"), timeout)
    hasher = hashlib.sha256()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        context = _ssl_context()
        with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
            total = int(resp.headers.get("Content-Length") or info.get("size") or 0)
            downloaded = 0
            with open(dest, "wb") as f:
                while True:
                    chunk = resp.read(262144)
                    if not chunk:
                        break
                    f.write(chunk)
                    hasher.update(chunk)
                    downloaded += len(chunk)
                    if progress_cb:
                        progress_cb(downloaded, total)
    except Exception:
        return None

    if expected and hasher.hexdigest().lower() != expected:
        try:
            dest.unlink()
        except OSError:
            pass
        return None
    return dest


def schedule_update(new_exe):
    """
    Write and launch _update.bat beside the running EXE. The batch waits for
    this process to exit, copies new_exe over the current EXE, and restarts it.
    Only works in a frozen PyInstaller build; returns False in dev mode or on
    any failure.
    """
    if not getattr(sys, "frozen", False):
        return False
    try:
        current_exe = Path(sys.executable)
        new_exe = Path(new_exe)
        install_dir = current_exe.parent
        batch = install_dir / "_update.bat"
        pid = os.getpid()

        script = f"""@echo off
setlocal
:waitloop
tasklist /FI "PID eq {pid}" 2>NUL | find "{pid}" >NUL
if not errorlevel 1 (
    timeout /t 1 /nobreak >NUL
    goto waitloop
)
timeout /t 2 /nobreak >NUL
copy /Y "{new_exe}" "{current_exe}" >NUL
set PYINSTALLER_RESET_ENVIRONMENT=1
set _MEIPASS2=
set _PYI_APPLICATION_HOME_DIR=
set _PYI_ARCHIVE_FILE=
set _PYI_PARENT_PROCESS_LEVEL=
start "" /D "{install_dir}" "{current_exe}"
del "%~f0"
"""
        batch.write_text(script, encoding="utf-8")
        subprocess.Popen(
            ["cmd", "/c", str(batch)],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            cwd=str(install_dir),
        )
        return True
    except Exception:
        return False
