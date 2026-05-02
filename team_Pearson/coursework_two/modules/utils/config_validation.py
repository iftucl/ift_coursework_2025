from __future__ import annotations

"""Typed CW2 configuration loading and validation."""

from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class _BaseCfg(BaseModel):
    model_config = ConfigDict(extra="allow")


_FACTOR_COVARIANCE_METHODS = {
    "statistical_factor",
    "factor_model",
    "pca_factor",
    "fundamental_factor",
    "fundamental_factor_model",
    "barra_lite",
}


_MAX_PORTFOLIO_NAME_LEN = 100


def _validate_factor_covariance_aliases(
    *,
    method: str,
    factor_count: Optional[int],
    n_factors: Optional[int],
    context: str,
) -> None:
    if (
        str(method).strip().lower() in _FACTOR_COVARIANCE_METHODS
        and factor_count is not None
        and n_factors is not None
        and int(factor_count) != int(n_factors)
    ):
        raise ValueError(
            f"{context}.factor_count and {context}.n_factors must match when both are set"
        )


def _validate_factor_weight_spec(
    *,
    raw_weights: str | Dict[str, float],
    sub_variables: List[str],
    context: str,
) -> None:
    if isinstance(raw_weights, str):
        if raw_weights.strip().lower() != "equal":
            raise ValueError(f"{context} must be 'equal' or a dict keyed by sub_variable")
        return

    unknown = sorted(set(raw_weights) - set(sub_variables))
    if unknown:
        raise ValueError(f"{context} keys must be declared in sub_variables: " + ", ".join(unknown))
    total = 0.0
    for key, value in raw_weights.items():
        weight = float(value)
        if weight < 0.0:
            raise ValueError(f"{context} cannot be negative: {key}")
        total += weight
    if total <= 0.0:
        raise ValueError(f"{context} must contain positive total weight")


def _validate_max_length(*, value: str, max_len: int, context: str) -> None:
    if len(str(value)) > max_len:
        raise ValueError(f"{context} cannot exceed {max_len} characters")


class FactorGroupConfig(_BaseCfg):
    sub_variables: List[str]
    weights: str | Dict[str, float] = "equal"
    regime_weights: Optional[Dict[str, str | Dict[str, float]]] = None

    @model_validator(mode="after")
    def _validate_weights(self) -> "FactorGroupConfig":
        sub_variables = [str(name) for name in self.sub_variables]
        if not sub_variables:
            raise ValueError("factor group must declare at least one sub_variable")

        _validate_factor_weight_spec(
            raw_weights=self.weights,
            sub_variables=sub_variables,
            context="factor group weight",
        )

        if self.regime_weights:
            unknown_regimes = sorted(set(self.regime_weights) - {"normal", "stress"})
            if unknown_regimes:
                raise ValueError(
                    "factor group regime_weights only supports normal/stress keys: "
                    + ", ".join(unknown_regimes)
                )
            for regime_name, regime_weights in self.regime_weights.items():
                _validate_factor_weight_spec(
                    raw_weights=regime_weights,
                    sub_variables=sub_variables,
                    context=f"factor group {regime_name} regime_weights",
                )
        return self


class PreprocessingConfig(_BaseCfg):
    winsorize_percentile: float = Field(ge=0.0, lt=0.5)
    min_observations: int = Field(ge=1)
    neutralize_by: str = "gics_sector"


class InvestableUniverseConfig(_BaseCfg):
    country_allowlist: Optional[List[str]] = None
    min_market_cap_log: Optional[float] = None
    market_cap_bottom_percentile: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    min_liquidity_20d: Optional[float] = Field(default=None, ge=0.0)
    liquidity_bottom_percentile: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class RegimeWeightsConfig(_BaseCfg):
    quality: float = Field(ge=0.0)
    value: float = Field(ge=0.0)
    market_technical: float = Field(ge=0.0)
    sentiment: float = Field(ge=0.0)
    dividend: float = Field(ge=0.0)

    @model_validator(mode="after")
    def _validate_sum(self) -> "RegimeWeightsConfig":
        total = (
            float(self.quality)
            + float(self.value)
            + float(self.market_technical)
            + float(self.sentiment)
            + float(self.dividend)
        )
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"regime weights must sum to 1.0, got {total:.6f}")
        return self


