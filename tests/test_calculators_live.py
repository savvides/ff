"""The runtime drift check: bundle names are content hashes, so a known name is
verified for free; a new name is downloaded once and its functions compared."""

import responses

from ff.analysis.calculators import FINGERPRINTS
from ff.values import calculators_live as live

FC = live.FC_SITE
KTC = live.KTC_SITE
KNOWN_KTC_PAGE = f'<script src="/js/site.min.js?v={FINGERPRINTS["ktc"]["version"]}"></script>'


def _fc_page(main):
    return f'<script src="{main}" type="module"></script>'


@responses.activate
def test_known_bundles_are_verified_without_downloading_them():
    responses.add(responses.GET, f"{FC}/trade-calculator", body=_fc_page(FINGERPRINTS["fc"]["main"]))
    assert live.check_calculators(KNOWN_KTC_PAGE) == []
    assert len(responses.calls) == 1  # just the small FantasyCalc page


@responses.activate
def test_a_new_main_bundle_with_the_same_calculator_chunk_is_still_verified():
    responses.add(responses.GET, f"{FC}/trade-calculator", body=_fc_page("main-NEWBUILD.js"))
    chunk = FINGERPRINTS["fc"]["chunk"]
    responses.add(responses.GET, f"{FC}/main-NEWBUILD.js",
                  body=f'{{path:"trade-calculator",pathMatch:"full",loadChildren:()=>import("./{chunk}")}}')
    assert live.check_calculators(KNOWN_KTC_PAGE) == []


@responses.activate
def test_changed_calculator_code_is_reported_as_drift():
    responses.add(responses.GET, f"{FC}/trade-calculator", body=_fc_page("main-NEWBUILD.js"))
    responses.add(responses.GET, f"{FC}/main-NEWBUILD.js",
                  body='{path:"trade-calculator",loadChildren:()=>import("./chunk-NEWCALC.js")}')
    responses.add(responses.GET, f"{FC}/chunk-NEWCALC.js",
                  body="var Y={pctFactor:.75,adjustmentFactor:800,adjustmentScalar:.23};")
    responses.add(responses.GET, f"{KTC}/js/site.min.js?v=NEWKTC", body="var ALGOTOUSE=3;")
    problems = live.check_calculators('<script src="/js/site.min.js?v=NEWKTC"></script>')
    assert any("FantasyCalc" in p and "changed" in p for p in problems)
    assert any(p.startswith("KTC") and "changed" in p for p in problems)


@responses.activate
def test_an_unreachable_site_cannot_be_verified():
    responses.add(responses.GET, f"{FC}/trade-calculator", status=404)
    problems = live.check_calculators(KNOWN_KTC_PAGE)
    assert problems == ["could not verify FantasyCalc's calculator code (HTTPError)"]
