"""FantasyCalc's and KeepTradeCut's trade-calculator math, ported from their live JS.

Both sites add a *package adjustment* to one side of a trade before comparing
totals, so a raw sum disagrees with them on nearly every uneven deal (and KTC
adjusts 1-for-1s too). These are verbatim ports of the functions the sites run:
FantasyCalc's `getValueAdjustment` (dynasty) and KTC's `adjustPackageNew` with
`processVNew` / `reverseAdjustNew` / `solveForX` / `checkEquality`. They are pinned
by vectors produced by executing the sites' own code
(`scripts/calculator_oracle.mjs` -> `tests/fixtures/calculator_vectors.json`).

Pure: no I/O and no imports from contracts or other analysis modules. JavaScript
numeric semantics are reproduced on purpose (Math.round rounds halves up, NaN
flows through Math.min/Math.max, x/0 is inf or NaN, pow of a negative base is
NaN) because the ports must match the sites to the digit.

`FINGERPRINTS` records the site code these ports were verified against. The
runtime drift check (`ff.values.calculators_live`) compares the live bundles with
it, so `ff` never reports a verdict from math a site has since changed.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

NAN = float("nan")

# --- FantasyCalc (chunk-F4CNOEUX.js: Y={pctFactor:.6982,adjustmentFactor:753,adjustmentScalar:.23})
FC_PCT_FACTOR = 0.6982
FC_ADJUSTMENT_FACTOR = 753
FC_ADJUSTMENT_SCALAR = 0.23

# --- KTC (site.min.js)
KTC_PV_SCALE = 10099  # hard-coded in processVNew
KTC_MAX_PLAYER_VAL = 10000  # MAXPLAYERVAL=1e4
KTC_VARIANCE = 5  # tcFilters.variance default (the page's slider runs 0-10)
KTC_TOP_OFFSET = 100  # t = playersArray[0].value + 100 in adjustPackageNew
KTC_DISPLAY_RATIO = 0.033  # below this share of the combined total the block is hidden


# --- JavaScript numeric semantics -------------------------------------------

def _isnan(x: float) -> bool:
    return isinstance(x, float) and math.isnan(x)


def js_round(x: float) -> float:
    """Math.round: halves round up (toward +inf), NaN/inf pass through."""
    if _isnan(x) or math.isinf(x):
        return x
    return float(math.floor(x + 0.5))


def _floor(x: float) -> float:
    if _isnan(x) or math.isinf(x):
        return x
    return float(math.floor(x))


def _min(*xs: float) -> float:
    return NAN if any(_isnan(x) for x in xs) else min(xs)


def _max(*xs: float) -> float:
    return NAN if any(_isnan(x) for x in xs) else max(xs)


def _div(a: float, b: float) -> float:
    if b == 0:
        if a == 0 or _isnan(a):
            return NAN
        return math.inf if a > 0 else -math.inf
    return a / b


def _pow(base: float, exp: float) -> float:
    if _isnan(base) or _isnan(exp):
        return NAN
    if base < 0 and not float(exp).is_integer():
        return NAN
    try:
        return math.pow(base, exp)
    except OverflowError:
        return math.inf


# --- FantasyCalc -------------------------------------------------------------

def fc_adjustment(side1: Sequence[int], side2: Sequence[int]) -> Tuple[int, int]:
    """FantasyCalc's dynasty waiver adjustment, (side1_adj, side2_adj).

    Port of `getValueAdjustment(isDynasty=true, side1, side2)`: equal piece counts or
    an empty side get nothing. Otherwise the side sending FEWER pieces is credited
    with floor(min(v*0.6982, 753 + i*0.23)) for each of the k lowest-valued pieces
    on the other side (k = the piece-count gap, i = 0.. in ascending value order).
    Picks are pieces like players.
    """
    n1, n2 = len(side1), len(side2)
    if n1 == n2 or n1 == 0 or n2 == 0:
        return 0, 0
    more = side2 if n1 < n2 else side1
    k = abs(n1 - n2)
    parts = [min(v * FC_PCT_FACTOR, FC_ADJUSTMENT_FACTOR + i * FC_ADJUSTMENT_SCALAR)
             for i, v in enumerate(sorted(more)[:k])]
    adj = 0
    for p in parts:
        adj += math.floor(p)
    return (adj, 0) if n1 < n2 else (0, adj)


# --- KTC ---------------------------------------------------------------------

class KtcAdjustment(NamedTuple):
    """KTC's value adjustment for one trade. `adj1`/`adj2` are what the site adds to
    each team's total before judging (either can be 0, and in rare branches the
    added value is <= 0). `shown` is whether the page draws the "Value Adjustment"
    block; a hidden adjustment still counts toward the verdict."""

    adj1: float
    adj2: float
    side: int
    shown: bool


class _SolveError(Exception):
    pass


def _process_v(value: float, top_in_trade: float) -> float:
    """processVNew(e, a): (0.1*(v/10099)^1.4 + 0.7*(v/(1.05*a))^1.25 + 0.2) * v."""
    return 1 * (0.1 * _pow(value / KTC_PV_SCALE, 1.4)
                + 0.7 * _pow(_div(value, 1.05 * top_in_trade), 1.25) + 0.2) * value


def _solve_for_x(target: float, t: float, r: float) -> float:
    """solveForX(e, a=t, t=r): Newton root of processV-with-t(x) = target."""
    x = 5 * target
    for _ in range(20):
        fx = (0.1 * _pow(_div(x, t), 1.4) + 0.7 * _pow(_div(x, 1.05 * r), 1.25) + 0.2) * x - target
        dfx = (_div(0.24 * _pow(x, 1.4), _pow(t, 1.4))
               + _div(1.575 * _pow(x, 1.25), _pow(1.05, 1.25) * _pow(r, 1.25)) + 0.2)
        if abs(dfx) < 1e-12:
            raise _SolveError
        nx = x - _div(fx, dfx)
        if abs(nx - x) < 1e-8:
            return nx
        x = nx
    raise _SolveError


def _reverse_adjust(target: float, r: float, t: float) -> float:
    """reverseAdjustNew(e, a=r, t): Math.round(solveForX(e, t, a))."""
    return js_round(_solve_for_x(target, t, r))


def _check_equality(e: float, a: float, t: float) -> bool:
    e = _max(0, e)
    a = _max(0, a)
    n = _min(100, _div(abs(e - a), e + a) * 100)
    return not (js_round(10 * n) / 10 > t)


def ktc_adjustment(side1: Sequence[int], side2: Sequence[int], top: int,
                   variance: int = KTC_VARIANCE) -> Optional[KtcAdjustment]:
    """KTC's value adjustment. Verbatim port of `adjustPackageNew` (ALGOTOUSE=2).

    `top` is `playersArray[0].value`: the most valuable asset on the whole page in
    the chosen format/TEP. Returns None when a side is empty (the site then only
    prints an "add a player worth ~N" hint, no verdict) or when the Newton solve
    fails to converge (the site shows an error). `variance` is the page's slider,
    which moves the adjustment as well as the verdict.
    """
    if not side1 or not side2:
        return None
    t1 = sorted(side1, reverse=True)
    t2 = sorted(side2, reverse=True)
    s1 = sum(t1)
    s2 = sum(t2)
    t = top + KTC_TOP_OFFSET
    r = max(t1[0], t2[0])
    e = 0.0
    for v in t1:
        e += _process_v(v, r)
    a = 0.0
    for v in t2:
        a += _process_v(v, r)
    d = _div(e, s1)
    u = _div(a, s2)
    c = _floor(abs(e - a))
    f = _check_equality(s1, s2, variance)
    h = _check_equality(e, a, variance)

    side, value, adj1, adj2, y = -1, 0.0, 0.0, 0.0, True
    try:
        if f and h:
            if e > a:
                side = 1
                b = s2 + _reverse_adjust(c, r, t) - s1
                if b > 0:
                    value = adj1 = b
                else:
                    y, side = False, 2
                    value = adj2 = -1 * b
            elif a > e:
                side = 2
                b = s1 + _reverse_adjust(c, r, t) - s2
                if b > 0:
                    value = adj2 = b
                else:
                    y, side = False, 1
                    value = adj1 = -1 * b
        elif d > u:
            side = 1
            if e > a:
                b = s2 + _reverse_adjust(c, r, t) - s1
                if b > 0:
                    value = adj1 = b
                else:
                    y, side = False, 2
                    value = adj2 = abs(b)
            else:
                g = 1 if s1 < s2 else (2 if s2 < s1 else -1)
                w = _reverse_adjust(abs(e - a), r, t)
                if w > 0 and g > 0:
                    side = g
                    if g == 2:
                        tt = w - (s1 - s2)
                        if tt > 0:
                            value = adj2 = tt
                        else:
                            y = False
                            value = adj2 = tt
                    else:
                        tt = w - (s2 - s1)
                        if tt > 0:
                            if tt > KTC_MAX_PLAYER_VAL:
                                y, value, side, adj1 = False, 0.0, 1, 0.0
                            else:
                                side = 2
                                value = adj2 = tt
                        else:
                            y = True
                            value = adj1 = -1 * tt
                else:
                    y = False
        else:
            side = 2
            if a > e:
                b = s1 + _reverse_adjust(c, r, t) - s2
                if b > 0:
                    value = adj2 = b
                else:
                    y, side = False, 1
                    value = adj1 = abs(b)
            else:
                g = 1 if s1 < s2 else (2 if s2 < s1 else -1)
                w = _reverse_adjust(abs(e - a), r, t)
                if w > 0 and g > 0:
                    side = g
                    if g == 1:
                        tt = w - (s2 - s1)
                        if tt > 0:
                            value = adj1 = tt
                        else:
                            y = False
                            value = adj1 = tt
                    else:
                        tt = w - (s1 - s2)
                        if tt > 0:
                            if tt > KTC_MAX_PLAYER_VAL:
                                y, value, side, adj2 = False, 0.0, 1, 0.0
                            else:
                                side = 1
                                value = adj1 = tt
                        else:
                            y = True
                            value = adj2 = -1 * tt
                else:
                    y = False
    except _SolveError:
        return None

    shown = False
    if value != 0:
        shown = y
        if abs(_div(value, s1 + s2)) < KTC_DISPLAY_RATIO:
            shown = False
    # The page draws the block only when a side has more than one asset.
    shown = shown and (len(side1) > 1 or len(side2) > 1)
    return KtcAdjustment(adj1=adj1, adj2=adj2, side=side, shown=shown)


def ktc_site_pct(total1: float, total2: float) -> float:
    """KTC's verdict percentage: |t-r| / (t+r) * 100 on the adjusted totals, each
    clamped at 0 (evaluateTrade). A share of the COMBINED total, not the larger side."""
    t = _max(0, total1)
    r = _max(0, total2)
    return _min(100, _div(abs(t - r), t + r) * 100)


def ktc_site_fair(total1: float, total2: float, variance: int = KTC_VARIANCE) -> bool:
    """KTC's "Fair Trade" verdict: the percentage rounded to 0.1 is at most `variance`."""
    return not (js_round(10 * ktc_site_pct(total1, total2)) / 10 > variance)


