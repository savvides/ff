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
        assert res["slots"] == []
        assert res["bench"] == []
        assert "news_review" in res

def test_dispatch_get_waivers() -> None:
    from ff.services.llm.dispatcher import dispatch_tool
    mock_target = MagicMock()
    mock_target.asset.is_pick = False
    mock_target.asset.id = "p1"
    mock_target.model_dump.return_value = {"asset": {"name": "Player A"}, "add_count": 10}
    with patch("ff.analysis.waivers.waiver_targets", return_value=[mock_target]) as calculate:
        res = dispatch_tool("get_waivers", {"position": "RB", "limit": 5}, ctx={})
        assert res["targets"] == [{"asset": {"name": "Player A"}, "add_count": 10}]
        assert "news_review" in res
    assert calculate.call_args.kwargs["position"] == "RB"
    assert calculate.call_args.kwargs["limit"] == 5


def test_waivers_filter_before_limit_and_use_league_format():
    from ff.contracts import Asset, Format
    from ff.core.config import Config
    from ff.services.llm.dispatcher import dispatch_tool
    from ff.values import ValueBook

    book = ValueBook([
        Asset(id="wr", name="Receiver", position="WR", value=5000),
        Asset(id="rb", name="Runner", position="RB", value=1000),
    ])
    ctx = {"value_book": book, "trending": [{"player_id": p, "count": 1} for p in ("wr", "rb")],
           "config": Config(league_id="x", season=2026, format=Format(superflex=False))}
    result = dispatch_tool("get_waivers", {"position": "RB", "limit": 1}, ctx)
    assert [t["asset"]["id"] for t in result["targets"]] == ["rb"]
    with patch("ff.analysis.waivers.waiver_targets", return_value=[]) as calculate:
        dispatch_tool("get_waivers", {}, ctx)
    assert calculate.call_args.kwargs["is_superflex"] is False


def test_cleanup_dispatch_uses_league_format_and_drop_limit():
    from ff.contracts import Format, Roster
    from ff.core.config import Config
    from ff.services.llm.dispatcher import dispatch_tool

    cfg = Config(league_id="x", season=2026, user_id="me", format=Format(superflex=False))
    with patch("ff.analysis.cleanup.audit_roster") as calculate:
        dispatch_tool("get_roster_cleanup", {"limit": 3}, {
            "config": cfg, "rosters": [Roster(roster_id=1, owner_id="me")],
        })
    assert calculate.call_args.kwargs["is_superflex"] is False
    assert calculate.call_args.kwargs["drop_limit"] == 3

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
        assert res["drop_candidates"] == []
        assert "news_review" in res

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
    cfg = MagicMock(user_id="u1", user_name="")
    with pytest.raises(ValueError, match="could not find that team"):
        dispatch_tool("get_roster", {"team": "zzzz-not-a-team"}, ctx={"rosters": [a, b], "config": cfg})


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


def test_dispatch_evaluate_trade_coerces_string_inputs() -> None:
    from ff.services.llm.dispatcher import dispatch_tool
    mock_eval = MagicMock()
    mock_eval.model_dump.return_value = {"give_total": 5000, "get_total": 5500}
    with patch("ff.analysis.trade.evaluate_trade", return_value=mock_eval) as mock_trade:
        res = dispatch_tool("evaluate_trade", {"give": "Gibbs, 2026 2nd", "get": "Bijan"}, ctx={})
        assert res == {"give_total": 5000, "get_total": 5500}
        mock_trade.assert_called_once()
        _, kwargs = mock_trade.call_args
        assert kwargs["give_inputs"] == ["Gibbs", "2026 2nd"]
        assert kwargs["get_inputs"] == ["Bijan"]


