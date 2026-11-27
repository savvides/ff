"""Find trade offers that pass the offer rule, from live data only (`ff offers`).

    ff offers --sell "Kirk Cousins" --to troyharris --to "Team Name"

For each manager (Sleeper username or team name; everyone else when none is
named), tries packages of one or two of their
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
from pathlib import Path
from typing import AbstractSet, Callable, Dict, List, Optional, Sequence, Set, Tuple, TypedDict

from ff.analysis import apply_site_adjustments, offer_verdict, pick_ledger, pick_tier, value_all_rosters
from ff.analysis.fit import positional_standing, startable_value, starting_assets
from ff.cli import _finish_ranks, _has_secondary, _pick_window, _season_sim, _secondary_short, render_news_review
from ff.contracts import Asset, FuturePick, OfferVerdict, Roster, TradeEvaluation, TradeSide
from ff.core.config import load_config
from ff.news import review_players
from ff.qa import run_qa
from ff.sleeper import SleeperClient, build_rosters, detect_format
from rich.console import Console
from ff.values import ValueBook, ValuesClient
from ff.values.calculators_live import check_calculators

YOUNG_AGE = 25
FALLING = -300  # a 30-day value change at or below this is flagged


def _young(a: Asset) -> bool:
    return a.is_pick or (a.age or 99) <= YOUNG_AGE


def judge(
    give: Sequence[Asset],
    get: Sequence[Asset],
    *,
    top: Optional[int] = None,
    is_dynasty: bool = True,
    secondary_source: Optional[str] = None,
    secondary_label: str = "KTC",
    fc_only: bool = False,
) -> Tuple[TradeEvaluation, OfferVerdict]:
    """Price one package as the sites would and apply the offer rule."""
    ev = TradeEvaluation(
        side_a=TradeSide(assets=[a.model_copy() for a in get]),
        side_b=TradeSide(assets=[a.model_copy() for a in give]),
        label_a="You get",
        label_b="You give",
        is_dynasty=is_dynasty,
        secondary_top=top,
        secondary_source=secondary_source,
        secondary_label=secondary_label,
    )
    apply_site_adjustments(ev)
    return ev, offer_verdict(ev, fc_only=fc_only)


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


def flags(a: Asset, dropped: AbstractSet[str]) -> List[str]:
    """Warnings a manager should see before asking for this piece."""
    out = []
    if a.injury_tag:
        out.append(a.injury_tag.strip("[]"))
    if a.trend_30day is not None and a.trend_30day <= FALLING:
        out.append(f"value {a.trend_30day:+,} in 30 days")
    if a.id in dropped:
        out.append("among Sleeper's most-dropped players today")
    return out


class OfferResult(TypedDict):
    give: List[str]
    get: List[str]
    assets: List[Asset]
    roles: Dict[str, str]
    lineup_gain: int
    fc_pct: Optional[float]
    ktc_pct: Optional[float]
    ktc_site_pct: Optional[float]
    secondary_pct: Optional[float]
    fc_totals: Tuple[int, int]
    ktc_totals: Tuple[Optional[int], Optional[int]]
    net_youth: int
    their_winnow: int


def search(
    sale: Sequence[Asset],
    theirs: Sequence[Asset],
    balancers: Sequence[Asset],
    *,
    top: Optional[int] = None,
    is_dynasty: bool = True,
    max_age: float = 26,
    limit: int = 5,
    my_players: Sequence[Asset] = (),
    roster_positions: Sequence[str] = (),
    needs: Optional[Set[str]] = None,
    dropped: AbstractSet[str] = frozenset(),
    secondary_source: Optional[str] = None,
    secondary_label: str = "KTC",
    fc_only: bool = False,
) -> List[OfferResult]:
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
    rows: List[OfferResult] = []
    for give in give_options:
        for get in get_options:
            ev, verdict = judge(
                give,
                get,
                top=top,
                is_dynasty=is_dynasty,
                secondary_source=secondary_source,
                secondary_label=secondary_label,
                fc_only=fc_only,
            )
            if not verdict.passes:
                continue
            role, lineup_gain = roles(get, give, my_players, roster_positions, needs)
            helps = [a for a in get if _young(a) and not role[a.name].startswith("surplus")
                     and not flags(a, dropped)]
            sec_pct = verdict.secondary_pct if verdict.secondary_pct is not None else verdict.ktc_pct
            rows.append({
                "give": [a.name for a in give],
                "get": [a.name for a in get],
                "assets": list(get),
                "roles": role,
                "lineup_gain": lineup_gain,
                "fc_pct": verdict.fc_pct,
                "ktc_pct": verdict.ktc_pct,
                "ktc_site_pct": verdict.ktc_site_pct,
                "secondary_pct": sec_pct,
                "fc_totals": (ev.value_b, ev.value_a),
                "ktc_totals": (ev.secondary_value_b, ev.secondary_value_a),
                "net_youth": sum(a.value for a in helps) - sum(a.value for a in give if _young(a)),
                "their_winnow": sum(a.redraft_value or 0 for a in give) - sum(a.redraft_value or 0 for a in get),
            })
    rows.sort(key=lambda r: (
        -r["net_youth"],
        -r["lineup_gain"],
        -r["their_winnow"],
        max(r["fc_pct"] or 0.0, r["secondary_pct"] or 0.0),
    ))
    return rows[:limit]


def _roster_assets(
    book: ValueBook,
    players: Sequence[Asset],
    picks: Sequence[FuturePick],
    tier_of: Callable[[int], str],
    origin_of: Callable[[int], str],
    origins: Dict[str, str],
    *,
    fc_only: bool = False,
    skipped_seasons: Optional[Set[str]] = None,
) -> List[Asset]:
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
        if not fc_only and pick.secondary_value is None:
            if skipped_seasons is not None and pick.value > 0:
                skipped_seasons.add(p.season)
            continue
        base, n = pick.name, 1
        while pick.name in origins:
            n += 1
            pick.name = f"{base} #{n}"
        origins[pick.name] = origin_of(p.original_roster_id)
        assets.append(pick)
    if fc_only:
        return [a for a in assets if a.value > 0]
    return [a for a in assets if a.secondary_value is not None and a.value > 0]


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--sell", action="append", required=True, help="asset you sell (repeatable)")
    ap.add_argument("--to", action="append", default=None,
                    help="manager's Sleeper username or team name (repeatable; default: every other team)")
    ap.add_argument("--with", dest="balancers", action="append", default=None,
                    help="asset of yours allowed as a balancer (default: your vets 27+ and picks after "
                         "round 1, each worth no more than what you sell)")
    ap.add_argument("--max-age", type=float, default=26, help="oldest player you would take back")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--years", type=int, default=3,
                    help="future draft years whose picks can be traded (both sites price three)")
    ap.add_argument("--market", default="dp",
                    help="secondary market: dp or ktc (default: dp)")
    ap.add_argument("--ktc-file", type=Path, default=None,
                    help="load KeepTradeCut values from a local ktc_pool.json file")
    ap.add_argument("--fc-only", action="store_true",
                    help="evaluate using FantasyCalc only (skip secondary market)")
    args = ap.parse_args(argv)

    market_clean = args.market.strip().lower()
    if market_clean not in ("dp", "ktc", "dealer"):
        print("--market must be dp or ktc.")
        return 2
    sec = "ktc" if (market_clean in ("ktc", "dealer") or args.ktc_file is not None) else "dp"

    cfg = load_config()
    sc = SleeperClient()
    league = sc.league(cfg.league_id) or {}
    fmt = detect_format(league) if league else cfg.format
    try:
        try:
            client = ValuesClient(secondary=sec, ktc_file=args.ktc_file)
        except TypeError:
            client = ValuesClient()
        book = client.fetch(fmt, include_secondary=not args.fc_only, fresh=True)
    except ValueError as err:
        print(f"error: {err}")
        return 1
    if not args.fc_only and not _has_secondary(book):
        print(
            f"{book.secondary_label} values unavailable — retry, "
            "pass --ktc-file <path>, or pass --fc-only."
        )
        return 1
    problems = check_calculators(
        book.secondary_html,
        check_ktc=(not args.fc_only and book.secondary_source == "ktc"),
    )
    if problems:
        print("cannot judge any offer: " + "; ".join(problems))
        return 1
    users = sc.league_users(cfg.league_id)
    rosters = build_rosters(sc.rosters(cfg.league_id), users)
    league = sc.league(cfg.league_id) or {}
    meta = sc.players()
    valuations = value_all_rosters(rosters, book, meta)  # players priced, with injury/depth status
    val_of = {v.roster_id: v for v in valuations}
    ranks, _ = _finish_ranks(_season_sim(cfg, sc, league, rosters), valuations)
    roster_positions = league.get("roster_positions") or []
    seasons, rounds = _pick_window(sc, cfg, league, years=args.years)
    ledger = {tp.roster_id: tp.picks for tp in pick_ledger(rosters, sc.traded_picks(cfg.league_id), book,
                                                           ranks, seasons=seasons, rounds=rounds)}
    team_of = {r.roster_id: r.team_name for r in rosters}

    def tier_of(original_roster_id: int) -> str:
        return pick_tier(ranks.get(original_roster_id), len(rosters))

    mine = next(r for r in rosters if r.owner_id == cfg.user_id)
    my_val = val_of[mine.roster_id]
    needs = {s.position for s in positional_standing(my_val, valuations, roster_positions) if s.is_hole}
    dropped = {str(t.get("player_id")) for t in sc.trending(kind="drop", limit=50)}
    skipped_seasons: Set[str] = set()
    track_skipped = skipped_seasons if (book.secondary_source == "dp" and not args.fc_only) else None
    my_origins: Dict[str, str] = {}
    my_assets = _roster_assets(
        book,
        my_val.assets,
        ledger.get(mine.roster_id, []),
        tier_of,
        lambda rid: "your own" if rid == mine.roster_id else f"from {team_of[rid]}",
        my_origins,
        fc_only=args.fc_only,
        skipped_seasons=track_skipped,
    )
    my_fc_assets = my_assets if args.fc_only else _roster_assets(
        book,
        my_val.assets,
        ledger.get(mine.roster_id, []),
        tier_of,
        lambda rid: "your own" if rid == mine.roster_id else f"from {team_of[rid]}",
        {},
        fc_only=True,
    )

    def mine_named(tok: str, pool: Sequence[Asset]) -> Optional[Asset]:
        """Your asset for a token, preferring the tier-priced pick over a stand-in."""
        by_name = next((m for m in pool if m.name.lower() == tok.strip().lower()), None)
        if by_name is not None:
            return by_name
        a = book.resolve(tok)
        return next((m for m in pool if a is not None and m.id == a.id), None)

    sale: List[Asset] = []
    for tok in args.sell:
        a = mine_named(tok, my_assets)
        if a is None:
            if not args.fc_only and mine_named(tok, my_fc_assets) is not None:
                hint = "--fc-only or --market dp" if book.secondary_source == "ktc" else "--fc-only or --market ktc"
                print(
                    f"{tok}: on your roster in FantasyCalc, but unpriced in "
                    f"{book.secondary_label} (pass {hint})"
                )
            else:
                print(f"not on your roster (or unpriced): {tok}")
            return 2
        sale.append(a)
    if args.balancers:
        balancers = [a for a in (mine_named(t, my_assets) for t in args.balancers) if a is not None]
    else:
        # A balancer is a small add-on, never a bigger asset than the one being sold.
        cap = sum(a.value for a in sale)
        balancers = [a for a in my_assets if a.value <= cap and (
            (not a.is_pick and (a.age or 0) >= 27) or (a.is_pick and a.id.split()[1] not in ("1", "pick")))]
    balancers = list({a.id: a for a in balancers}.values())

    queries = list(args.to or [r.team_name for r in rosters if r is not mine])
    prepared: List[Tuple[str, Optional[Roster], List[Asset], Dict[str, str]]] = []
    for query in queries:
        roster = next((r for r in rosters if r is not mine and query.lower() in r.team_name.lower()), None)
        if roster is None:
            prepared.append((query, None, [], {}))
            continue
        their_origins: Dict[str, str] = {}
        target_rid = roster.roster_id

        def their_origin(rid: int, target_rid: int = target_rid) -> str:
            return "their own" if rid == target_rid else f"theirs, from {team_of[rid]}"

        theirs = _roster_assets(
            book,
            val_of[roster.roster_id].assets,
            ledger.get(roster.roster_id, []),
            tier_of,
            their_origin,
            their_origins,
            fc_only=args.fc_only,
            skipped_seasons=track_skipped,
        )
        prepared.append((query, roster, theirs, their_origins))

    my_players = [a for a in my_assets if not a.is_pick]
    offer_player_ids: List[str] = [a.id for a in sale if not a.is_pick]
    needs_str = ", ".join(sorted(needs)) or "none below the league median"
    if args.fc_only:
        print(
            f"values live: FantasyCalc (FC-only mode); calculators verified; "
            f"rule: under 10% in FantasyCalc; your needs: {needs_str}"
        )
    elif book.secondary_source == "dp":
        print(
            f"values live: FantasyCalc + {book.secondary_label}; calculators verified; "
            f"rule: under 10% in FantasyCalc and {book.secondary_label}; your needs: {needs_str}"
        )
    else:
        top_str = f" (top {book.secondary_top:,})" if book.secondary_top is not None else ""
        print(
            f"values live: FantasyCalc + {book.secondary_label}{top_str}; calculators verified; "
            f"rule: under 10% in both markets and {book.secondary_label} says Fair; "
            f"your needs: {needs_str}"
        )
    if not args.fc_only:
        if book.secondary_source == "dp" and skipped_seasons:
            seasons_str = ", ".join(sorted(skipped_seasons))
            print(
                f"note: skipped {seasons_str} picks (unpriced in {book.secondary_label}; "
                "pass --fc-only to include)"
            )
        for note in dict.fromkeys(book.secondary_notes):
            print(f"note: {note}")

    sec_tag = _secondary_short(book)
    for query, roster, theirs, their_origins in prepared:
        if roster is None:
            print(f"\nno manager named {query}")
            continue
        rows = search(
            sale,
            theirs,
            balancers,
            top=book.secondary_top,
            is_dynasty=cfg.format.is_dynasty,
            max_age=args.max_age,
            limit=args.limit,
            my_players=my_players,
            roster_positions=roster_positions,
            needs=needs,
            dropped=dropped,
            secondary_source=book.secondary_source,
            secondary_label=book.secondary_label,
            fc_only=args.fc_only,
        )
        print(f"\n{roster.team_name}: {len(rows)} passing package(s)" + ("" if rows else " - none within the rule"))
        for r in rows:
            for a in r["assets"]:
                if not a.is_pick:
                    offer_player_ids.append(a.id)
            fc_give, fc_get = r["fc_totals"]
            k_give, k_get = r["ktc_totals"]
            k_str = f"{k_give:,} vs {k_get:,}" if k_give is not None and k_get is not None else "-- vs --"
            fc_pct_str = f"{r['fc_pct']:.2f}%" if r["fc_pct"] is not None else "--%"
            sec_pct = r["secondary_pct"] if r["secondary_pct"] is not None else r["ktc_pct"]
            sec_pct_str = f"{sec_pct:.2f}%" if sec_pct is not None else "--%"
            ktc_site_str = f"{r['ktc_site_pct']:.1f}%" if r["ktc_site_pct"] is not None else "--%"
            print(f"  give {' + '.join(r['give'])}  for  {' + '.join(r['get'])}")
            if args.fc_only:
                print(f"      FC {fc_give:,} vs {fc_get:,} ({fc_pct_str})   lineup {r['lineup_gain']:+,}")
            elif book.secondary_source == "dp":
                print(
                    f"      FC {fc_give:,} vs {fc_get:,} ({fc_pct_str})   {sec_tag} {k_str} "
                    f"({sec_pct_str})   lineup {r['lineup_gain']:+,}"
                )
            else:
                print(
                    f"      FC {fc_give:,} vs {fc_get:,} ({fc_pct_str})   {sec_tag} {k_str} "
                    f"({sec_pct_str}, site {ktc_site_str})   lineup {r['lineup_gain']:+,}"
                )
            for a in r["assets"]:
                age = f", {a.age:.0f}" if a.age and not a.is_pick else ""
                warn = flags(a, dropped)
                print(f"      - {a.name} ({a.position}{age}): {r['roles'][a.name]}"
                      + (f"  [!] {'; '.join(warn)}" if warn else ""))
            picks = [f"{n} = {my_origins[n]}" for n in r["give"] if n in my_origins]
            picks += [f"{n} = {their_origins[n]}" for n in r["get"] if n in their_origins]
            if picks:
                print("      picks: " + "; ".join(picks) + " (tier from the original team's projected finish)")
    if offer_player_ids:
        news_rev = review_players(offer_player_ids, meta, "trade")
        render_news_review(news_rev, Console())
        run_qa("news_review", review=news_rev)
    return 0


if __name__ == "__main__":
    sys.exit(main())