class FactorICWeightingConfig(_BaseCfg):
    enabled: bool = False
    lookback_months: int = Field(default=36, ge=1)
    min_history_months: int = Field(default=12, ge=1)
    min_cross_section: int = Field(default=25, ge=3)
    ic_method: Literal["spearman", "pearson"] = "spearman"
    score_metric: Literal["ic_ir", "ic_mean"] = "ic_ir"
    prior_mix: float = Field(default=0.50, ge=0.0, le=1.0)
    score_clip: float = Field(default=2.0, gt=0.0)
    positive_only: bool = True
    regime_split: bool = False

    @model_validator(mode="after")
    def _validate_history_window(self) -> "FactorICWeightingConfig":
        if self.min_history_months > self.lookback_months:
            raise ValueError("min_history_months cannot exceed lookback_months")
        return self


class RegimeConfig(_BaseCfg):
    signal_model: Literal["vix_only", "vix_term_spread"] = "vix_term_spread"
    mode: Literal["threshold", "hysteresis"] = "hysteresis"
    vix_stress_threshold: float = Field(ge=0.0)
    vix_warning_threshold: float = Field(ge=0.0)
    vix_exit_threshold: float = Field(ge=0.0)
    term_spread_stress_threshold: float = 0.0
    term_spread_confirm_days: int = Field(ge=1)
    stress_persistence: int = Field(ge=1)
    normal_persistence: int = Field(ge=1)
    history_lookback_days: int = Field(ge=1)
    normal: RegimeWeightsConfig
    stress: RegimeWeightsConfig
    ic_weighting: Optional[FactorICWeightingConfig] = None


class RiskOverlayConfig(_BaseCfg):
    min_market_cap_log: Optional[float] = None
    min_liquidity_20d: Optional[float] = None
    max_volatility_60d_percentile: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    max_missing_factor_pct: float = Field(ge=0.0, le=1.0)
    min_factor_groups_present: int = Field(ge=1)
    required_factor_groups: List[str] = Field(default_factory=list)
    missingness_factor_groups: List[str] = Field(default_factory=list)
    optional_percentile_blacklists: List[Dict[str, Any]] = Field(default_factory=list)


class PipelineGuardsConfig(_BaseCfg):
    min_scoring_universe: int = Field(ge=1)
    min_investable_universe: int = Field(ge=1)


class QualityGatesConfig(_BaseCfg):
    min_sub_score_rows: int = Field(ge=0)
    min_factor_score_rows: int = Field(ge=0)
    min_risk_overlay_rows: int = Field(ge=0)
    min_portfolio_targets: int = Field(ge=0)
    min_factor_score_coverage_vs_scoring: float = Field(ge=0.0, le=1.0)
    min_risk_pass_rate: float = Field(ge=0.0, le=1.0)
    max_as_of_date_shift_days: int = Field(ge=0)


class CovarianceConfig(_BaseCfg):
    method: Literal[
        "diagonal_shrinkage",
        "ledoit_wolf",
        "statistical_factor",
        "factor_model",
        "pca_factor",
        "fundamental_factor",
        "fundamental_factor_model",
        "barra_lite",
    ] = "diagonal_shrinkage"
    lookback_days: int = Field(ge=20)
    min_history_days: int = Field(ge=20)
    shrinkage_intensity: float = Field(ge=0.0, le=1.0)
    factor_count: Optional[int] = Field(default=None, ge=1)
    n_factors: Optional[int] = Field(default=None, ge=1)
    max_factor_count: int = Field(default=5, ge=1)
    factor_variance_target: Optional[float] = Field(default=None, gt=0.0, le=1.0)
    specific_variance_floor_ratio: float = Field(default=0.05, ge=0.0)
    style_factors: List[str] = Field(default_factory=list)
    include_sector_factors: bool = True
    exposure_lag_days: int = Field(default=1, ge=0)
    max_exposure_staleness_days: int = Field(default=540, ge=0)
    min_factor_return_days: int = Field(default=40, ge=1)
    min_cross_section: int = Field(default=8, ge=3)
    min_sector_members: int = Field(default=2, ge=1)
    factor_ridge: float = Field(default=1.0e-4, ge=0.0)
    factor_cov_shrinkage: float = Field(default=0.10, ge=0.0, le=1.0)
    fallback_to_statistical_factor: bool = True
    fallback_to_diagonal_shrinkage: bool = True
    max_forward_fill_days: int = Field(ge=0)
    alpha_signal: str = "composite_alpha"
    alpha_transform: Literal["zscore", "clipped_zscore", "rank"] = "clipped_zscore"
    alpha_clip: float = Field(default=2.0, gt=0.0)
    anchor_scheme: Literal["equal", "score_weighted", "inverse_volatility"] = "equal"
    use_active_risk: bool = True
    annualize_covariance: bool = True
    covariance_annualization_factor: float = Field(default=252.0, gt=0.0)
    risk_aversion: float = Field(gt=0.0)
    ridge_penalty: float = Field(ge=0.0)
    turnover_penalty: float = Field(default=0.0, ge=0.0)
    max_active_overweight: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    max_active_underweight: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    max_iter: int = Field(ge=1)
    tolerance: float = Field(gt=0.0)
    always_build: bool = False

    @model_validator(mode="after")
    def _validate_factor_aliases(self) -> "CovarianceConfig":
        _validate_factor_covariance_aliases(
            method=self.method,
            factor_count=self.factor_count,
            n_factors=self.n_factors,
            context="portfolio_construction.covariance",
        )
        return self


