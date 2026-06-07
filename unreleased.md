### Added

### Changed
- **Security**: Updated `aiohttp` to `3.14.0` in `requirements.txt` to mitigate known CVEs (CVE-2026-34993, CVE-2026-47265).
- **Security**: Hardened Flask session cookies by setting `SESSION_COOKIE_SAMESITE = 'Strict'` for better CSRF protection.

### Fixed
- **Security**: Fixed a "Zip Slip" directory traversal vulnerability in the backup restore functionality (`app/web.py`) by explicitly validating paths of files within user-uploaded archives.
