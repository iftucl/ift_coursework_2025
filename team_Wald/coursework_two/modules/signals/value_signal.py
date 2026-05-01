"""
UCL -- Institute of Finance & Technology
Author  : Team Wald
Topic   : Sector-relative value scoring (MSCI Enhanced Value 4-stage pipeline)
Project : CW2 - Value-Sentiment Investment Strategy

UPGRADE from CW1: Replaces cross-sectional percentile ranking with
sector-relative z-score normalisation.

Problem: Cross-sectional ranking makes financials/utilities always
appear 'cheap' vs technology due to structural sector differences.
Ehsani, Harvey & Li (2023): standard HML 'consistently overweights
Finance and Utilities'.

Solution — MSCI 4-Stage Pipeline:
  Stage 1: Flip ratios (E/P, B/P, EBITDA/EV, Div Yield).
           Winsorize at 2.5/97.5 percentiles.
           Exclude EV/EBITDA for financials.
  Stage 2: Cross-sectional z-scores across all stocks.
  Stage 3: Composite z = average of metric z-scores.
           Within-sector re-standardization.
  Stage 4: Cap at ±3.  Bayesian shrinkage for small sectors.

Evidence:
  - Ehsani et al. (2023): within-sector Sharpe 0.154 vs 0.032 across-sector
  - Asness, Porter & Stevens (2000): within-industry characteristics
    more precise

Ref: Part A §A2
"""

import logging

import numpy as np
import pandas as pd
from scipy import stats

logger = logging.getLogger(__name__)


