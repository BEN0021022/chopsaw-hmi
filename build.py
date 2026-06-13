#!/usr/bin/env python
# build.py
#
# Publish a new Chop Saw HMI release to GitHub Releases.
#
#   python build.py                      # build current version, publish
#   python build.py patch                # 1.0.0 -> 1.0.1, build, publish
#   python build.py minor                # 1.0.0 -> 1.1.0
#   python build.py major                # 1.0.0 -> 2.0.0
#   python build.py patch --notes "..."  # set release notes
#   python build.py --no-publish         # build only, skip GitHub
#   python build.py --no-bump            # don't change the version
#
# Requires the GitHub CLI (`gh`) authenticated as the repo owner:
#   gh auth login
# On the first publish for a new repo, pass --create-repo to make it.

import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VERSION_FILE = ROOT / "_version.py"
SPEC_FILE = ROOT / "ChopSawHMI.spec"
DIST_EXE = ROOT / "dist" / "ChopSawHMI.exe"

GITHUB_OWNER = "BEN0021022"
GITHUB_REPO = "chopsaw-hmi"
REPO_SLUG = f"{GITHUB_OWNER}/{GITHUB_REPO}"


def read_version():
    text = VERSION_FILE.read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', text)
    if not m:
        raise SystemExit("Could not find __version__ in _version.py")
    return m.group(1)


def write_version(version):
    text = VERSION_FILE.read_text(encoding="utf-8")
    text = re.sub(r'__version__\s*=\s*["\'][^"\']+["\']',
                  f'__version__ = "{version}"', text)
    VERSION_FILE.write_text(text, encoding="utf-8")


def bump_version(current, part):
    nums = [int(x) for x in current.split(".")]
    while len(nums) < 3:
        nums.append(0)
    major, minor, patch = nums[:3]
    if part == "major":
        major, minor, patch = major + 1, 0, 0
    elif part == "minor":
        minor, patch = minor + 1, 0
    elif part == "patch":
        patch += 1
    return f"{major}.{minor}.{patch}"


def run(cmd, **kw):
    print(f"$ {' '.join(str(c) for c in cmd)}")
    return subprocess.run(cmd, check=True, **kw)


def build_exe():
    run([sys.executable, "-m", "PyInstaller", str(SPEC_FILE), "--noconfirm"], cwd=str(ROOT))
    if not DIST_EXE.exists():
        raise SystemExit(f"Build did not produce {DIST_EXE}")


def write_sha256(exe_path):
    digest = hashlib.sha256(exe_path.read_bytes()).hexdigest()
    sha_path = exe_path.with_name(exe_path.name + ".sha256")
    sha_path.write_text(f"{digest}  {exe_path.name}\n", encoding="utf-8")
    print(f"SHA-256: {digest}")
    return sha_path


def gh_available():
    try:
        subprocess.run(["gh", "--version"], check=True, capture_output=True)
        return True
    except Exception:
        return False


def repo_exists():
    try:
        subprocess.run(["gh", "repo", "view", REPO_SLUG],
                       check=True, capture_output=True)
        return True
    except Exception:
        return False


def publish_release(version, notes, exe_path, sha_path, create_repo):
    if not gh_available():
        raise SystemExit("GitHub CLI (gh) not found. Install it and run `gh auth login`.")
    if not repo_exists():
        if not create_repo:
            raise SystemExit(
                f"Repo {REPO_SLUG} not found. Re-run with --create-repo to create it.")
        run(["gh", "repo", "create", REPO_SLUG, "--public",
             "--source", str(ROOT), "--remote", "origin", "--push"])

    tag = f"v{version}"
    release_notes = notes or f"Release {version}"
    run(["gh", "release", "create", tag,
         str(exe_path), str(sha_path),
         "--repo", REPO_SLUG,
         "--title", tag,
         "--notes", release_notes])
    print(f"\nPublished {tag} to https://github.com/{REPO_SLUG}/releases/tag/{tag}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("part", nargs="?", choices=["major", "minor", "patch"],
                    help="version part to bump")
    ap.add_argument("--no-bump", action="store_true", help="don't change the version")
    ap.add_argument("--no-publish", action="store_true", help="build only")
    ap.add_argument("--notes", default="", help="release notes")
    ap.add_argument("--create-repo", action="store_true",
                    help="create the GitHub repo if it doesn't exist (first publish)")
    args = ap.parse_args()

    version = read_version()
    if args.part and not args.no_bump:
        version = bump_version(version, args.part)
        write_version(version)
        print(f"Version bumped to {version}")
    else:
        print(f"Building version {version}")

    build_exe()
    sha_path = write_sha256(DIST_EXE)

    if args.no_publish:
        print("Build complete (publish skipped).")
        return
    publish_release(version, args.notes, DIST_EXE, sha_path, args.create_repo)


if __name__ == "__main__":
    main()
