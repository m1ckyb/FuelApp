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
# Generate a random secret key if not provided via environment
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', secrets.token_hex(32))

# Global config instance
config: Optional[Config] = None
fetcher: Optional[FuelDataFetcher] = None


def init_app(config_obj: Config):
    """Initialize the Flask app with configuration."""
    global config, fetcher
    config = config_obj
    fetcher = FuelDataFetcher()


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
    
    # Add station
    new_station = {
        'station_id': station_id,
        'fuel_types': fuel_types
    }
    config.stations.append(new_station)
    
    # Save to config file
    save_config()
    
    return jsonify({'message': 'Station added successfully', 'station': new_station}), 201


@app.route('/api/stations/<int:station_id>', methods=['DELETE'])
def delete_station(station_id):
    """Delete a station from configuration."""
    if not config:
        return jsonify({'error': 'Configuration not loaded'}), 500
    
    # Find and remove station
    config.stations = [s for s in config.stations if s['station_id'] != station_id]
    
    # Save to config file
    save_config()
    
    return jsonify({'message': 'Station deleted successfully'}), 200


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
    
    # Find and update station
    for station in config.stations:
        if station['station_id'] == station_id:
            station['fuel_types'] = fuel_types
            save_config()
            return jsonify({'message': 'Station updated successfully', 'station': station}), 200
    
    return jsonify({'error': 'Station not found'}), 404


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
        return jsonify({'error': str(exc)}), 500


@app.route('/api/fuel-types', methods=['GET'])
def get_fuel_types():
    """Get list of allowed fuel types."""
    return jsonify({'fuel_types': ALLOWED_FUEL_TYPES})


@app.route('/api/config', methods=['GET'])
def get_config():
    """Get current configuration."""
    if not config:
        return jsonify({'error': 'Configuration not loaded'}), 500
    
    return jsonify({
        'influxdb_url': config.influxdb_url,
        'influxdb_org': config.influxdb_org,
        'influxdb_bucket': config.influxdb_bucket,
        'poll_interval': config.poll_interval,
        'log_level': config.log_level
    })


def save_config():
    """Save current configuration to file."""
    if not config:
        return
    
    config_data = {
        'influxdb': {
            'url': config.influxdb_url,
            'token': config.influxdb_token,
            'org': config.influxdb_org,
            'bucket': config.influxdb_bucket
        },
        'stations': config.stations,
        'poll_interval': config.poll_interval,
        'log_level': config.log_level
    }
    
    config_file = Path('config.yaml')
    with open(config_file, 'w') as f:
        yaml.dump(config_data, f, default_flow_style=False, sort_keys=False)
    
    _LOGGER.info("Configuration saved to config.yaml")


def run_web_app(config_obj: Config, host='0.0.0.0', port=5000, debug=False):
    """Run the Flask web application."""
    init_app(config_obj)
    app.run(host=host, port=port, debug=debug)