# --- site-code fingerprints (drift detection) ---------------------------------

# Verified against the live bundles (scripts/calculator_oracle.mjs) on the date below. The bundle names
# are content-hashed, so an unchanged name means unchanged code.
FINGERPRINTS: Dict[str, Dict[str, Any]] = {
    "verified": {"date": "2026-09-30"},
    "fc": {
        "main": "main-QU22HJEG.js",
        "chunk": "chunk-F4CNOEUX.js",
        "constants": {"pctFactor": FC_PCT_FACTOR, "adjustmentFactor": FC_ADJUSTMENT_FACTOR,
                      "adjustmentScalar": FC_ADJUSTMENT_SCALAR},
        "hashes": {
            "getValueAdjustment": "2f6f3a12c4be77eeb59ce5b373f4eb4c8ed35ad0d8fe6e91285c8c3ec01e3155",
            "updateWaiverAdjustments": "3748d33e45371f5b0f7b2cbba009c9f107e732c54fcfebc7563df3ce3224249d",
            "calculate": "2f4b912aa7d31c118c8b49c3881590d8c70aac8929a1201222e147d10ccd5392",
        },
    },
    "ktc": {
        "version": "q_FrAXDmPCSBij8MDiPA1mxk_RQ17dn3TxS0QPcvRHk",
        "constants": {"ALGOTOUSE": 2, "MAXPLAYERVAL": KTC_MAX_PLAYER_VAL, "variance": KTC_VARIANCE,
                      "pickVal": 0},
        "hashes": {
            "adjustPackageNew": "b26ab426ebad3ae412350e4f7933bee40b90954d784fe347e8e1b91799706322",
            "processVNew": "06eeac86e1d4a9261e56145c2bd091b3a6173556eedbe84c9c8c2a5e05f7c27f",
            "reverseAdjustNew": "1f390640fb2ab27ce0abe8ffba63df8b8ae8b4f77a7559cad8ab5f278d4fff2d",
            "solveForX": "cf9462244fcaa0407f6b79c26777c40296bad0486764118ad64f402697a0ad6f",
            "checkEquality": "6fd27e4f2bafbf2982fc04401405e210996e54041ae53d7ed93bec3ab143431b",
            "evaluateTrade": "49e5517cc8726edb1b5cd3a3955235c2a86baebf621e2a91e888f86dee436c46",
            "updateSingleDynastyAsset": "e20849129d2df6f858eb78eb395f6e51527c7655f4eb7e48609aba97c9c37f11",
            "processTeam": "f4b774e852690ecf4d3400bda202891888369b07b377be3477a8f7d3d667d35c",
        },
    },
}

