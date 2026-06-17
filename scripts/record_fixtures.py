"""Capture a real league snapshot to ./samples/<league_id>/ for inspection.

This does NOT overwrite the curated gate fixtures in tests/fixtures - those are
deliberately tiny + deterministic. Use this to eyeball real payload shapes or to
hand-author new fixtures from real data.

    python scripts/record_fixtures.py <league_id> [season]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from ff.sleeper import SleeperClient, detect_format


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    league_id = sys.argv[1]
    sc = SleeperClient()

    league = sc.league(league_id)
    fmt = detect_format(league)
    out = Path("samples") / league_id
    out.mkdir(parents=True, exist_ok=True)

    snapshots = {
        "league": league,
        "rosters": sc.rosters(league_id),
        "users": sc.league_users(league_id),
        "traded_picks": sc.traded_picks(league_id),
        "trending_add": sc.trending(kind="add", limit=25),
        "format": fmt.model_dump(),
    }
    for name, data in snapshots.items():
        (out / f"{name}.json").write_text(json.dumps(data, indent=2))

    print(f"wrote {len(snapshots)} files to {out}/")
    print(f"detected format: {fmt.label()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
