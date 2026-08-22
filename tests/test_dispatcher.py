from unittest.mock import MagicMock, patch
import pytest

def test_tool_schemas_registered() -> None:
    from ff.services.llm.tools import TOOL_SCHEMAS
    tool_names = [t["name"] for t in TOOL_SCHEMAS]
    expected_tools = [
        "setup_league",
        "evaluate_trade",
        "get_lineup",
        "get_waivers",
        "get_roster",
        "get_power_rankings",
        "get_picks",
        "get_roster_cleanup",
        "get_movers",
        "get_draft_fit",
        "get_dynasty_values",
    ]
    for tool in expected_tools:
        assert tool in tool_names, f"Tool {tool} not found in TOOL_SCHEMAS"

def test_dispatch_evaluate_trade() -> None:
    from ff.services.llm.dispatcher import dispatch_tool
    mock_eval = MagicMock()
    mock_eval.model_dump.return_value = {"give_total": 5000, "get_total": 5500}
    with patch("ff.analysis.trade.evaluate_trade", return_value=mock_eval):
        res = dispatch_tool("evaluate_trade", {"give": ["Gibbs"], "get": ["Bijan"]}, ctx={})
        assert res == {"give_total": 5000, "get_total": 5500}

def test_dispatch_setup_league() -> None:
    from ff.services.llm.dispatcher import dispatch_tool
    mock_cfg = MagicMock()
    mock_cfg.model_dump.return_value = {"league_id": "123", "user_name": "philippos"}
    mock_onboard = MagicMock(return_value=mock_cfg)
    res = dispatch_tool("setup_league", {"username": "philippos"}, ctx={"onboard_user": mock_onboard})
    assert res == {"league_id": "123", "user_name": "philippos"}
    mock_onboard.assert_called_once_with(username="philippos")

def _named_roster(name: str = "Team A"):
    r = MagicMock()
    r.team_name = name
    r.owner_id = "u1"
    r.roster_id = 1
    r.player_ids = []
    return r


def test_dispatch_get_lineup() -> None:
    from ff.services.llm.dispatcher import dispatch_tool
    mock_lineup = MagicMock()
    mock_lineup.model_dump.return_value = {"slots": [], "bench": []}
    mock_roster = _named_roster("Team A")
    with patch("ff.analysis.lineup.optimal_lineup", return_value=mock_lineup):
        res = dispatch_tool("get_lineup", {"team": "Team A", "week": 1}, ctx={"rosters": [mock_roster]})
        assert res == {"slots": [], "bench": []}

def test_dispatch_get_waivers() -> None:
    from ff.services.llm.dispatcher import dispatch_tool
    mock_target = MagicMock()
    mock_target.model_dump.return_value = {"asset": {"name": "Player A"}, "add_count": 10}
    mock_target.asset.position = "RB"
    with patch("ff.analysis.waivers.waiver_targets", return_value=[mock_target]):
        res = dispatch_tool("get_waivers", {"position": "RB", "limit": 5}, ctx={})
        assert res == [{"asset": {"name": "Player A"}, "add_count": 10}]

def test_dispatch_get_roster() -> None:
    from ff.services.llm.dispatcher import dispatch_tool
    mock_val = MagicMock()
    mock_val.model_dump.return_value = {"total_value": 50000}
    mock_roster = _named_roster("Team A")
    with patch("ff.analysis.roster.value_roster", return_value=mock_val):
        res = dispatch_tool("get_roster", {"team": "Team A"}, ctx={"rosters": [mock_roster]})
        assert res == {"total_value": 50000}

def test_dispatch_get_power_rankings() -> None:
    from ff.services.llm.dispatcher import dispatch_tool
    mock_val = MagicMock()
    mock_val.model_dump.return_value = {"power_rank": 1, "total_value": 60000}
    with patch("ff.analysis.roster.value_all_rosters", return_value=[mock_val]):
        res = dispatch_tool("get_power_rankings", {}, ctx={"rosters": [MagicMock()]})
        assert res == [{"power_rank": 1, "total_value": 60000}]

def test_dispatch_get_picks() -> None:
    from ff.services.llm.dispatcher import dispatch_tool
    mock_tp = MagicMock()
    mock_tp.model_dump.return_value = {"roster_id": 1, "total_value": 15000}
    with patch("ff.analysis.picks.pick_ledger", return_value=[mock_tp]):
        res = dispatch_tool("get_picks", {}, ctx={})
        assert res == [{"roster_id": 1, "total_value": 15000}]

