"""Flask web application for NSW Fuel Station monitoring."""

from __future__ import annotations

import json
import logging
import os
import secrets
import shutil
import subprocess
import tempfile
import zipfile
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter

from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for, session
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.middleware.proxy_fix import ProxyFix
from influxdb_client import InfluxDBClient
from werkzeug.security import generate_password_hash, check_password_hash
import webauthn
from webauthn import (
    generate_registration_options,
    verify_registration_response,
    generate_authentication_options,
    verify_authentication_response,
    options_to_json,
    base64url_to_bytes,
)
from webauthn.helpers import (
    bytes_to_base64url,
)
from webauthn.helpers.structs import (
    AuthenticatorAttachment,
    AuthenticatorSelectionCriteria,
    ResidentKeyRequirement,
    UserVerificationRequirement,
    RegistrationCredential,
    AuthenticationCredential,
)

from .config import Config, ALLOWED_FUEL_TYPES, setup_logging
from .data import FuelDataFetcher
from .mqtt import MQTTClient
from .notifications import DiscordClient, is_valid_discord_webhook_url

_LOGGER = logging.getLogger(__name__)


def _is_valid_http_url(url: str) -> bool:
    """Validate that a URL uses http/https and cannot be misinterpreted as a CLI flag."""
    if not url or not isinstance(url, str):
        return False
    stripped = url.strip()
    if stripped.startswith('-'):
        return False
    try:
        parsed = urlparse(stripped)
        return parsed.scheme in ('http', 'https') and bool(parsed.netloc)
    except Exception:
        return False


def _check_rate_limit(key: str, max_attempts: int = 5, window_seconds: int = 60) -> bool:
    """Check if a rate limit has been exceeded. Returns True if allowed."""
    if config and config.db:
        return config.db.check_rate_limit(key, max_attempts, window_seconds)
    return True


from flask_wtf.csrf import CSRFProtect

app = Flask(__name__, template_folder='../templates')
csrf = CSRFProtect(app)
login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.login_message_category = "info"


# Global config instance
config: Optional[Config] = None
fetcher: Optional[FuelDataFetcher] = None

class User(UserMixin):
    """User class for Flask-Login."""
    def __init__(self, user_id, username):
        self.id = user_id
        self.username = username

@login_manager.user_loader
def load_user(user_id):
    """Load user by ID."""
    if not config or not config.db:
        return None
    user_data = config.db.get_user(int(user_id))
    if user_data:
        return User(user_data['id'], user_data['username'])
    return None


@login_manager.unauthorized_handler
def unauthorized():
    """Handle unauthorized requests."""
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Unauthorized'}), 401
    return redirect(url_for('login'))


@app.errorhandler(500)
def handle_500(error):
    """Handle 500 errors with JSON for API requests."""
    _LOGGER.exception("Unhandled Exception")
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Internal Server Error'}), 500
    return "Internal Server Error", 500


@app.after_request
def add_headers(response):
    """Add security and cache-control headers to all responses."""
    # Security headers
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    # Cache control for API endpoints
    if request.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response


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
    
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
    login_manager.init_app(app)
    init_app(config)
    return app


def init_app(config_obj: Config):
    """Initialize the Flask app with configuration."""
    global config, fetcher
    config = config_obj
    fetcher = FuelDataFetcher(
        client_id=config.fuel_api_client_id,
        client_secret=config.fuel_api_client_secret
    )

    # Set timezone for the process
    if config.timezone:
        os.environ['TZ'] = config.timezone
        if hasattr(time, 'tzset'):
            time.tzset()
        _LOGGER.info("Web app timezone set to %s", config.timezone)

    # Configure secret key from data_dir
    secret_key = os.environ.get('FLASK_SECRET_KEY')
    if not secret_key:
        secret_file = Path(config.data_dir) / '.flask_secret'
        try:
            import fcntl
            # Open or create the file with lock
            with open(secret_file, 'a+') as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                f.seek(0)
                content = f.read().strip()
                if content:
                    secret_key = content
                else:
                    secret_key = secrets.token_hex(32)
                    f.write(secret_key)
                    try:
                        os.chmod(secret_file, 0o600)
                    except Exception:
                        pass
        except Exception as e:
            _LOGGER.warning("Error with file locking for Flask secret: %s. Using fallback.", e)
            if secret_file.exists():
                try:
                    with open(secret_file, 'r') as f:
                        secret_key = f.read().strip()
                except Exception:
                    pass
            if not secret_key:
                secret_key = secrets.token_hex(32)
    app.config['SECRET_KEY'] = secret_key
    app.config['SESSION_COOKIE_SAMESITE'] = 'Strict'
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    if os.environ.get('FORCE_HTTPS') or os.environ.get('REVERSE_PROXY'):
        app.config['SESSION_COOKIE_SECURE'] = True

    # Ensure backup directory exists
    backup_dir = Path(config.data_dir) / 'backups'
    backup_dir.mkdir(parents=True, exist_ok=True)


def refresh_config_and_fetcher():
    """Reload configuration from database and update fetcher credentials."""
    global config, fetcher
    if config and config.db:
        try:
            config.load_from_database()
            if fetcher:
                fetcher.client_id = config.fuel_api_client_id
                fetcher.client_secret = config.fuel_api_client_secret
        except Exception as e:
            _LOGGER.error("Failed to refresh configuration: %s", e)
    return config, fetcher


@app.before_request
def check_auth():
    """Check if the user is authenticated or if setup is required."""
    if request.endpoint == 'healthz':
        return

    if not config or not config.auth_enabled:
        return
    
    # Check if we have any users. If not, redirect to setup
    if config.db and config.db.get_user_count() == 0:
        if request.endpoint not in ('setup', 'static', 'healthz'):
            return redirect(url_for('setup'))
        return

    # Normal auth check
    if not current_user.is_authenticated:
        allowed_endpoints = (
            'login', 
            'setup', 
            'static',
            'healthz',
            'webauthn_login_begin', 
            'webauthn_login_complete'
        )
        if request.endpoint not in allowed_endpoints:
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Unauthorized'}), 401
            return redirect(url_for('login'))