class AlphaSmoothingConfig(_BaseCfg):
    enabled: bool = False
    method: Literal["ewma"] = "ewma"
    half_life_days: float = Field(default=60.0, gt=0.0)
    max_lookback_days: int = Field(default=252, ge=1)
    min_history_points: int = Field(default=3, ge=0)


class PortfolioConstructionConfig(_BaseCfg):
    portfolio_name: str
    target_generation_frequency: Literal["monthly", "quarterly", "semiannual", "annual"] = "monthly"
    ranking_mode: str
    ranking_blend_global_weight: float = Field(ge=0.0, le=1.0)
    selection_mode: Literal["fixed_n", "top_pct", "hybrid"] = "hybrid"
    top_n: int = Field(default=25, ge=1)
    top_pct: float = Field(default=0.15, gt=0.0, le=1.0)
    hybrid_min_n: int = Field(default=30, ge=1)
    hybrid_max_n: int = Field(default=50, ge=1)
    min_names: int = Field(default=25, ge=1)
    min_candidate_pool: int = Field(default=25, ge=1)
    min_target_weight: float = Field(default=0.0, ge=0.0, le=1.0)
    no_trade_band_weight: float = Field(default=0.0, ge=0.0, le=1.0)
    per_name_max_trade_weight: float = Field(default=0.0, ge=0.0, le=1.0)
    max_new_names_per_rebalance: int = Field(default=0, ge=0)
    deduplicate_issuer_positions: bool = True
    weighting: str
    alpha_smoothing: Optional[AlphaSmoothingConfig] = None
    turnover_cap: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    incumbent_exit_rank: Optional[int] = Field(default=None, ge=1)
    max_single_weight: float = Field(default=0.05, gt=0.0, le=1.0)
    max_sector_weight: float = Field(default=0.25, gt=0.0, le=1.0)
    relax_sector_cap_if_needed: bool = True
    covariance: CovarianceConfig

    @model_validator(mode="after")
    def _validate_bounds(self) -> "PortfolioConstructionConfig":
        _validate_max_length(
            value=self.portfolio_name,
            max_len=_MAX_PORTFOLIO_NAME_LEN,
            context="portfolio_construction.portfolio_name",
        )
        if self.hybrid_min_n > self.hybrid_max_n:
            raise ValueError("hybrid_min_n cannot exceed hybrid_max_n")
        if self.min_candidate_pool < self.min_names:
            raise ValueError("min_candidate_pool cannot be below min_names")
        if self.selection_mode == "fixed_n" and self.min_names > self.top_n:
            raise ValueError("min_names cannot exceed top_n when selection_mode=fixed_n")
        if self.selection_mode == "hybrid" and self.min_names > self.hybrid_max_n:
            raise ValueError("min_names cannot exceed hybrid_max_n when selection_mode=hybrid")
        if self.incumbent_exit_rank is not None:
            if self.incumbent_exit_rank < self.min_names:
                raise ValueError("incumbent_exit_rank cannot be below min_names")
            if self.selection_mode == "fixed_n" and self.incumbent_exit_rank < self.top_n:
                raise ValueError(
                    "incumbent_exit_rank cannot be below top_n when selection_mode=fixed_n"
                )
            if self.selection_mode == "hybrid" and self.incumbent_exit_rank < self.hybrid_min_n:
                raise ValueError(
                    "incumbent_exit_rank cannot be below hybrid_min_n when selection_mode=hybrid"
                )
        if self.max_single_weight * self.min_names < 1.0 - 1e-8:
            raise ValueError(
                "max_single_weight and min_names must provide enough aggregate capacity "
                "to keep the portfolio fully invested"
            )
        if self.min_target_weight > self.max_single_weight + 1e-8:
            raise ValueError("min_target_weight cannot exceed max_single_weight")
        if self.min_target_weight * self.min_names > 1.0 + 1e-8:
            raise ValueError("min_target_weight and min_names imply more than 100% minimum capital")
        return self


