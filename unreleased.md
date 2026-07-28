### Added
- **Security**: Added anti-CSRF protection across all forms and AJAX endpoints utilizing `Flask-WTF`.
- **Database**: Implemented an SQLite-backed rate limiter to persist and synchronize rate limit checks across multiple Gunicorn workers.

### Fixed
- **Security**: Fixed Flask Session Secret desynchronization bug under Gunicorn concurrency by introducing file-locking logic.
- **Reliability**: Added connection and socket timeout constraints to outbound aiohttp requests.
- **Reliability**: Implemented lazy thread-local connection pools in `ConfigDatabase` to prevent database access thread locks.
- **Scalability**: Decoupled dashboard price querying from the live NSW/TAS APIs by reading cached price indices from InfluxDB.
- **Architecture**: Enforced database lookup reload states to keep configuration unified across different Gunicorn worker instances.
- **Infrastructure**: Configured default CPU and memory limits inside `docker-compose.yml`.
