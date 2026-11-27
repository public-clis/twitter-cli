"""Dependency-floor guards for curl_cffi and xclienttransaction."""

from __future__ import annotations

import re
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def _declared_specifiers() -> dict[str, str]:
    """Return {package: minimal-version-specifier} from [project].dependencies."""
    text = PYPROJECT.read_text(encoding="utf-8")
    block = re.search(r"^dependencies\s*=\s*\[\s*$(.*?)^\]\s*$", text, re.S | re.M)
    assert block, "could not locate dependencies = [...] in pyproject.toml"
    specifiers = {}
    for raw in re.findall(r'"([^"]+)"', block.group(1)):
        name, sep, version = raw.partition(">=")
        if sep:
            specifiers[name.strip().lower()] = ">=" + version.strip()
    return specifiers


def _parse_version_tuple(raw: str) -> tuple[int, ...]:
    parts = []
    for chunk in raw.split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def test_curl_cffi_floor_excludes_ghsa_qw2m_4pqf_rmpp() -> None:
    """GHSA-qw2m-4pqf-rmpp (CVE-2026-33752): redirect SSRF, fixed in 0.15.0."""
    specifier = _declared_specifiers()["curl_cffi"]
    min_version = _parse_version_tuple(specifier.removeprefix(">="))
    assert min_version >= (0, 15, 0), (
        "curl_cffi floor must be >=0.15.0 to exclude GHSA-qw2m-4pqf-rmpp; got %s" % specifier
    )


def test_installed_curl_cffi_is_not_vulnerable() -> None:
    import curl_cffi

    raw = getattr(curl_cffi, "__version__", "0")
    assert _parse_version_tuple(raw) >= (0, 15, 0), (
        "installed curl_cffi %s is affected by GHSA-qw2m-4pqf-rmpp" % raw
    )


def test_xclienttransaction_floor_supports_numeric_module_map() -> None:
    specifier = _declared_specifiers()["xclienttransaction"]
    min_version = _parse_version_tuple(specifier.removeprefix(">="))
    assert min_version >= (1, 0, 3), (
        "xclienttransaction floor must be >=1.0.3; got %s" % specifier
    )
