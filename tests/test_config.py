import pytest

from foerderpilot.config import load_config


def test_config_rejects_plaintext_secret(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("connectors:\n  - type: sql\n    url: sqlite:///x\n    api_key: super-secret\n", encoding="utf-8")
    with pytest.raises(ValueError, match="env:"):
        load_config(cfg)


def test_config_accepts_env_reference(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("connectors:\n  - type: sql\n    url: env:MY_URL\n", encoding="utf-8")
    config = load_config(cfg)
    assert config["output_dir"] == "out"
    assert config["connectors"][0]["url"] == "env:MY_URL"
