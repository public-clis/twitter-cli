from __future__ import annotations

import json
import os
import sys
from types import SimpleNamespace

import pytest

from twitter_cli import auth


def _patch_home(monkeypatch, tmp_path) -> None:
    """Point ``os.path.expanduser("~")`` at ``tmp_path`` on POSIX and Windows."""
    monkeypatch.setenv("HOME", str(tmp_path))
    if os.name == "nt":
        monkeypatch.setenv("USERPROFILE", str(tmp_path))


def test_get_cookies_prefers_env(monkeypatch) -> None:
    monkeypatch.setattr(auth, "load_from_env", lambda: {"auth_token": "env-token", "ct0": "env-csrf"})
    monkeypatch.setattr(auth, "extract_from_browser", lambda: pytest.fail("should not extract from browser"))
    seen = []
    monkeypatch.setattr(
        auth,
        "verify_cookies",
        lambda auth_token, ct0, cookie_string=None: seen.append((auth_token, ct0, cookie_string)) or {},
    )

    cookies = auth.get_cookies()

    assert cookies == {"auth_token": "env-token", "ct0": "env-csrf"}
    assert seen == [("env-token", "env-csrf", None)]


def test_get_cookies_reextracts_after_verify_failure(monkeypatch) -> None:
    monkeypatch.setattr(auth, "load_from_env", lambda: None)
    extracted = iter(
        [
            ({"auth_token": "stale-token", "ct0": "stale-csrf", "cookie_string": "stale=1"}, []),
            ({"auth_token": "fresh-token", "ct0": "fresh-csrf", "cookie_string": "fresh=1"}, []),
        ]
    )
    monkeypatch.setattr(auth, "extract_from_browser", lambda: next(extracted))

    calls = []

    def _verify(auth_token, ct0, cookie_string=None):
        calls.append((auth_token, ct0, cookie_string))
        if auth_token == "stale-token":
            raise RuntimeError("expired")
        return {}

    monkeypatch.setattr(auth, "verify_cookies", _verify)

    cookies = auth.get_cookies()

    assert cookies["auth_token"] == "fresh-token"
    assert calls == [
        ("stale-token", "stale-csrf", "stale=1"),
        ("fresh-token", "fresh-csrf", "fresh=1"),
    ]


def test_load_from_env_logs_incomplete_env(monkeypatch, caplog) -> None:
    monkeypatch.setenv("TWITTER_AUTH_TOKEN", "token")
    monkeypatch.delenv("TWITTER_CT0", raising=False)

    with caplog.at_level("DEBUG"):
        cookies = auth.load_from_env()

    assert cookies is None
    assert "Environment cookies incomplete" in caplog.text


def test_extract_cookies_from_jar_logs_missing_required_cookies(caplog) -> None:
    class Cookie:
        def __init__(self, domain: str, name: str, value: str) -> None:
            self.domain = domain
            self.name = name
            self.value = value

    jar = [Cookie(".x.com", "auth_token", "token")]

    with caplog.at_level("DEBUG"):
        cookies = auth._extract_cookies_from_jar(jar, source="test-jar")

    assert cookies is None
    assert "test-jar" in caplog.text
    assert "ct0=False" in caplog.text


def test_extract_from_browser_logs_warning_when_all_methods_fail(monkeypatch, caplog) -> None:
    monkeypatch.setattr(auth, "_extract_in_process", lambda: (None, []))
    monkeypatch.setattr(auth, "_extract_via_subprocess", lambda: (None, []))

    with caplog.at_level("WARNING"):
        cookies, diagnostics = auth.extract_from_browser()

    assert cookies is None
    assert "Twitter cookie extraction failed in both in-process and subprocess modes" in caplog.text


