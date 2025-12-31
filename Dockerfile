# Use Python 3.12 slim image as base
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    gcc \
    curl \
    gnupg \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://repos.influxdata.com/influxdata-archive_compat.key | gpg --dearmor -o /etc/apt/keyrings/influxdata-archive_compat.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/influxdata-archive_compat.gpg] https://repos.influxdata.com/debian stable main" | tee /etc/apt/sources.list.d/influxdata.list \
    && apt-get update \
    && apt-get install -y influxdb2-cli \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements file
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt

# Copy application files
COPY run.py .
COPY app/ ./app/
COPY templates/ ./templates/

# Create config directory
RUN mkdir -p /app/config

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Expose port for web UI
EXPOSE 5000

# Default command - run web UI with Gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "4", "--threads", "2", "--access-logfile", "-", "--error-logfile", "-", "app.web:create_app()"]