@app.route('/healthz', methods=['GET'])
def healthz():
    """Lightweight health check endpoint for container liveness/readiness probes."""
    try:
        if config and config.db:
            config.db.get_user_count()
            return jsonify({'status': 'ok'}), 200
        return jsonify({'status': 'degraded'}), 503
    except Exception:
        return jsonify({'status': 'error'}), 503


@app.route('/setup', methods=['GET', 'POST'])
def setup():
    """First-run setup to create an admin user."""
    if not config or not config.db:
        return "Database not initialized", 500
        
    if config.db.get_user_count() > 0:
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        # Rate limit setup attempts by IP
        ip = request.remote_addr or 'unknown'
        if not _check_rate_limit(f'setup:ip:{ip}', max_attempts=3, window_seconds=300):
            return render_template('setup.html', error="Too many setup attempts. Please try again later.")
        
        username = request.form.get('username')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        if not username or not password:
            return render_template('setup.html', error="Username and password are required")
            
        if password != confirm_password:
            return render_template('setup.html', error="Passwords do not match")
            
        if len(password) < 8:
            return render_template('setup.html', error="Password must be at least 8 characters long")
            
        password_hash = generate_password_hash(password)
        user_id = config.db.create_first_user(username, password_hash)
        
        if user_id:
            user = User(user_id, username)
            session.clear()
            login_user(user)
            return redirect(url_for('index'))
        else:
            if config.db.get_user_count() > 0:
                return redirect(url_for('login'))
            return render_template('setup.html', error="Failed to create user")
            
    return render_template('setup.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login page."""
    if current_user.is_authenticated:
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        username = request.form.get('username', '')
        
        # Rate limit by username AND IP
        ip = request.remote_addr or 'unknown'
        if not _check_rate_limit(f'login:{ip}:{username}', max_attempts=5, window_seconds=60):
            return render_template('login.html', error="Too many login attempts. Please try again later.")
        if not _check_rate_limit(f'login:ip:{ip}', max_attempts=20, window_seconds=60):
            return render_template('login.html', error="Too many login attempts. Please try again later.")
        
        password = request.form.get('password')
        
        user_data = config.db.get_user_by_username(username)
        if user_data and check_password_hash(user_data['password_hash'], password):
            user = User(user_data['id'], user_data['username'])
            session.clear()
            login_user(user, remember=True)
            return redirect(url_for('index'))
            
        return render_template('login.html', error="Invalid username or password")
        
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    """Logout the current user."""
    logout_user()
    return redirect(url_for('login'))


# --- WebAuthn / Passkey Routes ---

@app.route('/api/webauthn/register/begin', methods=['POST'])
@login_required
def webauthn_register_begin():
    """Start WebAuthn registration process."""
    if not config or not config.db:
        return jsonify({'error': 'Database not initialized'}), 500
        
    user = current_user
    
    # Get existing credentials to avoid re-registration
    existing_credentials = config.db.get_credentials_by_user(user.id)
    exclude_credentials = []
    for cred in existing_credentials:
        exclude_credentials.append({
            "id": cred['credential_id'],
            "type": "public-key",
        })
        
    registration_options = generate_registration_options(
        rp_id=config.webauthn_rp_id,
        rp_name=config.webauthn_rp_name,
        user_id=str(user.id).encode(),
        user_name=user.username,
        exclude_credentials=exclude_credentials,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
    )
    
    # Store options in session for verification
    session['registration_options'] = options_to_json(registration_options)
    
    return app.response_class(session['registration_options'], mimetype='application/json')


@app.route('/api/webauthn/register/complete', methods=['POST'])
@login_required
def webauthn_register_complete():
    """Complete WebAuthn registration process."""
    if not config or not config.db:
        return jsonify({'error': 'Database not initialized'}), 500
        
    options_json = session.pop('registration_options', None)
    if not options_json:
        return jsonify({'error': 'Registration session expired'}), 400
        
    credential_data = request.get_json(silent=True)
    if not isinstance(credential_data, dict):
        return jsonify({'error': 'Invalid JSON payload'}), 400

    try:
        registration_verification = verify_registration_response(
            credential=credential_data,
            expected_origin=request.host_url.rstrip('/'),
            expected_rp_id=config.webauthn_rp_id,
            expected_challenge=base64url_to_bytes(json.loads(options_json)['challenge']),
        )
    except Exception as exc:
        _LOGGER.warning("WebAuthn registration verification failed: %s", exc)
        return jsonify({'error': 'Passkey verification failed'}), 400
    
    # Save credential to database
    success = config.db.add_credential(
        user_id=current_user.id,
        credential_id=registration_verification.credential_id,
        public_key=registration_verification.credential_public_key,
        sign_count=registration_verification.sign_count,
        transports=json.dumps(credential_data.get('response', {}).get('transports', []))
    )
    
    if success:
        return jsonify({'message': 'Passkey registered successfully'}), 200
    else:
        return jsonify({'error': 'Failed to save credential'}), 500


@app.route('/api/webauthn/login/begin', methods=['POST'])
def webauthn_login_begin():
    """Start WebAuthn login process."""
    # Rate limit by IP
    ip = request.remote_addr or 'unknown'
    if not _check_rate_limit(f'webauthn_begin:ip:{ip}', max_attempts=10, window_seconds=60):
        return jsonify({'error': 'Too many requests. Please try again later.'}), 429
        
    if not config or not config.db:
        return jsonify({'error': 'Database not initialized'}), 500
        
    # We can do "discoverable credentials" (resident keys) if we don't know the username yet
    # Or we can ask for username first. Let's try discoverable credentials first.
    
    authentication_options = generate_authentication_options(
        rp_id=config.webauthn_rp_id,
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    
    session['authentication_options'] = options_to_json(authentication_options)
    
    return app.response_class(session['authentication_options'], mimetype='application/json')


@app.route('/api/webauthn/login/complete', methods=['POST'])
def webauthn_login_complete():
    """Complete WebAuthn login process."""
    ip = request.remote_addr or 'unknown'
    if not _check_rate_limit(f'webauthn_complete:ip:{ip}', max_attempts=10, window_seconds=60):
        return jsonify({'error': 'Too many requests. Please try again later.'}), 429

    if not config or not config.db:
        return jsonify({'error': 'Database not initialized'}), 500
        
    options_json = session.pop('authentication_options', None)
    if not options_json:
        return jsonify({'error': 'Login session expired'}), 400
        
    credential_dict = request.get_json(silent=True)
    if not isinstance(credential_dict, dict) or not credential_dict.get('id'):
        return jsonify({'error': 'Invalid credential payload'}), 400

    try:
        credential_id_bin = base64url_to_bytes(credential_dict.get('id'))
    except Exception:
        return jsonify({'error': 'Invalid credential ID'}), 400
    
    # Find credential in database
    db_credential = config.db.get_credential_by_id(credential_id_bin)
    if not db_credential:
        _LOGGER.warning("WebAuthn credential not found")
        return jsonify({'error': 'Credential not found'}), 404
        
    try:
        authentication_verification = verify_authentication_response(
            credential=credential_dict,
            expected_origin=request.host_url.rstrip('/'),
            expected_rp_id=config.webauthn_rp_id,
            expected_challenge=base64url_to_bytes(json.loads(options_json)['challenge']),
            credential_public_key=db_credential['public_key'],
            credential_current_sign_count=db_credential['sign_count'],
        )
    except Exception as exc:
        _LOGGER.warning("WebAuthn authentication verification failed: %s", exc)
        return jsonify({'error': 'Authentication verification failed'}), 401
    
    # Update sign count
    config.db.update_credential_sign_count(
        credential_id=db_credential['credential_id'],
        sign_count=authentication_verification.new_sign_count
    )
    
    # Login user (clear session first to prevent session fixation)
    user_data = config.db.get_user(db_credential['user_id'])
    if user_data:
        user = User(user_data['id'], user_data['username'])
        session.clear()
        login_user(user, remember=True)
        return jsonify({'message': 'Logged in successfully'}), 200
        
    return jsonify({'error': 'User not found'}), 404


@app.route('/api/webauthn/credentials', methods=['GET'])
@login_required
def webauthn_credentials():
    """Get list of registered WebAuthn credentials for current user."""
    if not config or not config.db:
        return jsonify({'error': 'Database not initialized'}), 500
        
    credentials = config.db.get_credentials_by_user(current_user.id)
    # Convert binary credential_id to hex for easier transport
    result = []
    for cred in credentials:
        result.append({
            'id': cred['credential_id'].hex(),
            'sign_count': cred['sign_count'],
            'transports': json.loads(cred['transports']) if cred['transports'] else []
        })
    return jsonify({'credentials': result})


@app.route('/api/webauthn/credentials/<string:credential_id_hex>', methods=['DELETE'])
@login_required
def webauthn_delete_credential(credential_id_hex):
    """Delete a WebAuthn credential."""
    if not config or not config.db:
        return jsonify({'error': 'Database not initialized'}), 500
        
    success = config.db.delete_credential(credential_id_hex, current_user.id)
    if success:
        return jsonify({'message': 'Credential deleted successfully'}), 200
    else:
        return jsonify({'error': 'Failed to delete credential'}), 500


@app.route('/api/config/password', methods=['PUT'])
@login_required
def update_password():
    """Update user password."""
    if not config or not config.db:
        return jsonify({'error': 'Database not initialized'}), 500
        
    data = request.get_json(silent=True) or {}
    current_password = data.get('current_password')
    new_password = data.get('new_password')
    
    if not current_password or not new_password:
        return jsonify({'error': 'Missing password data'}), 400
        
    if len(new_password) < 8:
        return jsonify({'error': 'Password must be at least 8 characters long'}), 400
        
    user_data = config.db.get_user(current_user.id)
    if not user_data or not check_password_hash(user_data['password_hash'], current_password):
        return jsonify({'error': 'Invalid current password'}), 401
        
    password_hash = generate_password_hash(new_password)
    if config.db.update_password(current_user.id, password_hash):
        return jsonify({'message': 'Password updated successfully'}), 200
    else:
        return jsonify({'error': 'Failed to update password'}), 500


@app.route('/')
def index():
    """Dashboard page."""
    return render_template('dashboard.html')


@app.route('/stations')
def stations():
    """Stations management page."""
    return render_template('stations.html')


@app.route('/alerts')
def alerts_page():
    """Price alerts management page."""
    return render_template('alerts.html')


@app.route('/settings')
def settings():
    """Settings page."""
    return render_template('settings.html')


@app.route('/api/stations/lookup', methods=['GET'])
@login_required
def lookup_station():
    """Lookup station details and available fuel types."""
    cfg, ftr = refresh_config_and_fetcher()
    if not ftr:
        return jsonify({'error': 'Fetcher not initialized'}), 500
    
    station_id = request.args.get('station_id', type=int)
    if not station_id:
        return jsonify({'error': 'station_id is required'}), 400
        
    # For lookup, we try to fetch all stations (NSW and TAS) to find the ID
    data = ftr.fetch_station_price_data([
        {'station_id': station_id, 'au_state': 'NSW'},
        {'station_id': station_id, 'au_state': 'TAS'}
    ])
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
        'au_state': station.au_state,
        'station_name': station.name,
        'available_fuel_types': sorted(available_fuel_types)
    })


