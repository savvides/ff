from __future__ import annotations

TOOL_SCHEMAS = [
    {
        "name": "setup_league",
        "description": "Onboard or set up Sleeper league by username.",
        "parameters": {
            "type": "object",
            "properties": {
                "username": {"type": "string", "description": "Sleeper username"}
            },
            "required": ["username"]
        }
    },
    {
        "name": "evaluate_trade",
        "description": "Evaluate trade fairness between given assets and received assets.",
        "parameters": {
            "type": "object",
            "properties": {
                "give": {"type": "array", "items": {"type": "string"}, "description": "Assets to give up"},
                "get": {"type": "array", "items": {"type": "string"}, "description": "Assets to receive"}
            },
            "required": ["give", "get"]
        }
    },
    {
        "name": "get_lineup",
        "description": "Get optimal starting lineup for a team/week.",
        "parameters": {
            "type": "object",
            "properties": {
                "team": {"type": "string", "description": "Team name or roster owner"},
                "week": {"type": "integer", "description": "NFL week number"}
            }
        }
    },
    {
        "name": "get_waivers",
        "description": "Get top waiver targets ranked by dynasty value.",
        "parameters": {
            "type": "object",
            "properties": {
                "position": {"type": "string", "description": "Positional filter (QB, RB, WR, TE)"},
                "limit": {"type": "integer", "description": "Number of targets to return"},
                "free_agents_only": {"type": "boolean", "description": "Filter for unrostered players only"}
            }
        }
    },
    {
        "name": "get_roster",
        "description": "Get roster breakdown and dynasty valuation.",
        "parameters": {
            "type": "object",
            "properties": {
                "team": {"type": "string", "description": "Team name or roster owner"}
            }
        }
    },
    {
        "name": "get_power_rankings",
        "description": "Get power rankings for all teams in the league.",
        "parameters": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_picks",
        "description": "Get future draft picks owned by a team or all teams.",
        "parameters": {
            "type": "object",
            "properties": {
                "team": {"type": "string", "description": "Team name or roster owner"}
            }
        }
    },
    {
        "name": "get_roster_cleanup",
        "description": "Audit roster for drops and taxi moves.",
        "parameters": {
            "type": "object",
            "properties": {
                "team": {"type": "string", "description": "Team name or roster owner"}
            }
        }
    },
    {
        "name": "get_movers",
        "description": "Get buy-low or sell-high candidates based on dynasty vs redraft gap.",
        "parameters": {
            "type": "object",
            "properties": {
                "buy": {"type": "boolean", "description": "True for buy-low candidates, False for sell-high candidates"},
                "limit": {"type": "integer", "description": "Number of players to return"}
            }
        }
    },
    {
        "name": "get_draft_fit",
        "description": "Get draft fit rankings tailored to team competitive status.",
        "parameters": {
            "type": "object",
            "properties": {
                "team": {"type": "string", "description": "Team name or roster owner"},
                "position": {"type": "string", "description": "Positional filter (QB, RB, WR, TE)"},
                "limit": {"type": "integer", "description": "Number of fit candidates to return"}
            }
        }
    },
    {
        "name": "get_dynasty_values",
        "description": "Get top overall player dynasty values.",
        "parameters": {
            "type": "object",
            "properties": {
                "position": {"type": "string", "description": "Positional filter (QB, RB, WR, TE)"},
                "limit": {"type": "integer", "description": "Number of players to return"}
            }
        }
    }
]

ALLOWED_TOOLS = [t["name"] for t in TOOL_SCHEMAS]
