# NSW & TAS Fuel Station Price Monitor

A standalone Python application that monitors fuel station prices across New South Wales (NSW) and Tasmania (TAS), storing historical data in InfluxDB. 

This application is based on the [Home Assistant NSW Fuel Station integration](https://github.com/home-assistant/core/tree/dev/homeassistant/components/nsw_fuel_station) by [@nickw444](https://github.com/nickw444) and has been expanded to support multi-state monitoring and modern notification systems.

**Note: This project was created with the assistance of AI. Use with caution.**

## Features

- 🇦🇺 **Multi-State Support**: Monitor fuel stations in both New South Wales and Tasmania.
- 🔐 **Robust Security**: Full authentication system with support for traditional passwords and modern **Passkeys (WebAuthn)**.
- 📊 **Real-time Monitoring**: Fetches prices from NSW/TAS FuelCheck APIs at configurable intervals.
- 💾 **Historical Persistence**: Stores every price change in InfluxDB 2.x for long-term trend analysis.
- 🌐 **Modern Web UI**: A dark-themed, responsive dashboard for visualizing trends and managing stations.
- 🔔 **Discord Notifications**: Get notified of price hikes via Discord webhooks.
- 🚨 **Price Alerts**: Configure granular alerts for specific stations and fuel types with custom thresholds.
- 🏠 **Home Assistant Integration**: Built-in MQTT discovery for seamless integration with Home Assistant.
- 📈 **Interactive Charts**: Visualize price history (7/14/28/90 days) with Chart.js.
- 🐳 **Docker Ready**: Easy deployment with Docker Compose, including pre-configured InfluxDB and Grafana.

## Requirements

### Docker (Recommended)
- Docker Engine 20.10 or higher
- Docker Compose V2

### Manual Installation
- Python 3.12 or higher
- InfluxDB 2.x instance
- **API Credentials**: You must register for an API key at the [NSW/TAS Fuel API Portal](https://api.nsw.gov.au/) to obtain a `Client ID` and `Client Secret`.

## Installation

### Docker Installation (Recommended)

**📖 For detailed Docker documentation, see [DOCKER.md](DOCKER.md)**

1. **Clone the repository:**
   ```bash
   git clone https://github.com/m1ckyb/FuelApp.git
   cd FuelApp
   ```

2. **Start the services:**
   ```bash
   docker compose up -d
   ```

3. **Access the application:**
   - **FuelApp Web UI**: http://localhost:5000
   - **InfluxDB**: http://localhost:8086 (admin/adminpassword)
   - **Grafana**: http://localhost:3000 (admin/admin)

### Manual Installation

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure the application:**
   Copy the example config and edit it with your credentials:
   ```bash
   cp config.yaml.example config.yaml
   ```

3. **Run the application:**
   ```bash
   python run.py
   ```

## Usage

### Web UI
The Web UI is the primary way to interact with FuelApp. Accessible at `http://localhost:5000`.

- **Dashboard**: View current prices and trend indicators (Rise/Drop/Stable).
- **Stations**: Search for stations by ID and manage your monitored list.
- **Alerts**: Create custom notification rules for specific fuel types.
- **Settings**: Configure InfluxDB, MQTT, Discord, and API credentials.

### CLI Options
```bash
# Run web UI and background monitoring (Default)
python run.py

# Run web UI only
python run.py --web

# Run a single update cycle and exit
python run.py --once
```

## Configuration Reference

### config.yaml
```yaml
# InfluxDB Configuration
influxdb:
  url: "http://localhost:8086"
  token: "your-influxdb-token"
  org: "fuelapp"
  bucket: "fuel_prices"

# Fuel API Credentials (Required)
fuel_api:
  client_id: "your-client-id"
  client_secret: "your-client-secret"

# Notifications (Optional)
notifications:
  discord:
    webhook_url: "https://discord.com/api/webhooks/..."
    price_threshold: 5.0  # Global threshold in cents. Set to 0 to disable global alerts.

# Monitored Stations
stations:
  - station_id: 350
    au_state: "NSW"
    fuel_types: ["E10", "U91", "P98"]
```

## Data Schema (InfluxDB)

**Measurement:** `fuel_price`
**Tags:** `station_id`, `station_name`, `station_address`, `fuel_type`
**Fields:** `price` (float, cents per liter)

## Development

### Project Structure
```
FuelApp/
├── app/
│   ├── config.py          # Configuration & SQLite DB handling
│   ├── data.py            # API fetching & InfluxDB writing
│   ├── main.py           # Background worker & scheduler
│   ├── mqtt.py           # Home Assistant MQTT integration
│   ├── notifications.py   # Discord notification logic
│   └── web.py            # Flask Web UI & API
├── run.py                 # Application entry point
├── templates/             # Jinja2 HTML templates
├── scripts/               # Maintenance and helper scripts
└── Dockerfile             # Alpine-based multi-stage build
```

## Credits
- Based on the [Home Assistant NSW Fuel Station integration](https://github.com/home-assistant/core/tree/dev/homeassistant/components/nsw_fuel_station) by [@nickw444](https://github.com/nickw444).
- Powered by the `nsw-tas-fuel-api-client` library.
- Data provided by NSW Government FuelCheck and TAS FuelCheck.

## License
MIT License. See [LICENSE](LICENSE) for details.

## Disclaimer
This application is not officially affiliated with or endorsed by any government body. Use at your own risk.
