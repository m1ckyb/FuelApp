# NSW Fuel Station Price Monitor - Feature Summary

## Core Features
- **Real-time Monitoring**: Fetches fuel prices from NSW FuelCheck API every 60 minutes (configurable).
- **Data Persistence**: Stores price history in InfluxDB 2.x for trend analysis.
- **Web Dashboard**: Dark-themed, responsive UI showing current prices and trends.
- **Station Management**: Add/Remove stations and fuel types via UI.
- **Price Trends**: Visual indicators for price rise (Red), drop (Green), or stable (Grey).
- **Historical Analysis**: Interactive charts for 7/14/28/90 day price history.
- **Backup & Restore**: Built-in tools to backup and restore InfluxDB data.

## Technical Stack
- **Language**: Python 3.12
- **Web Framework**: Flask with Gunicorn
- **Database**: InfluxDB 2.7 (TimeSeries), SQLite (Configuration)
- **Frontend**: Bootstrap 5, Chart.js
- **Deployment**: Docker Compose with Supervisor