def test_extract_in_process_supports_arc(monkeypatch) -> None:
    class Cookie:
        def __init__(self, domain: str, name: str, value: str) -> None:
            self.domain = domain
            self.name = name
            self.value = value

    fake_module = SimpleNamespace(
        arc=lambda: [Cookie(".x.com", "auth_token", "token"), Cookie(".x.com", "ct0", "csrf")],
        chrome=lambda: pytest.fail("chrome should not be used when arc succeeds"),
        edge=lambda: pytest.fail("edge should not be used when arc succeeds"),
        firefox=lambda: pytest.fail("firefox should not be used when arc succeeds"),
        brave=lambda: pytest.fail("brave should not be used when arc succeeds"),
    )
    monkeypatch.setitem(sys.modules, "browser_cookie3", fake_module)

    cookies, diagnostics = auth._extract_in_process()

    assert cookies is not None
    assert cookies["auth_token"] == "token"
    assert cookies["ct0"] == "csrf"


def test_extract_via_subprocess_script_includes_arc(monkeypatch) -> None:
    class Completed:
        def __init__(self, stdout: str, stderr: str = "") -> None:
            self.stdout = stdout
            self.stderr = stderr

    seen = {}

    def _run(cmd, capture_output=True, text=True, timeout=15):
        script = cmd[-1]
        seen["script"] = script
        return Completed(json.dumps({"error": "No Twitter cookies found", "attempts": []}))

    monkeypatch.setattr(auth.subprocess, "run", _run)

    cookies, diagnostics = auth._extract_via_subprocess()

    assert cookies is None
    assert 'DEFAULT_ORDER = ["arc", "chrome", "edge", "firefox", "brave", "vivaldi", "zen"]' in seen["script"]
    assert 'CUSTOM_CHROMIUM_BROWSER = "custom-chromium"' in seen["script"]
    assert "browser_cookie3.chromium(" in seen["script"]


def test_extract_via_subprocess_retries_uv_when_current_env_has_no_output(monkeypatch) -> None:
    class Completed:
        def __init__(self, stdout: str, stderr: str = "") -> None:
            self.stdout = stdout
            self.stderr = stderr

    calls = []

    def _run(cmd, capture_output=True, text=True, timeout=15):
        calls.append(cmd)
        if cmd[0] == sys.executable:
            return Completed("", "")
        return Completed(json.dumps({"auth_token": "token", "ct0": "csrf", "browser": "arc"}))

    monkeypatch.setattr(auth.subprocess, "run", _run)

    cookies, diagnostics = auth._extract_via_subprocess()

    assert cookies == {"auth_token": "token", "ct0": "csrf"}
    assert len(calls) == 2
    assert calls[1][:5] == ["uv", "run", "--with", "browser-cookie3", "python"]


def test_verify_cookies_logs_attempt_summary_on_non_auth_failures(monkeypatch, caplog) -> None:
    class Response:
        def __init__(self, status_code: int, payload=None) -> None:
            self.status_code = status_code
            self._payload = payload or {}

        def json(self):
            return self._payload

    class Session:
        def __init__(self) -> None:
            self.calls = 0

        def get(self, url, headers=None, timeout=5):
            self.calls += 1
            if self.calls == 1:
                return Response(404)
            raise Exception("network")

    monkeypatch.setattr("twitter_cli.client._get_cffi_session", lambda: Session())

    with caplog.at_level("INFO"):
        result = auth.verify_cookies("token", "csrf")

    assert result == {}
    assert "verify_credentials.json=404" in caplog.text
    assert "settings.json=Exception" in caplog.text


