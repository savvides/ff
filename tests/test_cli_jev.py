"""Full offline HTTP -> interpretation -> calculation -> table journeys."""
import json
from unittest.mock import Mock

import pytest
import requests
import responses
from typer.testing import CliRunner

from ff.cli import app
from ff.contracts import Format
from ff.core.config import Config, load_config, save_config
from ff.services.llm.jev import ENDPOINT

runner = CliRunner()


@pytest.fixture
def configured(fake_clients, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "private-test-key")
    monkeypatch.setenv("FF_QA", "strict")
    save_config(Config(league_id="LG1", season=2026, format=Format(), user_id="userA"))
    terminal = Mock(side_effect=AssertionError("Jev must not start a terminal runner"))
    monkeypatch.setattr("ff.cli.TerminalRunner", terminal)
    return terminal


def serve(operation, arguments, low_stage=None):
    def callback(request):
        body = json.loads(request.body)
        questions = body["questions"]
        selected = {"operation": operation} if "operation" in questions else {"scope": "supported", **arguments}
        answers = {
            name: {"type": "choice", "choice": selected[name],
                   "confidence": 0.1 if name == low_stage else 0.95,
                   "probabilities": {k: float(k == selected[name]) for k in q["criteria"]}}
            for name, q in questions.items()
        }
        return 200, {}, json.dumps({"model": "jev-test", "answers": answers, "usage": {"input_tokens": 100, "output_tokens": 10}})
    responses.add_callback(responses.POST, ENDPOINT, callback=callback)


@pytest.mark.parametrize("operation, arguments, expected", [
    ("get_roster", {"team": "mine", "limit": "default"}, "dynasty value"),
    ("get_power_rankings", {}, "League power rankings"),
    ("get_dynasty_values", {"position": "RB", "limit": "1"}, "Dynasty player values"),
    ("get_waivers", {"position": "RB", "limit": "5"}, "Trending free agents"),
    ("get_picks", {"team": "mine"}, "2027"),
    ("get_picks", {"team": "league"}, "Gridiron Kings"),
    ("get_roster_cleanup", {"team": "mine", "limit": "3"}, "Drop candidates"),
    ("get_lineup", {"team": "mine"}, "2026 week 1"),
])
@responses.activate
def test_supported_journeys(configured, operation, arguments, expected):
    serve(operation, arguments)
    result = runner.invoke(app, ["ask", "test question", "--backend", "jev"])
    assert result.exit_code == 0, result.output + str(result.exception)
    assert "Interpreted:" in result.output
    assert expected in result.output
    assert result.output.count("QA:") == 1
    configured.assert_not_called()
    assert len(responses.calls) == 2
    # Never send roster contents or valuation data to the model.
    for call in responses.calls:
        body = json.loads(call.request.body)
        assert body["state"] == "test question"
        assert "player_ids" not in str(body)
        assert "userA" not in str(body)


@pytest.mark.parametrize("stage", ["operation", "team", "scope"])
@responses.activate
def test_low_confidence_does_not_dispatch(configured, monkeypatch, stage):
    serve("get_lineup", {"team": "mine"}, low_stage=stage)
    dispatch = Mock(side_effect=AssertionError("Must not dispatch"))
    monkeypatch.setattr("ff.cli.dispatch_tool", dispatch)
    result = runner.invoke(app, ["ask", "unclear", "--backend", "jev"])
    assert result.exit_code == 3
    assert "confidently" in result.output
    dispatch.assert_not_called()
    assert len(responses.calls) == (1 if stage == "operation" else 2)


@pytest.mark.parametrize("operation, arguments", [
    ("trade", {}), ("ambiguous", {}),
    ("get_lineup", {"team": "mine", "scope": "unsupported"}),
    ("get_picks", {"team": "unknown"}),
])
@responses.activate
def test_abstains_without_dispatch(configured, monkeypatch, operation, arguments):
    serve(operation, arguments)
    dispatch = Mock()
    monkeypatch.setattr("ff.cli.dispatch_tool", dispatch)
    result = runner.invoke(app, ["ask", "unsupported", "--backend", "jev"])
    assert result.exit_code == 3, result.output
    assert "Interpreted:" not in result.output
    dispatch.assert_not_called()


