"""Offline Jev HTTP contract and bounded interpretation tests."""
import copy
from unittest.mock import Mock

import pytest
import requests
import responses

from ff.contracts import Roster
from ff.services.llm.jev import (
    DEFERRED, ENDPOINT, ChoiceAnswer, Clarification, JevClient, JevError, choice, interpret,
)


def payload(questions, selected, confidence=0.95):
    return {"model": "jev-test", "usage": {"input_tokens": 100, "output_tokens": 10}, "answers": {
        name: {"type": "choice", "choice": selected[name], "confidence": confidence,
               "probabilities": {key: float(key == selected[name]) for key in spec["criteria"]}}
        for name, spec in questions.items()
    }}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "private-test-key")
    return JevClient()


@responses.activate
def test_client_posts_contract_and_model_override(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "private-test-key")
    monkeypatch.setenv("TYPESAFE_MODEL", "jev-pinned")
    client = JevClient()
    questions = {"operation": choice("Which operation?", {"a": "A", "b": "B"})}
    responses.post(ENDPOINT, json=payload(questions, {"operation": "a"}))
    assert client.choose("question", questions)["operation"].choice == "a"
    import json
    call = responses.calls[0]
    assert call.request.headers["Authorization"] == "Bearer private-test-key"
    assert json.loads(call.request.body) == {"model": "jev-pinned", "state": "question", "questions": questions}
    assert client.calls == [{"model": "jev-test", "input_tokens": 100, "output_tokens": 10}]


