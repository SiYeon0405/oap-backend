from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


Score = float | None
ValueType = Literal["observed", "derived", "estimated"]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class Scale(ContractModel):
    min: float
    max: float

    @model_validator(mode="after")
    def validate_range(self):
        if self.min > self.max:
            raise ValueError("min must be less than or equal to max")
        return self


class Metric(ContractModel):
    key: str
    label: str
    value: float | int | None = None
    unit: Literal["score", "percent", "count", "index"]
    scale: Scale | None = None
    direction: Literal["higher_is_better", "lower_is_better", "neutral"]
    displayLevel: Literal["high", "medium", "low"] | None = None
    displayText: str | None = None
    valueType: ValueType
    confidence: float | None = Field(default=None, ge=0, le=1)
    sampleSize: int | None = Field(default=None, ge=0)
    evidenceIds: list[int] = Field(default_factory=list)
    calculation: str | None = None
    asOf: date | None = None

    @model_validator(mode="after")
    def validate_metric(self):
        if self.unit == "score" and self.value is not None:
            if not 0 <= self.value <= 100:
                raise ValueError("score must be between 0 and 100")
        self.evidenceIds = list(dict.fromkeys(self.evidenceIds))
        if self.valueType == "estimated" and self.value is not None:
            if not self.calculation or "AI 추정" not in self.calculation:
                raise ValueError("estimated metrics must identify AI estimation")
        return self


class NumericRange(ContractModel):
    min: float
    max: float
    currency: str | None = None
    unit: str | None = None

    @model_validator(mode="after")
    def validate_range(self):
        if self.min > self.max:
            raise ValueError("min must be less than or equal to max")
        return self


class PurchaseFactor(ContractModel):
    id: str
    label: str
    score: Score = Field(default=None, ge=0, le=100)
    mentionCount: int | None = Field(default=None, ge=0)
    positiveMentionRate: float | None = Field(default=None, ge=0, le=1)
    searchGrowthRate: float | None = None
    valueType: ValueType
    confidence: float | None = Field(default=None, ge=0, le=1)
    sampleSize: int | None = Field(default=None, ge=0)
    evidenceIds: list[int] = Field(default_factory=list)
    calculation: str | None = None
    asOf: date | None = None

    @model_validator(mode="after")
    def deduplicate_evidence(self):
        self.evidenceIds = list(dict.fromkeys(self.evidenceIds))
        if self.valueType == "estimated" and self.score is not None:
            if not self.calculation or "AI 추정" not in self.calculation:
                raise ValueError("estimated scores must identify AI estimation")
        return self


class MessageCoverage(ContractModel):
    id: str
    label: str
    brandCount: int | None = Field(default=None, ge=0)
    brandRate: float | None = Field(default=None, ge=0, le=1)
    copyCount: int | None = Field(default=None, ge=0)
    saturationScore: Score = Field(default=None, ge=0, le=100)
    opportunityScore: Score = Field(default=None, ge=0, le=100)
    competitorIds: list[str] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidenceIds: list[int] = Field(default_factory=list)
    calculation: str | None = None
    asOf: date | None = None

    @model_validator(mode="after")
    def deduplicate_evidence(self):
        self.evidenceIds = list(dict.fromkeys(self.evidenceIds))
        return self


class TargetSegment(ContractModel):
    id: str
    rank: int = Field(ge=1)
    label: str
    priorityScore: Score = Field(default=None, ge=0, le=100)
    problemFrequencyScore: Score = Field(default=None, ge=0, le=100)
    purchaseIntentScore: Score = Field(default=None, ge=0, le=100)
    reachabilityScore: Score = Field(default=None, ge=0, le=100)
    priceSensitivityScore: Score = Field(default=None, ge=0, le=100)
    estimatedShare: float | None = Field(default=None, ge=0, le=1)
    jobs: list[str] = Field(default_factory=list)
    needs: list[str] = Field(default_factory=list)
    barriers: list[str] = Field(default_factory=list)
    preferredChannels: list[str] = Field(default_factory=list)
    sampleSize: int | None = Field(default=None, ge=0)
    valueType: ValueType
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidenceIds: list[int] = Field(default_factory=list)
    scoringModelVersion: str

    @model_validator(mode="after")
    def deduplicate_evidence(self):
        self.evidenceIds = list(dict.fromkeys(self.evidenceIds))
        components = (
            self.problemFrequencyScore,
            self.purchaseIntentScore,
            self.reachabilityScore,
            self.priceSensitivityScore,
        )
        if all(component is not None for component in components):
            expected = (
                self.problemFrequencyScore * 0.35
                + self.purchaseIntentScore * 0.35
                + self.reachabilityScore * 0.20
                + (100 - self.priceSensitivityScore) * 0.10
            )
            if self.priorityScore is None or abs(self.priorityScore - expected) > 0.01:
                raise ValueError("priorityScore does not match target-priority-v1.0")
        return self