class ExecutionConfig(_BaseCfg):
    cost_model: Literal["flat_total_bps", "decomposed_components"] = "flat_total_bps"
    assumed_aum: float = Field(default=10_000_000.0, gt=0.0)
    enable_liquidity_clipping: bool = True
    adv_lookback_days: int = Field(default=20, ge=1)
    min_adv_history_days: int = Field(default=5, ge=1)
    max_adv_participation: float = Field(default=0.05, gt=0.0, le=1.0)
    base_slippage_bps: float = Field(default=0.0, ge=0.0)
    open_execution_penalty_bps: float = Field(default=0.0, ge=0.0)
    gap_slippage_multiplier: float = Field(default=0.0, ge=0.0)
    participation_slippage_bps: float = Field(default=0.0, ge=0.0)
    bid_ask_spread_model: Literal["none", "fixed", "adv_tier"] = "none"
    fixed_bid_ask_spread_bps: float = Field(default=0.0, ge=0.0)
    bid_ask_crossing_fraction: float = Field(default=0.0, ge=0.0, le=1.0)
    bid_ask_adv_low_threshold: float = Field(default=1_000_000.0, gt=0.0)
    bid_ask_adv_medium_threshold: float = Field(default=10_000_000.0, gt=0.0)
    bid_ask_spread_bps_low_adv: float = Field(default=12.0, ge=0.0)
    bid_ask_spread_bps_medium_adv: float = Field(default=6.0, ge=0.0)
    bid_ask_spread_bps_high_adv: float = Field(default=2.0, ge=0.0)
    fallback_transaction_cost_bps: float = Field(default=15.0, ge=0.0)
    max_forward_fill_days: int = Field(default=5, ge=0)

    @model_validator(mode="after")
    def _validate_adv_tiers(self) -> "ExecutionConfig":
        if self.bid_ask_adv_low_threshold > self.bid_ask_adv_medium_threshold:
            raise ValueError("bid_ask_adv_low_threshold cannot exceed bid_ask_adv_medium_threshold")
        return self


class DrawdownBrakeConfig(_BaseCfg):
    enabled: bool = False
    lookback_periods: int = Field(ge=1)
    threshold_pct: float = Field(gt=0.0, lt=1.0)
    recovery_drawdown_pct: float = Field(ge=0.0, lt=1.0)
    de_risk_fraction: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _validate_recovery(self) -> "DrawdownBrakeConfig":
        if self.recovery_drawdown_pct > self.threshold_pct:
            raise ValueError("recovery_drawdown_pct cannot exceed threshold_pct")
        return self


class IntradayTriggersConfig(_BaseCfg):
    enabled: bool = False
    stock_stop_loss_pct: float = Field(lt=0.0)
    stop_loss_mode: Literal["fixed_pct", "vol_scaled"] = "vol_scaled"
    stop_loss_vol_lookback_days: int = Field(ge=1)
    stop_loss_min_history_days: int = Field(ge=1)
    stop_loss_vol_multiplier: float = Field(gt=0.0)
    stop_loss_min_abs_pct: float = Field(gt=0.0, lt=1.0)
    stop_loss_max_abs_pct: float = Field(gt=0.0, lt=1.0)
    vix_spike_pct: float = Field(ge=0.0)
    vix_spike_min_level: float = Field(ge=0.0)
    term_spread_confirm_enabled: bool = False
    term_spread_stress_threshold: float = 0.0
    vix_hard_stress_level: float = Field(ge=0.0)
    vix_recovery_threshold: float = Field(ge=0.0)
    vix_recovery_consecutive_days: int = Field(ge=1)
    regime_switch_mode: str = "next_day_rebalance"
    allow_reentry_after_stop_loss: bool = False
    mid_frequency_rebalance_enabled: bool = False
    mid_frequency_rebalance_weekday: int = Field(ge=0, le=6)
    mid_frequency_min_turnover: float = Field(ge=0.0, le=1.0)
    event_driven_enabled: bool = False
    news_sentiment_shock_enabled: bool = False
    news_sentiment_surprise_threshold: float = 0.0
    news_sentiment_min_article_count: float = Field(ge=0.0)
    news_sentiment_trim_fraction: float = Field(ge=0.0, le=1.0)
    earnings_event_enabled: bool = False
    earnings_require_publication_flag: bool = True
    earnings_negative_news_min_count: float = Field(ge=0.0)
    earnings_trim_fraction: float = Field(ge=0.0, le=1.0)
    rating_downgrade_event_enabled: bool = False
    rating_downgrade_min_count: float = Field(ge=0.0)
    rating_trim_fraction: float = Field(ge=0.0, le=1.0)
    event_cooldown_days: int = Field(ge=0)
    transaction_cost_bps: float = Field(ge=0.0)
    save_daily_state: bool = False
    max_forward_fill_days: int = Field(default=5, ge=0)

    @model_validator(mode="after")
    def _validate_stop_band(self) -> "IntradayTriggersConfig":
        if self.stop_loss_min_abs_pct > self.stop_loss_max_abs_pct:
            raise ValueError("stop_loss_min_abs_pct cannot exceed stop_loss_max_abs_pct")
        return self


