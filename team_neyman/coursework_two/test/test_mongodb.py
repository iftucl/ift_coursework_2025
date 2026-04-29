import mongomock
import pytest

from modules.db_loader import mongodb


# This fixture resets the global client and mocks the config for every test
@pytest.fixture(autouse=True)
def mock_db_env(mocker):
    # Reset the global variable so tests don't leak into each other
    mongodb._mongo_client = None

    # Mock the config return
    mock_conf = {
        "host": "localhost",
        "port": 27017,
        "dbname": "test_db",
        "collection": "test_trades",
    }
    mocker.patch("modules.db_loader.mongodb.load_config", return_value=mock_conf)

    # Patch MongoClient to return a mongomock client
    mocker.patch("modules.db_loader.mongodb.MongoClient", mongomock.MongoClient)


def test_save_trade_log_logic():
    """Verify that document structure is correct when saving."""
    trades = [{"symbol": "AAPL", "weight": 0.5}]
    mongodb.save_trade_log("2025-01-01", 100000.0, trades)

    col = mongodb.get_collection()
    saved_doc = col.find_one({"portfolio_date": "2025-01-01"})

    assert saved_doc is not None
    assert saved_doc["capital"] == 100000.0
    assert saved_doc["status"] == "PENDING"
    assert saved_doc["year"] == 2025
    assert len(saved_doc["trades"]) == 1


def test_get_pending_flow():
    """Ensure we only retrieve 'PENDING' items."""
    col = mongodb.get_collection()
    # Insert one pending and one executed
    col.insert_many(
        [
            {"portfolio_date": "2025-01-01", "status": "EXECUTED"},
            {"portfolio_date": "2025-01-02", "status": "PENDING"},
        ]
    )

    pending = mongodb.get_pending()
    assert pending["portfolio_date"] == "2025-01-02"


def test_get_sector_weights_agg():
    """Test the pandas aggregation logic within the Mongo query."""
    col = mongodb.get_collection()
    col.insert_one(
        {
            "portfolio_date": "2025-01-31",
            "trades": [
                {"gics_sector": "Tech", "weight": 0.4},
                {"gics_sector": "Tech", "weight": 0.2},
                {"gics_sector": "Energy", "weight": 0.4},
            ],
        }
    )

    weights = mongodb.get_sector_weights("2025", "1", "test_trades")

    assert weights["Tech"] == pytest.approx(0.6)
    assert weights["Energy"] == pytest.approx(0.4)
    assert weights.index[0] == "Tech"  # Sorted check


def test_get_latest_date_logic():
    """Verify chronological sorting of dates."""
    col = mongodb.get_collection()
    col.insert_many(
        [
            {"portfolio_date": "2024-12-31"},
            {"portfolio_date": "2025-01-05"},
            {"portfolio_date": "2025-01-01"},
        ]
    )

    assert mongodb.get_latest_date("test_trades") == "2025-01-05"
    assert mongodb.get_initial_date("test_trades") == "2024-12-31"


def test_reset_mongodb_execution(mocker):

    # Mock the client and database drop
    mock_client = mocker.patch("modules.db_loader.mongodb.MongoClient")
    mocker.patch(
        "modules.db_loader.mongodb.load_config",
        return_value={"host": "h", "port": 1, "dbname": "test"},
    )

    mongodb.reset_mongodb()
    mock_client.return_value.drop_database.assert_called_once_with("test")