@app.route('/api/stations', methods=['GET'])
@login_required
def get_stations():
    """Get all configured stations directly from SQLite (no blocking live API fetch)."""
    cfg, _ = refresh_config_and_fetcher()
    if not cfg:
        return jsonify({'error': 'Configuration not loaded'}), 500
    
    stations_list = cfg.stations
    if cfg.db:
        try:
            db_stations = cfg.db.get_stations()
            if db_stations is not None:
                stations_list = db_stations
        except Exception as e:
            _LOGGER.error("Failed to fetch stations from DB: %s", e)

    result = []
    for station in stations_list:
        sid = station['station_id']
        result.append({
            'station_id': sid,
            'au_state': station.get('au_state', 'NSW'),
            'station_name': station.get('station_name') or f"Station {sid}",
            'fuel_types': station['fuel_types'],
            'discount': station.get('discount', 0.0)
        })
        
    return jsonify({'stations': result})


@app.route('/api/stations', methods=['POST'])
@login_required
def add_station():
    """Add a new station to configuration."""
    if not config or not config.db:
        return jsonify({'error': 'Configuration not loaded'}), 500
    
    data = request.get_json(silent=True) or {}
    try:
        station_id = int(data.get('station_id'))
    except (ValueError, TypeError):
        return jsonify({'error': 'Valid positive station_id is required'}), 400

    if station_id <= 0:
        return jsonify({'error': 'station_id must be a positive integer'}), 400

    fuel_types = data.get('fuel_types', [])
    au_state = str(data.get('au_state', 'NSW')).upper()
    station_name = str(data.get('station_name', '') or '').strip()

    if au_state not in ('NSW', 'TAS'):
        return jsonify({'error': 'au_state must be NSW or TAS'}), 400

    try:
        discount = float(data.get('discount', 0.0))
        if discount < 0:
            return jsonify({'error': 'discount cannot be negative'}), 400
    except (ValueError, TypeError):
        return jsonify({'error': 'Invalid discount value'}), 400
    
    if not isinstance(fuel_types, list) or not fuel_types:
        return jsonify({'error': 'At least one fuel type is required'}), 400
    
    invalid_types = [ft for ft in fuel_types if ft not in ALLOWED_FUEL_TYPES]
    if invalid_types:
        return jsonify({'error': f'Invalid fuel types: {invalid_types}'}), 400
    
    stations_list = config.db.get_stations()
    for station in stations_list:
        if station['station_id'] == station_id:
            return jsonify({'error': 'Station already exists'}), 400
    
    if config.db.add_station(station_id, fuel_types, au_state, discount, station_name=station_name):
        new_station = {
            'station_id': station_id,
            'au_state': au_state,
            'station_name': station_name or f"Station {station_id}",
            'fuel_types': fuel_types,
            'discount': discount
        }
        return jsonify({'message': 'Station added successfully', 'station': new_station}), 201
    else:
        return jsonify({'error': 'Failed to add station'}), 500