@responses.activate
def test_picks_window_follows_latest_draft(configured):
    serve("get_picks", {"team": "league"})
    result = runner.invoke(app, ["ask", "league picks", "--backend", "jev"])
    assert result.exit_code == 0, result.output
    assert "seasons: ['2027', '2028']; rounds: 2" in result.output
    assert "2027 1st" in result.output and "2026 1st" not in result.output


@responses.activate
def test_lineup_missing_projections(configured, monkeypatch):
    serve("get_lineup", {"team": "mine"})
    monkeypatch.setattr("ff.cli.ProjectionsClient", lambda: Mock(week=Mock(return_value={})))
    result = runner.invoke(app, ["ask", "my lineup", "--backend", "jev"])
    assert result.exit_code == 3
    assert "No projections available" in result.output


@responses.activate
def test_lineup_fetch_and_label_use_same_week(configured, monkeypatch):
    import ff.cli as cli
    original = cli.SleeperClient()
    original.state = lambda: {"season": "2026", "week": 3, "display_week": 4}
    monkeypatch.setattr(cli, "SleeperClient", lambda: original)
    projections = Mock(week=Mock(return_value={"7564": {"rec": 8}}))
    monkeypatch.setattr(cli, "ProjectionsClient", lambda: projections)
    serve("get_lineup", {"team": "mine"})
    result = runner.invoke(app, ["ask", "my lineup", "--backend", "jev"])
    assert result.exit_code == 0, result.output
    projections.week.assert_called_once_with("2026", 4)
    assert "2026 week 4" in result.output


@responses.activate
def test_lineup_state_unavailable(configured, monkeypatch):
    import ff.cli as cli
    sleeper = cli.SleeperClient()
    sleeper.state = lambda: None
    monkeypatch.setattr(cli, "SleeperClient", lambda: sleeper)
    serve("get_lineup", {"team": "mine"})
    result = runner.invoke(app, ["ask", "my lineup", "--backend", "jev"])
    assert result.exit_code == 3
    assert "season is not current" in result.output
    assert isinstance(result.exception, SystemExit)


@responses.activate
def test_lineup_stale_season(configured):
    cfg = load_config()
    cfg.season = 2025
    save_config(cfg)
    serve("get_lineup", {"team": "mine"})
    result = runner.invoke(app, ["ask", "my lineup", "--backend", "jev"])
    assert result.exit_code == 3
    assert "season is not current" in result.output


@pytest.mark.parametrize("limit, pool", [("5", 50), ("20", 60)])
@responses.activate
def test_waiver_pool_matches_ff_waivers(configured, monkeypatch, trending, limit, pool):
    import ff.cli as cli
    sleeper = cli.SleeperClient()
    sleeper.trending = Mock(return_value=trending)
    monkeypatch.setattr(cli, "SleeperClient", lambda: sleeper)
    serve("get_waivers", {"position": "all", "limit": limit})
    result = runner.invoke(app, ["ask", "waivers", "--backend", "jev"])
    assert result.exit_code == 0, result.output
    sleeper.trending.assert_called_once_with(kind="add", limit=pool)


@pytest.mark.parametrize("limit, note", [("5", "Only 2 of 5"), ("1", None)])
@responses.activate
def test_waiver_shortfall_note(configured, limit, note):
    serve("get_waivers", {"position": "WR", "limit": limit})
    result = runner.invoke(app, ["ask", "waiver receivers", "--backend", "jev"])
    assert result.exit_code == 0, result.output
    if note:
        assert note in result.output
    else:
        assert "Only " not in result.output


@responses.activate
def test_empty_waivers(configured, monkeypatch):
    import ff.cli as cli
    sleeper = cli.SleeperClient()
    sleeper.trending = lambda **kwargs: []
    monkeypatch.setattr(cli, "SleeperClient", lambda: sleeper)
    serve("get_waivers", {"position": "all", "limit": "default"})
    result = runner.invoke(app, ["ask", "waivers", "--backend", "jev"])
    assert result.exit_code == 0, result.output
    assert "no results" in result.output


