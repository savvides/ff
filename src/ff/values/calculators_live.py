"""Runtime check that the calculator sites still run the math ff ported.

`ff trade` calls `check_calculators()` on every run so a site redeploy can never
leave ff reporting a verdict from outdated math. It costs one small request (the
FantasyCalc trade-calculator page) plus reading KTC's bundle version from the page
ff already fetched for KTC values. Bundle names are content hashes, so an unchanged
name proves unchanged code. Only a new name downloads that bundle (cached forever
under its name) and compares the ported functions' normalized hashes with
`analysis.calculators.FINGERPRINTS`. Every mismatch comes back as a problem string,
which the offer rule turns into "cannot judge".
"""

from __future__ import annotations

import re
from typing import List

from ff.analysis.calculators import FINGERPRINTS, fingerprint_problems
from ff.core.http import get_text

FC_SITE = "https://fantasycalc.com"
KTC_SITE = "https://keeptradecut.com"


def check_calculators(ktc_html: str = "", fresh: bool = True) -> List[str]:
    """Problems that mean ff's calculator ports may no longer match the sites.
    Empty = verified. `ktc_html` is the KTC page ff fetched for values."""
    problems: List[str] = []
    for label, check in (("FantasyCalc", lambda: _check_fantasycalc(fresh)),
                         ("KTC", lambda: _check_ktc(ktc_html))):
        try:
            problems += check()
        except Exception as err:  # unreachable site, bad TLS, parse failure
            problems.append(f"could not verify {label}'s calculator code ({err.__class__.__name__})")
    return problems


def _check_fantasycalc(fresh: bool) -> List[str]:
    fp = FINGERPRINTS["fc"]
    page = get_text(f"{FC_SITE}/trade-calculator", ttl=0 if fresh else 3600)
    main = re.search(r'src="(main-[A-Z0-9]+\.js)"', page)
    if not main:
        return ["FantasyCalc's calculator page changed (no main bundle found)"]
    if main.group(1) == fp["main"]:
        return []
    main_js = get_text(f"{FC_SITE}/{main.group(1)}", ttl=None)
    chunk = re.search(r'path:"trade-calculator"[^}]*?import\("\./(chunk-[A-Z0-9]+\.js)"\)', main_js)
    if not chunk:
        return ["FantasyCalc's trade-calculator route changed"]
    if chunk.group(1) == fp["chunk"]:
        return []
    return fingerprint_problems("fc", get_text(f"{FC_SITE}/{chunk.group(1)}", ttl=None))


def _check_ktc(ktc_html: str) -> List[str]:
    if not ktc_html:
        return []  # no KTC values at all; the offer rule already cannot judge
    version = re.search(r"site\.min\.js\?v=([\w-]+)", ktc_html)
    if not version:
        return ["KTC's calculator page changed (no site.min.js version found)"]
    if version.group(1) == FINGERPRINTS["ktc"]["version"]:
        return []
    js = get_text(f"{KTC_SITE}/js/site.min.js?v={version.group(1)}", ttl=None)
    return fingerprint_problems("ktc", js)
