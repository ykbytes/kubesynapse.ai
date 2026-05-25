"""Tests for agentctl.config — profile persistence, token store, settings resolution."""

from __future__ import annotations

from pathlib import Path

from agentctl.config import (
    Config,
    Profile,
    load_config,
    save_config,
    load_token,
    save_token,
    clear_token,
    resolve_settings,
)


class TestConfigRoundtrip:
    def test_load_config_returns_defaults_when_no_file(self, temp_config_dir: Path) -> None:
        cfg = load_config()
        assert cfg.active_profile == "default"
        assert "default" in cfg.profiles
        assert cfg.profiles["default"].gateway_url == "http://localhost:8080"

    def test_save_and_load_roundtrip(self, temp_config_dir: Path) -> None:
        cfg = Config(
            active_profile="staging",
            profiles={
                "default": Profile(name="default"),
                "staging": Profile(name="staging", gateway_url="https://staging.example.com", namespace="staging-ns"),
            },
        )
        save_config(cfg)
        loaded = load_config()
        assert loaded.active_profile == "staging"
        assert loaded.profiles["staging"].gateway_url == "https://staging.example.com"
        assert loaded.profiles["staging"].namespace == "staging-ns"

    def test_save_and_load_preserves_timeout(self, temp_config_dir: Path) -> None:
        cfg = Config(
            active_profile="default",
            profiles={"default": Profile(name="default", timeout=120.0)},
        )
        save_config(cfg)
        loaded = load_config()
        assert loaded.profiles["default"].timeout == 120.0

    def test_load_config_handles_corrupted_yaml(self, temp_config_dir: Path) -> None:
        config_file = temp_config_dir / "config" / "config.yaml"
        config_file.write_text(": broken yaml [\n")
        cfg = load_config()
        assert cfg.active_profile == "default"

    def test_active_profile_fallback_when_missing(self, temp_config_dir: Path) -> None:
        cfg = Config(active_profile="missing", profiles={"default": Profile()})
        save_config(cfg)
        # Manually corrupt the active_profile
        import yaml
        raw = yaml.safe_load(Path(temp_config_dir / "config" / "config.yaml").read_text())
        raw["active_profile"] = "nonexistent"
        Path(temp_config_dir / "config" / "config.yaml").write_text(yaml.dump(raw))
        loaded = load_config()
        assert loaded.active_profile == "default"


class TestTokenStore:
    def test_save_and_load_token(self, temp_config_dir: Path) -> None:
        save_token("my-secret-token", "default")
        assert load_token("default") == "my-secret-token"

    def test_load_token_defaults_to_empty(self, temp_config_dir: Path) -> None:
        assert load_token("nonexistent") == ""

    def test_clear_token(self, temp_config_dir: Path) -> None:
        save_token("secret", "default")
        clear_token("default")
        assert load_token("default") == ""

    def test_tokens_are_profile_scoped(self, temp_config_dir: Path) -> None:
        save_token("token-a", "profile-a")
        save_token("token-b", "profile-b")
        assert load_token("profile-a") == "token-a"
        assert load_token("profile-b") == "token-b"

    def test_clear_nonexistent_profile_does_not_error(self, temp_config_dir: Path) -> None:
        clear_token("does-not-exist")


class TestResolveSettings:
    def test_uses_profile_values_by_default(self, temp_config_dir: Path) -> None:
        cfg = Config(
            active_profile="staging",
            profiles={
                "default": Profile(),
                "staging": Profile(name="staging", gateway_url="https://staging.example.com", namespace="staging-ns"),
            },
        )
        save_config(cfg)
        # No CLI flags, no env
        result = resolve_settings()
        assert result.gateway_url == "https://staging.example.com"
        assert result.namespace == "staging-ns"

    def test_cli_flag_overrides_profile(self, temp_config_dir: Path) -> None:
        cfg = Config(
            active_profile="default",
            profiles={"default": Profile(name="default", gateway_url="http://default:8080")},
        )
        save_config(cfg)
        result = resolve_settings(gateway_url="http://cli-override:8080")
        assert result.gateway_url == "http://cli-override:8080"

    def test_cli_flag_overrides_env(self, temp_config_dir: Path, monkeypatch) -> None:
        monkeypatch.setenv("AGENT_GATEWAY_URL", "http://env:8080")
        result = resolve_settings(gateway_url="http://cli:8080")
        assert result.gateway_url == "http://cli:8080"

    def test_env_var_overrides_profile(self, temp_config_dir: Path, monkeypatch) -> None:
        monkeypatch.setenv("AGENT_GATEWAY_TOKEN", "env-token")
        result = resolve_settings()
        assert result.token == "env-token"

    def test_token_from_cli_overrides_env(self, temp_config_dir: Path, monkeypatch) -> None:
        monkeypatch.setenv("AGENT_GATEWAY_TOKEN", "env-token")
        result = resolve_settings(token="cli-token")
        assert result.token == "cli-token"

    def test_token_from_saved_credentials(self, temp_config_dir: Path) -> None:
        save_token("saved-token", "default")
        result = resolve_settings()
        assert result.token == "saved-token"

    def test_namespace_fallback(self, temp_config_dir: Path, monkeypatch) -> None:
        monkeypatch.setenv("AGENT_NAMESPACE", "env-ns")
        result = resolve_settings()
        assert result.namespace == "env-ns"

    def test_output_format_default(self, temp_config_dir: Path) -> None:
        result = resolve_settings()
        assert result.output_format == "table"

    def test_output_format_custom(self, temp_config_dir: Path) -> None:
        result = resolve_settings(output_format="json")
        assert result.output_format == "json"

    def test_timeout_fallback(self, temp_config_dir: Path) -> None:
        result = resolve_settings()
        assert result.timeout == 60.0

    def test_timeout_from_cli(self, temp_config_dir: Path) -> None:
        result = resolve_settings(timeout=30.0)
        assert result.timeout == 30.0

    def test_saved_token_preferred_over_profile(self, temp_config_dir: Path) -> None:
        save_token("saved", "default")
        result = resolve_settings()
        assert result.token == "saved"
