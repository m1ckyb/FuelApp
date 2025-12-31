"""Main application for NSW Fuel Station price monitoring."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from pathlib import Path

import schedule

from .config import Config, setup_logging
from .data import FuelDataFetcher, InfluxDBWriter

_LOGGER = logging.getLogger(__name__)

# Global flag for graceful shutdown
running = True


def signal_handler(signum, frame):
    """Handle shutdown signals."""
    global running
    _LOGGER.info("Shutdown signal received, stopping...")
    running = False


class FuelApp:
    """Main application class for NSW Fuel Station monitoring."""

    def __init__(self, config: Config):
        """Initialize the fuel application."""
        self.config = config
        self.fetcher = FuelDataFetcher()
        self.writer = InfluxDBWriter(
            url=config.influxdb_url,
            token=config.influxdb_token,
            org=config.influxdb_org,
            bucket=config.influxdb_bucket
        )
        self.connected = False

    def connect(self) -> bool:
        """Connect to InfluxDB."""
        self.connected = self.writer.connect()
        return self.connected

    def fetch_and_store(self):
        """Fetch fuel prices and store them in InfluxDB."""
        if not self.connected:
            _LOGGER.error("Not connected to InfluxDB, skipping update")
            return

        _LOGGER.info("Starting fuel price update cycle")
        
        # Fetch data from NSW FuelCheck API
        data = self.fetcher.fetch_station_price_data()
        
        if data is None:
            _LOGGER.error("Failed to fetch fuel price data")
            return

        # Prepare station IDs and fuel types
        station_ids = [s['station_id'] for s in self.config.stations]
        fuel_types_by_station = {
            s['station_id']: s['fuel_types'] 
            for s in self.config.stations
        }

        # Write to InfluxDB
        success = self.writer.write_fuel_prices(
            data,
            station_ids,
            fuel_types_by_station
        )

        if success:
            _LOGGER.info("Fuel price update completed successfully")
        else:
            _LOGGER.error("Failed to write fuel prices to InfluxDB")

    def run_once(self):
        """Run a single update cycle."""
        if not self.connect():
            _LOGGER.error("Failed to connect to InfluxDB")
            return False

        self.fetch_and_store()
        self.writer.close()
        return True

    def run_scheduled(self):
        """Run the application with scheduled updates."""
        if not self.connect():
            _LOGGER.error("Failed to connect to InfluxDB, exiting")
            return

        # Schedule the fetch and store job
        interval = self.config.poll_interval
        schedule.every(interval).minutes.do(self.fetch_and_store)

        _LOGGER.info(
            "Starting scheduled monitoring (interval: %d minutes)",
            interval
        )

        # Run once immediately
        self.fetch_and_store()

        # Main loop
        global running
        try:
            while running:
                schedule.run_pending()
                time.sleep(1)
        except KeyboardInterrupt:
            _LOGGER.info("Keyboard interrupt received")
        finally:
            _LOGGER.info("Shutting down...")
            self.writer.close()


def main():
    """Main entry point for the application."""
    parser = argparse.ArgumentParser(
        description='NSW Fuel Station Price Monitor with InfluxDB'
    )
    parser.add_argument(
        '-c', '--config',
        default='config.yaml',
        help='Path to configuration file (default: config.yaml)'
    )
    parser.add_argument(
        '--once',
        action='store_true',
        help='Run once and exit (no scheduling)'
    )
    parser.add_argument(
        '--web',
        action='store_true',
        help='Run web UI server'
    )
    parser.add_argument(
        '--host',
        default='0.0.0.0',
        help='Web server host (default: 0.0.0.0)'
    )
    parser.add_argument(
        '--port',
        default=5000,
        type=int,
        help='Web server port (default: 5000)'
    )
    parser.add_argument(
        '--log-level',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
        help='Override log level from config'
    )

    args = parser.parse_args()

    # Load configuration
    config = Config()
    
    if not config.load_from_file(args.config):
        print(f"Error: Failed to load configuration from {args.config}")
        print(f"Please create a config file based on config.yaml.example")
        sys.exit(1)

    # Load environment variables (these override file config)
    config.load_from_env()

    # Override log level if specified
    if args.log_level:
        config.log_level = args.log_level

    # Setup logging
    setup_logging(config.log_level)

    _LOGGER.info("NSW Fuel Station App starting...")

    # Validate configuration
    if not config.validate():
        _LOGGER.error("Invalid configuration, exiting")
        sys.exit(1)

    # Setup signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Create and run the application
    app = FuelApp(config)

    if args.web:
        _LOGGER.info("Starting web UI server on %s:%d", args.host, args.port)
        from .web import run_web_app
        run_web_app(config, host=args.host, port=args.port, debug=False)
    elif args.once:
        _LOGGER.info("Running in single-shot mode")
        success = app.run_once()
        sys.exit(0 if success else 1)
    else:
        app.run_scheduled()


if __name__ == '__main__':
    main()
