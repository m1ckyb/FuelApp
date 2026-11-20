"""Comprehensive unit and integration tests for FuelApp."""

from __future__ import annotations

import io
import zipfile
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.config import Config, ConfigDatabase
from app.data import InfluxDBWriter, StationPriceData
from app.main import FuelApp
from app.notifications import DiscordClient, is_valid_discord_webhook_url
import app.web as web_module


# --- ConfigDatabase & Config Tests ---


def test_config_database_connection_reuse_and_foreign_keys(tmp_path):
    db_path = str(tmp_path / "test.db")
    cfg = Config(db_path=db_path)
    assert cfg.save_to_database() is True

    first_db = cfg.db
    first_conn = first_db.conn

    # Reloading from database must reuse the existing ConfigDatabase and connection
    assert cfg.load_from_database() is True
    assert cfg.db is first_db
    assert cfg.db.conn is first_conn

    # Foreign keys must be enabled (PRAGMA foreign_keys = 1)
    fk_status = cfg.db.conn.execute("PRAGMA foreign_keys").fetchone()[0]
    assert fk_status == 1

    # Cascade delete on webauthn_credentials when user is deleted
    uid = cfg.db.create_user("alice", "hash")
    assert uid is not None
    assert cfg.db.add_credential(uid, b"cred1", b"pubkey1", 0, "[]") is True
    assert len(cfg.db.get_credentials_by_user(uid)) == 1
    cfg.db.conn.execute("DELETE FROM users WHERE id = ?", (uid,))
    cfg.db.conn.commit()
    assert cfg.db.get_credentials_by_user(uid) == []

    cfg.db.close()


def test_create_first_user_is_atomic(tmp_path):
    db = ConfigDatabase(str(tmp_path / "first_user.db"))
    assert db.connect() is True
    uid1 = db.create_first_user("admin1", "hash1")
    uid2 = db.create_first_user("admin2", "hash2")
    assert uid1 is not None
    assert uid2 is None
    assert db.get_user_count() == 1
    db.close()


def test_rate_limiter_enforces_limit(tmp_path):
    db = ConfigDatabase(str(tmp_path / "ratelimit.db"))
    assert db.connect() is True
    assert db.check_rate_limit("login:1.2.3.4:admin", max_attempts=2, window_seconds=60) is True
    assert db.check_rate_limit("login:1.2.3.4:admin", max_attempts=2, window_seconds=60) is True
    assert db.check_rate_limit("login:1.2.3.4:admin", max_attempts=2, window_seconds=60) is False
    db.close()


def test_station_metadata_persistence(tmp_path):
    db = ConfigDatabase(str(tmp_path / "stations.db"))
    assert db.connect() is True
    assert db.add_station(350, ["P98", "E10"], "NSW", 4.0, station_name="Shell Sydney") is True
    stations = db.get_stations()
    assert len(stations) == 1
    assert stations[0]["station_name"] == "Shell Sydney"

    assert db.update_station_metadata(350, "Shell Sydney Updated", "123 George St") is True
    stations = db.get_stations()
    assert stations[0]["station_name"] == "Shell Sydney Updated"
    assert stations[0]["station_address"] == "123 George St"
    db.close()


# --- InfluxDBWriter Tests ---


def test_influxdb_writer_close():
    writer = InfluxDBWriter("http://localhost:8086", "tok", "org", "bucket")
    mock_client = MagicMock()
    writer.client = mock_client
    writer.write_api = MagicMock()
    writer.close()
    mock_client.close.assert_called_once()
    assert writer.client is None
    assert writer.write_api is None


# --- Discord SSRF Validation Tests ---


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://discord.com/api/webhooks/123456/abcdef", True),
        ("https://discordapp.com/api/webhooks/123456/abcdef", True),
        ("https://ptb.discord.com/api/webhooks/123/xyz", True),
        ("http://discord.com/api/webhooks/123456/abcdef", False),  # HTTP disallowed
        ("http://169.254.169.254/latest/meta-data/", False),       # AWS metadata SSRF
        ("http://localhost:8086/api/v2/write", False),             # Internal SSRF
        ("https://evil.com/api/webhooks/123/abc", False),          # Wrong host
        ("https://discord.com/not-a-webhook", False),              # Wrong path
        ("", False),
    ],
)
def test_discord_webhook_ssrf_validation(url, expected):
    assert is_valid_discord_webhook_url(url) is expected


def test_discord_client_refuses_invalid_url():
    client = DiscordClient("http://127.0.0.1:8086/secret")
    assert client.send_notification("hello") is False


# --- FuelApp Core Logic Tests ---


