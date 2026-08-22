from unittest.mock import patch
from pathlib import Path
import pytest

from ff.contracts import Format
from ff.services.llm.onboarding import onboard_user


def test_onboard_user_creates_config(tmp_path: Path) -> None:
    mock_leagues = [{"league_id": "999", "name": "My Dynasty", "season": "2026"}]
    real_format = Format(superflex=True, ppr=1.0)

    with patch("ff.services.llm.onboarding.sleeper_client.get_user", return_value={"user_id": "u1"}), \
         patch("ff.services.llm.onboarding.sleeper_client.get_user_leagues", return_value=mock_leagues), \
         patch("ff.services.llm.onboarding.sleeper_client.detect_format", return_value=real_format):
        cfg_file = tmp_path / "config.json"
        cfg = onboard_user(username="philippos", config_path=cfg_file)
        assert cfg.league_id == "999"
        assert cfg.user_id == "u1"
        assert cfg.user_name == "philippos"
        assert cfg_file.exists()


def test_onboard_user_no_leagues_raises_error(tmp_path: Path) -> None:
    with patch("ff.services.llm.onboarding.sleeper_client.get_user", return_value={"user_id": "u1"}), \
         patch("ff.services.llm.onboarding.sleeper_client.get_user_leagues", return_value=[]):
        cfg_file = tmp_path / "config.json"
        with pytest.raises(ValueError, match="No active leagues found for user 'unknown_user'"):
            onboard_user(username="unknown_user", config_path=cfg_file)


def test_onboard_user_unknown_user_raises() -> None:
    with patch("ff.services.llm.onboarding.sleeper_client.get_user",
               side_effect=ValueError("Sleeper user 'nope' not found.")):
        with pytest.raises(ValueError, match="not found"):
            onboard_user(username="nope")


def test_onboard_user_multiple_leagues_requires_setup(tmp_path: Path) -> None:
    leagues = [
        {"league_id": "111", "name": "League A", "season": "2026"},
        {"league_id": "222", "name": "League B", "season": "2026"},
    ]
    with patch("ff.services.llm.onboarding.sleeper_client.get_user", return_value={"user_id": "u1"}), \
         patch("ff.services.llm.onboarding.sleeper_client.get_user_leagues", return_value=leagues):
        with pytest.raises(ValueError, match="2 leagues"):
            onboard_user(username="philippos", config_path=tmp_path / "config.json")


def test_onboard_user_explicit_league_id(tmp_path: Path) -> None:
    leagues = [
        {"league_id": "111", "name": "League A", "season": "2026"},
        {"league_id": "222", "name": "League B", "season": "2026"},
    ]
    fmt = Format(superflex=True, ppr=1.0, num_teams=10)
    with patch("ff.services.llm.onboarding.sleeper_client.get_user", return_value={"user_id": "u1"}), \
         patch("ff.services.llm.onboarding.sleeper_client.get_user_leagues", return_value=leagues), \
         patch("ff.services.llm.onboarding.sleeper_client.detect_format", return_value=fmt):
        cfg = onboard_user(username="testuser", config_path=tmp_path / "config.json",
                           league_id="222")
        assert cfg.league_id == "222"
        assert cfg.format.num_teams == 10


def test_onboard_user_with_real_format_object(tmp_path: Path) -> None:
    mock_leagues = [{"league_id": "888", "name": "Superflex League", "season": "2026"}]
    real_format = Format(superflex=True, ppr=1.0, num_teams=10)

    with patch("ff.services.llm.onboarding.sleeper_client.get_user", return_value={"user_id": "u2"}), \
         patch("ff.services.llm.onboarding.sleeper_client.get_user_leagues", return_value=mock_leagues), \
         patch("ff.services.llm.onboarding.sleeper_client.detect_format", return_value=real_format):
        cfg_file = tmp_path / "config.json"
        cfg = onboard_user(username="testuser", config_path=cfg_file)
        assert cfg.league_id == "888"
        assert cfg.user_name == "testuser"
        assert cfg.format.superflex is True
        assert cfg.format.num_teams == 10
        assert cfg_file.exists()