def test_dispatch_get_roster_cleanup() -> None:
    from ff.services.llm.dispatcher import dispatch_tool
    mock_audit = MagicMock()
    mock_audit.model_dump.return_value = {"drop_candidates": []}
    roster = _named_roster("Mine")
    cfg = MagicMock(user_id="u1", user_name="")
    with patch("ff.analysis.cleanup.audit_roster", return_value=mock_audit):
        res = dispatch_tool("get_roster_cleanup", {}, ctx={"rosters": [roster], "config": cfg})
        assert res == {"drop_candidates": []}

def test_dispatch_get_movers() -> None:
    from ff.services.llm.dispatcher import dispatch_tool
    mock_asset = MagicMock()
    mock_asset.model_dump.return_value = {"name": "Player X"}
    with patch("ff.analysis.movers.top_movers", return_value=[(mock_asset, 25.0)]):
        res = dispatch_tool("get_movers", {"buy": True}, ctx={})
        assert res == [{"asset": {"name": "Player X"}, "gap_pct": 25.0}]

def test_dispatch_get_draft_fit() -> None:
    from ff.services.llm.dispatcher import dispatch_tool
    mock_team_ctx = MagicMock()
    mock_team_ctx.model_dump.return_value = {"status": "contend"}
    mock_fit = MagicMock()
    mock_fit.model_dump.return_value = {"fit_score": 9000}
    with patch("ff.analysis.fit.rank_fits", return_value=(mock_team_ctx, [mock_fit])):
        res = dispatch_tool("get_draft_fit", {}, ctx={"rosters": [MagicMock()]})
        assert res == {
            "context": {"status": "contend"},
            "fits": [{"fit_score": 9000}]
        }

def test_dispatch_get_dynasty_values() -> None:
    from ff.services.llm.dispatcher import dispatch_tool
    mock_book = MagicMock()
    mock_asset = MagicMock()
    mock_asset.model_dump.return_value = {"name": "Bijan Robinson", "value": 9000}
    mock_book.top.return_value = [mock_asset]
    res = dispatch_tool("get_dynasty_values", {"position": "RB", "limit": 1}, ctx={"value_book": mock_book})
    assert res == [{"name": "Bijan Robinson", "value": 9000}]
    mock_book.top.assert_called_once_with(position="RB", limit=1)

def test_dispatch_unknown_tool() -> None:
    from ff.services.llm.dispatcher import dispatch_tool
    with pytest.raises(ValueError, match="Unknown tool"):
        dispatch_tool("nonexistent_tool", {}, ctx={})


def test_dispatch_unknown_team_does_not_fallback() -> None:
    from ff.contracts import Roster
    from ff.services.llm.dispatcher import dispatch_tool
    a = Roster(roster_id=1, team_name="Gridiron Kings", owner_id="u1")
    b = Roster(roster_id=2, team_name="Dynasty Warriors", owner_id="u2")
    with pytest.raises(ValueError, match="could not find that team"):
        dispatch_tool("get_roster", {"team": "zzzz-not-a-team"}, ctx={"rosters": [a, b]})


def test_dispatch_get_draft_fit_excludes_rostered_players() -> None:
    from ff.contracts import Asset, Roster
    from ff.services.llm.dispatcher import dispatch_tool
    from ff.values import ValueBook

    taken = Asset(id="7564", name="Ja'Marr Chase", position="WR", value=9000)
    free = Asset(id="9221", name="Jahmyr Gibbs", position="RB", value=8000)
    book = ValueBook([taken, free])
    r = Roster(roster_id=1, team_name="Mine", owner_id="u1", player_ids=["7564"])
    cfg = MagicMock(user_id="u1", user_name="")
    captured = {}

    def fake_rank(candidates, my_val, all_vals, roster_positions, status, limit):
        captured["ids"] = [c.id for c in candidates]
        ctx = MagicMock()
        ctx.model_dump.return_value = {"status": "contend"}
        fit = MagicMock()
        fit.model_dump.return_value = {"fit_score": 1}
        return ctx, [fit]

    with patch("ff.analysis.fit.rank_fits", side_effect=fake_rank):
        dispatch_tool("get_draft_fit", {}, ctx={
            "rosters": [r],
            "value_book": book,
            "config": cfg,
        })
    assert "7564" not in captured["ids"]
    assert "9221" in captured["ids"]