class KPI(ContractModel):
    key: str
    label: str
    metric: str
    unit: str
    baseline: float | int | None = None
    target: float | int | None = None
    targetOperator: Literal[">=", "<=", "between"]
    targetMin: float | int | None = None
    targetMax: float | int | None = None
    measurementWindow: str
    minimumSampleSize: int | None = Field(default=None, ge=0)
    decisionRule: str
    source: str
    calculation: str
    targetBasis: Literal[
        "observed", "historical", "industry_benchmark", "ai_estimated"
    ] | None = None

    @model_validator(mode="after")
    def validate_target(self):
        if self.targetOperator == "between":
            if self.targetMin is None or self.targetMax is None:
                raise ValueError("between requires targetMin and targetMax")
            if self.targetMin > self.targetMax:
                raise ValueError("targetMin must be <= targetMax")
        elif self.target is None:
            raise ValueError(">= and <= require target")
        return self


class ExecutionPhase(ContractModel):
    phase: str
    order: int = Field(ge=1)
    label: str
    goal: str
    actions: list[str] = Field(default_factory=list)
    deliverables: list[str] = Field(default_factory=list)
    channels: list[str] = Field(default_factory=list)
    kpis: list[KPI] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    evidenceIds: list[int] = Field(default_factory=list)


class ChannelScoreBreakdown(ContractModel):
    audienceFit: Score = Field(default=None, ge=0, le=100)
    contentFormatFit: Score = Field(default=None, ge=0, le=100)
    costEfficiency: Score = Field(default=None, ge=0, le=100)
    conversionIntent: Score = Field(default=None, ge=0, le=100)
    executionFeasibility: Score = Field(default=None, ge=0, le=100)


class ChannelScoreWeights(ContractModel):
    audienceFit: float = Field(ge=0, le=1)
    contentFormatFit: float = Field(ge=0, le=1)
    costEfficiency: float = Field(ge=0, le=1)
    conversionIntent: float = Field(ge=0, le=1)
    executionFeasibility: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_sum(self):
        if abs(sum(self.model_dump().values()) - 1) > 1e-6:
            raise ValueError("scoreWeights must sum to 1")
        return self


class RankedPlatform(ContractModel):
    priority_rank: int = Field(ge=1)
    platform: str
    score: Score = Field(default=None, ge=0, le=100)
    reason: str
    customer_stage: str
    expected_effect: str
    low_budget_method: str
    caution: str
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidenceIds: list[int] = Field(default_factory=list)
    scoringModelVersion: str
    scoreBreakdown: ChannelScoreBreakdown | None = None
    scoreWeights: ChannelScoreWeights | None = None

    @model_validator(mode="after")
    def validate_weighted_score(self):
        if self.scoreBreakdown is not None and self.scoreWeights is not None:
            breakdown = self.scoreBreakdown.model_dump()
            weights = self.scoreWeights.model_dump()
            if all(value is not None for value in breakdown.values()):
                expected = sum(
                    breakdown[key] * weights[key]
                    for key in breakdown
                )
                if self.score is None or abs(self.score - expected) > 0.01:
                    raise ValueError("platform score does not match scoreWeights")
        return self


class Axis(ContractModel):
    key: str
    label: str
    min: float
    max: float
    direction: Literal["higher_is_better", "lower_is_better", "neutral"]

    @model_validator(mode="after")
    def validate_range(self):
        if self.min > self.max:
            raise ValueError("min must be <= max")
        return self


class OpportunityPoint(ContractModel):
    id: str
    label: str
    x: Score = Field(default=None, ge=0, le=100)
    y: Score = Field(default=None, ge=0, le=100)
    size: Score = Field(default=None, ge=0, le=100)
    sizeMeaning: str | None = None
    segment: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidenceIds: list[int] = Field(default_factory=list)


class OpportunityMatrix(ContractModel):
    xAxis: Axis
    yAxis: Axis
    points: list[OpportunityPoint] = Field(default_factory=list)


class TrendPoint(ContractModel):
    period: str
    value: float


class DemandTrend(ContractModel):
    interval: str | None = None
    unit: str | None = None
    series: list[TrendPoint] = Field(default_factory=list)
    source: str | None = None
    asOf: date | None = None
    evidenceIds: list[int] = Field(default_factory=list)


class Competitor(ContractModel):
    id: str
    name: str
    website: str | None = None
    primaryMessages: list[str] = Field(default_factory=list)
    activeChannels: list[str] = Field(default_factory=list)
    priceRange: NumericRange | None = None
    messageSimilarityScore: Score = Field(default=None, ge=0, le=100)
    channelIntensityScore: Score = Field(default=None, ge=0, le=100)
    channelIntensityCalculation: str | None = None
    evidenceIds: list[int] = Field(default_factory=list)