@app.route('/api/stations/<int:station_id>', methods=['DELETE'])
@login_required
def delete_station(station_id):
    """Delete a station from configuration."""
    if not config or not config.db:
        return jsonify({'error': 'Configuration not loaded'}), 500
    
    if config.db.delete_station(station_id):
        return jsonify({'message': 'Station deleted successfully'}), 200
    else:
        return jsonify({'error': 'Station not found'}), 404


@app.route('/api/stations/<int:station_id>', methods=['PUT'])
@login_required
def update_station(station_id):
    """Update a station configuration."""
    if not config or not config.db:
        return jsonify({'error': 'Configuration not loaded'}), 500
    
    data = request.get_json(silent=True) or {}
    fuel_types = data.get('fuel_types', [])
    au_state = str(data.get('au_state', 'NSW')).upper()
    station_name = data.get('station_name')

    if au_state not in ('NSW', 'TAS'):
        return jsonify({'error': 'au_state must be NSW or TAS'}), 400

    try:
        discount = float(data.get('discount', 0.0))
        if discount < 0:
            return jsonify({'error': 'discount cannot be negative'}), 400
    except (ValueError, TypeError):
        return jsonify({'error': 'Invalid discount value'}), 400
    
    if not isinstance(fuel_types, list) or not fuel_types:
        return jsonify({'error': 'At least one fuel type is required'}), 400
    
    invalid_types = [ft for ft in fuel_types if ft not in ALLOWED_FUEL_TYPES]
    if invalid_types:
        return jsonify({'error': f'Invalid fuel types: {invalid_types}'}), 400
    
    if config.db.update_station(station_id, fuel_types, au_state, discount, station_name=station_name):
        updated = {
            'station_id': station_id,
            'au_state': au_state,
            'fuel_types': fuel_types,
            'discount': discount,
        }
        return jsonify({'message': 'Station updated successfully', 'station': updated}), 200
    else:
        return jsonify({'error': 'Station not found'}), 404


