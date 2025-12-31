"""Flask web application for NSW Fuel Station monitoring."""

from __future__ import annotations

import json
import logging
import os
import secrets
import yaml
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from flask import Flask, render_template, request, jsonify, redirect, url_for
from influxdb_client import InfluxDBClient
from influxdb_client.client.flux_table import FluxTable

from config_loader import Config
from fuel_data import FuelDataFetcher, StationPriceData
from constants import ALLOWED_FUEL_TYPES

_LOGGER = logging.getLogger(__name__)

app = Flask(__name__)

# Global config instance
config: Optional[Config] = None
fetcher: Optional[FuelDataFetcher] = None


def init_app(config_obj: Config):
    """Initialize the Flask app with configuration."""
    global config, fetcher
    config = config_obj
    fetcher = FuelDataFetcher()

    # Configure secret key from data_dir
    secret_key = os.environ.get('FLASK_SECRET_KEY')
    if not secret_key:
        secret_file = Path(config.data_dir) / '.flask_secret'
        if secret_file.exists():
            with open(secret_file, 'r') as f:
                secret_key = f.read().strip()
        else:
            secret_key = secrets.token_hex(32)
            try:
                with open(secret_file, 'w') as f:
                    f.write(secret_key)
            except Exception:
                _LOGGER.warning("Could not persist Flask secret key to file")
    app.config['SECRET_KEY'] = secret_key


@app.route('/')
def index():
    """Dashboard page."""
    return render_template('dashboard.html')


@app.route('/stations')
def stations():
    """Stations management page."""
    return render_template('stations.html')


@app.route('/settings')
def settings():
    """Settings page."""
    return render_template('settings.html')


@app.route('/api/stations', methods=['GET'])
def get_stations():
    """Get all configured stations."""
    if not config:
        return jsonify({'error': 'Configuration not loaded'}), 500
    
    return jsonify({'stations': config.stations})


@app.route('/api/stations', methods=['POST'])
def add_station():
    """Add a new station to configuration."""
    if not config:
        return jsonify({'error': 'Configuration not loaded'}), 500
    
    data = request.get_json()
    station_id = data.get('station_id')
    fuel_types = data.get('fuel_types', [])
    
    if not station_id:
        return jsonify({'error': 'station_id is required'}), 400
    
    if not fuel_types:
        return jsonify({'error': 'At least one fuel type is required'}), 400
    
    # Validate fuel types
    invalid_types = [ft for ft in fuel_types if ft not in ALLOWED_FUEL_TYPES]
    if invalid_types:
        return jsonify({'error': f'Invalid fuel types: {invalid_types}'}), 400
    
    # Check if station already exists
    for station in config.stations:
        if station['station_id'] == station_id:
            return jsonify({'error': 'Station already exists'}), 400
    
    # Add station to database
    if config.db and config.db.add_station(station_id, fuel_types):
        # Update in-memory config
        new_station = {
            'station_id': station_id,
            'fuel_types': fuel_types
        }
        config.stations.append(new_station)
        return jsonify({'message': 'Station added successfully', 'station': new_station}), 201
    else:
        return jsonify({'error': 'Failed to add station'}), 500


@app.route('/api/stations/<int:station_id>', methods=['DELETE'])
def delete_station(station_id):
    """Delete a station from configuration."""
    if not config:
        return jsonify({'error': 'Configuration not loaded'}), 500
    
    # Delete from database
    if config.db and config.db.delete_station(station_id):
        # Update in-memory config
        config.stations = [s for s in config.stations if s['station_id'] != station_id]
        return jsonify({'message': 'Station deleted successfully'}), 200
    else:
        return jsonify({'error': 'Failed to delete station'}), 500


@app.route('/api/stations/<int:station_id>', methods=['PUT'])
def update_station(station_id):
    """Update a station configuration."""
    if not config:
        return jsonify({'error': 'Configuration not loaded'}), 500
    
    data = request.get_json()
    fuel_types = data.get('fuel_types', [])
    
    if not fuel_types:
        return jsonify({'error': 'At least one fuel type is required'}), 400
    
    # Validate fuel types
    invalid_types = [ft for ft in fuel_types if ft not in ALLOWED_FUEL_TYPES]
    if invalid_types:
        return jsonify({'error': f'Invalid fuel types: {invalid_types}'}), 400
    
    # Update in database
    if config.db and config.db.update_station(station_id, fuel_types):
        # Update in-memory config
        for station in config.stations:
            if station['station_id'] == station_id:
                station['fuel_types'] = fuel_types
                return jsonify({'message': 'Station updated successfully', 'station': station}), 200
        return jsonify({'error': 'Station not found'}), 404
    else:
        return jsonify({'error': 'Failed to update station'}), 500


@app.route('/api/prices/current', methods=['GET'])
def get_current_prices():
    """Get current fuel prices from the API."""
    if not fetcher:
        return jsonify({'error': 'Fetcher not initialized'}), 500
    
    data = fetcher.fetch_station_price_data()
    if not data:
        return jsonify({'error': 'Failed to fetch fuel prices'}), 500
    
    # Filter for configured stations
    station_ids = [s['station_id'] for s in config.stations]
    fuel_types_by_station = {
        s['station_id']: s['fuel_types'] 
        for s in config.stations
    }
    
    result = []
    for station_id in station_ids:
        station = data.stations.get(station_id)
        if not station:
            continue
        
        fuel_types = fuel_types_by_station.get(station_id, [])
        prices = {}
        
        for fuel_type in fuel_types:
            price = data.prices.get((station_id, fuel_type))
            if price is not None:
                prices[fuel_type] = price
        
        result.append({
            'station_id': station_id,
            'station_name': station.name,
            'station_address': station.address,
            'prices': prices
        })
    
    return jsonify({'prices': result})


