from ff.analysis.standings import scoring_model, simulate_season
from ff.contracts import Roster


def _league():
    # Four teams, two divisions; team 4 is winless and low scoring.
    return [Roster(roster_id=i, team_name=f"T{i}", wins=w, losses=3 - w,
                   points_for=pf, division=d)
            for i, w, pf, d in ((1, 3, 390.0, 1), (2, 2, 360.0, 1), (3, 1, 330.0, 2), (4, 0, 240.0, 2))]


SCORES = {1: [130, 125, 135], 2: [120, 115, 125], 3: [110, 105, 115], 4: [80, 75, 85]}


def test_no_games_played_gives_no_projection():
    assert simulate_season(_league(), {1: [], 2: []}, [], playoff_teams=2) == []


def test_scoring_model_shrinks_toward_league_mean():
    means, sd = scoring_model(SCORES)
    assert 80 < means[4] < 107.5 < means[1] < 130  # between own PPG and the league's
    assert sd == 5.0  # pooled within-team spread


def test_finished_season_is_the_final_standings():
    sim = simulate_season(_league(), SCORES, [], playoff_teams=2)
    by = {p.roster_id: p for p in sim}
    # Division winners (1 and 3) take the playoff spots, even over a better record.
    assert [by[i].playoff_odds for i in (1, 2, 3, 4)] == [1.0, 0.0, 1.0, 0.0]
    # Non-playoff teams pick first, worst record first; playoff teams after.
    assert [by[i].draft_slot for i in (4, 2, 3, 1)] == [1.0, 2.0, 3.0, 4.0]
    assert by[1].exp_wins == 3.0


def test_simulation_is_seeded_and_favors_the_stronger_team():
    args = (_league(), SCORES, [[(1, 4), (2, 3)], [(1, 2), (3, 4)]])
    a = simulate_season(*args, playoff_teams=2, sims=300)
    assert a == simulate_season(*args, playoff_teams=2, sims=300)
    by = {p.roster_id: p for p in a}
    assert by[1].exp_wins > 4.5 and by[4].exp_wins < 0.5
    assert by[4].draft_slot < by[2].draft_slot
    assert round(sum(p.playoff_odds for p in a), 6) == 2.0


def test_median_game_adds_a_second_weekly_result():
    sim = simulate_season(_league(), SCORES, [[(1, 4), (2, 3)]], playoff_teams=2,
                          median_game=True, sims=200)
    assert round(sum(p.exp_wins for p in sim), 1) == 6 + 2 + 2  # 2 head-to-head + 2 median wins
