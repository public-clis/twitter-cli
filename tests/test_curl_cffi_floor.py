"""Dependency-floor guard for curl_cffi.

The pin exists for security rather than compatibility, and a well-meaning
"relax the pin" change can silently reintroduce a CVE. Asserting it here makes
that a failing test instead of a shipped vulnerability.

Deliberately parses `pyproject.toml` as text rather than with `tomllib`, which
only exists on Python 3.11+ while this project supports 3.10 — and a guard test
must not itself add a dependency.
"""

from __future__ import annotations

import re
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def _declared_specifiers() -> dict[str, str]:
    """Return {package: minimal-version-specifier} from [project].dependencies."""
    text = PYPROJECT.read_text(encoding="utf-8")
    # Match the `dependencies = [` list itself; anchoring on the assignment
    # avoids tripping over earlier list-valued keys such as `classifiers`.
    block = re.search(r"^dependencies\s*=\s*\[\s*$(.*?)^\]\s*$", text, re.S | re.M)
    assert block, "could not locate dependencies = [...] in pyproject.toml"
    specifiers = {}
    for raw in re.findall(r'"([^"]+)"', block.group(1)):
        name, sep, version = raw.partition(">=")
        if sep:
            specifiers[name.strip().lower()] = ">=" + version.strip()
    return specifiers


def test_curl_cffi_floor_excludes_ghsa_qw2m_4pqf_rmpp() -> None:
    """GHSA-qw2m-4pqf-rmpp (CVE-2026-33752): redirect SSRF, fixed in 0.15.0.

    Every curl_cffi release before 0.15.0 is vulnerable, so the declared floor
    must not allow one. This is not a cosmetic pin.
    """
    specifier = _declared_specifiers()["curl_cffi"]
    assert specifier == ">=0.15.0", (
        "curl_cffi floor must stay >=0.15.0 to exclude GHSA-qw2m-4pqf-rmpp; got %s"
        % specifier
    )


def test_installed_curl_cffi_is_not_vulnerable() -> None:
    """The resolved environment, not just the declaration, must be patched."""
    try:
        import curl_cffi
    except ImportError:  # pragma: no cover - curl_cffi is a required dependency
        import pytest

        pytest.skip("curl_cffi is not installed")

    raw = getattr(curl_cffi, "__version__", "0")
    parts = []
    for chunk in raw.split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    version = tuple(parts[:3])
    if len(version) < 3:
        version = version + (0,) * (3 - len(version))

    assert version >= (0, 15, 0), (
        "installed curl_cffi %s is affected by GHSA-qw2m-4pqf-rmpp" % raw
    )