class AnalysisCovarianceConfig(_BaseCfg):
    enabled: bool = True
    method: Literal[
        "diagonal_shrinkage",
        "ledoit_wolf",
        "statistical_factor",
        "factor_model",
        "pca_factor",
        "fundamental_factor",
        "fundamental_factor_model",
        "barra_lite",
    ] = "diagonal_shrinkage"
    lookback_days: int = Field(ge=20)
    min_history_days: int = Field(ge=20)
    shrinkage_intensity: float = Field(ge=0.0, le=1.0)
    factor_count: Optional[int] = Field(default=None, ge=1)
    n_factors: Optional[int] = Field(default=None, ge=1)
    max_factor_count: int = Field(default=5, ge=1)
    factor_variance_target: Optional[float] = Field(default=None, gt=0.0, le=1.0)
    specific_variance_floor_ratio: float = Field(default=0.05, ge=0.0)
    style_factors: List[str] = Field(default_factory=list)
    include_sector_factors: bool = True
    exposure_lag_days: int = Field(default=1, ge=0)
    max_exposure_staleness_days: int = Field(default=540, ge=0)
    min_factor_return_days: int = Field(default=40, ge=1)
    min_cross_section: int = Field(default=8, ge=3)
    min_sector_members: int = Field(default=2, ge=1)
    factor_ridge: float = Field(default=1.0e-4, ge=0.0)
    factor_cov_shrinkage: float = Field(default=0.10, ge=0.0, le=1.0)
    fallback_to_statistical_factor: bool = True
    fallback_to_diagonal_shrinkage: bool = True
    max_forward_fill_days: int = Field(ge=0)
    include_series: List[str] = Field(default_factory=list)
    max_condition_number: float = Field(gt=0.0, default=1e8)
    relative_eigen_floor: float = Field(gt=0.0, default=1e-10)
    absolute_eigen_floor: float = Field(gt=0.0, default=1e-12)

    @model_validator(mode="after")
    def _validate_factor_aliases(self) -> "AnalysisCovarianceConfig":
        _validate_factor_covariance_aliases(
            method=self.method,
            factor_count=self.factor_count,
            n_factors=self.n_factors,
            context="analysis.covariance",
        )
        return self


class AnalysisConfig(_BaseCfg):
    primary_benchmark: str = "SPY"
    secondary_benchmark: str = "universe_ew"
    stress_vix_threshold: float = Field(ge=0.0)
    universe_ew_deduct_cost: bool = False
    static_baseline_cost_bps: float = Field(ge=0.0)
    static_baseline_normal_weights: RegimeWeightsConfig
    covariance: AnalysisCovarianceConfig


class BacktestConfig(_BaseCfg):
    portfolio_name: str
    start_date: str | None = "auto"
    end_date: str | None = "auto"
    lookback_years: int = Field(ge=1)
    rebalance_frequency: str = "monthly"
    execution_lag: int = Field(ge=1)
    transaction_cost_bps: float = Field(ge=0.0)
    long_only: bool = True
    weighting: str
    top_n: int = Field(ge=1)
    benchmark_ticker: str
    initial_nav: float = Field(gt=0.0)
    min_eligible_universe: int = Field(ge=1)
    max_forward_fill_days: int = Field(ge=0)
    execution: ExecutionConfig
    drawdown_brake: DrawdownBrakeConfig = Field(default_factory=DrawdownBrakeConfig)
    intraday_triggers: IntradayTriggersConfig
    analysis: AnalysisConfig

    @model_validator(mode="after")
    def _validate_portfolio_name(self) -> "BacktestConfig":
        _validate_max_length(
            value=self.portfolio_name,
            max_len=_MAX_PORTFOLIO_NAME_LEN,
            context="backtest.portfolio_name",
        )
        return self