class P2Fields(ContractModel):
    currentKpiValue: float | int | None = None
    targetAchievementRate: float | None = None
    previousReportDelta: float | None = None
    actualCampaignPerformance: dict[str, Any] | None = None
    recommendationOutcomeGap: float | None = None


class ReportSection(ContractModel):
    title: str = ""
    summary: str = ""
    insights: list[str] = Field(default_factory=list)
    recommendations: Any = Field(default_factory=list)


class MarketAnalysisSection(ReportSection):
    metrics: list[Metric] = Field(default_factory=list)
    purchaseFactors: list[PurchaseFactor] = Field(default_factory=list)
    opportunityMatrix: OpportunityMatrix | None = None
    demandTrend: DemandTrend | None = None


class CompetitorAnalysisSection(ReportSection):
    competitorCount: int | None = Field(default=None, ge=0)
    analyzedCopyCount: int | None = Field(default=None, ge=0)
    messageCoverage: list[MessageCoverage] = Field(default_factory=list)
    competitors: list[Competitor] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_brand_rates(self):
        if self.competitorCount is not None:
            for item in self.messageCoverage:
                if item.brandCount is not None and item.brandRate is not None:
                    expected = item.brandCount / self.competitorCount if self.competitorCount else 0
                    if abs(item.brandRate - expected) > 1e-6:
                        raise ValueError("brandRate is inconsistent with competitorCount")
        return self


class TargetCustomerAnalysisSection(ReportSection):
    segments: list[TargetSegment] = Field(default_factory=list)
    scoringModelVersion: str | None = None

    @model_validator(mode="after")
    def validate_segment_ranking(self):
        scores = [segment.priorityScore for segment in self.segments]
        if any(score is None for score in scores):
            raise ValueError("ranked segments require priorityScore")
        if scores != sorted(scores, reverse=True):
            raise ValueError("segments must be sorted by priorityScore")
        if [segment.rank for segment in self.segments] != list(
            range(1, len(self.segments) + 1)
        ):
            raise ValueError("segment ranks must be sequential from 1")
        versions = {segment.scoringModelVersion for segment in self.segments}
        if len(versions) > 1:
            raise ValueError("segments must use one scoring model version")
        return self


class MarketingStrategySection(ReportSection, P2Fields):
    executionPhases: list[ExecutionPhase] = Field(default_factory=list)


class PlatformRecommendationSection(ReportSection, P2Fields):
    rankedPlatforms: list[RankedPlatform] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_platform_ranking(self):
        scores = [platform.score for platform in self.rankedPlatforms]
        if any(score is None for score in scores):
            raise ValueError("ranked platforms require score")
        if scores != sorted(scores, reverse=True):
            raise ValueError("platforms must be sorted by score")
        if [platform.priority_rank for platform in self.rankedPlatforms] != list(
            range(1, len(self.rankedPlatforms) + 1)
        ):
            raise ValueError("platform ranks must be sequential from 1")
        versions = {platform.scoringModelVersion for platform in self.rankedPlatforms}
        weights = {
            str(platform.scoreWeights.model_dump())
            for platform in self.rankedPlatforms
            if platform.scoreWeights is not None
        }
        if len(versions) > 1 or len(weights) > 1:
            raise ValueError("platforms must use one scoring model and weights")
        return self


class ReportMeta(ContractModel):
    schemaVersion: Literal["3.0", "2.1-legacy"]
    requestId: int
    generatedAt: datetime | None = None
    dataAsOf: date | None = None
    overallConfidence: float | None = Field(default=None, ge=0, le=1)
    evidenceCount: int = Field(ge=0)
    analysisLocale: Literal["ko-KR"] = "ko-KR"


class AnalysisStartResponse(BaseModel):
    requestId: int
    status: str


class AnalysisReportListItem(BaseModel):
    requestId: int
    serviceName: str
    oneLineDescription: str
    industry: str
    status: str
    createdAt: datetime


class AnalysisReportListResponse(BaseModel):
    items: list[AnalysisReportListItem]
    page: int
    size: int
    totalElements: int
    totalPages: int


class AnalysisReportResponse(ContractModel):
    serviceSummary: ReportSection
    marketAnalysis: MarketAnalysisSection
    competitorAnalysis: CompetitorAnalysisSection
    targetCustomerAnalysis: TargetCustomerAnalysisSection
    marketingStrategy: MarketingStrategySection
    platformRecommendation: PlatformRecommendationSection
    reportMeta: ReportMeta
    headlineMetrics: list[Metric] = Field(default_factory=list)


class AIAnalysisReportPayload(ContractModel):
    service_summary: ReportSection
    market_analysis: MarketAnalysisSection
    competitor_analysis: CompetitorAnalysisSection
    target_customer_analysis: TargetCustomerAnalysisSection
    marketing_strategy: MarketingStrategySection
    platform_recommendation: PlatformRecommendationSection
    headlineMetrics: list[Metric] = Field(default_factory=list)
