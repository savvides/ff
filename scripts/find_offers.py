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

Ranking favors a rebuild that fills needs: young value gained that actually helps
you (picks, or players <= 25 who would start for you or play a position where you
are below the league median, with no warning flag), net of young value you add;
then how much your starting lineup improves; then the other side's win-now gain;
then the closer gap. Each incoming piece is explained (the lineup slot it would
start in / fills a need / surplus, and who it would sit behind) and flagged when
injured, falling in value, or heavily dropped on Sleeper, so a balancer is never
passed off as a target.
"""

from __future__ import annotations

import argparse
import itertools
import sys
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

from ff.analysis import apply_site_adjustments, offer_verdict, pick_ledger, pick_tier, value_all_rosters
from ff.analysis.fit import positional_standing, startable_value, starting_assets
from ff.cli import _pick_window
from ff.contracts import Asset, FuturePick, OfferVerdict, TradeEvaluation, TradeSide
from ff.core.config import load_config
from ff.sleeper import SleeperClient, build_rosters
from ff.values import ValueBook, ValuesClient
from ff.values.calculators_live import check_calculators

YOUNG_AGE = 25
FALLING = -300  # a 30-day value change at or below this is flagged


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


def roles(get: Sequence[Asset], give: Sequence[Asset], my_players: Sequence[Asset],
          roster_positions: Sequence[str], needs: Set[str]) -> Tuple[Dict[str, str], int]:
    """What each incoming piece does for you, and the change in your starting
    lineup's value (scored like the draft board, `fit.starting_assets`)."""
    give_ids = {a.id for a in give}
    after = [a for a in my_players if a.id not in give_ids] + [a for a in get if not a.is_pick]
    base, _ = startable_value(list(my_players), list(roster_positions))
    new_start = starting_assets(after, list(roster_positions))
    slot_of = {a.id: slot for slot, a in new_start}
    out: Dict[str, str] = {}
    for a in get:
        if a.is_pick:
            out[a.name] = "pick"
        elif a.id in slot_of:
            out[a.name] = f"starts at {slot_of[a.id]}"
        elif a.position in needs:
            out[a.name] = f"fills a {a.position} need (below league median)"
        else:
            ahead = [m.name for _, m in new_start if m.position == a.position]
            out[a.name] = f"surplus {a.position}" + (f", behind {', '.join(ahead)}" if ahead else "")
    return out, sum(a.value for _, a in new_start) - base


def flags(a: Asset, dropped: Set[str]) -> List[str]:
    """Warnings a manager should see before asking for this piece."""
    out = []
    if a.injury_tag:
        out.append(a.injury_tag.strip("[]"))
    if a.trend_30day is not None and a.trend_30day <= FALLING:
        out.append(f"value {a.trend_30day:+,} in 30 days")
    if a.id in dropped:
        out.append("among Sleeper's most-dropped players today")
    return out


def search(sale: Sequence[Asset], theirs: Sequence[Asset], balancers: Sequence[Asset], *,
           top: Optional[int], is_dynasty: bool = True, max_age: float = 26, limit: int = 5,
           my_players: Sequence[Asset] = (), roster_positions: Sequence[str] = (),
           needs: Optional[Set[str]] = None, dropped: Set[str] = frozenset()) -> List[Dict[str, object]]:
    """Packages that PASS, best rebuild fit first. Pure: no I/O."""
    needs = needs or set()
    give_options = [tuple(sale)] + [tuple(sale) + (b,) for b in balancers if b.id not in {s.id for s in sale}]
    pool = [a for a in theirs if a.is_pick or (a.age or 99) <= max_age]
    # Separately owned picks at the same tier price identically; ask for each package once.
    get_options, seen = [], set()
    for get in [(a,) for a in pool] + list(itertools.combinations(pool, 2)):
        key = tuple(sorted((a.id, a.value, a.secondary_value or 0) for a in get))
        if key not in seen:
            seen.add(key)
            get_options.append(get)
    rows: List[Dict[str, object]] = []
    for give in give_options:
        for get in get_options:
            ev, verdict = judge(give, get, top=top, is_dynasty=is_dynasty)
            if not verdict.passes:
                continue
            role, lineup_gain = roles(get, give, my_players, roster_positions, needs)
            helps = [a for a in get if _young(a) and not role[a.name].startswith("surplus")
                     and not flags(a, dropped)]
            rows.append({
                "give": [a.name for a in give], "get": [a.name for a in get], "assets": list(get),
                "roles": role, "lineup_gain": lineup_gain,
                "fc_pct": verdict.fc_pct, "ktc_pct": verdict.ktc_pct, "ktc_site_pct": verdict.ktc_site_pct,
                "fc_totals": (ev.value_b, ev.value_a), "ktc_totals": (ev.secondary_value_b, ev.secondary_value_a),
                "net_youth": sum(a.value for a in helps) - sum(a.value for a in give if _young(a)),
                "their_winnow": sum(a.redraft_value or 0 for a in give) - sum(a.redraft_value or 0 for a in get),
            })
    rows.sort(key=lambda r: (-int(r["net_youth"]), -int(r["lineup_gain"]),  # type: ignore[call-overload]
                             -int(r["their_winnow"]),  # type: ignore[call-overload]
                             max(float(r["fc_pct"]), float(r["ktc_pct"]))))  # type: ignore[arg-type]
    return rows[:limit]


