"""SQLite database manager for application configuration."""

from __future__ import annotations

import logging
import sqlite3
import json
from pathlib import Path
from typing import Optional, List, Dict, Any

_LOGGER = logging.getLogger(__name__)

# Database schema version
SCHEMA_VERSION = 1

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
