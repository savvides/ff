"""Opt-in live routing evaluation using synthetic teams, without league API calls.

Run: .venv/bin/python scripts/eval_jev.py
Requires a saved key or TYPESAFE_API_KEY. Prints metrics and case IDs, never the key.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

from ff.contracts import Roster
from ff.services.llm.jev import Clarification, JevClient, JevError, interpret

CASES = Path(__file__).resolve().parents[1] / "evals" / "jev.json"


def main() -> int:
    try:
        client = JevClient()
    except JevError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    cases = json.loads(CASES.read_text())
    players = {
        "900001": {"full_name": "Jahmyr Gibbs", "first_name": "Jahmyr", "last_name": "Gibbs"},
        "900002": {"full_name": "Bijan Robinson", "first_name": "Bijan", "last_name": "Robinson"},
        "900003": {"full_name": "Nico Collins", "first_name": "Nico", "last_name": "Collins"},
        "900004": {"full_name": "Cooper Kupp", "first_name": "Cooper", "last_name": "Kupp"},
        "900005": {"full_name": "Aaron Jones", "first_name": "Aaron", "last_name": "Jones"},
        "900006": {"full_name": "Daniel Jones", "first_name": "Daniel", "last_name": "Jones"},
        "900007": {"full_name": "Justin Jefferson", "first_name": "Justin", "last_name": "Jefferson"},
    }
    rosters = [Roster(roster_id=1, team_name="Dynasty Warriors", owner_id="me", player_ids=list(players)[:6]),
               Roster(roster_id=2, team_name="Gridiron Kings", owner_id="other")]
    correct = abstained = errors = 0
    supported = sum(case["expected"] is not None for case in cases)
    durations = []
    results = []
    for case in cases:
        start = time.perf_counter()
        expected = case["expected"]
        # Diagnostics name ff's own question or locally built route, never raw replies.
        detail: dict = {}
        try:
            route = interpret(case["query"], client, lambda: rosters, "me", lambda: players)
            passed = expected is not None and route.model_dump() == expected
            if passed:
                correct += 1
            else:
                detail = {"route": route.model_dump()}
            outcome = "correct" if passed else "incorrect"
        except Clarification as exc:
            passed = expected is None
            if passed:
                abstained += 1
            outcome = "abstained"
            detail = {"question": exc.question, "confidence": exc.confidence, "message": str(exc)}
        except JevError as exc:
            passed = False
            errors += 1
            outcome = "api_error"
            detail = {"error": str(exc)}  # ff's fixed message, e.g. the HTTP status
        durations.append(time.perf_counter() - start)
        results.append({"id": case["id"], "passed": passed, "outcome": outcome, **detail})
    accuracy = correct / supported
    controls = [r for r in results if r["id"] == "control_roster"]
    controls_passed = len(controls) == 1 and controls[0]["passed"]
    passed = accuracy >= 0.90 and abstained == len(cases) - supported and errors == 0 and controls_passed
    print(json.dumps({
        "passed": passed, "models": sorted({c["model"] for c in client.calls}),
        "supported_exact_accuracy": accuracy, "supported_correct": correct, "supported_total": supported,
        "unsupported_abstained": abstained, "unsupported_total": len(cases) - supported,
        "api_errors": errors, "control_passed": controls_passed,
        "latency_median_seconds": round(statistics.median(durations), 3),
        "latency_max_seconds": round(max(durations), 3),
        "api_calls": client.request_count,
        "valid_responses": len(client.calls),
        "input_tokens": sum(c.get("input_tokens", 0) for c in client.calls),
        "output_tokens": sum(c.get("output_tokens", 0) for c in client.calls),
        "cases": results,
    }, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=CASES, help="Synthetic evaluation JSON (default: evals/jev.json)")
    CASES = parser.parse_args().cases
    raise SystemExit(main())
