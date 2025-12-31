"""Configuration loader for NSW Fuel Station App."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv

from constants import ALLOWED_FUEL_TYPES, DEFAULT_LOG_LEVEL, DEFAULT_POLL_INTERVAL

_LOGGER = logging.getLogger(__name__)


class Config:
    """Configuration for the NSW Fuel Station App."""

    def __init__(self):
        """Initialize configuration with default values."""
        self.influxdb_url: str = "http://localhost:8086"
        self.influxdb_token: str = ""
        self.influxdb_org: str = ""
        self.influxdb_bucket: str = "fuel_prices"
        
        self.stations: list[dict] = []
        self.poll_interval: int = DEFAULT_POLL_INTERVAL
        self.log_level: str = DEFAULT_LOG_LEVEL

    def load_from_file(self, config_path: str) -> bool:
        """
        Load configuration from YAML file.
        
        Args:
            config_path: Path to the configuration YAML file
            
        Returns:
            True if successful, False otherwise
        """
        try:
            config_file = Path(config_path)
            if not config_file.exists():
                _LOGGER.error("Configuration file not found: %s", config_path)
                return False

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
            return True

        except Exception as exc:
            _LOGGER.error("Failed to load configuration: %s", exc)
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
