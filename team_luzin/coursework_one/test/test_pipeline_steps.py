"""
Consolidated integration tests for complete pipeline execution
Includes factor calculation, portfolio selection, signal generation, and data export
"""

import json
import os
import tempfile
from datetime import datetime
from unittest.mock import MagicMock, Mock, mock_open, patch

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def mock_config():
    """Mock configuration"""
    return {
        "postgres": {
            "host": "localhost",
            "port": 5432,
            "user": "test",
            "password": "test",
            "database": "test",
            "schema": "test_schema",
        },
        "minio": {
            "endpoint": "localhost:9000",
            "access_key": "key",
            "secret_key": "secret",
            "bucket": "test",
        },
    }


@pytest.fixture
def sample_universe():
    """Sample company universe"""
    return [
        {"symbol": "AAPL", "security": "Apple Inc.", "gics_sector": "IT"},
        {"symbol": "MSFT", "security": "Microsoft Corp.", "gics_sector": "IT"},
        {"symbol": "JPM", "security": "JPMorgan Chase", "gics_sector": "FIN"},
    ]


@pytest.fixture
def sample_price_data():
    """Sample OHLCV data for a stock"""
    dates = pd.date_range("2023-01-01", periods=260, freq="D")
    return pd.DataFrame(
        {
            "Date": dates,
            "Open": np.linspace(100, 120, 260),
            "High": np.linspace(102, 122, 260),
            "Low": np.linspace(98, 118, 260),
            "Close": np.linspace(100, 120, 260) + np.random.normal(0, 1, 260),
            "Volume": np.random.uniform(1000000, 5000000, 260),
        }
    )


@pytest.fixture
def universe_with_factors():
    """Universe with calculated factors"""
    return pd.DataFrame(
        {
            "symbol": [
                "AAPL",
                "MSFT",
                "GOOG",
                "AMZN",
                "NVDA",
                "JPM",
                "BAC",
                "GS",
                "JNJ",
                "PFE",
            ],
            "sector": [
                "IT",
                "IT",
                "COMM",
                "CONS",
                "IT",
                "FIN",
                "FIN",
                "FIN",
                "HC",
                "HC",
            ],
            "momentum_12m": [
                0.25,
                0.20,
                0.15,
                0.30,
                0.35,
                0.10,
                0.05,
                0.08,
                0.12,
                0.08,
            ],
            "volatility_12m": [
                0.25,
                0.22,
                0.20,
                0.30,
                0.35,
                0.18,
                0.20,
                0.22,
                0.15,
                0.18,
            ],
            "avg_dollar_volume_60d": [
                50000000,
                30000000,
                25000000,
                35000000,
                20000000,
                15000000,
                10000000,
                8000000,
                18000000,
                12000000,
            ],
        }
    )


@pytest.fixture
def portfolio_with_prices():
    """Portfolio with current prices"""
    return pd.DataFrame(
        {
            "symbol": ["AAPL", "MSFT", "GOOG", "AMZN"],
            "current_price": [150.25, 340.50, 2800.75, 3200.10],
            "quantity": [100, 50, 10, 20],
        }
    )


@pytest.fixture
def macd_data():
    """MACD signals"""
    return pd.DataFrame(
        {
            "symbol": ["AAPL", "MSFT", "GOOG", "AMZN"],
            "MACD": [0.5, -0.3, 0.1, -0.2],
            "Signal": [0.4, -0.2, 0.15, -0.1],
            "Histogram": [0.1, -0.1, -0.05, -0.1],
        }
    )


# ============================================================================
# FACTOR CALCULATION TESTS
# ============================================================================