FC_FUNCTIONS = ("getValueAdjustment", "updateWaiverAdjustments", "calculate")
KTC_FUNCTIONS = ("adjustPackageNew", "processVNew", "reverseAdjustNew", "solveForX",
                 "checkEquality", "evaluateTrade", "updateSingleDynastyAsset", "processTeam")

_TOKEN = re.compile(
    r'"(?:\\.|[^"\\])*"'  # double-quoted string
    r"|'(?:\\.|[^'\\])*'"  # single-quoted string
    r"|`(?:\\.|[^`\\])*`"  # template literal
    r"|[A-Za-z_$][\w$]*"  # identifier
    r"|\d[\w.]*"  # number (1e4, .5 is '.' + '5')
    r"|\s+"
    r"|.", re.S)
_SHORT_KEYWORDS = {"var", "let", "for", "new", "try", "if", "in", "do", "of", "NaN"}


def _tokens(js: str) -> List[str]:
    return _TOKEN.findall(js)


def extract_functions(js: str, name: str) -> List[str]:
    """Source of every definition of `name` in minified JS: `function name(...){...}`
    or a class method `name(...){...}`. Calls (`x.name(`, `name(...)` not followed by
    a body) are skipped; brace matching ignores braces inside strings."""
    out: List[str] = []
    for m in re.finditer(r"(?<![\w$.])" + re.escape(name) + r"\(", js):
        start = m.start()
        toks = _TOKEN.finditer(js, m.end() - 1)
        depth = 0
        end_params = None
        for tok in toks:
            s = tok.group(0)
            if s == "(":
                depth += 1
            elif s == ")":
                depth -= 1
                if depth == 0:
                    end_params = tok.end()
                    break
        if end_params is None:
            continue
        rest = js[end_params:]
        stripped = rest.lstrip()
        if not stripped.startswith("{"):
            continue  # a call, not a definition
        body_start = end_params + (len(rest) - len(stripped))
        depth = 0
        for tok in _TOKEN.finditer(js, body_start):
            s = tok.group(0)
            if s == "{":
                depth += 1
            elif s == "}":
                depth -= 1
                if depth == 0:
                    out.append(js[start:tok.end()])
                    break
    return out


