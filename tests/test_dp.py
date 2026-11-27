from __future__ import annotations

import responses

from ff.contracts import Format
from ff.values.dp import DP_PLAYERIDS_URL, DP_VALUES_URL, DynastyProcessClient

VALUES_CSV = (
    '"player","pos","team","age","draft_year","ecr_1qb","ecr_2qb","ecr_pos","value_1qb","value_2qb","scrape_date","fp_id"\n'
    '"Ja\'Marr Chase","WR","CIN",26.7,2021,1.5,6.4,1.7,10136,9034,"2026-11-27","19788"\n'
    '"Michael Pittman Jr.","WR","PIT",29.2,2020,40.0,55.0,25.0,1441,461,"2026-11-27","19278"\n'
    '"Unmapped Rookie","RB","KC",22.0,2026,50.0,60.0,20.0,1200,950,"2026-11-27",""\n'
    '"2026 Pick 1.01","PICK",,, ,22.1,11.0,,7500,8114,"2026-11-27",\n'
    '"2027 Early 1st","PICK",,, ,30.0,20.0,,4800,5299,"2026-11-27",\n'
    '"2027 1st","PICK",,, ,45.0,35.0,,2100,2374,"2026-11-27",\n'
    '"2028 1st","PICK",,, ,55.0,45.0,,1700,1899,"2026-11-27",\n'
)
IDS_CSV = (
    "mfl_id,fantasypros_id,sleeper_id,name\n"
    "15001,19788,7564,Ja'Marr Chase\n"
    "15002,19278,6819,Michael Pittman\n"
)


@responses.activate
def test_dp_superflex_and_one_qb_values_and_sleeper_id_join():
    responses.add(responses.GET, DP_VALUES_URL, body=VALUES_CSV, status=200)
    responses.add(responses.GET, DP_PLAYERIDS_URL, body=IDS_CSV, status=200)
    snap_sf = DynastyProcessClient().fetch_snapshot(Format(superflex=True), use_cache=False)
    assert snap_sf.source == "dp"
    assert snap_sf.label == "DynastyProcess"
    assert snap_sf.top is None
    assert snap_sf.values["7564"] == 9034
    assert snap_sf.values["6819"] == 461
    assert snap_sf.values["michael pittman"] == 461

    snap_1qb = DynastyProcessClient().fetch_snapshot(Format(superflex=False), use_cache=False)
    assert snap_1qb.values["7564"] == 10136
    assert snap_1qb.values["6819"] == 1441


@responses.activate
def test_dp_unmapped_fp_id_falls_back_to_normalized_name():
    responses.add(responses.GET, DP_VALUES_URL, body=VALUES_CSV, status=200)
    responses.add(responses.GET, DP_PLAYERIDS_URL, body=IDS_CSV, status=200)
    vals = DynastyProcessClient().fetch_values(Format(superflex=True), use_cache=False)
    assert vals["unmapped rookie"] == 950


@responses.activate
def test_dp_picks_tiered_2027_and_flat_2028_and_slots():
    responses.add(responses.GET, DP_VALUES_URL, body=VALUES_CSV, status=200)
    responses.add(responses.GET, DP_PLAYERIDS_URL, body=IDS_CSV, status=200)
    snap = DynastyProcessClient().fetch_snapshot(Format(superflex=True), use_cache=False)
    assert snap.values["2026 pick 1.01"] == 8114
    assert snap.values["2027 1 early"] == 5299
    assert snap.values["2027 1"] == 2374
    assert snap.values["2028 1"] == 1899
    assert snap.approx_keys == set()


@responses.activate
def test_dp_tep_note_only_when_tep_positive():
    responses.add(responses.GET, DP_VALUES_URL, body=VALUES_CSV, status=200)
    responses.add(responses.GET, DP_PLAYERIDS_URL, body=IDS_CSV, status=200)
    plain = DynastyProcessClient().fetch_snapshot(Format(superflex=True, tep=0.0), use_cache=False)
    tep = DynastyProcessClient().fetch_snapshot(Format(superflex=True, tep=0.5), use_cache=False)
    assert plain.notes == []
    assert tep.notes == ["DynastyProcess values do not adjust for TE premium"]


@responses.activate
def test_dp_graceful_degradation_on_http_error():
    responses.add(responses.GET, DP_VALUES_URL, status=500)
    snap = DynastyProcessClient().fetch_snapshot(Format(superflex=True), use_cache=False)
    assert snap.source == "dp" and snap.label == "DynastyProcess" and snap.values == {}


@responses.activate
def test_dp_filters_r_na_sentinels_and_keeps_max_duplicate_name():
    values_csv = (
        '"player","pos","team","age","draft_year","ecr_1qb","ecr_2qb","ecr_pos","value_1qb","value_2qb","scrape_date","fp_id"\n'
        '"Isaiah Williams","WR","DET",24.0,2024,99.0,99.0,50.0,300,350,"2026-11-27","NA"\n'
        '"Isaiah Williams","WR","CIN",25.0,2024,99.0,99.0,50.0,100,120,"2026-11-27","na"\n'
        '"Real Player","RB","KC",23.0,2025,20.0,20.0,10.0,4000,4200,"2026-11-27","77777"\n'
    )
    ids_csv = (
        "mfl_id,fantasypros_id,sleeper_id,name\n"
        "10001,NA,99999,Unrelated Rookie\n"
        "10002,77777,NA,Real Player\n"
    )
    responses.add(responses.GET, DP_VALUES_URL, body=values_csv, status=200)
    responses.add(responses.GET, DP_PLAYERIDS_URL, body=ids_csv, status=200)
    snap = DynastyProcessClient().fetch_snapshot(Format(superflex=True), use_cache=False)
    assert "NA" not in snap.values
    assert "na" not in snap.values
    assert "99999" not in snap.values
    assert snap.values["isaiah williams"] == 350
    assert snap.values["real player"] == 4200


@responses.activate
def test_dp_playerids_http_error_still_returns_name_and_pick_values():
    responses.add(responses.GET, DP_VALUES_URL, body=VALUES_CSV, status=200)
    responses.add(responses.GET, DP_PLAYERIDS_URL, status=500)
    snap = DynastyProcessClient().fetch_snapshot(Format(superflex=True), use_cache=False)
    assert snap.values["michael pittman"] == 461
    assert snap.values["2028 1"] == 1899
    assert "6819" not in snap.values
