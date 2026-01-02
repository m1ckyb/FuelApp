"""Flask web application for NSW Fuel Station monitoring."""

from __future__ import annotations

import json
import logging
import os
import secrets
import shutil
import subprocess
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from flask import Flask, render_template, request, jsonify, send_file
from influxdb_client import InfluxDBClient

from .config import Config, ALLOWED_FUEL_TYPES, setup_logging
from .data import FuelDataFetcher
from .mqtt import MQTTClient

_LOGGER = logging.getLogger(__name__)

app = Flask(__name__, template_folder='../templates')

# Global config instance
config: Optional[Config] = None
fetcher: Optional[FuelDataFetcher] = None


def create_app():
    """Create and configure the Flask application."""
    global config
    
    # Load configuration
    config = Config()
    
    # Try loading from default file locations
    config_path = os.getenv('CONFIG_FILE', 'config.yaml')
    config.load_from_file(config_path)
    
    # Override with environment variables
    config.load_from_env()
    
    # Setup logging
    setup_logging(config.log_level)
    _LOGGER.info("Web application logging initialized")
    
    init_app(config)
    return app


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

    # Ensure backup directory exists
    backup_dir = Path(config.data_dir) / 'backups'
    backup_dir.mkdir(parents=True, exist_ok=True)



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


@app.route('/api/stations/lookup', methods=['GET'])
def lookup_station():
    """Lookup station details and available fuel types."""
    if not fetcher:
        return jsonify({'error': 'Fetcher not initialized'}), 500
    
    station_id = request.args.get('station_id', type=int)
    if not station_id:
        return jsonify({'error': 'station_id is required'}), 400
        
    data = fetcher.fetch_station_price_data()
    if not data:
        return jsonify({'error': 'Failed to fetch data'}), 500
        
    station = data.stations.get(station_id)
    if not station:
        return jsonify({'error': 'Station not found'}), 404
        
    # Find available fuel types for this station
    available_fuel_types = []
    for (sid, fuel_type) in data.prices.keys():
        if sid == station_id:
            available_fuel_types.append(fuel_type)
            
    return jsonify({
        'station_id': station_id,
        'station_name': station.name,
        'available_fuel_types': sorted(available_fuel_types)
    })


@app.route('/api/stations', methods=['GET'])
def get_stations():
    """Get all configured stations."""
    if not config:
        return jsonify({'error': 'Configuration not loaded'}), 500
    
    # Try to fetch station details to get names
    station_names = {}
    if fetcher:
        try:
            data = fetcher.fetch_station_price_data()
            if data and data.stations:
                for s in data.stations.values():
                    station_names[s.code] = s.name
        except Exception as e:
            _LOGGER.warning("Failed to fetch station names: %s", e)
    
    # Fetch stations from DB if available to avoid stale data across workers
    stations_list = config.stations
    if config.db:
        try:
            db_stations = config.db.get_stations()
            if db_stations is not None:
                stations_list = db_stations
        except Exception as e:
            _LOGGER.error("Failed to fetch stations from DB: %s", e)

    result = []
    for station in stations_list:
        sid = station['station_id']
        result.append({
            'station_id': sid,
            'station_name': station_names.get(sid, f"Station {sid}"),
            'fuel_types': station['fuel_types']
        })
        
    return jsonify({'stations': result})


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
    
    # Fetch stations from DB if available to avoid stale data
    stations_list = config.stations
    if config.db:
        try:
            db_stations = config.db.get_stations()
            if db_stations is not None:
                stations_list = db_stations
        except Exception as e:
            _LOGGER.error("Failed to fetch stations from DB: %s", e)

    # Filter for configured stations
    station_ids = [s['station_id'] for s in stations_list]
    fuel_types_by_station = {
        s['station_id']: s['fuel_types'] 
        for s in stations_list
    }
    
    # Fetch last known prices from InfluxDB for comparison
    last_prices = {}
    if config:
        try:
            client = InfluxDBClient(
                url=config.influxdb_url,
                token=config.influxdb_token,
                org=config.influxdb_org
            )
            query_api = client.query_api()
            
            # Query for the last 50 prices to find recent price changes
            query = f'from(bucket: "{config.influxdb_bucket}")'
            query += ' |> range(start: -7d)'
            query += ' |> filter(fn: (r) => r._measurement == "fuel_price")'
            query += ' |> filter(fn: (r) => r._field == "price")'
            query += ' |> sort(columns: ["_time"], desc: true)'
            query += ' |> limit(n: 50)'
            
            tables = query_api.query(query)
            
            for table in tables:
                for record in table.records:
                    sid = record.values.get('station_id')
                    ft = record.values.get('fuel_type')
                    price = record.get_value()
                    if sid and ft:
                        # Convert sid to int if it's stored as string
                        try:
                            sid = int(sid)
                            key = (sid, ft)
                            if key not in last_prices:
                                last_prices[key] = []
                            last_prices[key].append(price)
                        except ValueError:
                            pass
            
            client.close()
        except Exception as e:
            _LOGGER.warning("Failed to fetch last prices for comparison: %s", e)

    result = []
    for station_id in station_ids:
        station = data.stations.get(station_id)
        if not station:
            continue
        
        fuel_types = fuel_types_by_station.get(station_id, [])
        prices = {}
        last_updated = {}
        trends = {}
        
        for fuel_type in fuel_types:
            price_obj = data.prices.get((station_id, fuel_type))
            if price_obj is not None:
                price_val = price_obj.price
                prices[fuel_type] = price_val
                
                if hasattr(price_obj, 'last_updated') and price_obj.last_updated:
                    last_updated[fuel_type] = price_obj.last_updated.isoformat()
                else:
                    _LOGGER.debug(f"No last_updated for {station_id} {fuel_type}")
                
                # Determine trend by finding the last price that was different
                price_history = last_prices.get((station_id, fuel_type), [])
                trend = 'unknown'
                
                if price_history:
                    # Scan history for a price different from current
                    for hist_price in price_history:
                        # Use epsilon for float comparison
                        if abs(price_val - hist_price) > 0.001:
                            if price_val > hist_price:
                                trend = 'up'
                            else:
                                trend = 'down'
                            break
                    
                    # If we went through all history and found no difference, and history exists
                    if trend == 'unknown' and price_history:
                         trend = 'stable'
                
                trends[fuel_type] = trend
        
        result.append({
            'station_id': station_id,
            'station_name': station.name,
            'station_address': station.address,
            'prices': prices,
            'last_updated': last_updated,
            'trends': trends
        })
    
    return jsonify({'prices': result})


