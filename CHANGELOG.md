# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.0.2] - 2026-01-01
### Added
- Added Home Assistant MQTT Integration:
    - New MQTT configuration section in Settings.
    - Automatic discovery of fuel stations as Home Assistant devices/sensors.
    - Real-time price updates pushed to Home Assistant via MQTT.
- Added ability to lookup and pre-select available fuel types when adding or editing a station.
- Added a station-wide price history modal, accessible by clicking the station name on the Dashboard, displaying trends for all monitored fuel types at once.
- Added automated security scanning (Bandit and pip-audit) with reports stored in the `SECURITY/` directory.
- Added `DATA_DIR` environment variable support for persistent storage.
- Moved `config.db` and `.flask_secret` to the configured data directory (defaults to `/app/config` in Docker).
- Persistent volume support in `docker-compose.yml`.
- Added Backup & Restore functionality for InfluxDB data in the Settings page.
- Added `/api/backup` and `/api/restore` endpoints to the web API.
- Added `influxdb2-cli` to the Docker image to support backup operations.
- Added station name display to the Stations management page.
- Redesigned the Web UI with a modern dark theme inspired by RouteGhost.
- Implemented Gunicorn as the WSGI server for improved performance and reliability.
- Added Cron scheduling support (`cron_schedule`) for precise task timing.
- Added Timezone support (`timezone`) ensuring accurate scheduling (defaults to Australia/Sydney).
- Added `croniter` and `tzdata` dependencies.

### Changed
- Updated price cards on the Dashboard to use visual indicators for price trends:
    - Red up-triangle for price rise.
    - Green down-triangle for price drop.
    - Grey dash for stable price.
- Updated `dashboard.html` to allow viewing price trends without selecting a specific station or fuel type.
- Updated `web_app.py` logic for price history API to handle optional filters.
- Unified the page layout and container widths across the entire application.
- Updated the Stations table header from "Station ID" to "Station".
- Improved `.gitignore` to exclude local `data/` directory and keep the repository clean.
- Refactored codebase structure:
    - Moved source code to `app/` package.
    - Merged configuration files into `app/config.py`.
    - Merged data handling files into `app/data.py`.
    - Moved scripts to `scripts/` directory.
    - Added `run.py` as the application entry point.
- Integrated application logging with Gunicorn output.
- Migrated to a single-container architecture using Supervisor to run both Gunicorn (Web) and the Scheduler (Worker).
- Switched Docker base image to `python:3.12-alpine` with multi-stage build, reducing image size by >50%.

### Fixed
- Fixed form label visibility in Settings when editing options by ensuring they use the correct theme color.
- Fixed an issue where station updates might not appear immediately due to caching across Gunicorn workers by ensuring the API always reads the latest configuration from the database.
- Fixed an issue where price trends chart would not load initially.
- Fixed the "Edit" button functionality on the Stations management page.
- Unified `card-header` background colors across all pages for a consistent theme.
- Fixed missing background polling in Docker by ensuring the scheduler runs alongside the web server.

### Removed
- Removed default stations (350 and 4711) from configuration files and the database.

## [0.0.1] - 2025-12-31
### Added
- Initial setup of NSW Fuel Station Price Monitor.
- Real-time fuel price fetching from NSW FuelCheck API.
- InfluxDB integration for historical data storage.
- Modern Web UI for visualization and management.
- Docker support with docker-compose.