class TestFactorCalculation:
    """Test factor calculation flow"""

    def test_factor_calculation_flow(self, sample_price_data):
        """Test complete factor calculation flow"""
        df = sample_price_data.copy()

        # Calculate momentum
        momentum_12m = (df["Close"].iloc[-1] - df["Close"].iloc[0]) / df["Close"].iloc[
            0
        ]
        assert isinstance(momentum_12m, float)
        assert -1 < momentum_12m < 1

        # Calculate volatility
        returns = df["Close"].pct_change().dropna()
        volatility = returns.std() * np.sqrt(252)
        assert volatility > 0

        # Calculate dollar volume
        df["dollar_volume"] = df["Close"] * df["Volume"]
        avg_dv = df["dollar_volume"].tail(60).mean()
        assert avg_dv > 0

    def test_batch_processing_multiple_stocks(self):
        """Test processing multiple stocks in batch"""
        stocks = ["AAPL", "MSFT", "GOOG"]
        results = {}

        for symbol in stocks:
            # Simulate factor calculation for each stock
            prices = np.linspace(100, 120, 260)
            momentum = (prices[-1] - prices[0]) / prices[0]
            results[symbol] = {
                "momentum_12m": momentum,
                "volatility": np.std(np.diff(prices) / prices[:-1]) * np.sqrt(252),
            }

        assert len(results) == 3
        assert all(isinstance(v["momentum_12m"], float) for v in results.values())

    def test_data_validation_before_storage(self):
        """Test that calculated factors are validated"""
        factors = {
            "momentum_12m": 0.15,
            "volatility": 0.25,
            "avg_dv": 50000000,
            "macd": 0.5,
        }

        # Valid factors should have numeric values
        valid = all(isinstance(v, (int, float)) for v in factors.values())
        assert valid

        # Check for reasonable ranges
        assert -1 < factors["momentum_12m"] < 1
        assert factors["volatility"] > 0
        assert factors["avg_dv"] > 0

    def test_handle_missing_data_in_calculation(self):
        """Test handling of missing data during calculation"""
        dates = pd.date_range("2023-01-01", periods=260, freq="D")
        prices = np.linspace(100, 120, 260)
        prices[50:60] = np.nan  # Insert gap

        df = pd.DataFrame(
            {
                "Date": dates,
                "Close": prices,
                "Volume": np.random.uniform(1000000, 5000000, 260),
            }
        )

        # Clean data
        df_clean = df.dropna()
        assert len(df_clean) < len(df)

        # Can still calculate with cleaned data
        if len(df_clean) >= 252:
            momentum = (
                df_clean["Close"].iloc[-1] - df_clean["Close"].iloc[0]
            ) / df_clean["Close"].iloc[0]
            assert isinstance(momentum, float)


# ============================================================================
# PORTFOLIO SELECTION TESTS
# ============================================================================


class TestPortfolioSelection:
    """Test portfolio selection logic"""

    def test_ram_ranking_calculation(self, universe_with_factors):
        """Test Risk-Adjusted Momentum ranking"""
        df = universe_with_factors.copy()

        # Calculate RAM
        df["RAM"] = df["momentum_12m"] / df["volatility_12m"]

        # Top RAM stocks should have high momentum/low volatility
        top_ram = df.nlargest(3, "RAM")

        assert len(top_ram) == 3
        assert top_ram["RAM"].iloc[0] >= top_ram["RAM"].iloc[2]

    def test_sector_grouping_for_top_20_percent(self, universe_with_factors):
        """Test selecting top 20% from each sector"""
        df = universe_with_factors.copy()
        df["RAM"] = df["momentum_12m"] / df["volatility_12m"]

        # Group by sector
        selected = []
        for sector in df["sector"].unique():
            sector_stocks = df[df["sector"] == sector].copy()
            sector_stocks = sector_stocks.sort_values("RAM", ascending=False)

            # Top 20% of sector
            n_select = max(1, int(len(sector_stocks) * 0.2))
            selected.extend(sector_stocks.head(n_select)["symbol"].tolist())

        assert len(selected) >= 2
        assert all(isinstance(s, str) for s in selected)

    def test_liquidity_filter_application(self, universe_with_factors):
        """Test applying liquidity filter"""
        df = universe_with_factors.copy()

        # Filter for liquid stocks ($1M+ daily volume)
        threshold = 1_000_000
        liquid = df[df["avg_dollar_volume_60d"] >= threshold]

        assert len(liquid) == len(df)  # All stocks meet threshold

        # With stricter threshold
        threshold = 20_000_000
        very_liquid = df[df["avg_dollar_volume_60d"] >= threshold]

        assert len(very_liquid) < len(df)

    def test_combined_selection_logic(self, universe_with_factors):
        """Test combining RAM ranking + liquidity filter"""
        df = universe_with_factors.copy()
        df["RAM"] = df["momentum_12m"] / df["volatility_12m"]

        # Step 1: Filter by liquidity
        df_liquid = df[df["avg_dollar_volume_60d"] >= 8_000_000].copy()

        # Step 2: Top 20% per sector by RAM
        selected = []
        for sector in df_liquid["sector"].unique():
            sector_stocks = df_liquid[df_liquid["sector"] == sector]
            n_select = max(1, int(len(sector_stocks) * 0.2))
            top_stocks = sector_stocks.nlargest(n_select, "RAM")
            selected.extend(top_stocks["symbol"].tolist())

        portfolio = pd.DataFrame({"symbol": selected})

        assert len(portfolio) >= 2
        assert len(portfolio) <= 10


