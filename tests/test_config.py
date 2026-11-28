from __future__ import annotations

from pathlib import Path

from twitter_cli.config import DEFAULT_CONFIG, load_config


def test_load_config_supports_block_list_yaml(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "\n".join(
            [
                "fetch:",
                "  count: 25",
                "filter:",
                "  mode: score",
                "  lang:",
                "    - en",
                "    - zh",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(str(config_file))
    assert config["fetch"]["count"] == 25
    assert config["filter"]["mode"] == "score"
    assert config["filter"]["lang"] == ["en", "zh"]


def test_load_config_invalid_yaml_falls_back_to_defaults(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text("fetch: [", encoding="utf-8")

    config = load_config(str(config_file))
    assert config["fetch"]["count"] == DEFAULT_CONFIG["fetch"]["count"]
    assert config["filter"]["mode"] == DEFAULT_CONFIG["filter"]["mode"]


def test_load_config_does_not_mutate_defaults(tmp_path: Path) -> None:
    config = load_config(str(tmp_path / "missing-config.yaml"))
    config["filter"]["weights"]["likes"] = 999
    assert DEFAULT_CONFIG["filter"]["weights"]["likes"] == 1.0


def test_resolve_config_path_checks_user_home_dir(monkeypatch, tmp_path: Path) -> None:
    from twitter_cli import config as config_mod

    user_cfg = tmp_path / ".twitter-cli" / "config.yaml"
    user_cfg.parent.mkdir(parents=True)
    user_cfg.write_text("display:\n  time: absolute\n", encoding="utf-8")

    empty_cwd = tmp_path / "cwd"
    empty_cwd.mkdir()
    monkeypatch.chdir(empty_cwd)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    assert config_mod._resolve_config_path(None) == user_cfg
    loaded = load_config()
    assert loaded["display"]["time"] == "absolute"