def test_dispatcher_find_roster_owner_id_priority() -> None:
    from ff.contracts import Roster
    from ff.services.llm.dispatcher import _find_roster
    # Dan's owner id is "u1". Another team's name is "Dan's Rivals" owned by "u2".
    user_team = Roster(roster_id=1, team_name="Champion Squad", owner_id="u1")
    other_team = Roster(roster_id=2, team_name="Dan's Rivals", owner_id="u2")
    cfg = MagicMock(user_id="u1", user_name="dan")
    matched = _find_roster([other_team, user_team], None, {"config": cfg})
    assert matched.roster_id == 1


def test_roster_id_takes_priority_over_numeric_team_name():
    from ff.contracts import Roster
    from ff.services.llm.dispatcher import _find_roster
    wrong = Roster(roster_id=2, team_name="1")
    intended = Roster(roster_id=1, team_name="My Team")
    assert _find_roster([wrong, intended], "1", {}) is intended


def test_lineup_cannot_label_current_week_facts_as_another_week():
    from ff.services.llm.dispatcher import dispatch_tool
    import pytest
    from ff.contracts import Roster
    with pytest.raises(ValueError, match="current week"):
        dispatch_tool("get_lineup", {"team": "1", "week": 8}, {
            "rosters": [Roster(roster_id=1)], "weekly": object(), "week": 3})


def test_tool_schemas_includes_get_team_window() -> None:
    from ff.services.llm.tools import ALLOWED_TOOLS, TOOL_SCHEMAS
    assert "get_team_window" in ALLOWED_TOOLS
    assert any(t["name"] == "get_team_window" for t in TOOL_SCHEMAS)


def test_dispatch_get_team_window_and_trade_filters() -> None:
    from ff.contracts import Asset, Format, Roster
    from ff.core.config import Config
    from ff.services.llm.dispatcher import dispatch_tool
    from ff.values import ValueBook

    cfg = Config(league_id="LG1", season=2026, format=Format(), user_id="u1", window_mode="rebuild")
    r1 = Roster(roster_id=1, owner_id="u1", team_name="Mine", player_ids=["p1"], wins=4, losses=6, max_pf=1100.0)
    r2 = Roster(roster_id=2, owner_id="u2", team_name="Rival", player_ids=["p2"], wins=8, losses=2, max_pf=1500.0)
    a1 = Asset(id="p1", name="Vet RB", position="RB", age=27.0, value=3000, redraft_value=3500)
    a2 = Asset(id="p2", name="Young WR", position="WR", age=22.0, value=6000, redraft_value=5000)
    book = ValueBook([a1, a2])
    ctx = {
        "config": cfg,
        "rosters": [r1, r2],
        "value_book": book,
        "players_meta": {},
        "roster_positions": ["QB", "RB", "WR", "FLEX"],
        "state": {"season_type": "regular", "week": 8},
    }
    win = dispatch_tool("get_team_window", {}, ctx=ctx)
    assert win["effective_target"] == "rebuild"
    assert win["target_source"] == "config"

    rival_win = dispatch_tool("get_team_window", {"team": "Rival"}, ctx=ctx)
    assert rival_win["team_name"] == "Rival"
    assert rival_win["target_source"] == "auto"

    override_win = dispatch_tool("get_team_window", {"mode": "contend"}, ctx=ctx)
    assert override_win["effective_target"] == "contend"
    assert override_win["target_source"] == "override"

    with pytest.raises(ValueError, match="mode"):
        dispatch_tool("get_team_window", {"mode": "invalid"}, ctx=ctx)

    trade_res = dispatch_tool("evaluate_trade", {"give": ["Vet RB"], "get": ["Young WR"]}, ctx=ctx)
    assert "strategy_filters" in trade_res
    assert [f["name"] for f in trade_res["strategy_filters"]] == ["Duration", "RB Option Risk", "Seasonal Liquidity"]


