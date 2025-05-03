#!/bin/bash
set -e

echo "============================================"
echo "Squishy Container Starting"
echo "============================================"

# Create mount directories with proper permissions
mkdir -p /config /transcodes
chown -R squishy:squishy /config /transcodes

# Copy example config if needed
if [ ! -f /config/config.json ]; then
  echo "No config file found, creating one from example..."
  cp /app/config.json.example /config/config.json
  chown squishy:squishy /config/config.json
fi

echo "============================================"
echo "Hardware Acceleration Setup"
echo "============================================"

# Check for DRI devices
if [ -d "/dev/dri" ]; then
  echo "DRI devices found:"
  ls -la /dev/dri
  
  # Get the group ID of the renderD128 device
  if [ -e "/dev/dri/renderD128" ]; then
    GROUP_ID=$(stat -c "%g" /dev/dri/renderD128)
    GROUP_NAME=$(getent group $GROUP_ID | cut -d: -f1)
    
    echo "RenderD128 device has GID: $GROUP_ID (group name: $GROUP_NAME)"
    
    # Add squishy user to the correct group
    if [ ! -z "$GROUP_NAME" ]; then
      echo "Adding squishy user to $GROUP_NAME group"
      usermod -a -G $GROUP_NAME squishy
    else
      echo "Setting video group ID to $GROUP_ID"
      groupmod -g $GROUP_ID video
      usermod -a -G video squishy
    fi
    
    # Fix permissions
    echo "Setting permissions on /dev/dri"
    chmod -R 755 /dev/dri
    ls -la /dev/dri
  else
    echo "WARNING: /dev/dri exists but renderD128 device not found!"
    ls -la /dev/dri
  fi
else
  echo "WARNING: No DRI devices found! Hardware acceleration will not be available."
fi

echo "============================================"
echo "System Information"
echo "============================================"
uname -a
echo ""

echo "Environment variables:"
echo "LIBVA_DRIVER_NAME: $LIBVA_DRIVER_NAME"
echo "LIBVA_DRIVERS_PATH: $LIBVA_DRIVERS_PATH"
echo ""

echo "GPU Information:"
cat /proc/cpuinfo | grep "model name" | head -1
echo ""

echo "Installed VA-API drivers:"
find /usr/lib/x86_64-linux-gnu/dri/ -name "*_drv_video.so" | sort
echo ""

# Test DRI device access
echo "Testing DRI device access:"
ls -la /dev/dri/renderD128 2>&1 || echo "Cannot access renderD128 device"
echo ""

# Check environment for hardware acceleration
echo "Hardware Acceleration Environment:"
env | grep -E 'LIBVA|DRI|RENDER|VDPAU|VAAPI' || echo "No hardware acceleration environment variables set"
echo ""

# Try both iHD and i965 drivers
echo "Testing iHD driver:"
export LIBVA_DRIVER_NAME=iHD
vainfo --display drm --device /dev/dri/renderD128 2>&1 || echo "iHD driver test failed"
echo ""

echo "Testing i965 driver:"
export LIBVA_DRIVER_NAME=i965
vainfo --display drm --device /dev/dri/renderD128 2>&1 || echo "i965 driver test failed"
echo ""

# Always use the iHD driver for 12th gen Intel
export LIBVA_DRIVER_NAME=iHD
echo "Using driver: $LIBVA_DRIVER_NAME"

echo "============================================"
echo "Starting Squishy Application"
echo "============================================"

# Fix permissions on any mounted volumes
echo "Ensuring correct permissions on mounted volumes"
chown -R squishy:squishy /config /transcodes

# Final check/fix of hardware acceleration permissions for squishy user
if [ -e "/dev/dri/renderD128" ]; then
  echo "Final hardware acceleration setup:"
  # Make sure squishy is in video group
  usermod -a -G video squishy
  # Double-check permissions on renderD128
  chmod 777 /dev/dri/renderD128
  ls -la /dev/dri/renderD128
fi

# Switch to squishy user and run the application
echo "Starting as squishy user..."
exec su -s /bin/bash squishy -c "LIBVA_DRIVER_NAME=iHD python /app/run.py"