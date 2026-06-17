"""Weekly player projections from Sleeper (free, auth-free).

Sleeper's `api.sleeper.com/projections` endpoint returns, per player per week,
the projected *stat line* (pass_yd, rush_td, rec, rec_yd, ...). We keep the raw
stats so the lineup optimizer can score them with the league's own scoring
settings - which is what lets it honor things FantasyCalc can't, like TEP.
"""

from ff.projections.client import ProjectionsClient

__all__ = ["ProjectionsClient"]