def test_dispatch_get_draft_fit_honors_config_window_mode() -> None:
    from ff.contracts import Asset, Format, Roster
    from ff.core.config import Config
    from ff.services.llm.dispatcher import dispatch_tool
    from ff.values import ValueBook

    cfg = Config(league_id="LG1", season=2026, format=Format(), user_id="u1", window_mode="rebuild")
    # r1 has higher value so auto status would be "contend", r2 has lower value so auto would be "rebuild"
    r1 = Roster(roster_id=1, owner_id="u1", team_name="Mine", player_ids=["p1"])
    r2 = Roster(roster_id=2, owner_id="u2", team_name="Rival", player_ids=["p2"])
    r3 = Roster(roster_id=3, owner_id="u3", team_name="Mid", player_ids=["p3"])
    book = ValueBook([
        Asset(id="p1", name="Star A", position="WR", value=9000),
        Asset(id="p2", name="Bench B", position="WR", value=2000),
        Asset(id="p3", name="Mid C", position="WR", value=5000),
        Asset(id="p4", name="Rookie D", position="WR", value=4000),
    ])
    captured = []

    def fake_rank(candidates, my_val, all_vals, roster_positions, status, limit):
        captured.append(status)
        team_ctx = MagicMock()
        team_ctx.model_dump.return_value = {"status": status}
        return team_ctx, []

    ctx = {"config": cfg, "rosters": [r1, r2, r3], "value_book": book, "players_meta": {}, "roster_positions": []}
    with patch("ff.analysis.fit.rank_fits", side_effect=fake_rank):
        dispatch_tool("get_draft_fit", {}, ctx=ctx)
        dispatch_tool("get_draft_fit", {"team": "Rival"}, ctx=ctx)
    assert captured == ["rebuild", "rebuild"]

    # When cfg.window_mode="contend", Mine becomes "contend" while Rival remains auto-detected ("rebuild")
    cfg.window_mode = "contend"
    captured.clear()
    with patch("ff.analysis.fit.rank_fits", side_effect=fake_rank):
        dispatch_tool("get_draft_fit", {}, ctx=ctx)
        dispatch_tool("get_draft_fit", {"team": "Rival"}, ctx=ctx)
    assert captured == ["contend", "rebuild"]

    # Explicit mode="auto" clears saved cfg.window_mode and uses live window diagnosis; mode="rebuild" overrides
    cfg.window_mode = "rebuild"
    captured.clear()
    with patch("ff.analysis.fit.rank_fits", side_effect=fake_rank):
        dispatch_tool("get_draft_fit", {"mode": "auto"}, ctx=ctx)
        dispatch_tool("get_draft_fit", {"team": "Mid", "mode": "contend"}, ctx=ctx)
    assert captured == ["contend", "contend"]


