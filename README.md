# NSW Fuel Station Price Monitor

A standalone Python application that monitors NSW fuel station prices and stores historical data in InfluxDB. This application is based on the [Home Assistant NSW Fuel Station integration](https://github.com/home-assistant/core/tree/dev/homeassistant/components/nsw_fuel_station).

## Features

- 📊 Fetches real-time fuel prices from NSW FuelCheck API
- 💾 Stores price data in InfluxDB for historical analysis
- 🌐 Modern Web UI for visualizing data and managing stations
- 📈 Track price changes over time with interactive charts
- ⚙️ Configurable polling intervals
- 🏪 Monitor multiple fuel stations simultaneously
- ⛽ Support for all fuel types (E10, U91, P95, P98, DL, etc.)
- 🔄 Automatic scheduled updates
- 🎨 Clean, modern interface inspired by speedtest-tracker

## Requirements

### Docker (Recommended)
- Docker Engine 20.10 or higher
- Docker Compose V2

### Manual Installation
- Python 3.8 or higher
- InfluxDB 2.x instance (local or cloud)
- Internet connection to access NSW FuelCheck API

## Installation

### Docker Installation (Recommended)

The easiest way to run FuelApp is using Docker Compose, which will set up the application along with InfluxDB and Grafana automatically.

1. **Clone the repository:**
   ```bash
   git clone https://github.com/m1ckyb/FuelApp.git
   cd FuelApp
   ```

2. **Create configuration file:**
   ```bash
   cp config.yaml.docker config.yaml
   ```
   
   Edit `config.yaml` and update the station IDs and fuel types you want to monitor:
   ```yaml
   stations:
     - station_id: 350  # Replace with your station ID
       fuel_types:
         - E10
         - U91
   ```

3. **Start the services:**
   ```bash
   docker compose up -d
   ```

4. **Access the application:**
   - **FuelApp Web UI**: http://localhost:5000
   - **InfluxDB**: http://localhost:8086 (admin/adminpassword)
   - **Grafana**: http://localhost:3000 (admin/admin)

5. **View logs:**
   ```bash
   docker compose logs -f fuelapp
   ```

6. **Stop the services:**
   ```bash
   docker compose down
   ```

**Default Credentials:**
- InfluxDB: `admin` / `adminpassword`
- InfluxDB Token: `my-super-secret-auth-token`
- InfluxDB Org: `fuelapp`
- InfluxDB Bucket: `fuel_prices`
- Grafana: `admin` / `admin`

**Note:** For production use, change these default credentials in `docker-compose.yml`.

### Manual Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/m1ckyb/FuelApp.git
   cd FuelApp
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up InfluxDB:**
   - Install InfluxDB 2.x or use InfluxDB Cloud
   - Create an organization and bucket for fuel prices
   - Generate an API token with write permissions

4. **Configure the application:**
   
   Copy the example configuration file:
   ```bash
   cp config.yaml.example config.yaml
   ```
   
   Edit `config.yaml` and set your InfluxDB credentials and station IDs:
   ```yaml
   influxdb:
     url: "http://localhost:8086"
     token: "your-influxdb-token"
     org: "your-org"
     bucket: "fuel_prices"
   
   stations:
     - station_id: 350
       fuel_types:
         - E10
         - U91
   ```

   Alternatively, use environment variables by copying `.env.example`:
   ```bash
   cp .env.example .env
   ```
   
   Edit `.env` with your credentials.

## Finding Station IDs

Station IDs can be found from:
- The NSW FuelCheck mobile app
- The NSW FuelCheck website: https://www.fuelcheck.nsw.gov.au/
- The API response (run once to see all available stations)

## Usage

### Run the Web UI (recommended)

Start the web interface to visualize data and manage stations:
```bash
python main.py --web
```

The web UI will be available at `http://localhost:5000` by default. You can customize the host and port:
```bash
python main.py --web --host 0.0.0.0 --port 8080
```

The Web UI provides:
- **Dashboard**: View current fuel prices and historical trends with interactive charts
- **Stations**: Add, edit, and remove monitored fuel stations through the interface
- **Settings**: View your InfluxDB configuration and system information

### Run with scheduled updates (background monitoring)

Monitor fuel prices continuously with automatic updates:
```bash
python main.py
```

By default, the app will check prices every 60 minutes. Adjust the `poll_interval` in `config.yaml` to change this.

### Run once and exit

Fetch and store current prices without scheduling:
```bash
python main.py --once
```

### Specify custom configuration file

```bash
python main.py -c /path/to/custom/config.yaml
```

### Override log level

```bash
python main.py --log-level DEBUG
```

## Configuration Reference

### config.yaml

```yaml
# InfluxDB Configuration
influxdb:
  url: "http://localhost:8086"        # InfluxDB server URL
  token: "your-influxdb-token"        # API token with write access
  org: "your-org"                     # Organization name
  bucket: "fuel_prices"               # Bucket name for storing data

# Fuel Station Configuration
stations:
  - station_id: 350                   # Unique station ID
    fuel_types:                       # Fuel types to monitor
      - E10
      - U91
      - P95
      - P98
      - DL

# Polling interval in minutes (default: 60)
poll_interval: 60

# Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
log_level: "INFO"
```

### Supported Fuel Types

- `E10` - Ethanol 10% Unleaded
- `U91` - Unleaded 91
- `E85` - Ethanol 85%
- `P95` - Premium Unleaded 95
- `P98` - Premium Unleaded 98
- `DL` - Diesel
- `PDL` - Premium Diesel
- `B20` - Biodiesel 20%
- `LPG` - Liquefied Petroleum Gas
- `CNG` - Compressed Natural Gas
- `EV` - Electric Vehicle charging

## Data Schema in InfluxDB

The application stores data with the following schema:

**Measurement:** `fuel_price`

**Tags:**
- `station_id` - Unique identifier for the station
- `station_name` - Name of the fuel station
- `station_address` - Address of the station
- `fuel_type` - Type of fuel (E10, U91, etc.)

**Fields:**
- `price` - Price in cents per liter (float)

**Timestamp:** UTC time when the price was fetched

### Example Query

Query fuel prices in Flux:
```flux
from(bucket: "fuel_prices")
  |> range(start: -7d)
  |> filter(fn: (r) => r._measurement == "fuel_price")
  |> filter(fn: (r) => r.station_id == "350")
  |> filter(fn: (r) => r.fuel_type == "E10")
```

## Visualizing Data

### Web UI (Built-in)

The application includes a modern web interface for visualizing fuel prices:

```bash
python main.py --web
```

Features:
- **Real-time Price Display**: View current fuel prices for all configured stations
- **Interactive Charts**: Visualize price trends over time with Chart.js
- **Station Management**: Add and remove stations directly from the UI
- **Responsive Design**: Works on desktop, tablet, and mobile devices
- **Dark Theme**: Easy on the eyes with a modern dark interface

### External Tools

You can also visualize the historical price data using:
- **InfluxDB UI** - Built-in dashboards and graphs
- **Grafana** - Create custom dashboards with InfluxDB data source
- **Chronograf** - InfluxData's visualization tool

## Troubleshooting

### InfluxDB Connection Failed

- Verify InfluxDB is running: `curl http://localhost:8086/health`
- Check your token has write permissions
- Ensure the bucket exists in your organization

### No Price Data for Station

- Verify the station ID is correct
- Check if the fuel type is available at that station
- Some stations may not report all fuel types

### API Rate Limiting

The NSW FuelCheck API may have rate limits. The default 60-minute interval should be safe. Avoid polling more frequently than every 15 minutes.

## Development

### Project Structure

```
FuelApp/
├── main.py                 # Main application entry point
├── config_loader.py        # Configuration management
├── fuel_data.py           # NSW FuelCheck API integration
├── influxdb_writer.py     # InfluxDB client
├── constants.py           # Application constants
├── requirements.txt       # Python dependencies
├── config.yaml.example    # Example configuration
├── .env.example          # Example environment variables
└── README.md             # This file
```

### Running Tests

(Tests can be added here as the project grows)

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is open source and available under the MIT License.

## Credits

Based on the [Home Assistant NSW Fuel Station integration](https://github.com/home-assistant/core/tree/dev/homeassistant/components/nsw_fuel_station) by [@nickw444](https://github.com/nickw444).

Data provided by NSW Government FuelCheck.

## Disclaimer

This application is not officially affiliated with or endorsed by NSW Government or FuelCheck. Use at your own risk.