@app.route('/api/prices/history', methods=['GET'])
def get_price_history():
    """Get historical fuel prices from InfluxDB."""
    if not config:
        return jsonify({'error': 'Configuration not loaded'}), 500
    
    # Get query parameters
    station_id = request.args.get('station_id')
    fuel_type = request.args.get('fuel_type')
    days = request.args.get('days', default=7, type=int)
    
    # Validate fuel_type if provided
    if fuel_type and fuel_type not in ALLOWED_FUEL_TYPES:
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
        
        # Build Flux query
        # Start with base query
        query = f'from(bucket: "{config.influxdb_bucket}") |> range(start: -{days}d)'
        query += ' |> filter(fn: (r) => r._measurement == "fuel_price")'
        
        if station_id:
            query += f' |> filter(fn: (r) => r.station_id == "{station_id}")'
        
        if fuel_type:
            query += f' |> filter(fn: (r) => r.fuel_type == "{fuel_type}")'
            
        query += ' |> filter(fn: (r) => r._field == "price")'
        query += ' |> sort(columns: ["_time"])'
        
        tables = query_api.query(query)
        
        # Extract data
        history = []
        for table in tables:
            for record in table.records:
                history.append({
                    'time': record.get_time().isoformat(),
                    'price': record.get_value(),
                    'station_id': record.values.get('station_id'),
                    'fuel_type': record.values.get('fuel_type')
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
        'mqtt_broker': config.mqtt_broker,
        'mqtt_port': config.mqtt_port,
        'mqtt_user': config.mqtt_user,
        'mqtt_password': '***' if config.mqtt_password else '',
        'mqtt_discovery_prefix': config.mqtt_discovery_prefix,
        'poll_interval': config.poll_interval,
        'cron_schedule': config.cron_schedule,
        'timezone': config.timezone,
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
        
    # Update MQTT settings
    if 'mqtt_broker' in data:
        config.mqtt_broker = data['mqtt_broker']
    
    if 'mqtt_port' in data:
        try:
            config.mqtt_port = int(data['mqtt_port'])
        except (ValueError, TypeError):
            return jsonify({'error': 'Invalid MQTT port'}), 400
            
    if 'mqtt_user' in data:
        config.mqtt_user = data['mqtt_user']
        
    if 'mqtt_password' in data and data['mqtt_password'] and data['mqtt_password'] != '***':
        config.mqtt_password = data['mqtt_password']
        
    if 'mqtt_discovery_prefix' in data:
        config.mqtt_discovery_prefix = data['mqtt_discovery_prefix']
    
    # Update app settings
    if 'poll_interval' in data:
        try:
            poll_interval = int(data['poll_interval'])
            if poll_interval < 1:
                return jsonify({'error': 'Poll interval must be at least 1 minute'}), 400
            config.poll_interval = poll_interval
        except ValueError:
            return jsonify({'error': 'Invalid poll interval'}), 400
            
    if 'cron_schedule' in data:
        config.cron_schedule = data['cron_schedule']
        
    if 'timezone' in data:
        config.timezone = data['timezone']
    
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


@app.route('/api/config/mqtt/test', methods=['POST'])
def test_mqtt_config():
    """Test MQTT configuration."""
    data = request.get_json()
    
    broker = data.get('mqtt_broker')
    port = data.get('mqtt_port', 1883)
    user = data.get('mqtt_user')
    password = data.get('mqtt_password')
    
    # Fallback to stored password if not provided and user matches (or is new)
    # This handles the "leave blank to keep current" UI logic
    if not password and config and config.mqtt_password:
        password = config.mqtt_password

    if not broker:
        return jsonify({'error': 'Broker address is required'}), 400
        
    try:
        port = int(port)
    except (ValueError, TypeError):
        return jsonify({'error': 'Invalid port'}), 400
        
    success, message = MQTTClient.test_connection(broker, port, user, password)
    
    if success:
        return jsonify({'message': message}), 200
    else:
        return jsonify({'error': message}), 400


def ha_slugify(text):
    """Slugify a string for Home Assistant (lowercase, underscores)."""
    import re
    text = text.lower()
    text = re.sub(r'[^a-z0-9\s_]', '', text)
    text = re.sub(r'\s+', '_', text)
    return text

@app.route('/api/ha/generate-card', methods=['POST'])
def generate_ha_card():
    """Generate Home Assistant Lovelace card configuration."""
    if not config:
        return jsonify({'error': 'Configuration not loaded'}), 500
        
    data = request.get_json()
    fuel_type = data.get('fuel_type', 'P98')
    
    # Get all stations that support this fuel type
    stations_list = config.stations
    if config.db:
        try:
            db_stations = config.db.get_stations()
            if db_stations is not None:
                stations_list = db_stations
        except Exception as e:
            _LOGGER.error("Failed to fetch stations from DB: %s", e)
            
    # Try to fetch station details to get names
    station_names = {}
    if fetcher:
        try:
            station_data = fetcher.fetch_station_price_data()
            if station_data and station_data.stations:
                for s in station_data.stations.values():
                    station_names[s.code] = s.name
        except Exception as e:
            _LOGGER.warning("Failed to fetch station names: %s", e)

    # Build list of entities for this fuel type
    entities = []
    for station in stations_list:
        if fuel_type in station['fuel_types']:
            sid = station['station_id']
            name = station_names.get(sid, f"Station {sid}")
            
            # Construct entity ID based on HA discovery logic
            # "fuelapp/sensor/{station_id}/{fuel_type}/state"
            # Discovery name: "{fuel_type} Price"
            # Device name: "{Station Name}"
            # HA defaults to: sensor.{device_name}_{entity_name}
            
            device_slug = ha_slugify(name)
            fuel_slug = ha_slugify(fuel_type)
            entity_id = f"sensor.{device_slug}_{fuel_slug}_price"
            
            entities.append(entity_id)

    # If no entities found, return error
    if not entities:
        return jsonify({'error': f'No stations found with fuel type {fuel_type}'}), 404
        
    # Generate the YAML content
    fuel_slug = ha_slugify(fuel_type)
    
    # Create the prices list string for the template
    # states('sensor.coles_express_bowral_p98') | float(0),
    prices_list_str = ",\n                ".join([f"states('{e}') | float(0)" for e in entities])
    
    yaml_content = f"""type: custom:vertical-stack-in-card
cards:
  - type: custom:mushroom-title-card
    title: ⛽ {fuel_type} Fuel Prices
    alignment: center
    card_mod:
      style: |
        ha-card {{
          font-size: 18px;
          font-weight: bold;
        }}
  - type: custom:auto-entities
    card:
      type: grid
      columns: 1
      square: false
    card_param: cards
    sort:
      method: state
      numeric: true
      reverse: false
    filter:
      include:
        - entity_id: sensor.*_{fuel_slug}_price
          options:
            type: custom:mushroom-template-card
            icon: mdi:fuel
            primary: >-
              {{% set name = state_attr(entity, 'friendly_name') %}} {{% if name is
              not none %}}
                {{{{ name | replace(' {fuel_type} Price', '') }}}}
              {{% else %}}
                {{{{ entity }}}}
              {{% endif %}}
            secondary: "{{{{ states(entity) }}}} ¢/L"
            icon_color: |
              {{% set prices = [
                {prices_list_str}
              ] | select('>', 0) | list | sort %}}
              {{% set value = states(entity) | float(0) %}}
              {{% if prices | length > 0 and value > 0 %}}
                {{% if value == prices[0] %}} green
                {{% elif prices | length > 1 and value == prices[1] %}} darkgreen
                {{% elif value == prices[-1] %}} red
                {{% elif prices | length > 1 and value == prices[-2] %}} lightcoral
                {{% else %}} orange
                {{% endif %}}
              {{% else %}}
                grey
              {{% endif %}}
    exclude: []
    show_empty: true"""
    
    return jsonify({'yaml': yaml_content})


@app.route('/api/backup', methods=['POST'])
def create_backup():
    """Create a backup of InfluxDB data."""
    if not config:
        return jsonify({'error': 'Configuration not loaded'}), 500
    
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = Path(config.data_dir) / 'backups' / timestamp
        backup_dir.mkdir(parents=True, exist_ok=True)
        
        # Run influx backup command
        # Note: Requires influx CLI to be installed in the container
        cmd = [
            "influx", "backup",
            str(backup_dir),
            "--host", config.influxdb_url,
            "--token", config.influxdb_token,
            "--org", config.influxdb_org,
            "--bucket", config.influxdb_bucket
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            _LOGGER.error("Backup failed: %s", result.stderr)
            return jsonify({'error': f'Backup failed: {result.stderr}'}), 500
            
        # Create zip file
        zip_path = Path(config.data_dir) / 'backups' / f"backup_{timestamp}.zip"
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(backup_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, backup_dir)
                    zipf.write(file_path, arcname)
                    
        # Clean up directory
        shutil.rmtree(backup_dir)
        
        return send_file(
            zip_path,
            as_attachment=True,
            download_name=f"fuelapp_backup_{timestamp}.zip",
            mimetype='application/zip'
        )
        
    except Exception as exc:
        _LOGGER.error("Backup exception: %s", exc)
        return jsonify({'error': str(exc)}), 500


@app.route('/api/restore', methods=['POST'])
def restore_backup():
    """Restore InfluxDB data from a backup zip file."""
    if not config:
        return jsonify({'error': 'Configuration not loaded'}), 500
    
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
        
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
        
    if not file.filename.endswith('.zip'):
        return jsonify({'error': 'File must be a .zip archive'}), 400

    temp_dir = Path(config.data_dir) / 'restore_temp'
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True)
    
    try:
        # Save and extract zip
        zip_path = temp_dir / 'restore.zip'
        file.save(zip_path)
        
        with zipfile.ZipFile(zip_path, 'r') as zipf:
            zipf.extractall(temp_dir)
            
        # Run influx restore command
        # Note: Restore usually requires writing to a new bucket if the old one exists
        # or using --full to replace everything (dangerous). 
        # Here we'll try to restore to the configured bucket. 
        # If it fails due to existing data, we might need a different approach.
        # But 'influx restore' creates new buckets if they don't exist.
        # If the bucket exists, it might conflict. 
        
        # Basic restore command
        cmd = [
            "influx", "restore",
            str(temp_dir),
            "--host", config.influxdb_url,
            "--token", config.influxdb_token,
            "--full" # Trying full restore for now, implies admin token usage
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            # If full restore fails, try specific bucket restore? 
            # But backup format is specific.
            _LOGGER.error("Restore failed: %s", result.stderr)
            return jsonify({'error': f'Restore failed: {result.stderr}'}), 500
            
        return jsonify({'message': 'Restore completed successfully'}), 200
        
    except Exception as exc:
        _LOGGER.error("Restore exception: %s", exc)
        return jsonify({'error': str(exc)}), 500
    finally:
        # Cleanup
        if temp_dir.exists():
            shutil.rmtree(temp_dir)


def save_config():
    """Save current configuration to database (deprecated - kept for compatibility)."""
    if not config:
        return
    
    config.save_to_database()


def run_web_app(config_obj: Config, host='0.0.0.0', port=5000, debug=False):
    """Run the Flask web application."""
    init_app(config_obj)
    app.run(host=host, port=port, debug=debug)
