import os
import requests
import time
from datetime import datetime, timedelta, timezone
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

# Configuration
# If running inside container, these defaults might need adjustment or use env vars
APP_URL = os.getenv("APP_URL", "http://localhost:5000")
INFLUX_URL = os.getenv("INFLUXDB_URL", "http://localhost:8086")
INFLUX_TOKEN = os.getenv("INFLUXDB_TOKEN", "my-super-secret-auth-token")
INFLUX_ORG = os.getenv("INFLUXDB_ORG", "fuelapp")
INFLUX_BUCKET = os.getenv("INFLUXDB_BUCKET", "fuel_prices")

STATION_ID = 350  # 7-Eleven
FUEL_TYPES = ["E10", "P98"]

def setup_station():
    print(f"Adding station {STATION_ID}...")
    try:
        resp = requests.post(f"{APP_URL}/api/stations", json={
            "station_id": STATION_ID,
            "fuel_types": FUEL_TYPES
        })
        if resp.status_code in [200, 201]:
            print("Station added successfully.")
        elif resp.status_code == 400 and "already exists" in resp.text:
            print("Station already exists.")
        else:
            print(f"Failed to add station: {resp.status_code} {resp.text}")
            return False
    except Exception as e:
        print(f"Error connecting to app: {e}")
        return False
    return True

def get_first_available_station():
    print("Fetching current prices to find a target station...")
    try:
        resp = requests.get(f"{APP_URL}/api/prices/current")
        if resp.status_code == 200:
            data = resp.json()
            if 'prices' in data and len(data['prices']) > 0:
                target = data['prices'][0]
                print(f"Targeting Station {target['station_id']} ({target['station_name']})")
                return target['station_id'], target['prices']
            else:
                print("No stations with prices found.")
    except Exception as e:
        print(f"Error fetching prices: {e}")
    return None, None

def inject_history(station_id, current_prices):
    print(f"Injecting historical data for Station {station_id}...")
    client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
    write_api = client.write_api(write_options=SYNCHRONOUS)
    
    points = []
    time_past = datetime.now(timezone.utc) - timedelta(days=1)
    
    # Iterate over available fuel types for this station
    for fuel_type, price in current_prices.items():
        # Toggle strategy based on fuel type to show both trends if possible
        # Or just alternate based on something else
        
        # Strategy:
        # If E10 -> Trend UP
        # If P98 -> Trend DOWN
        # Else -> Trend UP
        
        if fuel_type == "E10" or fuel_type == "U91":
            old_price = price - 10.0 # Price ROSE (Up/Red)
            print(f"Injecting {fuel_type}: Current={price}, Old={old_price} (Should show UP/Red)")
        elif fuel_type == "P95":
            old_price = price # Price STABLE (Dash/Grey)
            print(f"Injecting {fuel_type}: Current={price}, Old={old_price} (Should show STABLE/Dash)")
        else:
            old_price = price + 10.0 # Price DROPPED (Down/Green)
            print(f"Injecting {fuel_type}: Current={price}, Old={old_price} (Should show DOWN/Green)")
            
        p = Point("fuel_price") \
            .tag("station_id", str(station_id)) \
            .tag("fuel_type", fuel_type) \
            .field("price", float(old_price)) \
            .time(time_past)
        points.append(p)

    if points:
        write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=points)
        print("Data injected successfully.")
    else:
        print("No points to inject.")
        
    client.close()

if __name__ == "__main__":
    # First try to find an existing station
    sid, prices = get_first_available_station()
    
    if not sid:
        # If none, try adding 350
        print("No active stations found. Adding fallback station 350...")
        if setup_station():
            time.sleep(5)
            sid, prices = get_first_available_station()
            
    if sid and prices:
        inject_history(sid, prices)
    else:
        print("Failed to find or configure a station with prices.")
