"""Roster-cleanup audit: capacity math, categorization, drop ranking, taxi moves.

Self-contained inline data (plus the shared `book` fixture for values) so it does
not perturb the pinned totals other fixtures assert on.
"""

from ff.analysis import audit_roster, taxi_eligible
from ff.contracts import Roster

# roster_positions with a known split: 5 starter slots, 3 bench slots.
RPOS = ["QB", "RB", "WR", "TE", "SUPER_FLEX", "BN", "BN", "BN"]

# Bench = Odunze (valued rookie) + two 0-value vets; one 0-value vet on taxi,
# one 0-value player on IR. Starters are five valued players from the book.
META = {
    "5555": {"full_name": "Rome Odunze", "position": "WR", "age": 24, "years_exp": 0},
    "dead1": {"full_name": "Dead Weight One", "position": "WR", "age": 30, "years_exp": 6},
    "dead2": {"full_name": "Dead Weight Two", "position": "QB", "age": 33, "years_exp": 9},
    "taxi1": {"full_name": "Taxi Junk", "position": "QB", "age": 27, "years_exp": 4},
    "ir1": {"full_name": "Injured Guy", "position": "RB", "age": 28, "years_exp": 5},
}


def _roster(**over):
    base = dict(
        roster_id=1,
        team_name="Test Team",
        player_ids=["4984", "9221", "7564", "6666", "8138",  # starters (valued)
                    "5555", "dead1", "dead2",                # bench
                    "taxi1",                                  # taxi
                    "ir1"],                                   # IR
        starters=["4984", "9221", "7564", "6666", "8138"],
        taxi=["taxi1"],
        reserve=["ir1"],
    )
    base.update(over)
    return Roster(**base)


def _audit(book, **kw):
    params = dict(roster_positions=RPOS, taxi_slots=2, reserve_slots=1,
                  taxi_allow_vets=False, taxi_years=0)
    params.update(kw)
    return audit_roster(_roster(), book, META, **params)


# --- taxi eligibility ----------------------------------------------------

def test_taxi_eligible_allow_vets_lets_anyone_stash():
    assert taxi_eligible(9, allow_vets=True, taxi_years=0) is True
    assert taxi_eligible(None, allow_vets=True, taxi_years=None) is True


def test_taxi_eligible_rookies_only_when_no_vets():
    assert taxi_eligible(0, allow_vets=False, taxi_years=None) is True
    assert taxi_eligible(1, allow_vets=False, taxi_years=None) is False


def test_taxi_eligible_within_year_window():
    assert taxi_eligible(2, allow_vets=False, taxi_years=2) is True
    assert taxi_eligible(3, allow_vets=False, taxi_years=2) is False


def test_taxi_eligible_unknown_experience_is_ineligible():
    assert taxi_eligible(None, allow_vets=False, taxi_years=None) is False


# --- capacity + categorization ------------------------------------------

def test_capacity_caps_and_counts(book):
    a = _audit(book)
    assert a.starter_cap == 5 and a.bench_cap == 3
    assert a.taxi_cap == 2 and a.ir_cap == 1
    assert a.active_cap == 8
    assert len(a.starters) == 5 and len(a.bench) == 3
    assert len(a.taxi) == 1 and len(a.ir) == 1
    assert a.active_count == 8
    assert a.active_open == 0          # start(5)+bench(3) exactly fills 8
    assert a.taxi_open == 1 and a.ir_open == 0


def test_categorization_precedence(book):
    a = _audit(book)
    by_id = {s.player_id: s for s in a.slots}
    assert by_id["4984"].slot == "START"
    assert by_id["5555"].slot == "BENCH"
    assert by_id["taxi1"].slot == "TAXI"
    assert by_id["ir1"].slot == "IR"
    # values joined from the book for valued players, 0 otherwise
    assert by_id["7564"].value == 9500
    assert by_id["dead1"].value == 0


def test_over_cap_is_negative_active_open(book):
    # add a 4th bench player -> 9 active vs cap 8
    over = _roster(player_ids=["4984", "9221", "7564", "6666", "8138",
                               "5555", "dead1", "dead2", "dead3", "taxi1", "ir1"])
    meta = dict(META, dead3={"full_name": "Extra", "position": "WR",
                             "age": 29, "years_exp": 5})
    a = audit_roster(over, book, meta, roster_positions=RPOS, taxi_slots=2,
                     reserve_slots=1, taxi_allow_vets=False, taxi_years=0)
    assert a.active_count == 9
    assert a.active_open == -1


# --- drop candidates -----------------------------------------------------

def test_drop_candidates_worst_first_never_a_starter(book):
    a = _audit(book)
    ids = [s.player_id for s in a.drop_candidates]
    # no starter appears
    assert not ({"4984", "9221", "7564", "6666", "8138"} & set(ids))
    # zeros first, oldest-first among ties, then the valued rookie last
    assert ids == ["dead2", "dead1", "ir1", "taxi1", "5555"]


def test_drop_flags_whether_it_frees_active_room(book):
    a = _audit(book)
    by_id = {s.player_id: s for s in a.drop_candidates}
    assert by_id["dead1"].is_active is True    # bench drop opens an active slot
    assert by_id["taxi1"].is_active is False   # taxi drop does not
    assert by_id["ir1"].is_active is False     # IR drop does not


def test_drop_limit_caps_the_list(book):
    a = _audit(book, drop_limit=2)
    assert len(a.drop_candidates) == 2
    assert a.drop_candidates[0].player_id == "dead2"


# --- taxi move suggestions ----------------------------------------------

def test_taxi_candidates_rookies_only_capped_by_open_slots(book):
    a = _audit(book)  # allow_vets False, taxi_years 0 -> rookies only
    # only Odunze (years_exp 0) is eligible; vets dead1/dead2 are not
    assert [s.player_id for s in a.taxi_candidates] == ["5555"]


def test_taxi_candidates_allow_vets_best_value_first(book):
    # allow vets + 3 taxi slots (1 filled -> 2 open): best two bench by value
    a = _audit(book, taxi_allow_vets=True, taxi_slots=3)
    assert a.taxi_open == 2
    # Odunze 4500 first, then the higher-sorting 0-value vet (name tiebreak)
    assert [s.player_id for s in a.taxi_candidates] == ["5555", "dead1"]


def test_no_taxi_candidates_when_taxi_full(book):
    a = _audit(book, taxi_slots=1)  # 1 slot, already filled by taxi1
    assert a.taxi_open == 0
    assert a.taxi_candidates == []
