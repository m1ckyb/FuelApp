# --- Builder Stage ---
FROM python:3.12-alpine AS builder

WORKDIR /app

# Install build dependencies
RUN apk add --no-cache \
    gcc \
    musl-dev \
    linux-headers \
    libffi-dev \
    curl \
    tzdata

# Install InfluxDB CLI
RUN ARCH=$(uname -m) && \
    if [ "$ARCH" = "x86_64" ]; then ARCH="amd64"; elif [ "$ARCH" = "aarch64" ]; then ARCH="arm64"; fi && \
    curl -fSL https://download.influxdata.com/influxdb/releases/influxdb2-client-2.7.3-linux-${ARCH}.tar.gz | tar xz && \
    mv influx /usr/local/bin/

# Install Python dependencies into a virtual env
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


# --- Runner Stage ---
FROM python:3.12-alpine

WORKDIR /app

# Install runtime dependencies only
RUN apk add --no-cache \
    supervisor \
    curl \
    tzdata

# Copy virtual env from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy influx binary from builder
COPY --from=builder /usr/local/bin/influx /usr/local/bin/influx

# Copy application files
COPY run.py .
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY app/ ./app/
COPY templates/ ./templates/
COPY scripts/ ./scripts/

# Create config directory
RUN mkdir -p /app/config

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Expose port for web UI
EXPOSE 5000

# Default command - run supervisor to manage processes
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