@app.route('/api/prices/current', methods=['GET'])
@login_required
def get_current_prices():
    """Get current fuel prices from the API."""
    cfg, ftr = refresh_config_and_fetcher()
    if not ftr:
        return jsonify({'error': 'Fetcher not initialized'}), 500
    
    # Fetch stations from DB if available to avoid stale data
    stations_list = cfg.stations
    if cfg.db:
        try:
            db_stations = cfg.db.get_stations()
            if db_stations is not None:
                stations_list = db_stations
        except Exception as e:
            _LOGGER.error("Failed to fetch stations from DB: %s", e)

    # Decouple web UI from live API by reading current prices from InfluxDB first
    class MockStation:
        def __init__(self, code, name, address, au_state='NSW'):
            self.code = code
            self.name = name
            self.address = address
            self.au_state = au_state

    class MockPrice:
        def __init__(self, station_code, fuel_type, price, last_updated):
            self.station_code = station_code
            self.fuel_type = fuel_type
            self.price = price
            self.last_updated = last_updated

    class MockStationPriceData:
        def __init__(self):
            self.stations = {}
            self.prices = {}

    data = MockStationPriceData()
    discounts_by_station = {
        s['station_id']: s.get('discount', 0.0)
        for s in stations_list
    }
    last_prices = {}

    if cfg:
        try:
            with InfluxDBClient(
                url=cfg.influxdb_url,
                token=cfg.influxdb_token,
                org=cfg.influxdb_org
            ) as client:
                query_api = client.query_api()
                
                # Single 30-day query sorted desc (limit 50 per series) provides both
                # the latest price and historical prices for trend comparison.
                query = f'from(bucket: "{cfg.influxdb_bucket}")'
                query += ' |> range(start: -30d)'
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
                        sname = record.values.get('station_name') or f"Station {sid}"
                        saddr = record.values.get('station_address') or ""
                        
                        if sid and ft:
                            try:
                                sid = int(sid)
                                key = (sid, ft)
                                if key not in last_prices:
                                    last_prices[key] = []
                                    if sid not in data.stations:
                                        au_state = 'NSW'
                                        for s in stations_list:
                                            if s['station_id'] == sid:
                                                au_state = s.get('au_state', 'NSW')
                                                break
                                        data.stations[sid] = MockStation(sid, sname, saddr, au_state)
                                    # InfluxDB stores discounted price; reconstruct raw price for downstream
                                    discount = discounts_by_station.get(sid, 0.0)
                                    raw_price = price + discount
                                    data.prices[key] = MockPrice(sid, ft, raw_price, record.get_time())
                                last_prices[key].append(price)
                            except ValueError:
                                pass
        except Exception as e:
            _LOGGER.error("Failed to query InfluxDB for current prices: %s", e)

    # Fallback to live API only if InfluxDB has no cached data (e.g. fresh installation)
    if not data.prices:
        _LOGGER.warning("No price data in InfluxDB, falling back to live API fetch")
        data = ftr.fetch_station_price_data(stations_list)
        if not data:
            return jsonify({'error': 'Failed to fetch fuel prices'}), 500

    # Filter for configured stations
    station_ids = [s['station_id'] for s in stations_list]
    fuel_types_by_station = {
        s['station_id']: s['fuel_types'] 
        for s in stations_list
    }

    result = []
    for station_id in station_ids:
        station = data.stations.get(station_id)
        if not station:
            continue
        
        fuel_types = fuel_types_by_station.get(station_id, [])
        prices = {}
        last_updated = {}
        trends = {}
        discount = discounts_by_station.get(station_id, 0.0)
        
        for fuel_type in fuel_types:
            price_obj = data.prices.get((station_id, fuel_type))
            if price_obj is not None:
                # Apply discount to price
                price_val = price_obj.price - discount
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
            'discount': discount,
            'prices': prices,
            'last_updated': last_updated,
            'trends': trends
        })
    
    average_trends = {}
    for key, price_history in last_prices.items():
        if key[0] == 0:
            fuel_type = key[1]
            trend = 'unknown'
            if price_history:
                current_avg = price_history[0]
                for hist_price in price_history[1:]:
                    if abs(current_avg - hist_price) > 0.001:
                        if current_avg > hist_price:
                            trend = 'up'
                        else:
                            trend = 'down'
                        break
                if trend == 'unknown' and price_history:
                    trend = 'stable'
            average_trends[fuel_type] = trend

    return jsonify({
        'prices': result,
        'average_trends': average_trends,
        'fetched_at': datetime.now().isoformat()
    })


@app.route('/api/prices/history', methods=['GET'])
@login_required
def get_price_history():
    """Get historical fuel prices from InfluxDB."""
    if not config:
        return jsonify({'error': 'Configuration not loaded'}), 500
    
    # Get query parameters
    station_id_s = request.args.get('station_id')
    fuel_type = request.args.get('fuel_type')
    days = request.args.get('days', default=7, type=int)
    
    # Validate station_id if provided
    station_id = None
    if station_id_s:
        try:
            station_id = int(station_id_s)
        except (ValueError, TypeError):
            return jsonify({'error': 'Invalid station_id'}), 400
    
    # Validate fuel_type if provided
    if fuel_type and fuel_type not in ALLOWED_FUEL_TYPES:
        return jsonify({'error': 'Invalid fuel type'}), 400
    
    # Validate days is reasonable
    if days < 1 or days > 365:
        return jsonify({'error': 'days must be between 1 and 365'}), 400
    
    try:
        with InfluxDBClient(
            url=config.influxdb_url,
            token=config.influxdb_token,
            org=config.influxdb_org
        ) as client:
            query_api = client.query_api()
            
            # Build Flux query
            filters = ['r._measurement == "fuel_price"']
            
            if station_id is not None:
                filters.append(f'r.station_id == "{station_id}"')
            
            if fuel_type:
                filters.append(f'r.fuel_type == "{fuel_type}"')
                
            filter_expr = ' and '.join(filters)
            query = f'from(bucket: "{config.influxdb_bucket}") |> range(start: -{days}d)'
            query += f' |> filter(fn: (r) => {filter_expr})'
            query += ' |> filter(fn: (r) => r._field == "price")'
            if days > 30 and station_id is None and not fuel_type:
                query += ' |> aggregateWindow(every: 6h, fn: mean, createEmpty: false)'
            query += ' |> sort(columns: ["_time"])'
            
            tables = query_api.query(query)
            
            history = []
            for table in tables:
                for record in table.records:
                    history.append({
                        'time': record.get_time().isoformat(),
                        'price': record.get_value(),
                        'station_id': record.values.get('station_id'),
                        'fuel_type': record.values.get('fuel_type')
                    })
        
        return jsonify({'history': history})
        
    except Exception as exc:
        _LOGGER.error("Failed to fetch price history: %s", exc)
        return jsonify({'error': 'Failed to fetch price history'}), 500


@app.route('/api/alerts', methods=['GET'])
@login_required
def get_alerts():
    """Get all configured price alerts (uses cached station names from SQLite)."""
    cfg, _ = refresh_config_and_fetcher()
    if not cfg or not cfg.db:
        return jsonify({'error': 'Database not available'}), 500
    
    alerts = cfg.db.get_alerts()
    station_names = {
        s['station_id']: s.get('station_name') or f"Station {s['station_id']}"
        for s in cfg.db.get_stations()
    }
    
    for alert in alerts:
        alert['station_name'] = station_names.get(alert['station_id'], f"Station {alert['station_id']}")
        
    return jsonify({'alerts': alerts})