def test_dispatch_window_and_draft_fit_without_user_id_uses_fallback_and_never_leaks_to_rival() -> None:
    from ff.contracts import Asset, Format, Roster
    from ff.core.config import Config
    from ff.services.llm.dispatcher import dispatch_tool
    from ff.values import ValueBook

    # Rank 1 = Rival ("contend" auto), Rank 2 = Mine ("balanced" / middle_trap auto), Rank 3 = Other ("rebuild" auto)
    r_rival = Roster(roster_id=2, owner_id="u2", team_name="Rival", player_ids=["p2"], wins=8, losses=2, max_pf=1500.0)
    r_mine = Roster(roster_id=1, owner_id="u1", team_name="Mine", player_ids=["p1"], wins=5, losses=5, max_pf=1200.0)
    r_other = Roster(roster_id=3, owner_id="u3", team_name="Other", player_ids=["p3"], wins=2, losses=8, max_pf=900.0)
    book = ValueBook([
        Asset(id="p2", name="Star WR", position="WR", age=24.0, value=9000, redraft_value=8500),
        Asset(id="p1", name="Mid RB", position="RB", age=25.0, value=5000, redraft_value=5000),
        Asset(id="p3", name="Bench TE", position="TE", age=23.0, value=2000, redraft_value=2000),
        Asset(id="p4", name="Rookie WR", position="WR", age=21.0, value=4000, redraft_value=3000),
    ])

    captured: list[str] = []

    def fake_rank(candidates, my_val, all_vals, roster_positions, status, limit):
        captured.append(status)
        team_ctx = MagicMock()
        team_ctx.model_dump.return_value = {"status": status}
        return team_ctx, []

    for cfg in (
        Config(league_id="LG1", season=2026, format=Format(), user_id=None, user_name="Mine", window_mode="rebuild"),
        Config(league_id="LG1", season=2026, format=Format(), user_id=None, username="mine", window_mode="rebuild"),
    ):
        ctx = {
            "config": cfg,
            "rosters": [r_rival, r_mine, r_other],
            "value_book": book,
            "players_meta": {},
            "roster_positions": ["QB", "RB", "WR", "FLEX"],
            "state": {"season_type": "regular", "week": 8},
        }

        my_win = dispatch_tool("get_team_window", {}, ctx=ctx)
        assert my_win["team_name"] == "Mine"
        assert my_win["effective_target"] == "rebuild"
        assert my_win["target_source"] == "config"

        my_named_win = dispatch_tool("get_team_window", {"team": "Mine"}, ctx=ctx)
        assert my_named_win["effective_target"] == "rebuild"
        assert my_named_win["target_source"] == "config"

        rival_win = dispatch_tool("get_team_window", {"team": "Rival"}, ctx=ctx)
        assert rival_win["team_name"] == "Rival"
        assert rival_win["effective_target"] == "contend"
        assert rival_win["target_source"] == "auto"

        captured.clear()
        with patch("ff.analysis.fit.rank_fits", side_effect=fake_rank):
            dispatch_tool("get_draft_fit", {}, ctx=ctx)
            dispatch_tool("get_draft_fit", {"team": "Mine"}, ctx=ctx)
            dispatch_tool("get_draft_fit", {"team": "Rival"}, ctx=ctx)
        assert captured == ["rebuild", "rebuild", "contend"]

    # Also verify no identity in config never leaks cfg.window_mode onto a rival
    anon_cfg = Config(league_id="LG1", season=2026, format=Format(), user_id=None, username=None, user_name=None, window_mode="rebuild")
    anon_ctx = {
        "config": anon_cfg,
        "rosters": [r_rival, r_mine, r_other],
        "value_book": book,
        "players_meta": {},
        "roster_positions": ["QB", "RB", "WR", "FLEX"],
        "state": {"season_type": "regular", "week": 8},
    }
    captured.clear()
    with patch("ff.analysis.fit.rank_fits", side_effect=fake_rank):
        dispatch_tool("get_draft_fit", {"team": "Rival"}, ctx=anon_ctx)
    assert captured == ["contend"]


def test_dispatch_standings_and_trade_plan() -> None:
    from ff.contracts import Asset, Roster, StandingProjection
    from ff.services.llm.dispatcher import dispatch_tool
    from ff.values import ValueBook

    vet = Asset(id="vet", name="Vet", position="RB", age=29, value=3000, redraft_value=4500)
    kid = Asset(id="kid", name="Kid", position="WR", age=22, value=4000, redraft_value=2000)
    ctx = {
        "rosters": [Roster(roster_id=1, owner_id="me", team_name="Mine", player_ids=["vet"]),
                    Roster(roster_id=2, owner_id="x", team_name="Other", player_ids=["kid"])],
        "value_book": ValueBook([vet, kid]),
        "players_meta": {},
        "season_sim": [StandingProjection(roster_id=1, team_name="Mine", exp_wins=2.0,
                                          playoff_odds=0.0, draft_slot=1.0)],
    }
    assert dispatch_tool("get_standings", {}, ctx)[0]["draft_slot"] == 1.0
    res = dispatch_tool("get_trade_plan", {"team": "Mine"}, ctx)
    assert res["stance"] == "seller"
    assert [r["player"] for r in res["shop"]] == ["Vet"]
    assert [r["player"] for r in res["target"]] == ["Kid"]
