from __future__ import annotations

from typing import Any, Dict, List, Optional

from ff.analysis import cleanup, fit, lineup, movers, picks, roster, trade, waivers


def _find_roster(rosters: List[Any], team_query: Optional[str], ctx: Dict[str, Any]) -> Any:
    if not rosters:
        return None
    if team_query:
        q = str(team_query).lower()
        for r in rosters:
            team_name = (getattr(r, "team_name", "") or "").lower()
            owner_id = (getattr(r, "owner_id", "") or "").lower()
            roster_id = str(getattr(r, "roster_id", "")).lower()
            if q == team_name or q == owner_id or q == roster_id:
                return r
        for r in rosters:
            team_name = (getattr(r, "team_name", "") or "").lower()
            if q in team_name:
                return r
    cfg = ctx.get("config")
    if cfg:
        user_name = (getattr(cfg, "user_name", "") or "").lower()
        user_id = (getattr(cfg, "user_id", "") or "").lower()
        for r in rosters:
            team_name = (getattr(r, "team_name", "") or "").lower()
            owner_id = (getattr(r, "owner_id", "") or "").lower()
            if user_name and (user_name == team_name or user_name in team_name):
                return r
            if user_id and user_id == owner_id:
                return r
    return rosters[0]


def _find_roster_valuation(all_vals: List[Any], team_query: Optional[str], ctx: Dict[str, Any]) -> Any:
    if not all_vals:
        return None
    if team_query:
        q = str(team_query).lower()
        for v in all_vals:
            team_name = (getattr(v, "team_name", "") or "").lower()
            roster_id = str(getattr(v, "roster_id", "")).lower()
            if q == team_name or q == roster_id:
                return v
        for v in all_vals:
            team_name = (getattr(v, "team_name", "") or "").lower()
            if q in team_name:
                return v
    cfg = ctx.get("config")
    if cfg:
        user_name = (getattr(cfg, "user_name", "") or "").lower()
        for v in all_vals:
            team_name = (getattr(v, "team_name", "") or "").lower()
            if user_name and user_name in team_name:
                return v
    return all_vals[0]