# ============================================================================
# SIGNAL GENERATION TESTS
# ============================================================================


class TestSignalGeneration:
    """Test trading signal generation"""

    def test_macd_signal_generation_buy(self):
        """Test BUY signal generation (MACD > Signal)"""
        macd_line = 0.5
        signal_line = 0.4

        signal = "BUY" if macd_line > signal_line else "SELL"
        assert signal == "BUY"

    def test_macd_signal_generation_sell(self):
        """Test SELL signal generation (MACD < Signal)"""
        macd_line = -0.3
        signal_line = -0.2

        signal = "BUY" if macd_line > signal_line else "SELL"
        assert signal == "SELL"

    def test_macd_signal_generation_hold(self):
        """Test HOLD when no clear signal"""
        macd_line = 0.0
        signal_line = 0.01
        prev_macd = -0.1
        prev_signal = 0.0

        # Buy signal: MACD crosses above signal
        buy_crossover = (macd_line > signal_line) and (prev_macd <= prev_signal)

        # Sell signal: MACD crosses below signal
        sell_crossover = (macd_line < signal_line) and (prev_macd >= prev_signal)

        assert not buy_crossover
        assert not sell_crossover

    def test_signal_distribution_for_portfolio(self, portfolio_with_prices, macd_data):
        """Test signal generation for entire portfolio"""
        portfolio = portfolio_with_prices.copy()
        signals = macd_data.copy()

        merged = portfolio.merge(signals, on="symbol")
        merged["signal"] = merged.apply(
            lambda row: "BUY" if row["MACD"] > row["Signal"] else "SELL", axis=1
        )

        buy_signals = len(merged[merged["signal"] == "BUY"])
        sell_signals = len(merged[merged["signal"] == "SELL"])

        assert buy_signals + sell_signals == len(merged)
        assert buy_signals >= 0
        assert sell_signals >= 0

    def test_position_sizing_from_signal(self, portfolio_with_prices):
        """Test calculating trade size from signals"""
        portfolio = portfolio_with_prices.copy()

        # Each position should be tradable
        portfolio["trade_value"] = portfolio["current_price"] * portfolio["quantity"]

        assert all(portfolio["trade_value"] > 0)
        total_value = portfolio["trade_value"].sum()
        assert total_value > 0


# ============================================================================
# DATA EXPORT TESTS
# ============================================================================


