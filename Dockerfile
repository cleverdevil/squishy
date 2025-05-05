FROM python:3.10-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    CONFIG_PATH=/config/config.json

# Create app user
RUN groupadd -r squishy && \
    useradd -r -g squishy -d /app -s /bin/bash squishy

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    ffmpeg \
    libva-dev \
    va-driver-all \
    mesa-va-drivers \
    intel-media-va-driver \
    i965-va-driver \
    libva-drm2 \
    libva-x11-2 \
    libdrm2 \
    libdrm-intel1 \
    libvdpau1 \
    ocl-icd-opencl-dev \
    vainfo \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create necessary directories
RUN mkdir -p /app && \
    chown -R squishy:squishy /app

# Set working directory
WORKDIR /app

# Copy project files
COPY . /app/
RUN chown -R squishy:squishy /app

# Copy entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Switch to app user for pip install
USER squishy

# Install Python dependencies
RUN pip install --upgrade pip && \
    pip install -e .

# Switch back to root for entrypoint
USER root

# Expose port
EXPOSE 5101

# Command to run
ENTRYPOINT ["/entrypoint.sh"]
