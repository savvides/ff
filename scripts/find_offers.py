#!/usr/bin/env python3
"""Find trade offers that pass the offer rule, from live data only.

    ./.venv/bin/python scripts/find_offers.py --sell "Kirk Cousins" --to troyharris --to devilz13s

For each named manager (Sleeper username), tries packages of one or two of their
assets (players, plus the picks they own, tiered like `ff picks`) against what you
sell plus at most one balancer of yours. Every package is priced exactly as
fantasycalc.com and keeptradecut.com would price it
(ff.analysis.trade.apply_site_adjustments) and kept only when the offer rule
passes (ff.analysis.trade.offer_verdict): under 10% of the larger side in both
markets, and KTC's own verdict "Fair Trade". One fresh fetch of both markets per
run, after checking that neither site's calculator code has drifted.

Ranking favors a rebuild: young value (players <= 25 and picks) gained net of any
young value you add, then the other side's win-now gain (redraft value), then the
closer of the two gaps.
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
import urllib.request
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from ff.analysis import apply_site_adjustments, offer_verdict, pick_ledger, pick_tier, value_all_rosters
from ff.cli import _pick_window
from ff.contracts import Asset, OfferVerdict, TradeEvaluation, TradeSide
from ff.core.config import load_config
from ff.sleeper import SleeperClient, build_rosters
from ff.values import ValueBook, ValuesClient
from ff.values.calculators_live import check_calculators

YOUNG_AGE = 25


def _young(a: Asset) -> bool:
    return a.is_pick or (a.age or 99) <= YOUNG_AGE


def judge(give: Sequence[Asset], get: Sequence[Asset], *, top: Optional[int],
          is_dynasty: bool = True) -> Tuple[TradeEvaluation, OfferVerdict]:
    """Price one package as the sites would and apply the offer rule."""
    ev = TradeEvaluation(side_a=TradeSide(assets=[a.model_copy() for a in get]),
                         side_b=TradeSide(assets=[a.model_copy() for a in give]),
                         label_a="You get", label_b="You give",
                         is_dynasty=is_dynasty, secondary_top=top)
    apply_site_adjustments(ev)
    return ev, offer_verdict(ev)


def search(sale: Sequence[Asset], theirs: Sequence[Asset], balancers: Sequence[Asset], *,
           top: Optional[int], is_dynasty: bool = True, max_age: float = 26,
           limit: int = 5) -> List[Dict[str, object]]:
    """Packages that PASS, best rebuild fit first. Pure: no I/O."""
    give_options = [tuple(sale)] + [tuple(sale) + (b,) for b in balancers if b.id not in {s.id for s in sale}]
    pool = [a for a in theirs if a.is_pick or (a.age or 99) <= max_age]
    get_options = [(a,) for a in pool] + list(itertools.combinations(pool, 2))
    rows: List[Dict[str, object]] = []
    for give in give_options:
        for get in get_options:
            ev, verdict = judge(give, get, top=top, is_dynasty=is_dynasty)
            if not verdict.passes:
                continue
            rows.append({
                "give": [a.name for a in give], "get": [a.name for a in get],
                "fc_pct": verdict.fc_pct, "ktc_pct": verdict.ktc_pct, "ktc_site_pct": verdict.ktc_site_pct,
                "fc_totals": (ev.value_b, ev.value_a), "ktc_totals": (ev.secondary_value_b, ev.secondary_value_a),
                "net_youth": sum(a.value for a in get if _young(a)) - sum(a.value for a in give if _young(a)),
                "their_winnow": sum(a.redraft_value or 0 for a in give) - sum(a.redraft_value or 0 for a in get),
                "notes": verdict.approximations,
            })
    rows.sort(key=lambda r: (-int(r["net_youth"]), -int(r["their_winnow"]),  # type: ignore[call-overload]
                             max(float(r["fc_pct"]), float(r["ktc_pct"]))))  # type: ignore[arg-type]
    return rows[:limit]


def _usernames(league_id: str) -> Dict[str, str]:
    def get(url: str) -> object:
        return json.load(urllib.request.urlopen(url, timeout=30))
    out = {}
    for u in get(f"https://api.sleeper.app/v1/league/{league_id}/users"):  # type: ignore[union-attr]
        full = get(f"https://api.sleeper.app/v1/user/{u['user_id']}")
        out[u["user_id"]] = full.get("username") or u.get("display_name")  # type: ignore[union-attr]
    return out


def _roster_assets(book: ValueBook, player_ids: Sequence[str], picks: Sequence[object],
                   tier_of: Callable[[int], str], origin_of: Callable[[int], str],
                   origins: Dict[str, str]) -> List[Asset]:
    """A roster's priced players plus the picks it owns. Each pick is priced at the
    tier ff projects from its ORIGINAL team's power rank (as `ff picks` does), on
    both sites, so KTC's number is its value for that exact Early/Mid/Late pick.
    Picks that would price identically collapse to one; `origins` records whose
    pick each name is, so an offer says which one to ask for."""
    assets = [a for a in (book.value_for_sleeper_id(p) for p in player_ids) if a is not None]
    seen = set()
    for p in picks:
        pick = book.pick_at_tier(p.season, p.round, tier_of(p.original_roster_id))  # type: ignore[attr-defined]
        if pick is None or pick.name in seen:
            continue
        seen.add(pick.name)
        origins[pick.name] = origin_of(p.original_roster_id)  # type: ignore[attr-defined]
        assets.append(pick)
    return [a for a in assets if a.secondary_value is not None and a.value > 0]


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--sell", action="append", required=True, help="asset you sell (repeatable)")
    ap.add_argument("--to", action="append", required=True, help="manager's Sleeper username (repeatable)")
    ap.add_argument("--with", dest="balancers", action="append", default=None,
                    help="asset of yours allowed as a balancer (default: your vets 27+ and picks after "
                         "round 1, each worth no more than what you sell)")
    ap.add_argument("--max-age", type=float, default=26, help="oldest player you would take back")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--years", type=int, default=3,
                    help="future draft years whose picks can be traded (both sites price three)")
    args = ap.parse_args(argv)

    cfg = load_config()
    sc = SleeperClient()
    book = ValuesClient().fetch(cfg.format, fresh=True)
    problems = check_calculators(book.secondary_html)
    if problems:
        print("cannot judge any offer: " + "; ".join(problems))
        return 1
    rosters = build_rosters(sc.rosters(cfg.league_id), sc.league_users(cfg.league_id))
    league = sc.league(cfg.league_id) or {}
    ranks = {v.roster_id: v.power_rank for v in value_all_rosters(rosters, book, sc.players())}
    seasons, rounds = _pick_window(sc, cfg, league, years=args.years)
    ledger = {tp.roster_id: tp.picks for tp in pick_ledger(rosters, sc.traded_picks(cfg.league_id), book,
                                                           ranks, seasons=seasons, rounds=rounds)}
    names = _usernames(cfg.league_id)
    user_of = {r.roster_id: names.get(r.owner_id or "", f"roster {r.roster_id}") for r in rosters}

    def tier_of(original_roster_id: int) -> str:
        return pick_tier(ranks.get(original_roster_id), len(rosters))

    mine = next(r for r in rosters if r.owner_id == cfg.user_id)
    my_origins: Dict[str, str] = {}
    my_assets = _roster_assets(book, mine.player_ids, ledger.get(mine.roster_id, []), tier_of,
                               lambda rid: "your own" if rid == mine.roster_id else f"from {user_of[rid]}",
                               my_origins)

    def mine_named(tok: str) -> Optional[Asset]:
        """Your asset for a token, preferring the tier-priced pick over a stand-in."""
        by_name = next((m for m in my_assets if m.name.lower() == tok.strip().lower()), None)
        if by_name is not None:
            return by_name
        a = book.resolve(tok)
        return next((m for m in my_assets if a is not None and m.id == a.id), None)

    sale = []
    for tok in args.sell:
        a = mine_named(tok)
        if a is None:
            print(f"not on your roster (or unpriced): {tok}")
            return 2
        sale.append(a)
    if args.balancers:
        balancers = [a for a in (mine_named(t) for t in args.balancers) if a is not None]
    else:
        # A balancer is a small add-on, never a bigger asset than the one being sold.
        cap = sum(a.value for a in sale)
        balancers = [a for a in my_assets if a.value <= cap and (
            (not a.is_pick and (a.age or 0) >= 27) or (a.is_pick and a.id.split()[1] not in ("1", "pick")))]
    balancers = list({a.id: a for a in balancers}.values())

    print(f"values live: FantasyCalc + KTC (top {book.secondary_top:,}); calculators verified; "
          f"rule: under 10% in both markets and KTC says Fair")
    for username in args.to:
        roster = next((r for r in rosters if names.get(r.owner_id or "") == username), None)
        if roster is None:
            print(f"\nno manager named {username}")
            continue
        their_origins: Dict[str, str] = {}
        theirs = _roster_assets(book, roster.player_ids, ledger.get(roster.roster_id, []), tier_of,
                                lambda rid, r=roster: "their own" if rid == r.roster_id else f"theirs, from {user_of[rid]}",
                                their_origins)
        rows = search(sale, theirs, balancers, top=book.secondary_top,
                      is_dynasty=cfg.format.is_dynasty, max_age=args.max_age, limit=args.limit)
        print(f"\n{username}: {len(rows)} passing package(s)" + ("" if rows else " - none within the rule"))
        for r in rows:
            fc_give, fc_get = r["fc_totals"]  # type: ignore[misc]
            k_give, k_get = r["ktc_totals"]  # type: ignore[misc]
            print(f"  give {' + '.join(r['give'])}  for  {' + '.join(r['get'])}")  # type: ignore[arg-type]
            print(f"      FC {fc_give:,} vs {fc_get:,} ({r['fc_pct']:.2f}%)   KTC {k_give:,} vs {k_get:,} "
                  f"({r['ktc_pct']:.2f}%, site {r['ktc_site_pct']:.1f}%)   net youth {r['net_youth']:+,}")
            picks = [f"{n} = {my_origins[n]}" for n in r["give"] if n in my_origins]  # type: ignore[union-attr]
            picks += [f"{n} = {their_origins[n]}" for n in r["get"] if n in their_origins]  # type: ignore[union-attr]
            if picks:
                print("      picks: " + "; ".join(picks) + " (tier projected from the original team's power rank)")
            for n in r["notes"]:  # type: ignore[union-attr]
                print(f"      note: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