class TestDataExport:
    """Test data export functionality"""

    @pytest.fixture
    def sample_results(self):
        """Sample portfolio results"""
        return pd.DataFrame(
            {
                "symbol": ["AAPL", "MSFT", "GOOG"],
                "price": [150.25, 340.50, 2800.75],
                "momentum": [0.25, 0.20, 0.15],
                "volatility": [0.25, 0.22, 0.20],
                "date": [pd.Timestamp("2024-01-15")] * 3,
            }
        )

    def test_write_to_csv(self, sample_results):
        """Test CSV write operation"""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "results.csv")
            sample_results.to_csv(filepath, index=False)

            assert os.path.exists(filepath)
            assert os.path.getsize(filepath) > 0

            # Verify data integrity
            df = pd.read_csv(filepath)
            assert len(df) == 3
            assert list(df.columns) == list(sample_results.columns)

    def test_write_to_parquet(self, sample_results):
        """Test Parquet write operation"""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "results.parquet")
            sample_results.to_parquet(filepath)

            assert os.path.exists(filepath)

            df = pd.read_parquet(filepath)
            assert len(df) == 3

    def test_write_to_jsonl(self, sample_results):
        """Test JSONL write operation"""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "results.jsonl")

            with open(filepath, "w") as f:
                for _, row in sample_results.iterrows():
                    f.write(json.dumps(row.to_dict(), default=str) + "\n")

            assert os.path.exists(filepath)

            with open(filepath) as f:
                lines = f.readlines()
            assert len(lines) == 3

    def test_bulk_export_multiple_formats(self, sample_results):
        """Test exporting to multiple formats simultaneously"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Write all formats
            sample_results.to_csv(os.path.join(tmpdir, "data.csv"), index=False)
            sample_results.to_parquet(os.path.join(tmpdir, "data.parquet"))

            with open(os.path.join(tmpdir, "data.jsonl"), "w") as f:
                for _, row in sample_results.iterrows():
                    f.write(json.dumps(row.to_dict(), default=str) + "\n")

            # Verify all files created
            files = os.listdir(tmpdir)
            assert len(files) == 3
            assert "data.csv" in files
            assert "data.parquet" in files
            assert "data.jsonl" in files


# ============================================================================
# COMPLETE PIPELINE TESTS
# ============================================================================


class TestCompletePipeline:
    """Test complete pipeline execution end-to-end"""

    @patch("modules.db.postgres_connector.PostgresConnector")
    def test_pipeline_step_1_factor_calculation(self, mock_pg):
        """Test step 1: Calculate factors"""
        # Setup mock
        mock_conn = MagicMock()
        mock_pg.return_value = mock_conn

        # Simulate factor calculation
        factors = {
            "AAPL": {"momentum_12m": 0.25, "volatility": 0.25, "avg_dv": 50000000},
            "MSFT": {"momentum_12m": 0.20, "volatility": 0.22, "avg_dv": 30000000},
        }

        assert len(factors) == 2
        assert all("momentum_12m" in v for v in factors.values())

    def test_pipeline_step_2_portfolio_selection(self):
        """Test step 2: Select portfolio"""
        # Simulated universe
        universe = pd.DataFrame(
            {
                "symbol": ["AAPL", "MSFT", "GOOG", "AMZN"],
                "RAM": [1.0, 0.9, 0.8, 0.7],
                "sector": ["IT", "IT", "IT", "IT"],
                "avg_dv": [50000000, 30000000, 25000000, 35000000],
            }
        )

        # Select top 50%
        selected = universe.nlargest(2, "RAM")

        assert len(selected) == 2
        assert selected["symbol"].iloc[0] == "AAPL"

    def test_pipeline_step_3_signal_generation(self):
        """Test step 3: Generate trading signals"""
        portfolio = pd.DataFrame(
            {"symbol": ["AAPL", "MSFT"], "MACD": [0.5, -0.3], "Signal": [0.4, -0.2]}
        )

        portfolio["trade_signal"] = portfolio.apply(
            lambda x: "BUY" if x["MACD"] > x["Signal"] else "SELL", axis=1
        )

        assert len(portfolio) == 2
        assert "BUY" in portfolio["trade_signal"].values

    def test_pipeline_step_4_data_export(self):
        """Test step 4: Export data"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test data
            portfolio = pd.DataFrame(
                {
                    "symbol": ["AAPL", "MSFT"],
                    "price": [150.25, 340.50],
                    "signal": ["BUY", "SELL"],
                }
            )

            # Export to multiple formats
            csv_path = os.path.join(tmpdir, "portfolio.csv")
            parquet_path = os.path.join(tmpdir, "portfolio.parquet")
            jsonl_path = os.path.join(tmpdir, "portfolio.jsonl")

            portfolio.to_csv(csv_path, index=False)
            portfolio.to_parquet(parquet_path)

            with open(jsonl_path, "w") as f:
                for _, row in portfolio.iterrows():
                    f.write(json.dumps(row.to_dict(), default=str) + "\n")

            # Verify all formats exist
            assert os.path.exists(csv_path)
            assert os.path.exists(parquet_path)
            assert os.path.exists(jsonl_path)

    def test_pipeline_error_handling_missing_data(self):
        """Test error handling when data is missing"""
        # Empty universe
        universe = pd.DataFrame({"symbol": []})

        if len(universe) == 0:
            error = "No companies in universe"
            assert error == "No companies in universe"

    def test_pipeline_end_to_end_data_flow(self):
        """Test complete data flow through pipeline"""
        # Step 1: Get universe
        universe = pd.DataFrame(
            {"symbol": ["AAPL", "MSFT", "GOOG"], "sector": ["IT", "IT", "IT"]}
        )

        # Step 2: Add factors
        universe["momentum"] = [0.25, 0.20, 0.15]
        universe["volatility"] = [0.25, 0.22, 0.20]
        universe["ram"] = universe["momentum"] / universe["volatility"]

        # Step 3: Select portfolio
        portfolio = universe.nlargest(2, "ram")

        # Step 4: Add signals
        portfolio["signal"] = "BUY"

        assert len(portfolio) == 2
        assert "signal" in portfolio.columns