class RecommendationConfig(_BaseCfg):
    portfolio_name: str
    default_status: str = "proposed"
    latest_as_of_policy: str = "latest_lte_run_date"
    approval_required: bool = True

    @model_validator(mode="after")
    def _validate_portfolio_name(self) -> "RecommendationConfig":
        _validate_max_length(
            value=self.portfolio_name,
            max_len=_MAX_PORTFOLIO_NAME_LEN,
            context="recommendation.portfolio_name",
        )
        return self


class KafkaTopicsConfig(_BaseCfg):
    cw1_news_structured: str
    cw1_event_proxies: str
    cw2_risk_actions_requested: str
    cw2_risk_actions_executed: str
    platform_run_status: str


class KafkaAuditConsumerConfig(_BaseCfg):
    enabled: bool = True
    consumer_group: str = "team_pearson_cw2_audit"
    consumer_component: str = "cw2.kafka_audit_consumer"
    topic_keys: List[str] = Field(
        default_factory=lambda: [
            "cw2_risk_actions_requested",
            "cw2_risk_actions_executed",
            "platform_run_status",
        ]
    )
    poll_timeout_ms: int = Field(default=1000, ge=1)
    max_batch_messages: int = Field(default=200, ge=1)
    max_idle_polls: int = Field(default=3, ge=1)
    max_retries_per_message: int = Field(default=3, ge=0)
    lag_warning_threshold: int = Field(default=100, ge=0)
    freshness_warning_minutes: int = Field(default=60, ge=1)
    pending_grace_minutes: int = Field(default=2, ge=0)
    orphan_reconcile_minutes: int = Field(default=60, ge=1)


class KafkaConfig(_BaseCfg):
    enabled: bool = False
    required: bool = False
    bootstrap_servers: List[str] = Field(default_factory=list)
    client_id: str = "team_pearson_cw2"
    linger_ms: int = Field(ge=0)
    batch_size: int = Field(ge=0)
    compression_type: str = "gzip"
    topics: KafkaTopicsConfig
    audit_consumer: KafkaAuditConsumerConfig = Field(default_factory=KafkaAuditConsumerConfig)


class ReportingConfig(_BaseCfg):
    output_dir: str


class GovernanceVersionsConfig(_BaseCfg):
    model_version: str
    factor_definition_version: str
    covariance_method_version: str
    risk_overlay_policy_version: str
    recommendation_version: str
    backtest_engine_version: str
    reporting_version: str


class GovernanceConfig(_BaseCfg):
    versions: GovernanceVersionsConfig


class CW2Config(_BaseCfg):
    factors: Dict[str, FactorGroupConfig]
    preprocessing: PreprocessingConfig
    investable_universe: InvestableUniverseConfig
    regime: RegimeConfig
    risk_overlay: RiskOverlayConfig
    pipeline_guards: PipelineGuardsConfig
    quality_gates: QualityGatesConfig
    portfolio_construction: PortfolioConstructionConfig
    backtest: BacktestConfig
    recommendation: RecommendationConfig
    kafka: KafkaConfig
    reporting: ReportingConfig
    governance: GovernanceConfig

    @model_validator(mode="after")
    def _validate_portfolio_floor_contract(self) -> "CW2Config":
        min_names = self.portfolio_construction.min_names
        min_candidate_pool = self.portfolio_construction.min_candidate_pool
        if self.pipeline_guards.min_investable_universe < min_candidate_pool:
            raise ValueError(
                "pipeline_guards.min_investable_universe cannot be below "
                "portfolio_construction.min_candidate_pool"
            )
        if self.quality_gates.min_portfolio_targets < min_names:
            raise ValueError(
                "quality_gates.min_portfolio_targets cannot be below "
                "portfolio_construction.min_names"
            )
        if self.backtest.min_eligible_universe < min_names:
            raise ValueError(
                "backtest.min_eligible_universe cannot be below " "portfolio_construction.min_names"
            )
        return self


def load_cw2_config(config_path: str | None = None) -> Dict[str, Any]:
    """Load and validate the CW2 YAML config."""
    path = (
        Path(config_path)
        if config_path
        else (Path(__file__).resolve().parents[2] / "config" / "conf.yaml")
    )
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    validated = CW2Config.model_validate(raw)
    return validated.model_dump(mode="python")
