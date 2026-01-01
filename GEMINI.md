# Gemini Project Documentation

## Project Overview
NSW Fuel Station Price Monitor is a standalone Python application designed to track fuel prices across New South Wales. It fetches real-time data from the NSW FuelCheck API, stores historical price information in InfluxDB, and provides a modern web interface for visualization and station management.

## Architecture
The application is built with a modular architecture:
- **Application Core**: Orchestrated by `main.py`, handling both background polling (using `schedule`) and the web server.
- **Data Acquisition**: `fuel_data.py` manages requests to the NSW FuelCheck API, parsing and formatting the responses.
- **Data Persistence**: `influxdb_writer.py` handles writing price data to InfluxDB 2.x, ensuring historical tracking.
- **Web Interface**: A Flask-based web application (`web_app.py`) serves a responsive UI using Jinja2 templates (`templates/`) and Chart.js for data visualization.
- **Configuration Management**: `config_loader.py` provides a unified way to load settings from YAML files and environment variables.
- **Containerization**: Docker and Docker Compose support allow for easy deployment of the app along with InfluxDB and Grafana.

## Key Files
- `main.py`: The primary entry point for the application.
- `fuel_data.py`: Logic for interacting with the NSW FuelCheck API.
- `influxdb_writer.py`: Client logic for InfluxDB operations.
- `web_app.py`: Flask application and route definitions for the Web UI.
- `config_loader.py`: Handles configuration loading and validation.
- `docker-compose.yml`: Defines the multi-container setup (App, InfluxDB, Grafana).
- `VERSION.txt`: Contains the current semantic version of the application.
- `CHANGELOG.md`: Tracks history of changes.
- `unreleased.md`: Buffer for upcoming release notes.
- `SECURITY/`: Contains historical security scan reports (Bandit, pip-audit).

## Session Initialization
When a new chat session begins, I must first read the following files to establish a complete understanding of the project's current state, architecture, and purpose:
- `GEMINI.md` (for architectural principles and workflows)
- `README.md` (for project overview and deployment instructions)
- `summary.md` (for a high-level feature summary)
- `CHANGELOG.md` (for recent changes and version history)
- `unreleased.md` (for upcoming changes and known bugs)

This ensures all subsequent responses are informed by the full project context.

## Development Workflow
### Continuous Documentation
After every feature addition, change, or bug fix, `unreleased.md` must be updated immediately with a concise summary of the change under the appropriate heading (`### Added`, `### Changed`, `### Fixed`). This ensures the changelog is always ready for the next release.

*Note: Changes made to `GEMINI.md` itself do not need to be documented in `unreleased.md`.*

## Release Process

### Make a dev release
When requested to "Make a dev release":
1. **Push to Dev**: Push the current code to the `dev` branch.

### Make a release
When requested to "Make a release", where `<type>` is **Patch**, **Minor**, or **Major**, the following steps must be performed on the `dev` branch:

1.  **Determine New Version**: Read the current version from `VERSION.txt` (e.g., X.Y.Z).
    - For a **Patch** release, the new version will be X.Y.(Z+1).
    - For a **Minor** release, the new version will be X.(Y+1).0.
    - For a **Major** release, the new version will be (X+1).0.0.

2.  **Update CHANGELOG.md**:
    - Create a new version heading with the new version number and current date (e.g., `## [1.0.0] - YYYY-MM-DD`).
    - Move only the content from `unreleased.md` that hasn't been released yet into this new section.
    - **CRITICAL**: Ensure you do not duplicate entries already present in older versions of `CHANGELOG.md`.
    - Do not add an `[Unreleased]` section back to the top of `CHANGELOG.md`.

3.  **Clear unreleased.md**: After moving the content, reset `unreleased.md` to an empty state (or just the sub-headers) to prevent those changes from being included in the next release.

4.  **Update VERSION.txt**: Change the content of `VERSION.txt` to the new version number.

5.  **Update docker-compose.yml**: Update the image tags for the services to the new version number.

6.  **Update Documentation**: Review `README.md` and other docs to reflect new features or significant changes.

7.  **Push to Dev**: Commit and push all release-related changes to the `dev` branch.

8.  **Merge to Main**: Checkout `main`, merge `dev`, and push to `origin main`.

9.  **GitHub Release**: Use the `gh` CLI to create a release/pre-release on GitHub, using the notes extracted from the changelog.
    - **Command**: `gh release create vX.Y.Z --title "vX.Y.Z - Description" --notes "content from changelog" --prerelease`