def test_iter_chrome_cookie_files_default_first(monkeypatch, tmp_path) -> None:
    """Default profile should be yielded first, then Profile N sorted."""
    monkeypatch.setattr(auth.sys, "platform", "linux")
    chrome_dir = tmp_path / ".config" / "Google" / "Chrome"

    (chrome_dir / "Default").mkdir(parents=True)
    (chrome_dir / "Default" / "Cookies").touch()
    (chrome_dir / "Profile 2").mkdir()
    (chrome_dir / "Profile 2" / "Cookies").touch()
    (chrome_dir / "Profile 1").mkdir()
    (chrome_dir / "Profile 1" / "Cookies").touch()

    monkeypatch.delenv("TWITTER_CHROME_PROFILE", raising=False)
    _patch_home(monkeypatch, tmp_path)

    paths = auth._iter_chrome_cookie_files("chrome")

    basenames = [os.path.basename(os.path.dirname(p)) for p in paths]
    assert basenames[0] == "Default"
    assert "Profile 1" in basenames
    assert "Profile 2" in basenames
    # Profile 1 should come before Profile 2
    assert basenames.index("Profile 1") < basenames.index("Profile 2")


def test_iter_chrome_cookie_files_env_override(monkeypatch, tmp_path) -> None:
    """TWITTER_CHROME_PROFILE should restrict to that single profile."""
    monkeypatch.setattr(auth.sys, "platform", "linux")
    chrome_dir = tmp_path / ".config" / "Google" / "Chrome"

    (chrome_dir / "Default").mkdir(parents=True)
    (chrome_dir / "Default" / "Cookies").touch()
    (chrome_dir / "Profile 5").mkdir()
    (chrome_dir / "Profile 5" / "Cookies").touch()

    _patch_home(monkeypatch, tmp_path)
    monkeypatch.setenv("TWITTER_CHROME_PROFILE", "Profile 5")

    paths = auth._iter_chrome_cookie_files("chrome")

    assert len(paths) == 1
    assert "Profile 5" in paths[0]


