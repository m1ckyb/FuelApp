"""Configuration management for NSW Fuel Station App."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
import yaml
from pathlib import Path
from typing import Optional, List, Dict, Any

from dotenv import load_dotenv

_LOGGER = logging.getLogger(__name__)

# --- Constants ---

# Data key for fuel station coordinator
DATA_NSW_FUEL_STATION = "nsw_fuel_station"

# Allowed fuel types
ALLOWED_FUEL_TYPES = [
    "E10",
    "U91",
    "E85",
    "P95",
    "P98",
    "DL",
    "PDL",
    "B20",
    "LPG",
    "CNG",
    "EV",
]

# Default configuration values
DEFAULT_POLL_INTERVAL = 60  # minutes
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_TIMEZONE = "Australia/Sydney"
DEFAULT_MQTT_PORT = 1883
DEFAULT_MQTT_DISCOVERY_PREFIX = "homeassistant"

# Database schema version
SCHEMA_VERSION = 1

# --- Logging ---

def setup_logging(log_level: str):
    """Configure logging for the application."""
    numeric_level = getattr(logging, log_level.upper(), None)
    if not isinstance(numeric_level, int):
        numeric_level = logging.INFO

    logging.basicConfig(
        level=numeric_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )


# --- Database Manager ---

class ConfigDatabase:
    """Manage configuration storage in SQLite database."""

    def __init__(self, db_path: str = "config.db"):
        """Initialize database connection.
        
        Args:
            db_path: Path to the SQLite database file
        """
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None

    def connect(self) -> bool:
        """Connect to the database and initialize schema if needed.
        
        Note: Uses check_same_thread=False for Flask compatibility.
        The Flask app runs in a single-threaded development server by default.
        For production use with multi-threading, consider using a connection pool
        or implementing proper thread synchronization.
        
        Returns:
            True if connection successful, False otherwise
        """
        try:
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            self._init_schema()
            return True
        except Exception as exc:
            _LOGGER.error("Failed to connect to database: %s", exc)
            return False

    def _init_schema(self):
        """Initialize database schema if it doesn't exist."""
        cursor = self.conn.cursor()
        
        # Create schema version table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create settings table for InfluxDB and app configuration
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create stations table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stations (
                station_id INTEGER PRIMARY KEY,
                fuel_types TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Check if schema exists
        cursor.execute("SELECT version FROM schema_version WHERE version = ?", (SCHEMA_VERSION,))
        if not cursor.fetchone():
            cursor.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
        
        self.conn.commit()
        _LOGGER.info("Database schema initialized")

    def get_setting(self, key: str) -> Optional[str]:
        """Get a setting value by key.
        
        Args:
            key: Setting key
            
        Returns:
            Setting value or None if not found
        """
        if not self.conn:
            return None
        
        cursor = self.conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row['value'] if row else None

    def set_setting(self, key: str, value: str) -> bool:
        """Set a setting value.
        
        Args:
            key: Setting key
            value: Setting value
            
        Returns:
            True if successful, False otherwise
        """
        if not self.conn:
            return False
        
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT INTO settings (key, value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = CURRENT_TIMESTAMP
            """, (key, value))
            self.conn.commit()
            return True
        except Exception as exc:
            _LOGGER.error("Failed to set setting %s: %s", key, exc)
            return False

    def get_all_settings(self) -> Dict[str, str]:
        """Get all settings as a dictionary.
        
        Returns:
            Dictionary of all settings
        """
        if not self.conn:
            return {}
        
        cursor = self.conn.cursor()
        cursor.execute("SELECT key, value FROM settings")
        return {row['key']: row['value'] for row in cursor.fetchall()}

    def get_stations(self) -> List[Dict[str, Any]]:
        """Get all configured stations.
        
        Returns:
            List of station dictionaries
        """
        if not self.conn:
            return []
        
        cursor = self.conn.cursor()
        cursor.execute("SELECT station_id, fuel_types FROM stations")
        
        stations = []
        for row in cursor.fetchall():
            stations.append({
                'station_id': row['station_id'],
                'fuel_types': json.loads(row['fuel_types'])
            })
        return stations

    def add_station(self, station_id: int, fuel_types: List[str]) -> bool:
        """Add a new station.
        
        Args:
            station_id: Station ID
            fuel_types: List of fuel types
            
        Returns:
            True if successful, False otherwise
        """
        if not self.conn:
            return False
        
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT INTO stations (station_id, fuel_types, created_at, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """, (station_id, json.dumps(fuel_types)))
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            _LOGGER.error("Station %d already exists", station_id)
            return False
        except Exception as exc:
            _LOGGER.error("Failed to add station %d: %s", station_id, exc)
            return False

    def update_station(self, station_id: int, fuel_types: List[str]) -> bool:
        """Update a station's fuel types.
        
        Args:
            station_id: Station ID
            fuel_types: List of fuel types
            
        Returns:
            True if successful, False otherwise
        """
        if not self.conn:
            return False
        
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                UPDATE stations
                SET fuel_types = ?, updated_at = CURRENT_TIMESTAMP
                WHERE station_id = ?
            """, (json.dumps(fuel_types), station_id))
            self.conn.commit()
            return cursor.rowcount > 0
        except Exception as exc:
            _LOGGER.error("Failed to update station %d: %s", station_id, exc)
            return False

    def delete_station(self, station_id: int) -> bool:
        """Delete a station.
        
        Args:
            station_id: Station ID
            
        Returns:
            True if successful, False otherwise
        """
        if not self.conn:
            return False
        
        try:
            cursor = self.conn.cursor()
            cursor.execute("DELETE FROM stations WHERE station_id = ?", (station_id,))
            self.conn.commit()
            return cursor.rowcount > 0
        except Exception as exc:
            _LOGGER.error("Failed to delete station %d: %s", station_id, exc)
            return False

    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None


# --- Configuration Loader ---

class Config:
    """Configuration for the NSW Fuel Station App."""

    def __init__(self, db_path: Optional[str] = None):
        """Initialize configuration with default values.
        
        Args:
            db_path: Path to SQLite database file
        """
        self.data_dir = os.getenv('DATA_DIR', '.')
        if db_path is None:
            self.db_path = os.path.join(self.data_dir, "config.db")
        else:
            self.db_path = db_path

        self.influxdb_url: str = "http://localhost:8086"
        self.influxdb_token: str = ""
        self.influxdb_org: str = ""
        self.influxdb_bucket: str = "fuel_prices"
        
        self.mqtt_broker: str = ""
        self.mqtt_port: int = DEFAULT_MQTT_PORT
        self.mqtt_user: str = ""
        self.mqtt_password: str = ""
        self.mqtt_discovery_prefix: str = DEFAULT_MQTT_DISCOVERY_PREFIX
        
        self.stations: list[dict] = []
        self.poll_interval: int = DEFAULT_POLL_INTERVAL
        self.cron_schedule: str = ""
        self.timezone: str = DEFAULT_TIMEZONE
        self.log_level: str = DEFAULT_LOG_LEVEL
        
        self.db: Optional[ConfigDatabase] = None

    def load_from_file(self, config_path: str) -> bool:
        """
        Load configuration.
        Priority: Database > YAML file
        
        Args:
            config_path: Path to the configuration YAML file
            
        Returns:
            True if successful, False otherwise
        """
        # Try loading from database first if it exists
        if Path(self.db_path).exists():
            if self.load_from_database():
                _LOGGER.info("Configuration loaded from database (ignoring YAML file)")
                return True
        
        try:
            config_file = Path(config_path)
            if not config_file.exists():
                _LOGGER.info("Configuration file not found: %s, will try database", config_path)
                return self.load_from_database()

            with open(config_file, 'r') as f:
                config_data = yaml.safe_load(f)

            # Load InfluxDB configuration
            if 'influxdb' in config_data:
                influx_config = config_data['influxdb']
                self.influxdb_url = influx_config.get('url', self.influxdb_url)
                self.influxdb_token = influx_config.get('token', self.influxdb_token)
                self.influxdb_org = influx_config.get('org', self.influxdb_org)
                self.influxdb_bucket = influx_config.get('bucket', self.influxdb_bucket)
            
            # Load MQTT configuration (optional in YAML)
            if 'mqtt' in config_data:
                mqtt_config = config_data['mqtt']
                self.mqtt_broker = mqtt_config.get('broker', self.mqtt_broker)
                self.mqtt_port = mqtt_config.get('port', self.mqtt_port)
                self.mqtt_user = mqtt_config.get('user', self.mqtt_user)
                self.mqtt_password = mqtt_config.get('password', self.mqtt_password)
                self.mqtt_discovery_prefix = mqtt_config.get('discovery_prefix', self.mqtt_discovery_prefix)

            # Load stations configuration
            if 'stations' in config_data:
                self.stations = config_data['stations']
                
                # Validate fuel types
                for station in self.stations:
                    fuel_types = station.get('fuel_types', [])
                    invalid_types = [
                        ft for ft in fuel_types 
                        if ft not in ALLOWED_FUEL_TYPES
                    ]
                    if invalid_types:
                        _LOGGER.warning(
                            "Station %d has invalid fuel types: %s",
                            station.get('station_id'),
                            invalid_types
                        )

            # Load other settings
            self.poll_interval = config_data.get('poll_interval', self.poll_interval)
            self.log_level = config_data.get('log_level', self.log_level)

            _LOGGER.info("Configuration loaded from %s", config_path)
            
            # Migrate to database if it doesn't exist
            if not Path(self.db_path).exists():
                _LOGGER.info("Migrating configuration from YAML to database")
                self.migrate_to_database()
            
            return True

        except Exception as exc:
            _LOGGER.error("Failed to load configuration from file: %s", exc)
            # Try loading from database as fallback
            return self.load_from_database()
    
    def load_from_database(self) -> bool:
        """
        Load configuration from SQLite database.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            self.db = ConfigDatabase(self.db_path)
            if not self.db.connect():
                _LOGGER.error("Failed to connect to database")
                return False
            
            # Load settings
            settings = self.db.get_all_settings()
            
            # If database is empty, return False so YAML can be tried
            if not settings:
                _LOGGER.info("Database is empty")
                return False
            
            self.influxdb_url = settings.get('influxdb_url', self.influxdb_url)
            self.influxdb_token = settings.get('influxdb_token', self.influxdb_token)
            self.influxdb_org = settings.get('influxdb_org', self.influxdb_org)
            self.influxdb_bucket = settings.get('influxdb_bucket', self.influxdb_bucket)
            
            # Load MQTT settings
            self.mqtt_broker = settings.get('mqtt_broker', self.mqtt_broker)
            try:
                self.mqtt_port = int(settings.get('mqtt_port', self.mqtt_port))
            except (ValueError, TypeError):
                pass
            self.mqtt_user = settings.get('mqtt_user', self.mqtt_user)
            self.mqtt_password = settings.get('mqtt_password', self.mqtt_password)
            self.mqtt_discovery_prefix = settings.get('mqtt_discovery_prefix', self.mqtt_discovery_prefix)
            
            # Parse poll_interval with error handling
            try:
                self.poll_interval = int(settings.get('poll_interval', self.poll_interval))
            except (ValueError, TypeError):
                _LOGGER.warning("Invalid poll_interval in database, using default: %d", self.poll_interval)
            
            self.cron_schedule = settings.get('cron_schedule', self.cron_schedule)
            self.timezone = settings.get('timezone', self.timezone)
            self.log_level = settings.get('log_level', self.log_level)
            
            # Load stations
            self.stations = self.db.get_stations()
            
            _LOGGER.info("Configuration loaded from database")
            return True
            
        except Exception as exc:
            _LOGGER.error("Failed to load configuration from database: %s", exc)
            return False
    
    def migrate_to_database(self) -> bool:
        """
        Migrate current configuration to SQLite database.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            if not self.db:
                self.db = ConfigDatabase(self.db_path)
                if not self.db.connect():
                    return False
            
            # Save settings
            self.db.set_setting('influxdb_url', self.influxdb_url)
            self.db.set_setting('influxdb_token', self.influxdb_token)
            self.db.set_setting('influxdb_org', self.influxdb_org)
            self.db.set_setting('influxdb_bucket', self.influxdb_bucket)
            
            # Save MQTT settings
            self.db.set_setting('mqtt_broker', self.mqtt_broker)
            self.db.set_setting('mqtt_port', str(self.mqtt_port))
            self.db.set_setting('mqtt_user', self.mqtt_user)
            self.db.set_setting('mqtt_password', self.mqtt_password)
            self.db.set_setting('mqtt_discovery_prefix', self.mqtt_discovery_prefix)
            
            self.db.set_setting('poll_interval', str(self.poll_interval))
            self.db.set_setting('cron_schedule', self.cron_schedule)
            self.db.set_setting('timezone', self.timezone)
            self.db.set_setting('log_level', self.log_level)
            
            # Save stations
            for station in self.stations:
                self.db.add_station(
                    station['station_id'],
                    station['fuel_types']
                )
            
            _LOGGER.info("Configuration migrated to database successfully")
            return True
            
        except Exception as exc:
            _LOGGER.error("Failed to migrate configuration to database: %s", exc)
            return False
    
    def save_to_database(self) -> bool:
        """
        Save current configuration to database.
        
        Returns:
            True if successful, False otherwise
        """
        if not self.db:
            self.db = ConfigDatabase(self.db_path)
            if not self.db.connect():
                return False
        
        try:
            # Save all settings
            self.db.set_setting('influxdb_url', self.influxdb_url)
            self.db.set_setting('influxdb_token', self.influxdb_token)
            self.db.set_setting('influxdb_org', self.influxdb_org)
            self.db.set_setting('influxdb_bucket', self.influxdb_bucket)
            
            # Save MQTT settings
            self.db.set_setting('mqtt_broker', self.mqtt_broker)
            self.db.set_setting('mqtt_port', str(self.mqtt_port))
            self.db.set_setting('mqtt_user', self.mqtt_user)
            self.db.set_setting('mqtt_password', self.mqtt_password)
            self.db.set_setting('mqtt_discovery_prefix', self.mqtt_discovery_prefix)
            
            self.db.set_setting('poll_interval', str(self.poll_interval))
            self.db.set_setting('cron_schedule', self.cron_schedule)
            self.db.set_setting('timezone', self.timezone)
            self.db.set_setting('log_level', self.log_level)
            
            _LOGGER.info("Configuration saved to database")
            return True
            
        except Exception as exc:
            _LOGGER.error("Failed to save configuration to database: %s", exc)
            return False

    def load_from_env(self):
        """Load configuration from environment variables."""
        load_dotenv()
        
        # Override with environment variables if present
        if os.getenv('INFLUXDB_URL'):
            self.influxdb_url = os.getenv('INFLUXDB_URL')
        if os.getenv('INFLUXDB_TOKEN'):
            self.influxdb_token = os.getenv('INFLUXDB_TOKEN')
        if os.getenv('INFLUXDB_ORG'):
            self.influxdb_org = os.getenv('INFLUXDB_ORG')
        if os.getenv('INFLUXDB_BUCKET'):
            self.influxdb_bucket = os.getenv('INFLUXDB_BUCKET')
            
        # Load MQTT env vars
        if os.getenv('MQTT_BROKER'):
            self.mqtt_broker = os.getenv('MQTT_BROKER')
        if os.getenv('MQTT_PORT'):
            try:
                self.mqtt_port = int(os.getenv('MQTT_PORT'))
            except ValueError:
                pass
        if os.getenv('MQTT_USER'):
            self.mqtt_user = os.getenv('MQTT_USER')
        if os.getenv('MQTT_PASSWORD'):
            self.mqtt_password = os.getenv('MQTT_PASSWORD')
        if os.getenv('MQTT_DISCOVERY_PREFIX'):
            self.mqtt_discovery_prefix = os.getenv('MQTT_DISCOVERY_PREFIX')
            
        if os.getenv('TIMEZONE'):
            self.timezone = os.getenv('TIMEZONE')
        if os.getenv('CRON_SCHEDULE'):
            self.cron_schedule = os.getenv('CRON_SCHEDULE')
        
        _LOGGER.debug("Environment variables loaded")

    def validate(self) -> bool:
        """
        Validate the configuration.
        
        Returns:
            True if configuration is valid, False otherwise
        """
        errors = []

        if not self.influxdb_url:
            errors.append("InfluxDB URL is required")
        if not self.influxdb_token:
            errors.append("InfluxDB token is required")
        if not self.influxdb_org:
            errors.append("InfluxDB organization is required")
        if not self.influxdb_bucket:
            errors.append("InfluxDB bucket is required")

        if not self.stations:
            errors.append("At least one station must be configured")
        else:
            for station in self.stations:
                if 'station_id' not in station:
                    errors.append("Station missing 'station_id'")
                if 'fuel_types' not in station or not station['fuel_types']:
                    errors.append(
                        f"Station {station.get('station_id', 'unknown')} "
                        "must have at least one fuel type"
                    )

        if errors:
            for error in errors:
                _LOGGER.error("Configuration error: %s", error)
            return False

        _LOGGER.info("Configuration validated successfully")
        return True