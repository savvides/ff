"""Unit tests for depth chart opportunity multipliers and dynasty value x depth heuristic."""

from __future__ import annotations

from ff.analysis.depth import (
    depth_chart_multiplier,
    opportunity_score,
    precompute_qb2_promotions,
)
from ff.analysis.waivers import waiver_targets
from ff.contracts import Asset
from ff.values import ValueBook


def test_depth_chart_multiplier_qb():
    # Superflex rewards backup QBs heavily
    assert depth_chart_multiplier("QB", 1, "BUF", is_superflex=True) == 1.0
    assert depth_chart_multiplier("QB", 2, "TB", is_superflex=True) == 0.75
    assert depth_chart_multiplier("QB", 3, "SEA", is_superflex=True) == 0.30
    assert depth_chart_multiplier("QB", 4, "KC", is_superflex=True) == 0.10

    # 1QB discounts backup QBs
    assert depth_chart_multiplier("QB", 1, "BUF", is_superflex=False) == 1.0
    assert depth_chart_multiplier("QB", 2, "TB", is_superflex=False) == 0.35
    assert depth_chart_multiplier("QB", 3, "SEA", is_superflex=False) == 0.25


def test_depth_chart_multiplier_skill_positions():
    # RB: primary handcuffs retain 0.80, buried backs fall off fast
    assert depth_chart_multiplier("RB", 1, "GB") == 1.0
    assert depth_chart_multiplier("RB", 2, "GB") == 0.80
    assert depth_chart_multiplier("RB", 3, "GB") == 0.45
    assert depth_chart_multiplier("RB", 4, "GB") == 0.20
    assert depth_chart_multiplier("RB", 5, "GB") == 0.10

    # WR: modern 3-WR sets preserve WR2 (0.90) and WR3 (0.75)
    assert depth_chart_multiplier("WR", 1, "MIN") == 1.0
    assert depth_chart_multiplier("WR", 2, "MIN") == 0.90
    assert depth_chart_multiplier("WR", 3, "MIN") == 0.75
    assert depth_chart_multiplier("WR", 4, "MIN") == 0.40
    assert depth_chart_multiplier("WR", 5, "MIN") == 0.15

    # TE: TE1 is 1.0, TE2 is 0.55
    assert depth_chart_multiplier("TE", 1, "KC") == 1.0
    assert depth_chart_multiplier("TE", 2, "KC") == 0.55
    assert depth_chart_multiplier("TE", 3, "KC") == 0.25


def test_depth_chart_multiplier_unsigned_free_agent():
    # No team or FA gets 0.25 discount
    assert depth_chart_multiplier("WR", 1, None) == 0.25
    assert depth_chart_multiplier("WR", 1, "FA") == 0.25
    assert depth_chart_multiplier("RB", None, "") == 0.25


def test_opportunity_score_heuristic():
    # RB2 with 400 value (400 * 0.80 = 320) outscores WR5 with 500 value (500 * 0.15 = 75)
    rb2_score = opportunity_score(400, "RB", 2, "DAL")
    wr5_score = opportunity_score(500, "WR", 5, "CHI")
    assert rb2_score == 320
    assert wr5_score == 75
    assert rb2_score > wr5_score

    # Unvalued player (value=0) scales baseline by depth chart
    unvalued_rb2 = opportunity_score(0, "RB", 2, "GB")
    unvalued_wr5 = opportunity_score(0, "WR", 5, "CHI")
    assert unvalued_rb2 == 40  # 50 * 0.80
    assert unvalued_wr5 == 8   # 50 * 0.15
    assert unvalued_rb2 > unvalued_wr5


def test_precompute_qb2_promotions():
    meta = {
        # Tampa Bay: Baker (1) and Jalon Daniels (3) -> Daniels promoted to 2
        "baker": {"team": "TB", "position": "QB", "depth_chart_order": 1, "status": "Active"},
        "jalon": {"team": "TB", "position": "QB", "depth_chart_order": 3, "status": "Active"},
        # Seattle: Geno (1), Lock (2), Milroe (3) -> Milroe NOT promoted (order 2 exists)
        "geno": {"team": "SEA", "position": "QB", "depth_chart_order": 1, "status": "Active"},
        "lock": {"team": "SEA", "position": "QB", "depth_chart_order": 2, "status": "Active"},
        "milroe": {"team": "SEA", "position": "QB", "depth_chart_order": 3, "status": "Active"},
    }
    promoted = precompute_qb2_promotions(meta)
    assert "jalon" in promoted
    assert "milroe" not in promoted