def normalized_hash(source: str) -> str:
    """sha256 of JS source with whitespace dropped and short (minifier-renamed)
    identifiers replaced by their order of first appearance, so a redeploy that only
    renames locals keeps the hash while any change to the formula moves it."""
    names: Dict[str, str] = {}
    parts: List[str] = []
    prev = ""
    for tok in _tokens(source):
        if tok.isspace():
            continue
        if (re.match(r"[A-Za-z_$]", tok) and len(tok) <= 3 and tok not in _SHORT_KEYWORDS
                and prev != "."):
            tok = names.setdefault(tok, f"#{len(names)}")
        parts.append(tok)
        prev = tok
    return hashlib.sha256("".join(parts).encode()).hexdigest()


def function_hashes(js: str, functions: Sequence[str]) -> Dict[str, str]:
    """Normalized hash per function name (all definitions concatenated); '' when
    the function is gone from the bundle."""
    return {fn: normalized_hash("".join(extract_functions(js, fn))) if extract_functions(js, fn) else ""
            for fn in functions}


def fc_constants(chunk_js: str) -> Optional[Dict[str, float]]:
    """The dynasty constants object that `getValueAdjustment` destructures."""
    defs = extract_functions(chunk_js, "getValueAdjustment")
    names = [m.group(1) for d in defs for m in [re.search(r"\}=([\w$]+),", d)] if m]
    for n in names:
        m = re.search(r"(?<![\w$.])" + re.escape(n)
                      + r"=\{pctFactor:([\d.]+),adjustmentFactor:([\d.]+),adjustmentScalar:([\d.]+)\}",
                      chunk_js)
        if m:
            return {"pctFactor": float(m.group(1)), "adjustmentFactor": float(m.group(2)),
                    "adjustmentScalar": float(m.group(3))}
    return None


