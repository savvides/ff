from unittest.mock import MagicMock, patch
from pathlib import Path
import pytest

from ff.contracts import Format
from ff.services.llm.onboarding import onboard_user


def test_onboard_user_creates_config(tmp_path: Path) -> None:
    mock_leagues = [{"league_id": "999", "name": "My Dynasty", "season": "2026"}]
    mock_format = MagicMock(is_superflex=True, ppr=1.0)
    
    with patch("ff.sleeper.client.get_user_leagues", return_value=mock_leagues), \
         patch("ff.sleeper.client.detect_format", return_value=mock_format):
        cfg_file = tmp_path / "config.json"
        cfg = onboard_user(username="philippos", config_path=cfg_file)
        assert cfg.league_id == "999"
        assert cfg.user_name == "philippos"
        assert cfg_file.exists()


def test_onboard_user_no_leagues_raises_error(tmp_path: Path) -> None:
    with patch("ff.sleeper.client.get_user_leagues", return_value=[]):
        cfg_file = tmp_path / "config.json"
        with pytest.raises(ValueError, match="No active leagues found for user 'unknown_user'"):
            onboard_user(username="unknown_user", config_path=cfg_file)


def test_onboard_user_with_real_format_object(tmp_path: Path) -> None:
    mock_leagues = [{"league_id": "888", "name": "Superflex League", "season": "2026"}]
    real_format = Format(superflex=True, ppr=1.0, num_teams=10)
    
    with patch("ff.sleeper.client.get_user_leagues", return_value=mock_leagues), \
         patch("ff.sleeper.client.detect_format", return_value=real_format):
        cfg_file = tmp_path / "config.json"
        cfg = onboard_user(username="testuser", config_path=cfg_file)
        assert cfg.league_id == "888"
        assert cfg.user_name == "testuser"
        assert cfg.format.superflex is True
        assert cfg.format.num_teams == 10
        assert cfg_file.exists()