def _roster_assets(book: ValueBook, players: Sequence[Asset], picks: Sequence[FuturePick],
                   tier_of: Callable[[int], str], origin_of: Callable[[int], str],
                   origins: Dict[str, str]) -> List[Asset]:
    """A roster's priced players (its valuation's assets) plus the picks it owns.
    Each pick is priced at the tier ff projects from its ORIGINAL team's power rank
    (as `ff picks` does), on both sites, so KTC's number is its value for that exact
    Early/Mid/Late pick.
    A second pick at the same tier is named "#2" (and so on); `origins` records
    whose pick each name is, so an offer says which one to ask for."""
    assets = list(players)
    for p in picks:
        pick = book.pick_at_tier(p.season, p.round, tier_of(p.original_roster_id))
        if pick is None:
            continue
        base, n = pick.name, 1
        while pick.name in origins:
            n += 1
            pick.name = f"{base} #{n}"
        origins[pick.name] = origin_of(p.original_roster_id)
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
    users = sc.league_users(cfg.league_id)
    rosters = build_rosters(sc.rosters(cfg.league_id), users)
    league = sc.league(cfg.league_id) or {}
    meta = sc.players()
    valuations = value_all_rosters(rosters, book, meta)  # players priced, with injury/depth status
    val_of = {v.roster_id: v for v in valuations}
    ranks = {v.roster_id: v.power_rank for v in valuations}
    roster_positions = league.get("roster_positions") or []
    seasons, rounds = _pick_window(sc, cfg, league, years=args.years)
    ledger = {tp.roster_id: tp.picks for tp in pick_ledger(rosters, sc.traded_picks(cfg.league_id), book,
                                                           ranks, seasons=seasons, rounds=rounds)}
    # League users carry display names only; the username is on each user record.
    names = {u["user_id"]: (sc.user(u["user_id"]) or {}).get("username") or u.get("display_name")
             for u in users}
    user_of = {r.roster_id: names.get(r.owner_id or "", f"roster {r.roster_id}") for r in rosters}

    def tier_of(original_roster_id: int) -> str:
        return pick_tier(ranks.get(original_roster_id), len(rosters))

    mine = next(r for r in rosters if r.owner_id == cfg.user_id)
    my_val = val_of[mine.roster_id]
    needs = {s.position for s in positional_standing(my_val, valuations, roster_positions) if s.is_hole}
    dropped = {str(t.get("player_id")) for t in sc.trending(kind="drop", limit=50)}
    my_origins: Dict[str, str] = {}
    my_assets = _roster_assets(book, my_val.assets, ledger.get(mine.roster_id, []), tier_of,
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

    my_players = [a for a in my_assets if not a.is_pick]
    print(f"values live: FantasyCalc + KTC (top {book.secondary_top:,}); calculators verified; "
          f"rule: under 10% in both markets and KTC says Fair; your needs: "
          f"{', '.join(sorted(needs)) or 'none below the league median'}")
    for username in args.to:
        roster = next((r for r in rosters if names.get(r.owner_id or "") == username), None)
        if roster is None:
            print(f"\nno manager named {username}")
            continue
        their_origins: Dict[str, str] = {}
        theirs = _roster_assets(
            book, val_of[roster.roster_id].assets, ledger.get(roster.roster_id, []), tier_of,
            lambda rid, r=roster: "their own" if rid == r.roster_id else f"theirs, from {user_of[rid]}",
            their_origins)
        rows = search(sale, theirs, balancers, top=book.secondary_top,
                      is_dynasty=cfg.format.is_dynasty, max_age=args.max_age, limit=args.limit,
                      my_players=my_players, roster_positions=roster_positions, needs=needs,
                      dropped=dropped)
        print(f"\n{username}: {len(rows)} passing package(s)" + ("" if rows else " - none within the rule"))
        for r in rows:
            fc_give, fc_get = r["fc_totals"]  # type: ignore[misc]
            k_give, k_get = r["ktc_totals"]  # type: ignore[misc]
            print(f"  give {' + '.join(r['give'])}  for  {' + '.join(r['get'])}")  # type: ignore[arg-type]
            print(f"      FC {fc_give:,} vs {fc_get:,} ({r['fc_pct']:.2f}%)   KTC {k_give:,} vs {k_get:,} "
                  f"({r['ktc_pct']:.2f}%, site {r['ktc_site_pct']:.1f}%)   lineup {r['lineup_gain']:+,}")
            for a in r["assets"]:  # type: ignore[attr-defined]
                age = f", {a.age:.0f}" if a.age and not a.is_pick else ""
                warn = flags(a, dropped)
                print(f"      - {a.name} ({a.position}{age}): {r['roles'][a.name]}"  # type: ignore[index]
                      + (f"  [!] {'; '.join(warn)}" if warn else ""))
            picks = [f"{n} = {my_origins[n]}" for n in r["give"] if n in my_origins]  # type: ignore[union-attr]
            picks += [f"{n} = {their_origins[n]}" for n in r["get"] if n in their_origins]  # type: ignore[union-attr]
            if picks:
                print("      picks: " + "; ".join(picks) + " (tier projected from the original team's power rank)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
