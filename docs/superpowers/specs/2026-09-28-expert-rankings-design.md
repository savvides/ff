# Expert rankings for weekly and dynasty decisions

Date: 2026-09-28
Status: Written specification approved on 2026-09-28; implementation plan review pending.

## Purpose and agreed direction

Use journalists' published rankings to improve both weekly start/sit decisions and dynasty roster decisions. Keep the evidence attributable and make disagreements understandable.

The agreed destination is expert-informed weekly recommendations and dynasty disagreement signals. League-scored projections remain the weekly foundation. FantasyCalc remains the dynasty price anchor. Expert ranks never become invented projected points or trade dollars.

The first release displays expert evidence without changing recommendations. It also preserves the inputs needed to evaluate weekly tie-breaking prospectively. Enabling that behavior requires a later, separately reviewed change supported by results. This specification covers the first release and the conditions for that later decision, not an automatic activation mechanism.

Success means the user can see who disagrees with the existing analysis, whether the comparison applies to their league, and how current the evidence is. An unavailable expert source must not prevent the existing analysis from working.

## Scope and assumptions for review

- Add optional expert evidence to `ff lineup` and `ff compare` using `--experts`.
- Add a dynasty expert-disagreement mode to `ff movers --experts`, separate from its existing dynasty/redraft and KTC modes.
- Start with CBS as the candidate publisher. Support multiple named analysts when usable data exists; add another publisher only after independently validating its data. A single analyst is labeled as one opinion, not consensus.
- Use command-triggered retrieval and local snapshots. No background polling or scheduled collection is included.
- Leave default command output, trade arithmetic, market values, lineup assignments, and Jev routing unchanged in this release. Expert-specific natural-language requests are a later scope decision.
- Exclude rest-of-season rankings, rookie-only lists, draft-pick rankings, prose sentiment analysis, automated transactions, and a generic scraping or plugin framework.

The command flags and freshness defaults below are proposed implementation choices for this written review. They were not separately selected in the conversation.

## Source access is a shipping prerequisite

