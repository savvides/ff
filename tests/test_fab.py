from ff.analysis.fab import bid_summary, winning_bids


def _row(pid, rid, bid, status="complete", week=3, note="", ts=0, kind="waiver"):
    return {"type": kind, "status": status, "leg": week, "adds": {pid: rid},
            "settings": {"waiver_bid": bid}, "metadata": {"notes": note}, "status_updated": ts}


OUTBID = "This player was claimed by another owner."


def test_winning_bid_joins_the_losing_bids_it_beat():
    claims = winning_bids([
        _row("p1", 1, 40, ts=2),
        _row("p1", 2, 25, "failed", note=OUTBID),
        _row("p1", 2, 12, "failed", note=OUTBID),  # same team's fallback claim: one bidder
        _row("p1", 3, 30, "failed", note=OUTBID),
        _row("p1", 4, 99, "failed", note="Unfortunately, your roster will have too many players"),
        _row("p1", 5, 50, "failed", week=4, note=OUTBID),  # a different waiver run
        _row("p2", 2, 0, ts=5),
        _row("p3", 2, 7, kind="free_agent"),
    ])
    assert [(c.player_id, c.bid, c.runner_up, c.bidders) for c in claims] == [
        ("p2", 0, None, 1), ("p1", 40, 30, 3)]  # newest first


def test_malformed_rows_are_not_prices():
    rows = [_row("p1", 1, None), _row("p1", 1, "5"),
            {"type": "waiver", "status": "complete", "adds": {"a": 1, "b": 1}, "settings": {"waiver_bid": 3}},
            {"type": "waiver", "status": "complete", "adds": None, "settings": None}]
    assert winning_bids(rows) == []


def test_bid_summary():
    assert bid_summary([]) is None
    assert bid_summary([1, 2, 3, 10, 50]) == {"n": 5, "median": 3, "p75": 10, "max": 50}