@app.route('/api/alerts', methods=['POST'])
@login_required
def add_alert():
    """Add a new price alert."""
    if not config or not config.db:
        return jsonify({'error': 'Database not available'}), 500
    
    data = request.get_json(silent=True) or {}
    try:
        station_id = int(data.get('station_id'))
    except (ValueError, TypeError):
        return jsonify({'error': 'Valid positive station_id is required'}), 400

    fuel_type = data.get('fuel_type')
    threshold = data.get('threshold')
    
    if station_id <= 0 or not fuel_type or threshold is None:
        return jsonify({'error': 'station_id, fuel_type, and threshold are required'}), 400

    if fuel_type not in ALLOWED_FUEL_TYPES:
        return jsonify({'error': f'Invalid fuel type: {fuel_type}'}), 400
    
    try:
        threshold = float(threshold)
        if threshold <= 0:
            return jsonify({'error': 'Threshold must be greater than 0'}), 400
    except (ValueError, TypeError):
        return jsonify({'error': 'Invalid threshold'}), 400
    
    if config.db.add_alert(station_id, fuel_type, threshold):
        return jsonify({'message': 'Alert added successfully'}), 201
    else:
        return jsonify({'error': 'Failed to add alert'}), 500


@app.route('/api/alerts/<int:alert_id>', methods=['DELETE'])
@login_required
def delete_alert(alert_id):
    """Delete a price alert."""
    if not config or not config.db:
        return jsonify({'error': 'Database not available'}), 500
    
    if config.db.delete_alert(alert_id):
        return jsonify({'message': 'Alert deleted successfully'}), 200
    else:
        return jsonify({'error': 'Alert not found'}), 404


@app.route('/api/alerts/<int:alert_id>/toggle', methods=['PUT'])
@login_required
def toggle_alert(alert_id):
    """Toggle an alert enabled state."""
    if not config or not config.db:
        return jsonify({'error': 'Database not available'}), 500
    
    data = request.get_json(silent=True) or {}
    enabled = bool(data.get('enabled', True))
    
    if config.db.toggle_alert(alert_id, enabled):
        return jsonify({'message': 'Alert toggled successfully'}), 200
    else:
        return jsonify({'error': 'Alert not found'}), 404


@app.route('/api/fuel-types', methods=['GET'])
@login_required
def get_fuel_types():
    """Get list of allowed fuel types."""
    return jsonify({'fuel_types': ALLOWED_FUEL_TYPES})


@app.route('/api/config', methods=['GET'])
@login_required
def get_config():
    """Get current configuration."""
    cfg, _ = refresh_config_and_fetcher()
    if not cfg:
        return jsonify({'error': 'Configuration not loaded'}), 500

    # Return full URL for editing in the UI; secrets are masked
    return jsonify({
        'influxdb_url': cfg.influxdb_url,
        'influxdb_org': cfg.influxdb_org,
        'influxdb_bucket': cfg.influxdb_bucket,
        'influxdb_token': '***' if cfg.influxdb_token else '',
        'fuel_api_client_id': cfg.fuel_api_client_id,
        'fuel_api_client_secret': '***' if cfg.fuel_api_client_secret else '',
        'discord_webhook_url': '***' if cfg.discord_webhook_url else '',
        'discord_price_threshold': cfg.discord_price_threshold,
        'mqtt_broker': cfg.mqtt_broker,
        'mqtt_port': cfg.mqtt_port,
        'mqtt_user': cfg.mqtt_user,
        'mqtt_password': '***' if cfg.mqtt_password else '',
        'mqtt_discovery_prefix': cfg.mqtt_discovery_prefix,
        'poll_interval': cfg.poll_interval,
        'cron_schedule': cfg.cron_schedule,
        'timezone': cfg.timezone,
        'log_level': cfg.log_level,
        'auth_enabled': cfg.auth_enabled,
        'webauthn_rp_id': cfg.webauthn_rp_id,
        'webauthn_rp_name': cfg.webauthn_rp_name,
        'version': cfg.version
    })


@app.route('/api/config', methods=['PUT'])
@login_required
def update_config():
    """Update configuration settings."""
    if not config:
        return jsonify({'error': 'Configuration not loaded'}), 500
    
    data = request.get_json(silent=True) or {}
    
    # Update InfluxDB settings
    if 'influxdb_url' in data:
        if not _is_valid_http_url(data['influxdb_url']):
            return jsonify({'error': 'Invalid InfluxDB URL (must be http:// or https://)'}), 400
        config.influxdb_url = data['influxdb_url'].strip()
    
    if 'influxdb_token' in data and data['influxdb_token'] and data['influxdb_token'] != '***':
        config.influxdb_token = data['influxdb_token']
    
    if 'influxdb_org' in data:
        config.influxdb_org = data['influxdb_org']
    
    if 'influxdb_bucket' in data:
        config.influxdb_bucket = data['influxdb_bucket']

    # Update Fuel API settings
    if 'fuel_api_client_id' in data:
        config.fuel_api_client_id = data['fuel_api_client_id']

    if 'fuel_api_client_secret' in data and data['fuel_api_client_secret'] and data['fuel_api_client_secret'] != '***':
        config.fuel_api_client_secret = data['fuel_api_client_secret']

    # Update Discord settings
    if 'discord_webhook_url' in data and data['discord_webhook_url'] and data['discord_webhook_url'] != '***':
        if not is_valid_discord_webhook_url(data['discord_webhook_url']):
            return jsonify({'error': 'Invalid Discord webhook URL'}), 400
        config.discord_webhook_url = data['discord_webhook_url'].strip()
    
    if 'discord_price_threshold' in data:
        try:
            threshold = float(data['discord_price_threshold'])
            if threshold < 0:
                return jsonify({'error': 'Discord price threshold cannot be negative'}), 400
            config.discord_price_threshold = threshold
        except (ValueError, TypeError):
            return jsonify({'error': 'Invalid Discord price threshold'}), 400

    # Update MQTT settings
    if 'mqtt_broker' in data:
        config.mqtt_broker = str(data['mqtt_broker']).strip()
    
    if 'mqtt_port' in data:
        try:
            port = int(data['mqtt_port'])
            if not (1 <= port <= 65535):
                return jsonify({'error': 'MQTT port must be between 1 and 65535'}), 400
            config.mqtt_port = port
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
        except (ValueError, TypeError):
            return jsonify({'error': 'Invalid poll interval'}), 400
            
    if 'cron_schedule' in data:
        cron_val = str(data['cron_schedule'] or '').strip()
        if cron_val and not croniter.is_valid(cron_val):
            return jsonify({'error': 'Invalid cron schedule expression'}), 400
        config.cron_schedule = cron_val
        
    if 'timezone' in data:
        tz_val = str(data['timezone'] or '').strip()
        if tz_val:
            try:
                ZoneInfo(tz_val)
            except (ZoneInfoNotFoundError, KeyError, ValueError):
                return jsonify({'error': f'Invalid timezone: {tz_val}'}), 400
        config.timezone = tz_val
    
    if 'log_level' in data:
        log_level = str(data['log_level']).upper()
        if log_level not in ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']:
            return jsonify({'error': 'Invalid log level'}), 400
        config.log_level = log_level

    # Auth settings
    if 'auth_enabled' in data:
        config.auth_enabled = str(data['auth_enabled']).lower() == 'true'
    
    if 'webauthn_rp_id' in data:
        config.webauthn_rp_id = data['webauthn_rp_id']
        
    if 'webauthn_rp_name' in data:
        config.webauthn_rp_name = data['webauthn_rp_name']
    
    # Save to database
    if config.save_to_database():
        global fetcher
        fetcher = FuelDataFetcher(
            client_id=config.fuel_api_client_id,
            client_secret=config.fuel_api_client_secret
        )
        return jsonify({'message': 'Configuration updated successfully'}), 200
    else:
        return jsonify({'error': 'Failed to save configuration'}), 500