CBS publishes [fantasy rankings](https://www.cbssports.com/fantasy/football/rankings/) and [Heath Cummings's dynasty rankings](https://www.cbssports.com/fantasy/football/news/dynasty-fantasy-football-updated-rankings/). These pages were inspected during brainstorming. Their existence does not establish a stable machine-readable feed, complete current lists, or sufficient metadata for this integration.

Before committing to a CBS adapter, inspect actual accessible payloads for both horizons and verify author, rank scope, scoring assumptions, ranking date, season/week where relevant, and player coverage. Identify whether the displayed date belongs to the rankings or only to surrounding article text. Check the supported access method and any reuse conditions. Do not bypass access controls or assume a paid feed is authorized.

Ship a source only when its entries and metadata can be deterministically extracted and checked against the published page. Preserve a small representative fixture for offline tests. Treat schema changes and incomplete responses as unavailable data, not an empty successful ranking list.

If CBS cannot meet these requirements for either horizon, report the precise gap and propose a verified alternate source before substituting one. No manual import product or browser-scraping service is implied by this design. Shipping both horizons requires at least one validated source for each.

## Data contract and module boundaries

Keep rank evidence separate from `Asset.value` and `Asset.secondary_value`. A rank is ordinal and depends on the list's universe.

Use a small ranking snapshot contract containing:

- Publisher and stable analyst identity, source URL, source revision/hash, retrieval timestamp, and source publication/update date with its precision.
- Horizon (`weekly` or `dynasty`), season and week for weekly lists, list scope (`overall`, `FLEX`, or a named position), and declared included positions.
- Published scoring and roster assumptions, including PPR, passing-touchdown scoring, TEP, and 1QB/superflex where provided. Unknown assumptions stay unknown.
- Entries with source player identity/name, published rank, optional published tier, and resolved Sleeper ID. Preserve source names and native ranks for auditing.
- Coverage and validation results, including unresolved identities and reasons evidence was excluded.

Prefer a verified source-ID mapping. Otherwise match normalized full names against Sleeper metadata and use position/team to disambiguate, allowing for stale team labels. Require a unique, defensible match; reject collisions instead of choosing the highest fuzzy score. Reuse existing normalization where appropriate without broadening typed-player lookup behavior.

Place source I/O and parsing under `src/ff/rankings/`, shared models under `contracts/`, and pure filtering/comparison helpers under `analysis/`. CLI orchestration loads the snapshots and passes validated data into those helpers. Keep fetching, snapshot writes, and clocks out of analysis functions; pass the evaluation time explicitly.

Use the existing local HTTP/cache patterns and `FF_HOME`. Store immutable normalized snapshots under `FF_HOME/rankings/`; identical source revisions may be deduplicated. Record original retrieval time separately from later reads. Do not commit real league snapshots. No new HTTP service or LLM call is needed.

## Compatibility and freshness

Compare only rankings with the same horizon and appropriate scope. A positional RB list cannot decide an RB-versus-WR FLEX choice. A 1QB overall dynasty list cannot be treated as a superflex overall list. A positional comparison may ignore roster differences that do not change that comparison, but must still disclose the source assumptions.

For weekly evidence, require the requested season/week and a source update no more than 48 hours old. For dynasty evidence, use a 30-day maximum age. These are conservative display policies, not empirically established accuracy thresholds. If a source gives only a date, use the earliest possible instant consistent with its documented timezone; if the timezone cannot be established, mark freshness uncertain. Never substitute the retrieval time for the publication time.

Evidence with missing or mismatched material scoring assumptions, including TEP for comparisons involving tight ends, may appear in a clearly labeled source-context section. It cannot contribute to an agreement count or comparable-rank difference. Missing, uncertain, future-dated, or stale publication dates also exclude evidence from those calculations; identify the reason in the availability summary.

Fresh publication does not establish current injury awareness. Existing availability, eligibility, unknown-timing, and game-lock rules remain authoritative.

## Weekly display

`ff compare PLAYER_A PLAYER_B --experts` retains the existing whole-lineup comparison and recommendation. Append each usable analyst's ranks for both players, preference, scope, source date, and link. An analyst contributes to a pairwise preference only when both players occur in the same compatible list. Missing players are not assigned a bottom rank; equal ranks are ties.

Report counts as evidence, for example: “Three analysts favor B; one favors A; two publishers represented.” Show ties and excluded sources separately. Count each analyst once per pair. Prefer the narrowest compatible scope containing both players (position, then FLEX, then overall), followed by the latest source update. Deduplicate syndicated copies; conflicting lists with otherwise equal precedence exclude that analyst from the count. Do not describe these votes as independent observations, a probability, or proof that the projection recommendation is wrong.

`ff lineup --experts` appends expert ranks for the displayed starters and bench, grouped by compatible scope and author. It does not synthesize an expert-selected lineup or arbitrarily pair bench players with starters. Direct users to `ff compare` for an explicit decision.

If both compared players already belong in the best available lineup, retain that conclusion. If one choice is locked, unavailable, or otherwise illegal, expert preference cannot make it actionable. Historical/projection-only lineup scenarios must not receive current-week evidence as though it belonged to the requested week.

## Dynasty display

`ff movers --experts` shows analyst-versus-FantasyCalc ordering disagreements, one table per analyst and compatible scope. Do not aggregate raw ranks from different list lengths into a consensus rank.

For each table, form the shared pool of uniquely matched, ranked players with positive FantasyCalc values. Exclude picks. Re-rank that same pool once by expert order and once by FantasyCalc value, then compute `market rank - expert rank`. Positive means the expert ranks the player higher. Preserve ties using competition ranks; use Sleeper ID only for stable display ordering within ties. Show the original published rank separately and label the computed difference “places within shared pool.” Report pool size and mapping coverage.

Apply `--min-value` to displayed candidates after calculating ranks, then `--limit` per table. `--buy` shows positive differences and `--sell` negative differences; with neither, show the largest absolute differences. Reject simultaneous buy/sell flags in this new mode and reject combining `--experts` with `--arbitrage`. Do not change existing mode behavior.

These are research leads. Display “expert above market” or “expert below market,” not a fair-price premium, a guaranteed bargain, or an instruction to trade. Preserve FantasyCalc values and their existing TEP caveat. Other dynasty commands can use this evidence later without repricing their assets.

## Failure behavior

With `--experts`, show a concise availability summary for fetch failures, stale lists, incompatible settings, parse failures, or unresolved players. Valid evidence from other sources remains usable. Base lineup and comparison results still succeed; the expert-only movers mode exits 1 with an explicit unavailable result when no usable comparison exists, distinct from a valid comparison with no disagreements (exit 0). A dynasty shared pool needs at least two players to support a comparison.

Validate positive ranks, source identities, horizon metadata, and duplicate entries. Reject a structurally invalid list as a unit. Individually unresolved player identities may be omitted with visible coverage counts. Preserve the last valid snapshot for audit, but apply freshness checks before any reuse.

## Prospective weekly evaluation and activation boundary

The first release records requested pair comparisons alongside the evidence: decision time, source revision IDs, scoring settings, both legal lineup alternatives, projected totals, eligibility/availability facts, and the unchanged baseline choice. Snapshot each record when the command runs. Repeated evaluations must not rewrite that record using information learned later.

Only comparisons recorded before both players' kickoffs can enter a future tie-breaking study. Already locked games and illegal alternatives are excluded. Missing actual outcomes remain missing. A later evaluator must score actual stat lines with the saved league settings and compare whole-lineup outcomes; pairwise rank agreement alone does not establish better fantasy decisions.

The later activation proposal must define its close-call threshold, source coverage rules, and evaluation metrics on development weeks, freeze them, and evaluate on later held-out weeks. Report decision count, publisher coverage, missing data, mean points gained/lost versus projections alone, uncertainty, and results by week. Account for repeated players and overlapping lineup decisions rather than treating them as independent samples.

No improvement claim or automatic activation follows from a few favorable examples. If held-out evidence is weak or mixed, keep the display-only behavior. This release neither picks an arbitrary tie threshold nor implements the evaluator, a weighted score, or a hidden activation switch.

## Verification and acceptance

Offline tests must cover extraction fixtures, identity collisions, duplicate/syndicated authors, rank ties, truncated lists, stale dates, week rollover, scoring mismatches, cross-position scope, unknown metadata, and source failures. Use hand-checkable fixtures for shared-pool ranks and pairwise counts.

Command tests must verify visible provenance and exclusions, no change to base recommendations or values, legal-choice handling, both-players-start behavior, and snapshot isolation through the existing temporary `FF_HOME` fixture. QA must check counts and source references without claiming recommendation accuracy.

Before shipping, run the repository gate and live source checks for each enabled adapter. Compare a small sample of mapped ranks and metadata with the published lists. Fixture tests prove parsing behavior; live checks establish current source access; neither establishes that expert tie-breaking improves results.

This document changes no executable behavior. Review of this specification precedes the implementation plan and selection of an execution method.