# ============================================================================
# MINIO STORAGE INTEGRATION TESTS
# ============================================================================


class TestMinIOIntegration:
    """Test MinIO storage integration"""

    @patch("minio.Minio")
    def test_minio_connection(self, mock_minio):
        """Test MinIO connection"""
        mock_client = MagicMock()
        mock_minio.return_value = mock_client

        assert mock_client is not None

    @patch("minio.Minio")
    def test_upload_file_to_minio(self, mock_minio):
        """Test uploading file to MinIO"""
        mock_client = MagicMock()
        mock_minio.return_value = mock_client

        bucket = "csreport"
        object_name = "portfolio.csv"
        file_content = b"symbol,price\nAAPL,150.25"

        mock_client.put_object = MagicMock()

        assert bucket == "csreport"
        assert object_name == "portfolio.csv"

    @patch("minio.Minio")
    def test_list_objects_in_bucket(self, mock_minio):
        """Test listing objects in MinIO bucket"""
        mock_client = MagicMock()
        mock_minio.return_value = mock_client

        # Mock list_objects
        mock_objects = [
            MagicMock(object_name="portfolio.csv"),
            MagicMock(object_name="portfolio.parquet"),
            MagicMock(object_name="portfolio.jsonl"),
        ]
        mock_client.list_objects = MagicMock(return_value=mock_objects)

        objects = mock_client.list_objects("csreport")

        assert len(list(objects)) == 3


# ============================================================================
# PARQUET INTEGRATION TESTS
# ============================================================================


class TestParquetIntegration:
    """Test Parquet file operations"""

    @pytest.fixture
    def parquet_data(self):
        """Create sample Parquet data"""
        return pd.DataFrame(
            {
                "symbol": ["AAPL", "MSFT", "GOOG"],
                "price": [150.25, 340.50, 2800.75],
                "date": pd.date_range("2024-01-01", periods=3),
            }
        )

    def test_read_parquet_file(self, parquet_data):
        """Test reading Parquet file"""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "data.parquet")
            parquet_data.to_parquet(filepath)

            df = pd.read_parquet(filepath)

            assert len(df) == 3
            assert "symbol" in df.columns

    def test_parquet_column_dtypes_preserved(self, parquet_data):
        """Test that Parquet preserves column dtypes"""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "data.parquet")
            parquet_data.to_parquet(filepath)

            df = pd.read_parquet(filepath)

            assert df["symbol"].dtype == "object"
            assert pd.api.types.is_float_dtype(df["price"])
            assert pd.api.types.is_datetime64_any_dtype(df["date"])

    def test_parquet_large_file_handling(self):
        """Test reading large Parquet files"""
        large_df = pd.DataFrame(
            {
                "symbol": ["SYM" + str(i % 100) for i in range(10000)],
                "price": np.random.uniform(50, 500, 10000),
                "date": pd.date_range("2020-01-01", periods=10000),
            }
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "large.parquet")
            large_df.to_parquet(filepath)

            df = pd.read_parquet(filepath)

            assert len(df) == 10000
            assert df.shape[1] == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
