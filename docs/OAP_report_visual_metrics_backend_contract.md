# OAP Report Visual Metrics Backend Contract

## Version and compatibility

- Current schema: `3.0`; locale: `ko-KR`.
- Existing six top-level sections and their `title`, `summary`, `insights`, `recommendations` remain unchanged.
- Legacy rows are converted on read to `2.1-legacy`; new arrays are `[]`, new scalar/P2 values are `null`.
- No migration is used: the six existing `analysis_reports` JSONB columns preserve the extended structure.

## Server-owned metadata

`reportMeta` contains `schemaVersion`, actual `requestId`, actual `generatedAt`, nullable `dataAsOf`, nullable `overallConfidence`, actual `evidenceCount`, and `analysisLocale`. AI output cannot set request ID, timestamps, or evidence count.

## Common models and validation

- `Scale`: `min`, `max`; `min <= max`.
- `Metric`: `key`, `label`, nullable numeric `value`, `unit(score|percent|count|index)`, nullable `scale`, required `direction`, nullable `displayLevel/displayText`, `valueType(observed|derived|estimated)`, nullable `confidence/sampleSize/calculation/asOf`, and deduplicated `evidenceIds`.
- Scores are `0~100`; confidence/rates are `0~1`; ranks/orders start at 1; unknown values remain `null` rather than zero.
- Estimated numeric metrics identify qualitative AI estimation in `calculation`.
- Range values preserve `min`, `max`, and optional currency/unit instead of inventing a single estimate.

## P0

- `headlineMetrics`: `market_attractiveness`, `competitive_intensity`, `target_clarity`, `evidence_coverage`. Competitive intensity is `lower_is_better`; evidence coverage is an observed server calculation from citation rows with confidence 1.
- `marketAnalysis.metrics` and `purchaseFactors`: factor ID/label, score, mention/rate/growth, provenance, confidence, sample, evidence, calculation, date.
- `competitorAnalysis`: nullable competitor/copy counts and `messageCoverage` with brand/copy counts, rates, saturation/opportunity scores, competitor IDs, confidence, evidence, calculation, date.
- `targetCustomerAnalysis.segments`: stable rank, five component scores, nullable share, jobs/needs/barriers/channels, sample, provenance, confidence, evidence, and `target-priority-v1.0`. Priority uses `problemFrequency*0.35 + purchaseIntent*0.35 + reachability*0.20 + (100-priceSensitivity)*0.10` only when every component exists. Equal scores preserve input order.
- `marketingStrategy.executionPhases`: ordered phase, goal, actions, deliverables, channels, KPI list, risks, dependencies, and evidence. KPI defines metric/unit, nullable baseline, target operator and target/range, calculation, window, minimum sample, decision rule, source, and target basis.
- `platformRecommendation.rankedPlatforms`: stable priority, platform, score, reason, customer stage, expected (not guaranteed) effect, low-budget method, caution, confidence, evidence, and one scoring model version. Items without a score are not ranked.

## P1

- `opportunityMatrix`: two analytical axes and points with nullable 0~100 x/y/size, meaning, segment, confidence, evidence.
- `demandTrend`: interval, unit, period/value series, source, as-of date, evidence. Without real period data, series is empty.
- `competitors`: ID/name, nullable verified website, messages, channels, nullable price range, message/channel scores, channel calculation, evidence.
- Channel `scoreBreakdown`: audience fit, content format fit, cost efficiency, conversion intent, execution feasibility. `scoreWeights` are each 0~1, sum to 1, are identical across platforms, and reproduce the final score under `channel-fit-v1.0`.

## P2

`currentKpiValue`, `targetAchievementRate`, `previousReportDelta`, `actualCampaignPerformance`, and `recommendationOutcomeGap` are optional. They remain `null` until real historical/campaign integrations exist. This release does not add campaign tables or integrations.

## Evidence and citations

- Every exposed `evidenceIds` value must exist in the current report's citations and use `retrieval_evidences.id`/citation `evidence_id` identity.
- IDs are recursively validated, foreign/missing IDs are removed, duplicates are removed, and safe count-only warnings are logged.
- An observed numeric value that claimed evidence but loses every valid ID becomes `null`.
- `evidenceCount` and evidence coverage use actual `report_citations` rows.
- Citation metadata preserves existing keys and optionally supports URL/source identifier, publisher, publication/collection dates, data period, sample size, source type, display code, and 0~1 reliability. Unknown metadata remains `null` and URLs are never invented.

## Transactions and storage

Retrieval audit/evidence, report JSONB, citations, and the COMPLETED status use the existing common SQLAlchemy Session and one final commit. Failures roll back and do not mark a missing report as completed. Production DB configuration permits only Supabase PostgreSQL and has no localhost fallback.

## Example disclaimer

Examples in API documentation are structural examples, not forecasts or guaranteed operating results. Clients must not replace `null` with invented scores, trends, sample sizes, or campaign outcomes.
The complete anonymized structural sample is `docs/OAP_report_v3_example.json`; every number in that file is explicitly an example value rather than an operating result.