def test_missing_config(monkeypatch):
    monkeypatch.setattr("ff.cli.JevClient", Mock(side_effect=AssertionError("No API before setup")))
    result = runner.invoke(app, ["ask", "hello", "--backend", "jev"])
    assert result.exit_code == 1
    assert "No league configured" in result.output


def test_missing_key(configured, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    result = runner.invoke(app, ["ask", "hello", "--backend", "jev"])
    assert result.exit_code == 1
    assert "TYPESAFE_API_KEY" in result.output


@responses.activate
def test_api_error_is_not_a_sleeper_or_config_error(configured):
    responses.post(ENDPOINT, status=401, body="private-test-key")
    result = runner.invoke(app, ["ask", "hello", "--backend", "jev"])
    assert result.exit_code == 1
    assert "authentication failed" in result.output
    assert "private-test-key" not in result.output
    assert "config is corrupt" not in result.output


@pytest.mark.parametrize("broken, message", [
    ("sleeper", "could not reach Sleeper/FantasyCalc"), ("result", "config is corrupt"),
])
@responses.activate
def test_data_errors_use_guard(configured, monkeypatch, broken, message):
    import ff.cli as cli
    if broken == "sleeper":
        sleeper = cli.SleeperClient()
        sleeper.rosters = Mock(side_effect=requests.exceptions.JSONDecodeError("Expecting value", "", 0))
        monkeypatch.setattr(cli, "SleeperClient", lambda: sleeper)
    else:
        monkeypatch.setattr(cli, "dispatch_tool", lambda *args: [{}])
    serve("get_power_rankings", {})
    result = runner.invoke(app, ["ask", "rank the league", "--backend", "jev"])
    assert result.exit_code == 1
    assert message in result.output
    assert "error:" not in result.output
    assert "validation error" not in result.output


@responses.activate
def test_saved_jev_backend(configured):
    result = runner.invoke(app, ["config", "set-llm", "jev"])
    assert result.exit_code == 0
    assert load_config().llm_backend == "jev"
    assert "private-test-key" not in load_config().model_dump_json()
    serve("get_power_rankings", {})
    result = runner.invoke(app, ["ask", "rank the league"])
    assert result.exit_code == 0, result.output


@responses.activate
def test_backend_name_is_case_insensitive(configured):
    serve("get_power_rankings", {})
    result = runner.invoke(app, ["ask", "rank the league", "--backend", "Jev"])
    assert result.exit_code == 0, result.output
    configured.assert_not_called()


@responses.activate
def test_saved_backend_name_is_case_insensitive(configured):
    cfg = load_config()
    cfg.llm_backend = "JEV"
    save_config(cfg)
    serve("get_power_rankings", {})
    result = runner.invoke(app, ["ask", "rank the league"])
    assert result.exit_code == 0, result.output
    configured.assert_not_called()


def test_unknown_backend_lists_jev(configured):
    result = runner.invoke(app, ["ask", "rank the league", "--backend", "jevv"])
    assert result.exit_code == 1
    assert "jev" in result.output.replace("jevv", "")
    configured.assert_not_called()


@responses.activate
def test_waiver_calculation_matches_direct_analysis(configured, book, rosters_raw, users_raw, players_meta, trending, monkeypatch):
    from ff.analysis.waivers import waiver_targets
    from ff.sleeper import build_rosters
    import ff.cli as cli
    original_dispatch = cli.dispatch_tool
    captured = {}
    def capture(tool, args, ctx):
        captured["result"] = original_dispatch(tool, args, ctx)
        return captured["result"]
    monkeypatch.setattr(cli, "dispatch_tool", capture)
    serve("get_waivers", {"position": "RB", "limit": "1"})
    result = runner.invoke(app, ["ask", "top available RB", "--backend", "jev"])
    assert result.exit_code == 0, result.output
    direct = waiver_targets(trending, book, build_rosters(rosters_raw, users_raw), players_meta, limit=len(trending), is_superflex=True)
    expected = [t.model_dump() for t in direct if t.asset.position == "RB"][:1]
    # Secondary market fields do not affect the opportunity score.
    assert [(t["asset"]["id"], t["opportunity_score"]) for t in captured["result"]] == [(t["asset"]["id"], t["opportunity_score"]) for t in expected]
