FROM python:3.10-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1

# Create app user
RUN groupadd -r squishy && \
    useradd -r -g squishy -d /app -s /bin/bash squishy

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    ffmpeg \
    libva-dev \
    vainfo \
    mesa-va-drivers \
    intel-media-va-driver-non-free \
    ocl-icd-opencl-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create necessary directories
RUN mkdir -p /app/config /app/data/transcodes && \
    chown -R squishy:squishy /app

# Switch to app user
USER squishy

# Set working directory
WORKDIR /app

# Copy project files
COPY --chown=squishy:squishy . /app/

# Create instance directory
RUN mkdir -p /app/instance && \
    chmod 755 /app/instance

# Install Python dependencies
RUN pip install --upgrade pip && \
    pip install -e .

# Expose port
EXPOSE 5101

# Set up config
RUN if [ ! -f /app/config/config.json ]; then \
    cp /app/config/config.example.json /app/config/config.json; \
    fi

# Command to run
CMD ["python", "run.py"]