def ktc_constants(site_js: str) -> Dict[str, Optional[float]]:
    def num(pattern: str) -> Optional[float]:
        m = re.search(pattern, site_js)
        return float(m.group(1)) if m else None
    return {
        "ALGOTOUSE": num(r"\bALGOTOUSE=(\d+)"),
        "MAXPLAYERVAL": num(r"\bMAXPLAYERVAL=([\d.e]+)"),
        "variance": num(r"\btcFilters=\{variance:(\d+)"),
        "pickVal": num(r"\btcFilters=\{variance:\d+,pickVal:(-?\d+)"),
    }


def fingerprint_problems(site: str, bundle_js: str) -> List[str]:
    """Differences between a live bundle and the verified FINGERPRINTS for `site`
    ('fc' chunk or 'ktc' site.min.js). Empty list = the ported math still applies."""
    fp = FINGERPRINTS[site]
    label = "FantasyCalc" if site == "fc" else "KTC"
    live_consts: Dict[str, Optional[float]]
    if site == "fc":
        live_consts = dict(fc_constants(bundle_js) or {})
        live = function_hashes(bundle_js, FC_FUNCTIONS)
    else:
        live_consts = ktc_constants(bundle_js)
        live = function_hashes(bundle_js, KTC_FUNCTIONS)
    expected: Dict[str, float] = fp["constants"]
    problems: List[str] = []
    if any(live_consts.get(k) is None or float(live_consts[k] or 0) != float(v)
           for k, v in expected.items()):
        problems.append(f"{label} calculator constants changed: {live_consts}")
    hashes: Dict[str, str] = fp["hashes"]
    for fn, h in hashes.items():
        if live.get(fn) != h:
            problems.append(f"{label} {fn}() changed")
    return problems
