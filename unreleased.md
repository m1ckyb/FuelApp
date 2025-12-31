### Added
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
- Fixed an issue where price trends chart would not load initially.
- Fixed the "Edit" button functionality on the Stations management page.
- Unified `card-header` background colors across all pages for a consistent theme.
- Fixed missing background polling in Docker by ensuring the scheduler runs alongside the web server.

### Removed
- Removed default stations (350 and 4711) from configuration files and the database.