@app.route('/api/config/discord/test', methods=['POST'])
@login_required
def test_discord_config():
    """Test Discord notification configuration."""
    cfg, _ = refresh_config_and_fetcher()
    data = request.get_json(silent=True) or {}
    webhook_url = data.get('discord_webhook_url')
    
    # Fallback to stored webhook URL if not provided
    if not webhook_url and cfg and cfg.discord_webhook_url:
        webhook_url = cfg.discord_webhook_url

    if not webhook_url:
        return jsonify({'error': 'Webhook URL is required'}), 400

    if not is_valid_discord_webhook_url(webhook_url):
        return jsonify({'error': 'Invalid Discord webhook URL (must be https://discord.com/api/webhooks/...)'}), 400
        
    notifier = DiscordClient(webhook_url)
    
    message = "🔔 **FuelApp Test Notification**\nYour Discord webhook is configured correctly!"
    success = notifier.send_notification(message)
    
    if success:
        return jsonify({'message': 'Test notification sent successfully'}), 200
    else:
        return jsonify({'error': 'Failed to send test notification. Check your webhook URL and logs.'}), 400


@app.route('/api/config/mqtt/test', methods=['POST'])
@login_required
def test_mqtt_config():
    """Test MQTT configuration."""
    cfg, _ = refresh_config_and_fetcher()
    data = request.get_json(silent=True) or {}
    
    broker = data.get('mqtt_broker')
    port = data.get('mqtt_port', 1883)
    user = data.get('mqtt_user')
    password = data.get('mqtt_password')
    
    if not password and cfg and cfg.mqtt_password:
        password = cfg.mqtt_password

    if not broker:
        return jsonify({'error': 'Broker address is required'}), 400
        
    try:
        port = int(port)
        if not (1 <= port <= 65535):
            return jsonify({'error': 'Port must be between 1 and 65535'}), 400
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
@login_required
def generate_ha_card():
    """Generate Home Assistant Lovelace card configuration."""
    try:
        cfg, ftr = refresh_config_and_fetcher()
        if not cfg:
            _LOGGER.error("Configuration not loaded in generate_ha_card")
            return jsonify({'error': 'Configuration not loaded'}), 500

            
        data = request.get_json()
        if not data:
             _LOGGER.error("No JSON data received in generate_ha_card")
             return jsonify({'error': 'Invalid request'}), 400

        fuel_type = data.get('fuel_type', 'P98')
        _LOGGER.info("Generating HA card for fuel type: %s", fuel_type)
        
        if fuel_type == 'Average':
            yaml_content = """type: custom:vertical-stack-in-card
cards:
  - type: custom:mushroom-title-card
    title: 📊 Average Fuel Prices
    alignment: center
    card_mod:
      style: |
        ha-card {
          font-size: 18px;
          font-weight: bold;
        }
  - type: custom:auto-entities
    card:
      type: grid
      columns: 2
      square: false
    card_param: cards
    sort:
      method: name
    filter:
      include:
        - entity_id: sensor.average_prices_*_price
          options:
            type: custom:mushroom-entity-card
            icon: mdi:gas-station
            icon_color: blue
    exclude: []
    show_empty: true"""
            return jsonify({'yaml': yaml_content})
        
        # Get all stations that support this fuel type
        stations_list = cfg.stations
        if cfg.db:
            try:
                db_stations = cfg.db.get_stations()
                if db_stations is not None:
                    stations_list = db_stations
            except Exception as e:
                _LOGGER.error("Failed to fetch stations from DB: %s", e)
        
        _LOGGER.info("Found %d configured stations", len(stations_list))

        # Build list of entities for this fuel type using cached station names from SQLite
        entities = []
        for station in stations_list:
            if fuel_type in station['fuel_types']:
                sid = station['station_id']
                name = station.get('station_name') or f"Station {sid}"
                
                device_slug = ha_slugify(name)
                fuel_slug = ha_slugify(fuel_type)
                entity_id = f"sensor.{device_slug}_{fuel_slug}_price"
                
                entities.append(entity_id)

        _LOGGER.info("Generated %d entities", len(entities))

        # If no entities found, return error
        if not entities:
            return jsonify({'error': f'No stations found with fuel type {fuel_type}'}), 404
            
        # Generate the YAML content
        fuel_slug = ha_slugify(fuel_type)
        
        # Create the prices list string for the template
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
        
    except Exception as e:
        _LOGGER.exception("Unexpected error in generate_ha_card")
        return jsonify({'error': 'Failed to generate HA card'}), 500


