# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.0.4] - 2026-01-02
### Fixed
- Settings: Added missing "PDL" fuel type to the dropdown in the Home Assistant Card Generator.

## [0.0.3] - 2026-01-02
### Added
- MQTT: Added 'Test Connection' button to MQTT settings to verify broker connectivity.
- Settings: Added 'Home Assistant Card Generator' to settings, allowing users to generate Lovelace YAML for ranked fuel price cards based on their configured stations.
- Scripts: Added 'deduplicate_db.py' script to remove redundant historical data from InfluxDB while preserving price change history.
- Dashboard: Added "Last Updated" timestamp next to the Refresh button to show when prices were last fetched.

### Changed
- Dashboard: Reverted caching implementation. The Dashboard now fetches fresh data from the NSW FuelCheck API on every load/refresh to ensure real-time accuracy.
- Dashboard: Updated price card grid to be dynamic (flex-based), allowing up to 5 cards per row and expanding to fill available space.
- UI: Made price cards slimmer with reduced padding and font sizes for better information density.
- UI: Moved Home Assistant Card Generator to a dedicated modal with a cleaner interface, accessible from the "Home Assistant (MQTT)" card header.
- UI: Improved layout of settings buttons to prevent visual overcrowding.
- Backend: Optimized InfluxDB storage to only write data points when fuel prices actually change, significantly reducing database growth for stable prices.
- UI: Reorganized Settings page layout into two balanced columns for better usability and reduced scrolling.
- UI: Changed default fuel type selection in Price Trends chart to 'P98' (or first available) instead of 'All Fuel Types' to reduce visual clutter.

### Fixed
- Web App: Fixed timezone issue where the web interface (and logs) used UTC instead of the configured timezone (e.g., Australia/Sydney).
- HA Generator: Fixed "Generate YAML" button responsiveness by improving error handling and fixing a broken JavaScript selector that prevented the button from working in some browsers.
- Dashboard: Fixed price trend calculation to correctly show up/down arrows even when the current price has already been written to InfluxDB.
- Dashboard: Improved 'Last Updated' display in dashboard to handle missing date libraries gracefully and ensure the time is always shown.
- Dashboard: Fixed layout shift in Price Trends chart by enforcing a minimum height for the chart container.
- Dashboard: Fixed page scroll jumping to top when clicking on a Station Name to view price history.
- Settings: Fixed MQTT settings issue where saving with a blank password would clear the existing password.
- Settings: Fixed MQTT "Test Connection" functionality to correctly use the stored password when the password field is left blank.
- Settings: Fixed "Copy to Clipboard" functionality in Settings page to work in non-secure (HTTP) contexts by adding a fallback mechanism.

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