def test_iter_chrome_cookie_files_edge_linux_uses_microsoft_edge_path(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(auth.sys, "platform", "linux")
    edge_dir = tmp_path / ".config" / "microsoft-edge"
    (edge_dir / "Default").mkdir(parents=True)
    (edge_dir / "Default" / "Cookies").touch()

    _patch_home(monkeypatch, tmp_path)
    monkeypatch.delenv("TWITTER_CHROME_PROFILE", raising=False)

    paths = auth._iter_chrome_cookie_files("edge")

    assert len(paths) == 1
    assert paths[0] == os.path.join(str(tmp_path), ".config", "microsoft-edge", "Default", "Cookies")


def test_iter_chrome_cookie_files_edge_windows_uses_user_data(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(auth.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("TWITTER_CHROME_PROFILE", raising=False)

    edge_dir = tmp_path / "Microsoft" / "Edge" / "User Data" / "Default"
    edge_dir.mkdir(parents=True)
    (edge_dir / "Cookies").touch()

    paths = auth._iter_chrome_cookie_files("edge")

    assert len(paths) == 1
    assert "Microsoft/Edge/User Data/Default/Cookies".replace("/", os.sep) in paths[0]


def test_extract_in_process_tries_multiple_profiles(monkeypatch, tmp_path) -> None:
    """When Default has no Twitter cookies but Profile 1 does, it should find them."""

    class Cookie:
        def __init__(self, domain: str, name: str, value: str) -> None:
            self.domain = domain
            self.name = name
            self.value = value

    default_cookies_path = str(tmp_path / "Default" / "Cookies")
    profile1_cookies_path = str(tmp_path / "Profile 1" / "Cookies")
    os.makedirs(os.path.dirname(default_cookies_path), exist_ok=True)
    os.makedirs(os.path.dirname(profile1_cookies_path), exist_ok=True)
    open(default_cookies_path, "w").close()
    open(profile1_cookies_path, "w").close()

    # Mock _iter_chrome_cookie_files to return our tmp paths
    def mock_iter(browser_name):
        if browser_name == "arc":
            return [default_cookies_path, profile1_cookies_path]
        return []

    monkeypatch.setattr(auth, "_iter_chrome_cookie_files", mock_iter)

    # Arc: Default returns empty jar, Profile 1 returns valid cookies
    def mock_arc(cookie_file=None):
        if cookie_file == profile1_cookies_path:
            return [
                Cookie(".x.com", "auth_token", "tok123"),
                Cookie(".x.com", "ct0", "csrf456"),
            ]
        return []  # Default — no cookies

    fake_module = SimpleNamespace(
        arc=mock_arc,
        chrome=lambda cookie_file=None: [],
        edge=lambda cookie_file=None: [],
        firefox=lambda: [],
        brave=lambda cookie_file=None: [],
    )
    monkeypatch.setitem(sys.modules, "browser_cookie3", fake_module)

    cookies, diagnostics = auth._extract_in_process()

    assert cookies is not None
    assert cookies["auth_token"] == "tok123"
    assert cookies["ct0"] == "csrf456"


def test_diagnose_keychain_issues_detects_decryption_error(monkeypatch) -> None:
    """_diagnose_keychain_issues should detect Keychain-related error strings."""
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.delenv("SSH_CLIENT", raising=False)
    monkeypatch.delenv("SSH_TTY", raising=False)
    monkeypatch.delenv("SSH_CONNECTION", raising=False)

    diagnostics = ["arc[Default]: Unable to get key for cookie decryption"]
    hint = auth._diagnose_keychain_issues(diagnostics)

    assert hint is not None
    assert "Keychain" in hint


def test_diagnose_keychain_issues_ssh_hint(monkeypatch) -> None:
    """When SSH env vars are set, hint should suggest unlock-keychain."""
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setenv("SSH_CLIENT", "1.2.3.4 54321 22")

    diagnostics = ["arc: Unable to get key for cookie decryption"]
    hint = auth._diagnose_keychain_issues(diagnostics)

    assert hint is not None
    assert "SSH session detected" in hint
    assert "security unlock-keychain" in hint


def test_diagnose_keychain_issues_windows_hint(monkeypatch) -> None:
    """On Windows, hint should mention DPAPI and environment variable workaround."""
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.delenv("SSH_CLIENT", raising=False)
    monkeypatch.delenv("SSH_TTY", raising=False)
    monkeypatch.delenv("SSH_CONNECTION", raising=False)

    diagnostics = ["chrome: Unable to get key for cookie decryption"]
    hint = auth._diagnose_keychain_issues(diagnostics)

    assert hint is not None
    assert "DPAPI" in hint
    assert "TWITTER_AUTH_TOKEN" in hint
    assert "shadowcopy" in hint


def test_diagnose_keychain_issues_returns_none_for_unrelated_errors() -> None:
    """Should return None when diagnostics don't mention Keychain."""
    diagnostics = ["chrome[Default]=no-cookies", "firefox: profile not found"]
    hint = auth._diagnose_keychain_issues(diagnostics)

    assert hint is None


def test_get_cookies_includes_keychain_hint_in_error(monkeypatch) -> None:
    """When extraction fails with Keychain errors, error msg should contain the hint."""
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setenv("SSH_CLIENT", "1.2.3.4 54321 22")
    monkeypatch.setattr(auth, "load_from_env", lambda: None)
    monkeypatch.setattr(
        auth,
        "extract_from_browser",
        lambda: (None, ["arc: Unable to get key for cookie decryption"]),
    )

    with pytest.raises(RuntimeError) as exc_info:
        auth.get_cookies()

    msg = str(exc_info.value)
    assert "security unlock-keychain" in msg
    assert "twitter -v" in msg


def test_extract_in_process_returns_diagnostics_on_failure(monkeypatch) -> None:
    """_extract_in_process should return diagnostics containing error strings."""
    from types import SimpleNamespace

    class BrowserError(Exception):
        pass

    fake_module = SimpleNamespace(
        arc=lambda: (_ for _ in ()).throw(BrowserError("Unable to get key for cookie decryption")),
        chrome=lambda: [],
        edge=lambda: (_ for _ in ()).throw(BrowserError("Edge not found")),
        firefox=lambda: (_ for _ in ()).throw(BrowserError("Firefox not found")),
        brave=lambda: (_ for _ in ()).throw(BrowserError("Brave not found")),
    )
    monkeypatch.setitem(sys.modules, "browser_cookie3", fake_module)

    cookies, diagnostics = auth._extract_in_process()

    assert cookies is None
    assert any("cookie decryption" in d for d in diagnostics)


def test_load_from_env_supports_full_cookie_string(monkeypatch) -> None:
    monkeypatch.delenv("TWITTER_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("TWITTER_CT0", raising=False)
    monkeypatch.setenv("TWITTER_COOKIE_STRING", "guest_id=v1; auth_token=tok123; ct0=csrf456; kdt=abc")

    cookies = auth.load_from_env()

    assert cookies == {
        "auth_token": "tok123",
        "ct0": "csrf456",
        "cookie_string": "guest_id=v1; auth_token=tok123; ct0=csrf456; kdt=abc",
    }


def test_get_browser_order_prepends_custom_chromium_dir(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("TWITTER_BROWSER", raising=False)
    monkeypatch.setenv("TWITTER_CHROMIUM_USER_DATA_DIR", str(tmp_path))

    order = auth._get_browser_order()

    assert order[0] == "custom-chromium"
    assert "chrome" in order


def test_iter_chrome_cookie_files_supports_custom_user_data_dir(monkeypatch, tmp_path) -> None:
    root = tmp_path / "Ungoogled Chromium"
    network_dir = root / "Profile 1" / "Network"
    network_dir.mkdir(parents=True)
    cookie_file = network_dir / "Cookies"
    cookie_file.touch()
    local_state = root / "Local State"
    local_state.touch()

    monkeypatch.setenv("TWITTER_CHROMIUM_USER_DATA_DIR", str(root))
    monkeypatch.delenv("TWITTER_CHROME_PROFILE", raising=False)

    paths = auth._iter_chrome_cookie_files("custom-chromium")

    assert paths == [str(cookie_file)]
    assert auth._profile_name_from_cookie_file(str(cookie_file)) == "Profile 1"
    assert auth._chromium_key_file_for_cookie(str(cookie_file)) == str(local_state)


def test_extract_in_process_uses_chromium_loader_for_custom_dir(monkeypatch, tmp_path) -> None:
    class Cookie:
        def __init__(self, domain: str, name: str, value: str) -> None:
            self.domain = domain
            self.name = name
            self.value = value

    root = tmp_path / "User Data"
    profile_dir = root / "Default" / "Network"
    profile_dir.mkdir(parents=True)
    cookie_file = profile_dir / "Cookies"
    cookie_file.touch()
    local_state = root / "Local State"
    local_state.touch()
    seen = {}

    def chromium(cookie_file=None, key_file=None):
        seen["cookie_file"] = cookie_file
        seen["key_file"] = key_file
        return [
            Cookie(".x.com", "auth_token", "custom-token"),
            Cookie(".x.com", "ct0", "custom-csrf"),
        ]

    monkeypatch.setenv("TWITTER_CHROMIUM_USER_DATA_DIR", str(root))
    monkeypatch.setattr(auth, "_get_browser_order", lambda: ["custom-chromium"])
    monkeypatch.setitem(sys.modules, "browser_cookie3", SimpleNamespace(chromium=chromium))

    cookies, diagnostics = auth._extract_in_process()

    assert diagnostics == []
    assert cookies is not None
    assert cookies["auth_token"] == "custom-token"
    assert seen == {"cookie_file": str(cookie_file), "key_file": str(local_state)}


def test_vivaldi_browser_order_and_paths(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("TWITTER_BROWSER", "vivaldi")
    order = auth._get_browser_order()
    assert order[0] == "vivaldi"
    assert "vivaldi" in order

    monkeypatch.setattr(auth.sys, "platform", "linux")
    vivaldi_dir = tmp_path / ".config" / "vivaldi"
    (vivaldi_dir / "Default").mkdir(parents=True)
    (vivaldi_dir / "Default" / "Cookies").touch()
    _patch_home(monkeypatch, tmp_path)
    monkeypatch.delenv("TWITTER_CHROME_PROFILE", raising=False)

    paths = auth._iter_chrome_cookie_files("vivaldi")
    assert paths == [os.path.join(str(tmp_path), ".config", "vivaldi", "Default", "Cookies")]


@pytest.mark.parametrize(
    "platform,relative",
    [
        ("linux", ".zen/test/cookies.sqlite"),
        ("linux", ".var/app/app.zen_browser.zen/zen/test/cookies.sqlite"),
        ("linux", ".var/app/app.zen_browser.zen/.zen/test/cookies.sqlite"),
        ("darwin", "Library/Application Support/zen/Profiles/test/cookies.sqlite"),
        ("win32", "zen/Profiles/test/cookies.sqlite"),
    ],
)
def test_zen_profile_discovery(monkeypatch, tmp_path, platform, relative) -> None:
    monkeypatch.setattr(auth.sys, "platform", platform)
    monkeypatch.setattr(auth.os.path, "expanduser", lambda _: str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    cookie_file = tmp_path / relative
    cookie_file.parent.mkdir(parents=True)
    cookie_file.touch()
    assert auth._iter_zen_cookie_files() == [str(cookie_file)]


@pytest.mark.parametrize("subprocess_mode", [False, True])
def test_zen_extracts_from_later_profile(monkeypatch, subprocess_mode) -> None:
    monkeypatch.setenv("TWITTER_BROWSER", " ZEN ")
    monkeypatch.setattr(auth, "_iter_zen_cookie_files", lambda: ["empty", "broken", "valid"])
    calls = []

    def firefox(cookie_file=None):
        calls.append(cookie_file)
        if cookie_file == "broken":
            raise RuntimeError("profile unreadable")
        if cookie_file != "valid":
            return []
        return [
            SimpleNamespace(domain=".x.com", name=name, value=value)
            for name, value in [("auth_token", "token"), ("ct0", "csrf"), ("extra", "value")]
        ]

    fake_module = SimpleNamespace(firefox=firefox)
    for name in ("arc", "chrome", "edge", "brave", "vivaldi"):
        setattr(fake_module, name, lambda: pytest.fail("Zen should succeed first"))
    monkeypatch.setitem(sys.modules, "browser_cookie3", fake_module)
    if subprocess_mode:
        import contextlib
        import io

        def run(cmd, **kwargs):
            output = io.StringIO()
            with contextlib.redirect_stdout(output), pytest.raises(SystemExit) as exited:
                exec(cmd[-1], {})
            assert exited.value.code == 0
            return SimpleNamespace(stdout=output.getvalue(), stderr="")

        monkeypatch.setattr(auth.subprocess, "run", run)
        cookies, _ = auth._extract_via_subprocess()
    else:
        cookies, _ = auth._extract_in_process()
    assert calls == ["empty", "broken", "valid"]
    assert cookies == {
        "auth_token": "token",
        "ct0": "csrf",
        "cookie_string": "auth_token=token; ct0=csrf; extra=value",
    }


def test_windows_app_bound_encryption_diagnostics(monkeypatch) -> None:
    monkeypatch.setattr(auth.sys, "platform", "win32")
    for var in ("SSH_CLIENT", "SSH_TTY", "SSH_CONNECTION"):
        monkeypatch.delenv(var, raising=False)

    hint = auth._diagnose_keychain_issues(
        ["chrome in-process extraction failed: Unable to get key for cookie decryption"]
    )
    assert hint is not None
    assert "App-Bound Encryption" in hint
    assert "not a permissions issue" in hint
    assert "TWITTER_BROWSER=firefox" in hint
    assert "TWITTER_COOKIE_STRING" in hint
    assert "VSS shadowcopy" in hint