@app.route('/api/prices/history', methods=['GET'])
def get_price_history():
    """Get historical fuel prices from InfluxDB."""
    if not config:
        return jsonify({'error': 'Configuration not loaded'}), 500
    
    # Get query parameters
    station_id = request.args.get('station_id', type=int)
    fuel_type = request.args.get('fuel_type')
    days = request.args.get('days', default=7, type=int)
    
    if not station_id or not fuel_type:
        return jsonify({'error': 'station_id and fuel_type are required'}), 400
    
    # Validate fuel_type is in allowed list to prevent injection
    if fuel_type not in ALLOWED_FUEL_TYPES:
        return jsonify({'error': 'Invalid fuel type'}), 400
    
    # Validate days is reasonable
    if days < 1 or days > 365:
        return jsonify({'error': 'days must be between 1 and 365'}), 400
    
    try:
        # Connect to InfluxDB
        client = InfluxDBClient(
            url=config.influxdb_url,
            token=config.influxdb_token,
            org=config.influxdb_org
        )
        query_api = client.query_api()
        
        # Build Flux query with proper escaping
        # Note: InfluxDB Flux doesn't support parameterized queries,
        # but we validate inputs above to prevent injection
        query = f'''
        from(bucket: "{config.influxdb_bucket}")
          |> range(start: -{days}d)
          |> filter(fn: (r) => r._measurement == "fuel_price")
          |> filter(fn: (r) => r.station_id == "{station_id}")
          |> filter(fn: (r) => r.fuel_type == "{fuel_type}")
          |> filter(fn: (r) => r._field == "price")
          |> sort(columns: ["_time"])
        '''
        
        tables = query_api.query(query)
        
        # Extract data
        history = []
        for table in tables:
            for record in table.records:
                history.append({
                    'time': record.get_time().isoformat(),
                    'price': record.get_value()
                })
        
        client.close()
        
        return jsonify({'history': history})
        
    except Exception as exc:
        _LOGGER.error("Failed to fetch price history: %s", exc)
        return jsonify({'error': 'Failed to fetch price history'}), 500


@app.route('/api/fuel-types', methods=['GET'])
def get_fuel_types():
    """Get list of allowed fuel types."""
    return jsonify({'fuel_types': ALLOWED_FUEL_TYPES})


@app.route('/api/config', methods=['GET'])
def get_config():
    """Get current configuration."""
    if not config:
        return jsonify({'error': 'Configuration not loaded'}), 500
    
    # Parse URL to hide sensitive parts
    from urllib.parse import urlparse
    parsed_url = urlparse(config.influxdb_url)
    safe_url = f"{parsed_url.scheme}://{parsed_url.hostname}"
    if parsed_url.port:
        safe_url += f":{parsed_url.port}"
    
    # Return full URL for editing in the UI
    # Note: This is intentional - users need the full URL to edit it
    # The token is masked for security
    return jsonify({
        'influxdb_url': config.influxdb_url,
        'influxdb_org': config.influxdb_org,
        'influxdb_bucket': config.influxdb_bucket,
        'influxdb_token': '***' if config.influxdb_token else '',
        'poll_interval': config.poll_interval,
        'log_level': config.log_level
    })


@app.route('/api/config', methods=['PUT'])
def update_config():
    """Update configuration settings."""
    if not config:
        return jsonify({'error': 'Configuration not loaded'}), 500
    
    data = request.get_json()
    
    # Update InfluxDB settings
    if 'influxdb_url' in data:
        config.influxdb_url = data['influxdb_url']
    
    if 'influxdb_token' in data and data['influxdb_token'] and data['influxdb_token'] != '***':
        # Only update token if it's provided and not the masked value
        config.influxdb_token = data['influxdb_token']
    
    if 'influxdb_org' in data:
        config.influxdb_org = data['influxdb_org']
    
    if 'influxdb_bucket' in data:
        config.influxdb_bucket = data['influxdb_bucket']
    
    # Update app settings
    if 'poll_interval' in data:
        try:
            poll_interval = int(data['poll_interval'])
            if poll_interval < 1:
                return jsonify({'error': 'Poll interval must be at least 1 minute'}), 400
            config.poll_interval = poll_interval
        except ValueError:
            return jsonify({'error': 'Invalid poll interval'}), 400
    
    if 'log_level' in data:
        log_level = data['log_level'].upper()
        if log_level not in ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']:
            return jsonify({'error': 'Invalid log level'}), 400
        config.log_level = log_level
    
    # Save to database
    if config.save_to_database():
        return jsonify({'message': 'Configuration updated successfully'}), 200
    else:
        return jsonify({'error': 'Failed to save configuration'}), 500


def save_config():
    """Save current configuration to database (deprecated - kept for compatibility)."""
    if not config:
        return
    
    config.save_to_database()


def run_web_app(config_obj: Config, host='0.0.0.0', port=5000, debug=False):
    """Run the Flask web application."""
    init_app(config_obj)
    app.run(host=host, port=port, debug=debug)
