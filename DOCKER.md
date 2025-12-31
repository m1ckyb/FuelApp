# Docker Quick Start Guide

This guide will help you get the NSW Fuel Station App running quickly using Docker.

## Prerequisites

- Docker Engine 20.10 or higher
- Docker Compose V2

## Quick Start

1. Clone the repository:
```bash
git clone https://github.com/m1ckyb/FuelApp.git
cd FuelApp
```

2. Start all services:
```bash
docker compose up -d
```

This will start FuelApp with the default configuration from `config.yaml.docker`.

3. Access the services:
   - **FuelApp Web UI**: http://localhost:5000
   - **InfluxDB UI**: http://localhost:8086
   - **Grafana**: http://localhost:3000

## Default Credentials

### InfluxDB
- **URL**: http://localhost:8086
- **Username**: admin
- **Password**: adminpassword
- **Token**: my-super-secret-auth-token
- **Organization**: fuelapp
- **Bucket**: fuel_prices

### Grafana
- **URL**: http://localhost:3000
- **Username**: admin
- **Password**: admin

**⚠️ Important**: Change these default credentials for production use!

## Common Commands

### View logs
```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f fuelapp
docker compose logs -f influxdb
docker compose logs -f grafana
```

### Stop services
```bash
docker compose stop
```

### Start services
```bash
docker compose start
```

### Restart services
```bash
docker compose restart
```

### Stop and remove everything (including volumes)
```bash
docker compose down -v
```

### Rebuild the FuelApp container
```bash
docker compose build fuelapp
docker compose up -d fuelapp
```

## Finding Station IDs

You can find station IDs from:
1. The NSW FuelCheck mobile app
2. The NSW FuelCheck website: https://www.fuelcheck.nsw.gov.au/
3. Run the app once and check the logs to see all available stations

## Configuration

### Default Configuration

By default, the docker-compose setup mounts `config.yaml.docker` which includes example stations (IDs 350 and 4711). The FuelApp container also uses environment variables to configure the InfluxDB connection automatically.

### Customizing Station Configuration

**Option 1: Edit config.yaml.docker directly** (Simplest)

Edit `config.yaml.docker` to change the monitored stations:
```yaml
stations:
  - station_id: 350  # Your station ID
    fuel_types:
      - E10
      - U91
```

Then restart the service:
```bash
docker compose restart fuelapp
```

**Option 2: Use your own config file**

1. Create your own configuration file:
```bash
cp config.yaml.docker config.yaml
# Edit config.yaml with your preferences
```

2. Update `docker-compose.yml` to mount your file:
```yaml
volumes:
  - ./config.yaml:/app/config.yaml:ro  # Changed from config.yaml.docker
```

3. Restart the service:
```bash
docker compose up -d fuelapp
```

### Environment Variables

The docker-compose setup uses environment variables to configure the FuelApp connection to InfluxDB. You can modify these in `docker-compose.yml`:

```yaml
fuelapp:
  environment:
    - INFLUXDB_URL=http://influxdb:8086
    - INFLUXDB_TOKEN=my-super-secret-auth-token
    - INFLUXDB_ORG=fuelapp
    - INFLUXDB_BUCKET=fuel_prices
```

## Customization

### Change Ports

Edit `docker-compose.yml` to change exposed ports:

```yaml
fuelapp:
  ports:
    - "8080:5000"  # Access on port 8080 instead of 5000

influxdb:
  ports:
    - "9086:8086"  # Access on port 9086 instead of 8086
```

### Use Different InfluxDB Credentials

Edit the `influxdb` service environment variables in `docker-compose.yml`:

```yaml
influxdb:
  environment:
    - DOCKER_INFLUXDB_INIT_USERNAME=myuser
    - DOCKER_INFLUXDB_INIT_PASSWORD=mypassword
    - DOCKER_INFLUXDB_INIT_ADMIN_TOKEN=my-custom-token
```

Don't forget to update the `fuelapp` service environment variables to match!

## Troubleshooting

### FuelApp won't start

Check if InfluxDB is healthy:
```bash
docker compose ps
```

View FuelApp logs:
```bash
docker compose logs fuelapp
```

### Cannot access web UI

Make sure the container is running:
```bash
docker compose ps
```

Check if port 5000 is available:
```bash
netstat -tuln | grep 5000
```

### Data persistence

All data is stored in Docker volumes:
- `fuelapp_influxdb-data` - InfluxDB data
- `fuelapp_influxdb-config` - InfluxDB configuration
- `fuelapp_grafana-data` - Grafana dashboards
- `fuelapp_fuelapp-data` - FuelApp configuration database

To back up volumes:
```bash
docker run --rm -v fuelapp_influxdb-data:/data -v $(pwd):/backup alpine tar czf /backup/influxdb-backup.tar.gz -C /data .
```

## Production Deployment

For production deployment:

1. **Change all default credentials** in `docker-compose.yml`
2. Use a production WSGI server instead of Flask's development server
3. Set up SSL/TLS certificates
4. Configure proper backup strategies
5. Monitor resource usage
6. Set appropriate restart policies

## Support

For issues and questions:
- GitHub Issues: https://github.com/m1ckyb/FuelApp/issues
- Check the main README.md for detailed documentation