def dispatch_tool(tool_name: str, kwargs: Dict[str, Any], ctx: Dict[str, Any]) -> Any:
    if tool_name == "setup_league":
        username = kwargs.get("username", "")
        onboard_fn = ctx.get("onboard_user")
        if onboard_fn:
            cfg = onboard_fn(username=username)
        else:
            from ff.services.llm.onboarding import onboard_user
            cfg = onboard_user(username=username)
        return cfg.model_dump() if hasattr(cfg, "model_dump") else cfg

    elif tool_name == "evaluate_trade":
        value_book = ctx.get("value_book")
        res = trade.evaluate_trade(
            give_inputs=kwargs.get("give", []),
            get_inputs=kwargs.get("get", []),
            book=value_book
        )
        return res.model_dump() if hasattr(res, "model_dump") else res

    elif tool_name == "get_lineup":
        rosters = ctx.get("rosters", [])
        team = kwargs.get("team")
        r = _find_roster(rosters, team, ctx)
        projections = ctx.get("projections", {})
        scoring = ctx.get("scoring", {})
        roster_positions = ctx.get("roster_positions", [])
        players_meta = ctx.get("players_meta")
        season = ctx.get("season", "")
        week = kwargs.get("week") or ctx.get("week", 0)
        res = lineup.optimal_lineup(r, projections, scoring, roster_positions, players_meta, season=season, week=week)
        return res.model_dump() if hasattr(res, "model_dump") else res

    elif tool_name == "get_waivers":
        trending = ctx.get("trending", [])
        value_book = ctx.get("value_book")
        rosters = ctx.get("rosters", [])
        players_meta = ctx.get("players_meta")
        limit = kwargs.get("limit", 25)
        free_agents_only = kwargs.get("free_agents_only", True)
        position = kwargs.get("position")
        targets = waivers.waiver_targets(
            trending=trending,
            book=value_book,
            rosters=rosters,
            players_meta=players_meta,
            limit=limit,
            free_agents_only=free_agents_only
        )
        if position:
            targets = [t for t in targets if t.asset and t.asset.position == position.upper()]
        return [t.model_dump() if hasattr(t, "model_dump") else t for t in targets]

    elif tool_name == "get_roster":
        rosters = ctx.get("rosters", [])
        team = kwargs.get("team")
        r = _find_roster(rosters, team, ctx)
        value_book = ctx.get("value_book")
        players_meta = ctx.get("players_meta")
        res = roster.value_roster(r, value_book, players_meta)
        return res.model_dump() if hasattr(res, "model_dump") else res

    elif tool_name == "get_power_rankings":
        rosters = ctx.get("rosters", [])
        value_book = ctx.get("value_book")
        players_meta = ctx.get("players_meta")
        valuations = roster.value_all_rosters(rosters, value_book, players_meta)
        return [v.model_dump() if hasattr(v, "model_dump") else v for v in valuations]

    elif tool_name == "get_picks":
        rosters = ctx.get("rosters", [])
        traded_picks = ctx.get("traded_picks", [])
        value_book = ctx.get("value_book")
        players_meta = ctx.get("players_meta")
        valuations = roster.value_all_rosters(rosters, value_book, players_meta) if (rosters and value_book) else []
        power_ranks = {v.roster_id: v.power_rank for v in valuations}
        seasons = ctx.get("seasons", ["2026", "2027", "2028"])
        rounds = ctx.get("rounds", 4)
        ledger = picks.pick_ledger(rosters, traded_picks, value_book, power_ranks, seasons=seasons, rounds=rounds)
        team = kwargs.get("team")
        if team and rosters:
            target_r = _find_roster(rosters, team, ctx)
            if target_r:
                ledger = [tp for tp in ledger if tp.roster_id == target_r.roster_id]
        return [tp.model_dump() if hasattr(tp, "model_dump") else tp for tp in ledger]

    elif tool_name == "get_roster_cleanup":
        rosters = ctx.get("rosters", [])
        team = kwargs.get("team")
        r = _find_roster(rosters, team, ctx)
        value_book = ctx.get("value_book")
        players_meta = ctx.get("players_meta")
        roster_positions = ctx.get("roster_positions", [])
        res = cleanup.audit_roster(
            r,
            value_book,
            players_meta,
            roster_positions=roster_positions,
            taxi_slots=ctx.get("taxi_slots", 0),
            reserve_slots=ctx.get("reserve_slots", 0),
            taxi_allow_vets=ctx.get("taxi_allow_vets", False),
            taxi_years=ctx.get("taxi_years", None),
        )
        return res.model_dump() if hasattr(res, "model_dump") else res

    elif tool_name == "get_movers":
        value_book = ctx.get("value_book")
        buy = kwargs.get("buy", False)
        limit = kwargs.get("limit", 20)
        res = movers.top_movers(value_book, buy=buy, limit=limit)
        out = []
        for asset, gap in res:
            asset_dict = asset.model_dump() if hasattr(asset, "model_dump") else asset
            out.append({"asset": asset_dict, "gap_pct": gap})
        return out

    elif tool_name == "get_draft_fit":
        rosters = ctx.get("rosters", [])
        team = kwargs.get("team")
        value_book = ctx.get("value_book")
        players_meta = ctx.get("players_meta")
        roster_positions = ctx.get("roster_positions", [])
        all_vals = roster.value_all_rosters(rosters, value_book, players_meta) if (rosters and value_book) else []
        my_val = _find_roster_valuation(all_vals, team, ctx)
        status = fit.detect_status(my_val.power_rank if my_val else None, len(all_vals))
        position = kwargs.get("position")
        limit = kwargs.get("limit", 10)
        candidates = value_book.top(position=position, limit=None) if value_book else []
        team_ctx, fit_list = fit.rank_fits(candidates, my_val, all_vals, roster_positions, status, limit)
        return {
            "context": team_ctx.model_dump() if hasattr(team_ctx, "model_dump") else team_ctx,
            "fits": [f.model_dump() if hasattr(f, "model_dump") else f for f in fit_list]
        }

    elif tool_name == "get_dynasty_values":
        value_book = ctx.get("value_book")
        position = kwargs.get("position")
        limit = kwargs.get("limit", 50)
        assets = value_book.top(position=position, limit=limit) if value_book else []
        return [a.model_dump() if hasattr(a, "model_dump") else a for a in assets]

    raise ValueError(f"Unknown tool: {tool_name}")
