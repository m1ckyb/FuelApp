### Added
- Added `DATA_DIR` environment variable support for persistent storage.
- Moved `config.db` and `.flask_secret` to the configured data directory (defaults to `/app/config` in Docker).
- Persistent volume support in `docker-compose.yml`.
- Added Backup & Restore functionality for InfluxDB data in the Settings page.
- Added `/api/backup` and `/api/restore` endpoints to the web API.
- Added `influxdb2-cli` to the Docker image to support backup operations.

### Changed
- Updated `dashboard.html` to allow viewing price trends without selecting a specific station or fuel type.
- Updated `web_app.py` logic for price history API to handle optional filters.

### Fixed
- Fixed an issue where price trends chart would not load initially.

### Removed
- Removed default stations (350 and 4711) from configuration files and the database.
