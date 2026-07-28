import os
import random
from datetime import datetime, timedelta, timezone
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

INFLUX_URL = os.getenv("INFLUXDB_URL", "http://influxdb:8086")
INFLUX_TOKEN = os.getenv("INFLUXDB_TOKEN", "my-super-secret-auth-token")
INFLUX_ORG = os.getenv("INFLUXDB_ORG", "fuelapp")
INFLUX_BUCKET = os.getenv("INFLUXDB_BUCKET", "fuel_prices")

def inject_history():
    print(f"Connecting to InfluxDB at {INFLUX_URL}...")
    client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
    query_api = client.query_api()
    write_api = client.write_api(write_options=SYNCHRONOUS)

    # Query for the last price of each station/fuel type
    query = f'from(bucket: "{INFLUX_BUCKET}") |> range(start: -1d) |> filter(fn: (r) => r._measurement == "fuel_price") |> filter(fn: (r) => r._field == "price") |> last()'
    tables = query_api.query(query)

    points = []
    now = datetime.now(timezone.utc)

    print(f"Found {len(tables)} active price series to generate history for.")

    for table in tables:
        for record in table.records:
            sid = record.values.get("station_id")
            ft = record.values.get("fuel_type")
            name = record.values.get("station_name")
            address = record.values.get("station_address")
            current_price = record.get_value()
            
            # Generate 7 days of history
            for day in range(1, 8):
                # Generate a slightly modified price for history
                historical_price = current_price + random.choice([-2.0, -1.0, 0.0, 1.0, 2.0])
                historical_price = round(max(100.0, min(300.0, historical_price)), 1)
                
                time_point = now - timedelta(days=day)
                
                p = Point("fuel_price") \
                    .tag("station_id", str(sid)) \
                    .tag("station_name", name) \
                    .tag("station_address", address) \
                    .tag("fuel_type", ft) \
                    .field("price", float(historical_price)) \
                    .time(time_point)
                points.append(p)

    if points:
        print(f"Writing {len(points)} historical points to InfluxDB...")
        write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=points)
        print("Successfully injected historical data points!")
    else:
        print("No current price points found to generate history from.")

    client.close()

if __name__ == "__main__":
    inject_history()
