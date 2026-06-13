# test_updater.py
#
# Client-side updater logic, exercised against a mocked GitHub API so no
# network is needed. Run: python test_updater.py

import hashlib
import json

import updater


def _release_json(tag, exe_url, size, sha_url=None, draft=False, prerelease=False):
    assets = [{"name": "ChopSawHMI.exe", "browser_download_url": exe_url, "size": size}]
    if sha_url:
        assets.append({"name": "ChopSawHMI.exe.sha256", "browser_download_url": sha_url})
    return json.dumps({
        "tag_name": tag, "body": "Test notes", "draft": draft,
        "prerelease": prerelease, "assets": assets,
    }).encode("utf-8")


def test_parse_version():
    assert updater._parse_version("1.2.50") == (1, 2, 50)
    assert updater._parse_version("v1.2.50") == (1, 2, 50)
    assert updater._parse_version("1.2.0-beta") == (0,)
    assert updater._parse_version("garbage") == (0,)
    assert updater._parse_version("2.0.0") > updater._parse_version("1.9.9")
    print("parse_version OK")


def test_newer_version_detected(monkeypatch):
    monkeypatch(updater, "_current_version", lambda: "1.0.0")
    payload = _release_json("v1.0.1", "https://x/ChopSawHMI.exe", 123)
    monkeypatch(updater, "_http_get", lambda *a, **k: payload)
    info = updater.check_for_update()
    assert info is not None, "should detect newer version"
    assert info["version"] == "1.0.1"
    assert info["download_url"].endswith("ChopSawHMI.exe")
    print("newer_version_detected OK")


def test_same_version_no_update(monkeypatch):
    monkeypatch(updater, "_current_version", lambda: "1.0.1")
    payload = _release_json("v1.0.1", "https://x/ChopSawHMI.exe", 123)
    monkeypatch(updater, "_http_get", lambda *a, **k: payload)
    assert updater.check_for_update() is None
    print("same_version_no_update OK")


def test_older_remote_no_update(monkeypatch):
    monkeypatch(updater, "_current_version", lambda: "2.0.0")
    payload = _release_json("v1.5.0", "https://x/ChopSawHMI.exe", 123)
    monkeypatch(updater, "_http_get", lambda *a, **k: payload)
    assert updater.check_for_update() is None
    print("older_remote_no_update OK")


def test_prerelease_ignored(monkeypatch):
    monkeypatch(updater, "_current_version", lambda: "1.0.0")
    payload = _release_json("v1.0.1", "https://x/ChopSawHMI.exe", 123, prerelease=True)
    monkeypatch(updater, "_http_get", lambda *a, **k: payload)
    assert updater.check_for_update() is None
    print("prerelease_ignored OK")


def test_no_exe_asset(monkeypatch):
    monkeypatch(updater, "_current_version", lambda: "1.0.0")
    payload = json.dumps({"tag_name": "v1.0.1", "assets": [
        {"name": "notes.txt", "browser_download_url": "https://x/notes.txt"}]}).encode()
    monkeypatch(updater, "_http_get", lambda *a, **k: payload)
    assert updater.check_for_update() is None
    print("no_exe_asset OK")


def test_offline_returns_none(monkeypatch):
    def boom(*a, **k):
        raise OSError("no network")
    monkeypatch(updater, "_http_get", boom)
    assert updater.check_for_update() is None
    print("offline_returns_none OK")


def test_download_verifies_sha(monkeypatch, tmp_dir):
    content = b"FAKE-EXE-BYTES" * 1000
    good_sha = hashlib.sha256(content).hexdigest()

    def fake_urlopen(req, timeout=None, context=None):
        class R:
            headers = {"Content-Length": str(len(content))}
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self, n=-1):
                if not hasattr(self, "_done"):
                    self._done = True
                    return content
                return b""
        return R()

    monkeypatch(updater.urllib.request, "urlopen", fake_urlopen)
    monkeypatch(updater, "update_cache_dir", lambda: tmp_dir)

    # Correct sha -> file kept
    monkeypatch(updater, "_expected_sha", lambda url, t: good_sha)
    path = updater.download_update({"download_url": "https://x/ChopSawHMI.exe",
                                    "sha256_url": "https://x/x.sha256", "size": len(content)})
    assert path is not None and path.exists(), "valid download should be kept"

    # Wrong sha -> file deleted, None returned
    monkeypatch(updater, "_expected_sha", lambda url, t: "0" * 64)
    path2 = updater.download_update({"download_url": "https://x/ChopSawHMI.exe",
                                     "sha256_url": "https://x/x.sha256", "size": len(content)})
    assert path2 is None, "bad checksum should fail"
    print("download_verifies_sha OK")


def test_schedule_update_dev_mode():
    # Not frozen in the test runner, so this must refuse to do anything
    assert updater.schedule_update("anything.exe") is False
    print("schedule_update_dev_mode OK")


# ---- tiny test harness (no pytest dependency) ----
class _Patcher:
    def __init__(self):
        self._undo = []
    def __call__(self, obj, name, value):
        old = getattr(obj, name)
        self._undo.append((obj, name, old))
        setattr(obj, name, value)
    def undo_all(self):
        for obj, name, old in reversed(self._undo):
            setattr(obj, name, old)
        self._undo.clear()


def main():
    import inspect
    import tempfile
    from pathlib import Path

    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        patcher = _Patcher()
        kwargs = {}
        params = inspect.signature(t).parameters
        if "monkeypatch" in params:
            kwargs["monkeypatch"] = patcher
        tmp = None
        if "tmp_dir" in params:
            tmp = tempfile.TemporaryDirectory()
            kwargs["tmp_dir"] = Path(tmp.name)
        try:
            t(**kwargs)
        except AssertionError as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"ERROR {t.__name__}: {e}")
        finally:
            patcher.undo_all()
            if tmp:
                tmp.cleanup()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
