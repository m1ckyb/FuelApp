#!/usr/bin/env python3
"""
Quick start script for NSW Fuel Station App.
This script helps set up a basic configuration.
"""

import os
import sys
from pathlib import Path


def create_config():
    """Create a basic configuration file."""
    config_content = """# NSW Fuel Station App Configuration

# InfluxDB Configuration
influxdb:
  url: "http://localhost:8086"
  token: "my-super-secret-auth-token"
  org: "fuelapp"
  bucket: "fuel_prices"

# Fuel Station Configuration
# Example stations in Sydney area
stations:
  # Example: Shell Coles Express - you can find station IDs via the FuelCheck app
  - station_id: 350
    fuel_types:
      - E10
      - U91
      - P95
      - P98
      - DL

# Polling interval in minutes (default: 60)
poll_interval: 60

# Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
log_level: "INFO"
"""
    
    config_path = Path("config.yaml")
    if config_path.exists():
        print("⚠️  config.yaml already exists!")
        response = input("Overwrite? (y/N): ")
        if response.lower() != 'y':
            print("Keeping existing config.yaml")
            return False
    
    with open(config_path, 'w') as f:
        f.write(config_content)
    
    print("✅ Created config.yaml")
    return True


def create_env():
    """Create a basic .env file."""
    env_content = """# Environment variables for NSW Fuel Station App
# These override values in config.yaml

INFLUXDB_URL=http://localhost:8086
INFLUXDB_TOKEN=my-super-secret-auth-token
INFLUXDB_ORG=fuelapp
INFLUXDB_BUCKET=fuel_prices
"""
    
    env_path = Path(".env")
    if env_path.exists():
        print("⚠️  .env already exists!")
        response = input("Overwrite? (y/N): ")
        if response.lower() != 'y':
            print("Keeping existing .env")
            return False
    
    with open(env_path, 'w') as f:
        f.write(env_content)
    
    print("✅ Created .env")
    return True


def main():
    """Main quick start function."""
    print("🚀 NSW Fuel Station App - Quick Start")
    print("=" * 50)
    print()
    
    # Check if dependencies are installed
    try:
        import nsw_fuel
        import yaml
        from influxdb_client import InfluxDBClient
    except ImportError as e:
        print("❌ Missing dependencies!")
        print(f"   Error: {e}")
        print()
        print("Please install dependencies first:")
        print("   pip install -r requirements.txt")
        sys.exit(1)
    
    print("✅ Dependencies installed")
    print()
    
    # Create configuration files
    print("Setting up configuration files...")
    print()
    
    create_config()
    create_env()
    
    print()
    print("=" * 50)
    print("Setup complete! 🎉")
    print()
    print("Next steps:")
    print()
    print("1. Start InfluxDB (using Docker):")
    print("   docker-compose up -d influxdb")
    print()
    print("2. Edit config.yaml to add your station IDs")
    print("   Find station IDs at: https://www.fuelcheck.nsw.gov.au/")
    print()
    print("3. Run the app:")
    print("   python main.py          # Run continuously")
    print("   python main.py --once   # Run once and exit")
    print()
    print("4. Access InfluxDB UI at: http://localhost:8086")
    print("   Username: admin")
    print("   Password: adminpassword")
    print()
    print("5. (Optional) Access Grafana at: http://localhost:3000")
    print("   Username: admin")
    print("   Password: admin")
    print()


if __name__ == '__main__':
    main()