@app.route('/api/backup', methods=['POST'])
@login_required
def create_backup():
    """Create a backup of InfluxDB data and return the filename."""
    if not config:
        return jsonify({'error': 'Configuration not loaded'}), 500
    
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = Path(config.data_dir) / 'backups' / timestamp
        backup_dir.mkdir(parents=True, exist_ok=True)
        
        _LOGGER.info("Starting InfluxDB backup to %s", backup_dir)
        
        if not _is_valid_http_url(config.influxdb_url):
            return jsonify({'error': 'Invalid InfluxDB URL configured'}), 400

        # Run influx backup command using env var instead of CLI arg to avoid process listing leak
        env = os.environ.copy()
        env['INFLUX_TOKEN'] = config.influxdb_token
        cmd = [
            "influx", "backup",
            str(backup_dir),
            "--host", config.influxdb_url,
            "--org", config.influxdb_org,
            "--bucket", config.influxdb_bucket
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, env=env)
        
        if result.returncode != 0:
            _LOGGER.error("Backup failed (code %d): %s\nStdout: %s", result.returncode, result.stderr, result.stdout)
            shutil.rmtree(backup_dir, ignore_errors=True)
            return jsonify({'error': 'Backup failed. Check server logs for details.'}), 500
            
        _LOGGER.info("Backup command successful, creating zip file")
        
        # Create zip file
        backups_root = Path(config.data_dir) / 'backups'
        zip_filename = f"backup_{timestamp}.zip"
        zip_path = backups_root / zip_filename
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            files_added = 0
            for root, dirs, files in os.walk(backup_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, backup_dir)
                    zipf.write(file_path, arcname)
                    files_added += 1
        
        _LOGGER.info("Zip file created: %s (added %d files)", zip_path, files_added)
        
        # Clean up staging directory
        shutil.rmtree(backup_dir, ignore_errors=True)

        # Prune older backup archives (keep latest 5)
        existing_zips = sorted(backups_root.glob('backup_*.zip'), key=lambda p: p.stat().st_mtime, reverse=True)
        for old_zip in existing_zips[5:]:
            try:
                old_zip.unlink()
            except Exception as exc:
                _LOGGER.warning("Failed to prune old backup %s: %s", old_zip, exc)
        
        return jsonify({
            'message': 'Backup created successfully',
            'filename': zip_filename,
            'size': zip_path.stat().st_size
        }), 200
        
    except Exception as exc:
        _LOGGER.error("Backup exception: %s", exc)
        return jsonify({'error': 'Backup failed'}), 500


@app.route('/api/backup/download/<filename>', methods=['GET'])
@login_required
def download_backup(filename):
    """Download a previously created backup file."""
    if not filename.endswith('.zip') or '/' in filename or '\\' in filename:
        return jsonify({'error': 'Invalid filename'}), 400
    
    backup_dir = (Path(config.data_dir) / 'backups').resolve()
    zip_path = (backup_dir / filename).resolve()
    if not zip_path.is_relative_to(backup_dir) or zip_path.parent != backup_dir:
        return jsonify({'error': 'Invalid filename'}), 400
    if not zip_path.exists():
        return jsonify({'error': 'Backup file not found'}), 404
        
    _LOGGER.info("Streaming backup file to client: %s (%d bytes)", filename, zip_path.stat().st_size)
    
    return send_file(
        zip_path,
        as_attachment=True,
        download_name=f"fuelapp_{filename}",
        mimetype='application/zip'
    )


@app.route('/api/restore', methods=['POST'])
@login_required
def restore_backup():
    """Restore InfluxDB data from a backup zip file."""
    if not config:
        return jsonify({'error': 'Configuration not loaded'}), 500
    
    if not _is_valid_http_url(config.influxdb_url):
        return jsonify({'error': 'Invalid InfluxDB URL configured'}), 400

    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
        
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
        
    if not file.filename.endswith('.zip'):
        return jsonify({'error': 'File must be a .zip archive'}), 400

    try:
        with tempfile.TemporaryDirectory(dir=config.data_dir, prefix='restore_') as tmp:
            temp_root = Path(tmp).resolve()
            zip_path = temp_root / 'restore.zip'
            extract_dir = (temp_root / 'extracted').resolve()
            extract_dir.mkdir(parents=True, exist_ok=True)
            file.save(zip_path)
            
            with zipfile.ZipFile(zip_path, 'r') as zipf:
                for member in zipf.namelist():
                    target_path = (extract_dir / member).resolve()
                    if not target_path.is_relative_to(extract_dir):
                        _LOGGER.error("Zip Slip vulnerability detected: %s", member)
                        return jsonify({'error': 'Invalid archive: contains unsafe paths'}), 400
                    zipf.extract(member, extract_dir)
                
            env = os.environ.copy()
            env['INFLUX_TOKEN'] = config.influxdb_token
            cmd = [
                "influx", "restore",
                str(extract_dir),
                "--host", config.influxdb_url,
                "--full"
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, env=env)
            
            if result.returncode != 0:
                _LOGGER.error("Restore failed: %s", result.stderr)
                return jsonify({'error': 'Restore failed. Check server logs for details.'}), 500
                
            return jsonify({'message': 'Restore completed successfully'}), 200
        
    except Exception as exc:
        _LOGGER.error("Restore exception: %s", exc)
        return jsonify({'error': 'Restore failed'}), 500


def run_web_app(config_obj: Config, host='0.0.0.0', port=5000, debug=False):
    """Run the Flask web application."""
    init_app(config_obj)
    app.run(host=host, port=port, debug=debug)
