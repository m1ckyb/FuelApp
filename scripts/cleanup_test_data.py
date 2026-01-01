import os
import requests
from influxdb_client import InfluxDBClient

# Configuration
APP_URL = os.getenv("APP_URL", "http://localhost:5000")
INFLUX_URL = os.getenv("INFLUXDB_URL", "http://localhost:8086")
INFLUX_TOKEN = os.getenv("INFLUXDB_TOKEN", "my-super-secret-auth-token")
INFLUX_ORG = os.getenv("INFLUXDB_ORG", "fuelapp")
INFLUX_BUCKET = os.getenv("INFLUXDB_BUCKET", "fuel_prices")

STATIONS_TO_CLEAN = ["350", "29"]

def cleanup_influxdb():
    print(f"Cleaning up InfluxDB data for stations: {STATIONS_TO_CLEAN}")
    client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
    delete_api = client.delete_api()

    start = "1970-01-01T00:00:00Z"
    stop = "2099-12-31T23:59:59Z"
    
    for sid in STATIONS_TO_CLEAN:
        predicate = f'_measurement="fuel_price" AND station_id="{sid}"'
        try:
            delete_api.delete(start, stop, predicate, bucket=INFLUX_BUCKET, org=INFLUX_ORG)
            print(f"  Deleted data for station {sid}")
        except Exception as e:
            print(f"  Error deleting data for station {sid}: {e}")
    
    client.close()

def cleanup_app_config():
    # Only remove 350 if it was the one we added as a fallback
    # 29 seemed to be already there.
    sid = 350
    print(f"Removing station {sid} from app configuration...")
    try:
        resp = requests.delete(f"{APP_URL}/api/stations/{sid}")
        if resp.status_code == 200:
            print(f"  Station {sid} removed successfully.")
        else:
            print(f"  Station {sid} not removed (maybe already gone): {resp.status_code}")
    except Exception as e:
        print(f"  Error connecting to app: {e}")

if __name__ == "__main__":
    cleanup_influxdb()
    cleanup_app_config()
    print("Cleanup complete.")
