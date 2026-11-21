### Added
- **Testing**: Expanded `tests/test_app.py` with tests covering Flux identifier validation, cross-worker config isolation, trend calculation, newly added station dashboard placeholders, history downsampling, password updates, WebAuthn error handling, and `paho-mqtt` v2 callbacks.
- **Database**: Added index on `login_attempts(updated_at)` to speed up stale rate-limit pruning.

### Changed
- **Architecture**: Extracted reusable worker-scoped `InfluxDBReader` and typed `CachedStation`/`CachedPrice` dataclasses into `app/data.py`, and deduplicated trend computation (`_compute_trend`) and Settings form saving (`saveConfigSection`).
- **Performance**: Added a 5-minute TTL cache to `/api/stations/lookup` to avoid repeated bulk NSW/TAS API fetches.
- **Dependencies**: Bumped `nsw-tas-fuel-api-client` from `0.0.1` to `0.0.2` and aligned Python requirement (`>=3.14`) across `setup.py`, CI, and documentation.
- **CI/CD**: Increased Dependabot `open-pull-requests-limit` to `10` for `pip` updates.

### Fixed
- **Reliability**: Fixed cross-worker configuration clobbering and partial in-memory mutation in `PUT /api/config` by refreshing from SQLite first, validating all fields before persisting, and writing only submitted keys.
- **Reliability**: Ensured newly added stations appear immediately on the Dashboard before the first scheduled poll, and refreshed DB config in `/api/prices/history`.
- **Security**: Validated `influxdb_bucket` and `influxdb_org` against Flux injection, disallowed runtime disabling of `auth_enabled` via API, added rate limiting to `/api/config/mqtt/test` and `/api/config/discord/test`, and added a `Content-Security-Policy` header.
### Removed