class ValueSignal:
    """Compute sector-relative value scores using MSCI 4-stage pipeline.

    :param config: Parsed backtest_config.yaml dict
    :type config: dict
    """

    def __init__(self, config: dict):
        self._winsorize_lower = config['scoring']['winsorize_lower']
        self._winsorize_upper = config['scoring']['winsorize_upper']
        self._zscore_cap = config['scoring']['zscore_cap']
        self._shrinkage_k = config['scoring']['shrinkage_k_sector']

    def compute(
        self,
        value_df: pd.DataFrame,
        sector_map: dict,
    ) -> pd.DataFrame:
        """Compute sector-relative value scores for all companies.

        Implements the full MSCI 4-stage pipeline:
        1. Flip ratios to value-favourable direction
        2. Cross-sectional z-score normalisation
        3. Composite z-score with within-sector re-standardisation
        4. Cap at ±3, apply Bayesian shrinkage for small sectors

        :param value_df: DataFrame with pe_ratio, pb_ratio, ev_ebitda,
                         dividend_yield, debt_equity per company_id
        :type value_df: pd.DataFrame
        :param sector_map: Dict mapping company_id → GICS sector
        :type sector_map: dict
        :returns: DataFrame with company_id and value_score columns
        :rtype: pd.DataFrame
        :raises ValueError: If no valid ratios exist for any company
        """
        df = value_df.copy()
        df = df.set_index('company_id') if 'company_id' in df.columns else df

        # Handle empty input
        if len(df) == 0:
            return pd.DataFrame(columns=['company_id', 'value_score', 'gics_sector'])

        # Map GICS sector onto each company
        df['gics_sector'] = df.index.map(sector_map)

        # ----------------------------------------------------------
        # Stage 1: Flip ratios to value-favourable direction
        # ----------------------------------------------------------
        df = self._stage1_flip_and_winsorize(df)

        # ----------------------------------------------------------
        # Stage 2: Cross-sectional z-scores
        # ----------------------------------------------------------
        df = self._stage2_cross_sectional_zscore(df)

        # ----------------------------------------------------------
        # Stage 3: Composite z + within-sector re-standardisation
        # ----------------------------------------------------------
        df = self._stage3_composite_and_sector_restand(df)

        # ----------------------------------------------------------
        # Stage 4: Cap at ±3, Bayesian shrinkage for small sectors
        # ----------------------------------------------------------
        df = self._stage4_cap_and_shrinkage(df)

        result = df[['value_score', 'gics_sector']].reset_index()
        result.rename(columns={'index': 'company_id'}, inplace=True)
        if result.columns[0] != 'company_id':
            result = result.rename(columns={result.columns[0]: 'company_id'})

        scored = result['value_score'].notna().sum()
        logger.info(
            "Sector-relative value scores: %d/%d companies scored",
            scored, len(result),
        )
        return result

    def _stage1_flip_and_winsorize(self, df: pd.DataFrame) -> pd.DataFrame:
        """Stage 1: Flip ratios and winsorize extremes.

        Converts P/E → E/P, P/B → B/P, EV/EBITDA → EBITDA/EV so
        that higher = cheaper (value-favourable).  Dividend Yield
        already has the correct direction.  Excludes EV/EBITDA for
        financials per MSCI methodology.

        :param df: DataFrame with raw ratios and gics_sector
        :type df: pd.DataFrame
        :returns: DataFrame with flipped, winsorized ratios
        :rtype: pd.DataFrame
        """
        # Flip ratios: higher = better value
        df['ep'] = np.where(
            (df['pe_ratio'] > 0) & df['pe_ratio'].notna(),
            1.0 / df['pe_ratio'],
            np.nan,
        )
        df['bp'] = np.where(
            (df['pb_ratio'] > 0) & df['pb_ratio'].notna(),
            1.0 / df['pb_ratio'],
            np.nan,
        )
        df['ebitda_ev'] = np.where(
            (df['ev_ebitda'] > 0) & df['ev_ebitda'].notna(),
            1.0 / df['ev_ebitda'],
            np.nan,
        )

        # Exclude EV/EBITDA for financials (per MSCI methodology)
        # Financials have different capital structure — EV/EBITDA not meaningful
        is_financial = df['gics_sector'] == 'Financials'
        df.loc[is_financial, 'ebitda_ev'] = np.nan

        # Dividend yield: already in correct direction (higher = better)
        df['div_yield'] = df['dividend_yield'].copy()

        # Winsorize at configured percentiles to limit outlier influence
        value_cols = ['ep', 'bp', 'ebitda_ev', 'div_yield']
        for col in value_cols:
            valid = df[col].dropna()
            if len(valid) < 5:
                continue
            lower = valid.quantile(self._winsorize_lower)
            upper = valid.quantile(self._winsorize_upper)
            df[col] = df[col].clip(lower=lower, upper=upper)

        logger.info(
            "Stage 1 complete: flipped and winsorized %d companies (%d financials excluded from EV/EBITDA)",
            len(df), is_financial.sum(),
        )
        return df

    def _stage2_cross_sectional_zscore(self, df: pd.DataFrame) -> pd.DataFrame:
        """Stage 2: Cross-sectional z-score normalisation.

        Standardises each flipped ratio across the full universe
        to z = (x - mean) / std, enabling comparability across
        different metric scales.

        :param df: DataFrame with flipped, winsorized ratios
        :type df: pd.DataFrame
        :returns: DataFrame with z-score columns appended
        :rtype: pd.DataFrame
        """
        value_cols = ['ep', 'bp', 'ebitda_ev', 'div_yield']
        for col in value_cols:
            z_col = f'{col}_z'
            valid_mask = df[col].notna()
            if valid_mask.sum() < 3:
                df[z_col] = np.nan
                continue
            mean_val = df.loc[valid_mask, col].mean()
            std_val = df.loc[valid_mask, col].std()
            if std_val > 0:
                df[z_col] = (df[col] - mean_val) / std_val
            else:
                df[z_col] = 0.0
            # Set NaN where original was NaN
            df.loc[~valid_mask, z_col] = np.nan

        logger.info("Stage 2 complete: cross-sectional z-scores computed")
        return df

    def _stage3_composite_and_sector_restand(self, df: pd.DataFrame) -> pd.DataFrame:
        """Stage 3: Composite z-score and within-sector re-standardisation.

        Averages the individual metric z-scores into a single composite,
        then re-standardises within each GICS sector to remove
        structural sector biases.

        Z_sector_rel = (Z_composite - mean_sector) / std_sector

        :param df: DataFrame with individual z-score columns
        :type df: pd.DataFrame
        :returns: DataFrame with sector-relative composite z-score
        :rtype: pd.DataFrame
        """
        z_cols = ['ep_z', 'bp_z', 'ebitda_ev_z', 'div_yield_z']
        # Composite z = mean of available z-scores per company
        df['composite_z'] = df[z_cols].mean(axis=1)

        # Within-sector re-standardisation using transform (preserves DataFrame shape)
        sector_groups = df.groupby('gics_sector')['composite_z']
        sector_mean = sector_groups.transform('mean')
        sector_std = sector_groups.transform('std')
        sector_count = sector_groups.transform('count')

        # Only re-standardise sectors with ≥3 stocks and positive std
        can_restand = (sector_std > 0) & (sector_count >= 3)
        df['sector_rel_z'] = np.where(
            can_restand,
            (df['composite_z'] - sector_mean) / sector_std,
            0.0,
        )

        logger.info("Stage 3 complete: within-sector re-standardisation applied")
        return df

    def _stage4_cap_and_shrinkage(self, df: pd.DataFrame) -> pd.DataFrame:
        """Stage 4: Cap z-scores and apply Bayesian shrinkage.

        Caps sector-relative z-scores at ±3 to limit extreme influence.
        For sectors with fewer than ``shrinkage_k`` stocks, applies
        Bayesian shrinkage toward zero to reduce estimation noise.

        Shrinkage formula: z_final = (n / (n + k)) × z_raw
        where k = shrinkage_k_sector (default 20).

        :param df: DataFrame with sector_rel_z column
        :type df: pd.DataFrame
        :returns: DataFrame with final value_score column
        :rtype: pd.DataFrame
        """
        # Cap at ±3
        df['value_score'] = df['sector_rel_z'].clip(
            lower=-self._zscore_cap,
            upper=self._zscore_cap,
        )

        # Bayesian shrinkage for small sectors
        sector_counts = df.groupby('gics_sector').size()
        for sector, count in sector_counts.items():
            if count < self._shrinkage_k:
                shrinkage = count / (count + self._shrinkage_k)
                mask = df['gics_sector'] == sector
                df.loc[mask, 'value_score'] = df.loc[mask, 'value_score'] * shrinkage
                logger.info(
                    "Applied Bayesian shrinkage to %s (%d stocks, factor=%.3f)",
                    sector, count, shrinkage,
                )

        logger.info(
            "Stage 4 complete: capped at ±%.1f, shrinkage applied",
            self._zscore_cap,
        )
        return df
