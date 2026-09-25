"""Check evaluator scoring separately from live model quality."""
import json
import runpy
import sys
from pathlib import Path

import pytest

from ff.services.llm.jev import Clarification, JevError, Route


@pytest.mark.parametrize("mode, exit_code", [("pass", 0), ("wrong", 1), ("api_error", 1), ("false_abstention", 1), ("control_fails", 1)])
@pytest.mark.parametrize("suite", ["jev.json", "jev-boundaries.json"])
def test_live_evaluator_gates(monkeypatch, capsys, mode, exit_code, suite):
    root = Path(__file__).parents[1]
    path = root / "evals" / suite
    monkeypatch.setattr(sys, "argv", ["eval_jev.py", "--cases", str(path)] if suite != "jev.json" else ["eval_jev.py"])
    cases = json.loads(path.read_text())
    expected = {c["query"]: c for c in cases}
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-only")
    def fake_interpret(query, client, get_rosters, user_id):
        case = expected[query]
        # Include a transient failure before each valid response, or exhausted retries.
        client.request_count += 3 if mode == "api_error" else 2
        if mode == "api_error":
            raise JevError("unavailable")
        client.calls.append({"model": "mock-only", "input_tokens": 10, "output_tokens": 1})
        if mode == "false_abstention" or (mode == "control_fails" and case["id"] == "control_roster"):
            raise Clarification("uncertain", "limit", 0.5)
        if case["expected"] is None:
            raise Clarification("unsupported", "time")
        if mode == "wrong":
            return Route(tool="get_power_rankings", kwargs={"bad": True})
        return Route.model_validate(case["expected"])
    monkeypatch.setattr("ff.services.llm.jev.interpret", fake_interpret)
    with pytest.raises(SystemExit) as outcome:
        runpy.run_path(str(root / "scripts/eval_jev.py"), run_name="__main__")
    assert outcome.value.code == exit_code
    report = json.loads(capsys.readouterr().out)
    assert report["passed"] is (mode == "pass")
    assert report["supported_total"] == sum(c["expected"] is not None for c in cases)
    assert report["unsupported_total"] == sum(c["expected"] is None for c in cases)
    assert report["api_calls"] == len(cases) * (3 if mode == "api_error" else 2)
    assert report["valid_responses"] == (0 if mode == "api_error" else len(cases))
    if mode == "api_error":
        assert report["api_errors"] == len(cases)
        assert report["unsupported_abstained"] == 0
        assert {c["error"] for c in report["cases"]} == {"unavailable"}
    if mode == "control_fails":
        assert report["supported_exact_accuracy"] > 0.90
        assert report["control_passed"] is False
    control = next(c for c in report["cases"] if c["id"] == "control_roster")
    if mode in ("false_abstention", "control_fails"):
        assert (control["question"], control["confidence"], control["message"]) == ("limit", 0.5, "uncertain")
    if mode == "wrong":
        assert control["route"] == {"tool": "get_power_rankings", "kwargs": {"bad": True}}
    abstention_id = "trade" if suite == "jev.json" else "market"
    abstention = next(c for c in report["cases"] if c["id"] == abstention_id)
    if mode in ("pass", "wrong", "control_fails"):
        assert (abstention["question"], abstention["confidence"]) == ("time", None)


def test_custom_suite_without_control_cannot_pass(monkeypatch, capsys, tmp_path):
    path = tmp_path / "cases.json"
    path.write_text(json.dumps([
        {"id": "supported", "query": "rank teams", "expected": {"tool": "get_power_rankings", "kwargs": {}}},
        {"id": "unsupported", "query": "trade", "expected": None},
    ]))
    monkeypatch.setattr(sys, "argv", ["eval_jev.py", "--cases", str(path)])
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-only")
    def fake_interpret(query, *args):
        if query == "trade":
            raise Clarification("unsupported")
        return Route(tool="get_power_rankings", kwargs={})
    monkeypatch.setattr("ff.services.llm.jev.interpret", fake_interpret)
    with pytest.raises(SystemExit) as outcome:
        runpy.run_path(str(Path(__file__).parents[1] / "scripts/eval_jev.py"), run_name="__main__")
    assert outcome.value.code == 1
    assert json.loads(capsys.readouterr().out)["control_passed"] is False