def test_missing_key(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(JevError, match="Set TYPESAFE_API_KEY"):
        JevClient()


@pytest.mark.parametrize("status, message", [(401, "authentication"), (403, "authentication"), (429, "rate limit"), (503, "HTTP 503"), (302, "HTTP 302")])
@responses.activate
def test_http_failures_are_safe_and_never_retried(client, status, message):
    responses.post(ENDPOINT, status=status, body="private-test-key secret provider body")
    with pytest.raises(JevError, match=message) as error:
        client.choose("test", {})
    assert "private-test-key" not in str(error.value)
    assert "provider body" not in str(error.value)
    assert len(responses.calls) == 1


def test_timeout_and_redirect_policy(client, monkeypatch):
    post = Mock(side_effect=requests.Timeout("private-test-key"))
    monkeypatch.setattr("ff.services.llm.jev.requests.post", post)
    with pytest.raises(JevError, match="timed out") as error:
        client.choose("test", {})
    assert "private-test-key" not in str(error.value)
    assert post.call_args.kwargs["timeout"] == 15
    assert post.call_args.kwargs["allow_redirects"] is False
    post.assert_called_once()


@pytest.mark.parametrize("corruption", ["missing", "unknown", "nan", "range", "probabilities", "wrong_winner", "wrong_type", "bad_json"])
@responses.activate
def test_rejects_bad_responses(client, corruption):
    questions = {"op": choice("Choose", {"a": "A", "b": "B"})}
    data = payload(questions, {"op": "a"})
    answer = data["answers"]["op"]
    if corruption == "missing":
        data["answers"] = {}
    elif corruption == "unknown":
        answer["choice"] = "shell"
    elif corruption == "nan":
        answer["confidence"] = float("nan")
    elif corruption == "range":
        answer["confidence"] = 1.2
    elif corruption == "probabilities":
        answer["probabilities"] = {"a": 0.2, "b": 0.2}
    elif corruption == "wrong_winner":
        answer["probabilities"] = {"a": 0.1, "b": 0.9}
    elif corruption == "wrong_type":
        answer["type"] = "score"
    if corruption == "bad_json":
        responses.post(ENDPOINT, body="not json: private-test-key")
    else:
        responses.post(ENDPOINT, json=data)
    with pytest.raises(JevError, match="invalid response"):
        client.choose("test", questions)


@responses.activate
def test_choose_returns_low_confidence_answers(client):
    # The floor is applied by interpret(), which knows which answers would execute.
    questions = {"op": choice("Choose", {"a": "A", "b": "B"})}
    responses.post(ENDPOINT, json=payload(questions, {"op": "a"}, 0.1))
    answer = client.choose("test", questions)["op"]
    assert (answer.choice, answer.confidence) == ("a", 0.1)


class ScriptedClient:
    def __init__(self, operation, answers, confidence=None):
        self.operation = operation
        self.answers = answers
        self.confidence = confidence or {}
        self.questions = []

    def choose(self, state, questions):
        self.questions.append(copy.deepcopy(questions))
        result = {"operation": self.operation} if "operation" in questions else self.answers
        assert set(result) == set(questions)
        for name, value in result.items():
            assert value in questions[name]["criteria"]
        return {name: ChoiceAnswer(type="choice", choice=value, confidence=self.confidence.get(name, 0.95),
                                   probabilities={k: float(k == value) for k in questions[name]["criteria"]})
                for name, value in result.items()}


@pytest.mark.parametrize("stage", ["operation", "scope", "team"])
@pytest.mark.parametrize("confidence, accepted", [(0.79, False), (0.8, True)])
def test_confidence_floor(stage, confidence, accepted):
    client = ScriptedClient("get_picks", {"scope": "supported", "team": "mine"}, {stage: confidence})
    teams = Mock(return_value=[Roster(roster_id=1, owner_id="me")])
    if accepted:
        assert interpret("question", client, teams, "me").kwargs == {"team": "1"}
    else:
        with pytest.raises(Clarification, match="confidently") as error:
            interpret("question", client, teams, "me")
        assert (error.value.question, error.value.confidence) == (stage, confidence)


@pytest.mark.parametrize("operation, answers, expected", [
    ("get_roster", {"team": "mine", "limit": "default"}, {"team": "1", "limit": 15}),
    ("get_roster", {"team": "roster_2", "limit": "3"}, {"team": "2", "limit": 3}),
    ("get_power_rankings", {}, {}),
    ("get_dynasty_values", {"position": "WR", "limit": "50"}, {"position": "WR", "limit": 50}),
    ("get_waivers", {"position": "RB", "limit": "5"}, {"position": "RB", "limit": 5, "free_agents_only": True}),
    ("get_picks", {"team": "league"}, {}),
    ("get_picks", {"team": "mine"}, {"team": "1"}),
    ("get_roster_cleanup", {"team": "mine", "limit": "default"}, {"team": "1", "limit": 8}),
    ("get_lineup", {"team": "roster_2"}, {"team": "2"}),
])
def test_interpret_validated_arguments(operation, answers, expected):
    client = ScriptedClient(operation, {"scope": "supported", **answers})
    teams = Mock(return_value=[Roster(roster_id=1, team_name="Alpha", owner_id="me"), Roster(roster_id=2, team_name="Beta")])
    route = interpret("question", client, teams, "me")
    assert route.tool == operation
    assert route.kwargs == expected
    if "team" not in answers:
        teams.assert_not_called()


@pytest.mark.parametrize("operation", ["trade", "setup", "draft", "news", "unsupported", "ambiguous"])
def test_deferred_operations_stop_before_arguments(operation):
    # Even an uncertain abstaining answer keeps its direct-command hint.
    client = ScriptedClient(operation, {}, {"operation": 0.3})
    teams = Mock()
    with pytest.raises(Clarification) as error:
        interpret("question", client, teams, "me")
    assert str(error.value) == DEFERRED[operation]
    assert error.value.question == "operation"
    assert len(client.questions) == 1
    teams.assert_not_called()


@pytest.mark.parametrize("answer", ["unknown", "mine"])
def test_unknown_or_missing_own_team(answer):
    client = ScriptedClient("get_picks", {"scope": "supported", "team": answer})
    with pytest.raises(Clarification):
        interpret("question", client, lambda: [Roster(roster_id=1, owner_id="someone_else")], "me")


@pytest.mark.parametrize("field, value", [("scope", "unsupported"), ("scope", "ambiguous"), ("position", "unsupported"), ("limit", "unsupported")])
def test_unsupported_details_abstain(field, value):
    answers = {"scope": "supported", "position": "all", "limit": "default", field: value}
    with pytest.raises(Clarification):
        interpret("question", ScriptedClient("get_waivers", answers), Mock(), "me")


def test_empty_query_does_not_call_api(client):
    client.choose = Mock()
    with pytest.raises(Clarification):
        interpret("  ", client, Mock(), "me")
    client.choose.assert_not_called()


def test_fixed_control_question_and_eval_cases_have_valid_routes():
    import json
    from pathlib import Path
    from ff.services.llm.jev import OPERATIONS
    cases = json.loads((Path(__file__).parents[1] / "evals/jev.json").read_text())
    assert len(cases) == 40
    assert len({c['id'] for c in cases}) == 40
    assert sum(c['expected'] is not None for c in cases) == 28
    assert {c['expected']['tool'] for c in cases if c['expected']} == set(OPERATIONS)
    control = next(c for c in cases if c['id'] == 'control_roster')
    assert control['query'] == 'Show my roster'
    client = ScriptedClient('get_roster', {'scope': 'supported', 'team': 'mine', 'limit': 'default'})
    route = interpret(control['query'], client, lambda: [Roster(roster_id=1, owner_id='me')], 'me')
    assert route.model_dump() == control['expected']
