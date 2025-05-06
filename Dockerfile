FROM nvidia/cuda:12.0.1-base-ubuntu22.04

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Install system dependencies including ffmpeg and CUDA development libraries
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-dev \
    ffmpeg \
    libavcodec-dev \
    libavformat-dev \
    libavutil-dev \
    libswscale-dev \
    nvidia-cuda-toolkit \
    nvidia-cuda-dev \
    libavfilter-dev \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Copy requirements and install
COPY pyproject.toml /app/
RUN pip3 install --no-cache-dir -e .

# Copy application code
COPY . /app/

# Create directories if they don't exist
RUN mkdir -p /media /transcode

# Entry point
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Set default environment variables
ENV MEDIA_PATH=/media
ENV TRANSCODE_PATH=/transcode

# Default ports
EXPOSE 5000

# Runtime label for using NVIDIA container
LABEL com.nvidia.volumes.needed="nvidia_driver"

# NVIDIA container required environment variables
ENV NVIDIA_VISIBLE_DEVICES=all
ENV NVIDIA_DRIVER_CAPABILITIES=video,compute,utility

# Default command
ENTRYPOINT ["/entrypoint.sh"]
CMD ["python3", "run.py"]