def test_precompute_qb2_promotions_when_qb2_injured():
    meta = {
        # Seattle: Lock (1, Active), Darnold (2, Out), Milroe (3, Active)
        "lock": {"team": "SEA", "position": "QB", "depth_chart_order": 1, "status": "Active"},
        "darnold": {"team": "SEA", "position": "QB", "depth_chart_order": 2, "status": "Active", "injury_status": "Out"},
        "milroe": {"team": "SEA", "position": "QB", "depth_chart_order": 3, "status": "Active"},
    }
    promoted = precompute_qb2_promotions(meta)
    assert "milroe" in promoted



def test_waivers_ranking_by_opportunity_score():
    # Book with an RB2 (moderate value 350) vs WR5 (higher nominal value 500)
    book = ValueBook([
        Asset(id="rb_handcuff", name="Handcuff RB", position="RB", value=350),
        Asset(id="deep_wr", name="Buried WR", position="WR", value=500),
    ])
    trending = [
        {"player_id": "deep_wr", "count": 1000},
        {"player_id": "rb_handcuff", "count": 1000},
    ]
    meta = {
        "rb_handcuff": {"position": "RB", "team": "DAL", "depth_chart_order": 2},
        "deep_wr": {"position": "WR", "team": "CHI", "depth_chart_order": 5},
    }
    targets = waiver_targets(trending, book, rosters=[], players_meta=meta)
    # Handcuff RB (350 * 0.80 = 280) outranks Buried WR (500 * 0.15 = 75)
    assert targets[0].asset.name == "Handcuff RB"
    assert targets[0].opportunity_score == 280
    assert targets[1].asset.name == "Buried WR"
    assert targets[1].opportunity_score == 75


def test_superflex_qb2_scarcity_floor():
    # Low-valued QB2 in Superflex (e.g. Jalon Daniels value=224 on TB)
    # should NOT score lower than a buried WR4 (value=531 * 0.40 = 212).
    # Superflex QB2 carries a 400 minimum base floor (400 * 0.75 = 300).
    qb2_score = opportunity_score(224, "QB", 2, "TB", is_superflex=True)
    wr4_score = opportunity_score(531, "WR", 4, "SEA", is_superflex=True)
    assert qb2_score >= 300
    assert qb2_score > wr4_score

    # In 1QB, QB2 does not get the Superflex floor
    qb2_1qb = opportunity_score(224, "QB", 2, "TB", is_superflex=False)
    assert qb2_1qb < wr4_score


def test_player_injury_news_discount():
    # Healthy WR4 (531 * 0.40 = 212)
    healthy = opportunity_score(531, "WR", 4, "SEA")
    assert healthy == 212

    # Questionable WR4 (531 * 0.40 * 0.85 = 180.54 -> 181)
    questionable = opportunity_score(531, "WR", 4, "SEA", injury_status="Questionable")
    assert questionable == 181

    # Out / IR WR4 (212 * 0.50 = 106)
    out = opportunity_score(531, "WR", 4, "SEA", injury_status="Out")
    assert out == 106

    ir = opportunity_score(531, "WR", 4, "SEA", status="Injured Reserve")
    assert ir == 106


def test_starter_injury_news_boost():
    # Healthy backup QB (500 base * 0.75 = 375)
    baseline = opportunity_score(500, "QB", 2, "ATL", is_superflex=True)

    # When starter is Questionable (e.g. Tua Tagovailoa on ATL), backup gets +0.10 boost
    with_q_starter = opportunity_score(
        500, "QB", 2, "ATL", is_superflex=True, starter_injury="Questionable"
    )
    assert with_q_starter > baseline
    assert with_q_starter == round(500 * (0.75 + 0.10))

    # When starter is Out, backup gets +0.25 boost (reaching 1.0 starter opportunity)
    with_out_starter = opportunity_score(
        500, "QB", 2, "ATL", is_superflex=True, starter_injury="Out"
    )
    assert with_out_starter == 500  # 500 * 1.0


def test_precompute_starter_injuries():
    from ff.analysis.depth import precompute_starter_injuries

    meta = {
        # Tua is QB1 in ATL and Questionable
        "tua": {"team": "ATL", "position": "QB", "depth_chart_order": 1, "injury_status": "Questionable"},
        # Baker is QB1 in TB and Healthy
        "baker": {"team": "TB", "position": "QB", "depth_chart_order": 1, "status": "Active"},
        # CMC is RB1 in SF and IR
        "cmc": {"team": "SF", "position": "RB", "depth_chart_order": 1, "status": "Injured Reserve"},
    }
    injuries = precompute_starter_injuries(meta)
    assert injuries.get(("ATL", "QB")) == "Questionable"
    assert ("TB", "QB") not in injuries
    assert injuries.get(("SF", "RB")) == "Injured Reserve"
