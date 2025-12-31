"""Configuration loader for NSW Fuel Station App."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv

from constants import ALLOWED_FUEL_TYPES, DEFAULT_LOG_LEVEL, DEFAULT_POLL_INTERVAL
from config_db import ConfigDatabase

_LOGGER = logging.getLogger(__name__)


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
        
        self.stations: list[dict] = []
        self.poll_interval: int = DEFAULT_POLL_INTERVAL
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
            
            # Parse poll_interval with error handling
            try:
                self.poll_interval = int(settings.get('poll_interval', self.poll_interval))
            except (ValueError, TypeError):
                _LOGGER.warning("Invalid poll_interval in database, using default: %d", self.poll_interval)
            
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
            self.db.set_setting('poll_interval', str(self.poll_interval))
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
            self.db.set_setting('poll_interval', str(self.poll_interval))
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

