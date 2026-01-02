#!/usr/bin/env python3
"""
Script to deduplicate InfluxDB data.
It reads all data from the configured bucket, filters out consecutive duplicate prices
(keeping the first occurrence of each price change), and writes to a new bucket.
"""

import sys
import os
import logging
from datetime import datetime

# Add project root to path to import app modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
from app.config import Config

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def main():
    # Load configuration
    config = Config()
    # Try loading from standard locations or env
    config_path = os.getenv('CONFIG_FILE', 'config.yaml')
    if os.path.exists(config_path):
        config.load_from_file(config_path)
    config.load_from_env()

    if not config.influxdb_url or not config.influxdb_token:
        logger.error("InfluxDB credentials not found in config or environment.")
        sys.exit(1)

    source_bucket = config.influxdb_bucket
    target_bucket = f"{source_bucket}_deduped"

    logger.info(f"Connecting to InfluxDB at {config.influxdb_url}")
    logger.info(f"Source Bucket: {source_bucket}")
    logger.info(f"Target Bucket: {target_bucket}")

    client = InfluxDBClient(
        url=config.influxdb_url,
        token=config.influxdb_token,
        org=config.influxdb_org
    )

    try:
        # Check connection
        if client.health().status != "pass":
            logger.error("Failed to connect to InfluxDB.")
            sys.exit(1)

        buckets_api = client.buckets_api()
        
        # Check if source bucket exists
        source_b = buckets_api.find_bucket_by_name(source_bucket)
        if not source_b:
            logger.error(f"Source bucket '{source_bucket}' not found.")
            sys.exit(1)

        # Check/Create target bucket
        target_b = buckets_api.find_bucket_by_name(target_bucket)
        if target_b:
            logger.warning(f"Target bucket '{target_bucket}' already exists.")
            confirm = input("Do you want to delete it and start fresh? [y/N]: ")
            if confirm.lower() == 'y':
                buckets_api.delete_bucket(target_b)
                target_b = buckets_api.create_bucket(bucket_name=target_bucket, org=config.influxdb_org)
                logger.info(f"Re-created bucket '{target_bucket}'.")
            else:
                logger.info("Exiting.")
                sys.exit(0)
        else:
            target_b = buckets_api.create_bucket(bucket_name=target_bucket, org=config.influxdb_org)
            logger.info(f"Created bucket '{target_bucket}'.")

        # Query all data
        logger.info("Querying all data from source bucket... (this may take a while)")
        query_api = client.query_api()
        
        # Query: Sort by time to ensure we process in order
        query = f'''
        from(bucket: "{source_bucket}")
            |> range(start: 0)
            |> filter(fn: (r) => r._measurement == "fuel_price")
            |> filter(fn: (r) => r._field == "price")
            |> sort(columns: ["_time"])
        '''
        
        # Stream results
        tables = query_api.query(query)
        
        total_points = 0
        kept_points = 0
        points_buffer = []
        BATCH_SIZE = 1000

        write_api = client.write_api(write_options=SYNCHRONOUS)

        logger.info("Processing data...")
        
        for table in tables:
            last_val = None
            
            for record in table.records:
                total_points += 1
                val = record.get_value()
                
                # Check for duplicate (allow small float diff)
                is_duplicate = False
                if last_val is not None:
                    if abs(val - last_val) < 0.001:
                        is_duplicate = True
                
                if not is_duplicate:
                    # Keep this point
                    p = Point("fuel_price")
                    
                    # Copy tags
                    for key, value in record.values.items():
                        if key not in ['result', 'table', '_start', '_stop', '_time', '_value', '_field', '_measurement']:
                            p.tag(key, value)
                    
                    p.field("price", val)
                    p.time(record.get_time())
                    
                    points_buffer.append(p)
                    kept_points += 1
                    last_val = val
                
                # Flush buffer
                if len(points_buffer) >= BATCH_SIZE:
                    write_api.write(bucket=target_bucket, record=points_buffer)
                    points_buffer = []
                    print(f"\rProcessed: {total_points}, Kept: {kept_points} ...", end="")

        # Flush remaining
        if points_buffer:
            write_api.write(bucket=target_bucket, record=points_buffer)
            
        print("") # Newline
        logger.info("Processing complete.")
        logger.info(f"Original Records: {total_points}")
        logger.info(f"Deduped Records:  {kept_points}")
        
        if total_points > 0:
            reduction = ((total_points - kept_points) / total_points) * 100
            logger.info(f"Reduction: {reduction:.2f}%")
        
        # Offer to swap
        print("\n--- SWAP BUCKETS ---")
        print(f"Data has been written to '{target_bucket}'.")
        print(f"To finalize, we can delete '{source_bucket}' and rename '{target_bucket}' to '{source_bucket}'.")
        confirm = input("Do you want to swap buckets now? (WARNING: This destroys the original bucket) [y/N]: ")
        
        if confirm.lower() == 'y':
            logger.info(f"Deleting original bucket '{source_bucket}'...")
            buckets_api.delete_bucket(source_b)
            
            logger.info(f"Renaming '{target_bucket}' to '{source_bucket}'...")
            # Updating bucket requires the bucket object (target_b) and the new name
            target_b.name = source_bucket
            buckets_api.update_bucket(target_b)
            
            logger.info("Swap complete! The database is now deduplicated.")
        else:
            logger.info("Skipping swap. You can verify data in Grafana or InfluxDB UI before manually swapping.")
            logger.info(f"New data is in bucket: {target_bucket}")

    except Exception as e:
        logger.exception("An error occurred:")
        sys.exit(1)
    finally:
        client.close()

if __name__ == "__main__":
    main()
