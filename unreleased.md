### Added
- Added 'Test Connection' button to MQTT settings to verify broker connectivity.
- Added 'Home Assistant Card Generator' to settings, allowing users to generate Lovelace YAML for ranked fuel price cards based on their configured stations.
- Added 'deduplicate_db.py' script to remove redundant historical data from InfluxDB while preserving price change history.

### Changed
- Optimized InfluxDB storage to only write data points when fuel prices actually change, significantly reducing database growth for stable prices.
- Reorganized Settings page layout into two balanced columns for better usability and reduced scrolling.

### Fixed
- Fixed price trend calculation to correctly show up/down arrows even when the current price has already been written to InfluxDB.
- Improved 'Last Updated' display in dashboard to handle missing date libraries gracefully and ensure the time is always shown.
- Fixed layout shift in Price Trends chart by enforcing a minimum height for the chart container.
- Changed default fuel type selection in Price Trends chart to 'P98' (or first available) instead of 'All Fuel Types' to reduce visual clutter.
- Fixed page scroll jumping to top when clicking on a Station Name to view price history.
- Fixed MQTT settings issue where saving with a blank password would clear the existing password.
- Fixed MQTT "Test Connection" functionality to correctly use the stored password when the password field is left blank.
- Fixed "Copy to Clipboard" functionality in Settings page to work in non-secure (HTTP) contexts by adding a fallback mechanism.