def test_fuelapp_averages_exclude_removed_fuel_types_and_reloads_mqtt(tmp_path):
    cfg = Config(db_path=str(tmp_path / "fuelapp.db"))
    cfg.data_dir = str(tmp_path)
    cfg.save_to_database()
    cfg.db.add_station(100, ["P98"], "NSW", 4.0)
    cfg.load_from_database()

    with patch("app.main.MQTTClient") as mock_mqtt_cls:
        mock_mqtt_instance = MagicMock()
        mock_mqtt_instance.connected = False
        mock_mqtt_cls.return_value = mock_mqtt_instance

        app = FuelApp(cfg)
        app.connected = True
        app.writer = MagicMock()
        app.writer.write_fuel_prices.return_value = True
        app.writer.write_average_prices.return_value = True

        # Pre-seed last_prices with a removed fuel type (E10) on station 100
        app.last_prices = {(100, "E10"): 180.0, (100, "P98"): 210.0}

        station_obj = SimpleNamespace(
            code=100, name="Test Station", address="1 Main St", brand="BP", au_state="NSW"
        )
        price_obj = SimpleNamespace(station_code=100, fuel_type="P98", price=224.0, last_updated=None)
        app.fetcher = MagicMock()
        app.fetcher.fetch_station_price_data.return_value = StationPriceData(
            stations={100: station_obj},
            prices={(100, "P98"): price_obj},
        )

        # Change MQTT broker in DB to trigger reload
        cfg.db.set_setting("mqtt_broker", "192.168.1.50")

        app.fetch_and_store()

        # Discount (4.0) applied: 224.0 - 4.0 = 220.0
        # Only active fuel type P98 should be in averages (removed E10 excluded)
        app.writer.write_average_prices.assert_called_once_with({"P98": 220.0})

        # Station metadata persisted back to SQLite
        stations = cfg.db.get_stations()
        assert stations[0]["station_name"] == "Test Station"
        assert stations[0]["station_address"] == "1 Main St"

        # MQTT client closed and re-initialized on broker change
        mock_mqtt_instance.close.assert_called_once()
        assert mock_mqtt_cls.call_count == 2


# --- Flask Web UI & API Tests ---


@pytest.fixture
def web_client(tmp_path):
    cfg = Config(db_path=str(tmp_path / "web.db"))
    cfg.data_dir = str(tmp_path)
    cfg.save_to_database()
    cfg.load_from_database()

    web_module.app.config["TESTING"] = True
    web_module.app.config["WTF_CSRF_ENABLED"] = False
    if not getattr(web_module.app, "login_manager", None):
        web_module.login_manager.init_app(web_module.app)
    web_module.init_app(cfg)

    with web_module.app.test_client() as client:
        yield client, cfg


def _create_and_login(client):
    resp = client.post(
        "/setup",
        data={"username": "admin", "password": "strongpassword", "confirm_password": "strongpassword"},
        follow_redirects=False,
    )
    assert resp.status_code == 302


def test_healthz_unauthenticated(web_client):
    client, _ = web_client
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}
    assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"


def test_station_crud_and_validation_across_workers(web_client):
    client, cfg = web_client
    _create_and_login(client)

    # Reject station_id <= 0 (reserved for Average Prices)
    r = client.post("/api/stations", json={"station_id": 0, "fuel_types": ["P98"]})
    assert r.status_code == 400

    # Reject negative discount
    r = client.post("/api/stations", json={"station_id": 350, "fuel_types": ["P98"], "discount": -2.0})
    assert r.status_code == 400

    # Add valid station
    r = client.post(
        "/api/stations",
        json={"station_id": 350, "au_state": "NSW", "station_name": "Metro Fuel", "fuel_types": ["P98"], "discount": 4.0},
    )
    assert r.status_code == 201

    # Simulate another Gunicorn worker with stale empty in-memory config.stations
    cfg.stations = []
    r = client.put(
        "/api/stations/350",
        json={"au_state": "NSW", "fuel_types": ["P98", "E10"], "discount": 2.0},
    )
    assert r.status_code == 200

    # GET /api/stations reads cached name from SQLite without live API call
    r = client.get("/api/stations")
    assert r.status_code == 200
    stations = r.get_json()["stations"]
    assert len(stations) == 1
    assert stations[0]["station_name"] == "Metro Fuel"
    assert stations[0]["fuel_types"] == ["P98", "E10"]


def test_config_validation_rejects_bad_cron_timezone_and_ssrf(web_client):
    client, _ = web_client
    _create_and_login(client)

    assert client.put("/api/config", json={"cron_schedule": "not a cron"}).status_code == 400
    assert client.put("/api/config", json={"timezone": "Mars/Olympus"}).status_code == 400
    assert client.put("/api/config", json={"discord_webhook_url": "http://169.254.169.254/meta"}).status_code == 400
    assert client.put("/api/config", json={"influxdb_url": "--help"}).status_code == 400

    # Valid updates succeed
    r = client.put(
        "/api/config",
        json={"cron_schedule": "0 * * * *", "timezone": "Australia/Sydney"},
    )
    assert r.status_code == 200


def test_backup_download_and_restore_zip_slip_blocked(web_client, tmp_path):
    client, cfg = web_client
    _create_and_login(client)

    # Create a sibling directory sharing prefix with 'backups'
    sibling = tmp_path / "backups_evil"
    sibling.mkdir()
    (sibling / "secret.zip").write_bytes(b"secret")

    # Attempt traversal to sibling directory
    r = client.get("/api/backup/download/..%2Fbackups_evil%2Fsecret.zip")
    assert r.status_code in (400, 404)

    # Attempt Zip Slip upload on /api/restore
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../../escaped.txt", "pwned")
    buf.seek(0)

    r = client.post(
        "/api/restore",
        data={"file": (buf, "evil.zip")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 400
    assert "unsafe paths" in r.get_json()["error"].lower()
