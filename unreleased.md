### Added
- Multi-state support: Added ability to monitor fuel stations in both New South Wales (NSW) and Tasmania (TAS).
- Station State Configuration: Added `au_state` field to station settings in the Web UI and database.
- Settings: Displayed application version number (from VERSION.txt) in the System Information section.
- Price Alerts: Added ability to monitor specific stations and fuel types for price increases.
- Discord Notifications: Added integration to send notifications via Discord webhooks when price increases exceed a configured threshold.
- Added 'Test Notification' button to Discord settings to verify webhook connectivity.
- New 'Alerts' management page in the Web UI to configure granular price thresholds.

### Changed
- Switched fuel API client from `nsw-fuel-api-client` to `nsw-tas-fuel-api-client`.
- Updated configuration and Web UI to support NSW/TAS Fuel API OAuth credentials (`client_id` and `client_secret`).
- Refactored fuel data fetching to support the asynchronous API of the new client library and parallel fetching across multiple states.
- MQTT: Updated Home Assistant discovery to correctly identify the manufacturer (NSW or TAS FuelCheck) based on the station's state.
- Discord Alerts: Refined notification logic to allow disabling global alerts by setting the threshold to 0, while still allowing specific alerts to trigger.

### Fixed
- Fixed stale data issue in Gunicorn environment by ensuring 'get_stations' and 'get_current_prices' API endpoints fetch configuration directly from the database instead of relying on per-worker in-memory cache.