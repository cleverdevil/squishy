# effeffmpeg

**FFmpeg Hardware-Aware Transcoder**

A Python wrapper around FFmpeg that simplifies video transcoding with hardware
acceleration. It automatically detects hardware capabilities and can fall back
to software encoding when needed.

## Features

- Automatic hardware acceleration detection (currently supports VAAPI)
- Smart fallback to software encoding when hardware acceleration isn't available
- Resolution scaling with common presets (360p, 480p, 720p, 1080p, 2160p)
- Support for various video and audio codecs with container compatibility validation
- Quality control using CRF or bitrate settings
- Preset system for common encoding configurations:
  - Load presets from JSON files
  - Define presets directly as Python data structures
- Command-line interface
- Python API for integration into other applications
- Non-blocking operation with live progress tracking
- Real-time progress reporting callback function

## Installation

No special installation is required. Simply copy the `effeffmpeg.py` file to
your project directory.

Requirements:
- Python 3.6 or later
- FFmpeg installed on your system
- `ffprobe` command (usually installed alongside FFmpeg)

## Command-line Usage

### Detect hardware capabilities

```bash
python3 effeffmpeg.py detect capabilities.json
```

### List available presets

```bash
python3 effeffmpeg.py presets --file presets.json
```

### Transcode a video using command-line options

```bash
python3 effeffmpeg.py transcode --to h264 --scale 720p --audio aac --run input.mp4 output.mp4
```

### Transcode using a preset

```bash
python3 effeffmpeg.py transcode --preset 720p-high --run input.mp4 output.mp4
```

## Python API Usage

You can import `effeffmpeg` as a Python module and use its functions in your own
code. The module includes support for non-blocking operation, progress tracking,
and presets defined as Python dictionaries.

## Preset System

The module includes a flexible preset system that allows you to define common encoding configurations and reuse them. Presets can be defined in two ways:

1. **JSON files**: Store presets in JSON files and load them at runtime
2. **Python dictionaries**: Define presets directly in your Python code

### Preset Format

Each preset is a dictionary with the following keys:

- `container`: The container format (e.g., ".mp4", ".mkv", ".webm")
- `codec`: The video codec to use (e.g., "h264", "hevc", "vp9")
- `scale`: The target resolution (e.g., "360p", "720p", "1080p")
- `audio_codec`: The audio codec to use (e.g., "aac", "opus", "flac")
- `audio_bitrate`: The audio bitrate (e.g., "128k", "192k")
- `bitrate` or `crf`: The video quality setting (bitrate-based or quality-based)
- `allow_fallback`: Whether to allow fallback to software encoding

## Preset Collections

The module comes with two preset collection JSON files in the `presets` directory:

### Compatible Presets (presets-compatible.json)

These presets focus on compatibility using H.264/MP4 with different bitrates:

```json
{
  "presets": {
    "360p-low": {
      "container": ".mp4",
      "codec": "h264",
      "scale": "360p",
      "audio_codec": "aac",
      "audio_bitrate": "64k",
      "bitrate": "500k",
      "allow_fallback": true
    },
    "360p-medium": {
      "container": ".mp4",
      "codec": "h264",
      "scale": "360p",
      "audio_codec": "aac",
      "audio_bitrate": "96k",
      "bitrate": "750k",
      "allow_fallback": true
    },
    "720p-medium": {
      "container": ".mp4",
      "codec": "h264",
      "scale": "720p",
      "audio_codec": "aac",
      "audio_bitrate": "128k",
      "bitrate": "2.5M",
      "allow_fallback": true
    },
    "1080p-high": {
      "container": ".mp4",
      "codec": "h264",
      "scale": "1080p",
      "audio_codec": "aac",
      "audio_bitrate": "192k",
      "bitrate": "8M",
      "allow_fallback": true
    }
    // ... and more
  }
}
```

### Quality Presets (presets-quality.json)

These presets focus on quality using HEVC/MKV with CRF-based encoding:

```json
{
  "presets": {
    "360p-low": {
      "container": ".mkv",
      "codec": "hevc",
      "scale": "360p",
      "audio_codec": "aac",
      "audio_bitrate": "64k",
      "crf": 28,
      "allow_fallback": true
    },
    "720p-medium": {
      "container": ".mkv",
      "codec": "hevc",
      "scale": "720p",
      "audio_codec": "aac",
      "audio_bitrate": "128k",
      "crf": 24,
      "allow_fallback": true
    },
    "1080p-high": {
      "container": ".mkv",
      "codec": "hevc",
      "scale": "1080p",
      "audio_codec": "aac",
      "audio_bitrate": "192k",
      "crf": 20,
      "allow_fallback": true
    },
    "2160p-high": {
      "container": ".mkv",
      "codec": "hevc",
      "scale": "2160p",
      "audio_codec": "aac",
      "audio_bitrate": "256k",
      "crf": 18,
      "allow_fallback": true
    }
    // ... and more
  }
}
```

### Using Preset Collections

```python
import effeffmpeg

# Using a preset from a JSON file
effeffmpeg.transcode(
    input_file="input.mp4",
    output_file="output.mp4",
    preset_name="720p-high",        # Name of the preset to use
    presets_file="presets/presets-compatible.json",  # Path to the presets file
    overwrite=True
)

# Using a quality-focused preset
effeffmpeg.transcode(
    input_file="input.mp4",
    output_file="output.mkv",
    preset_name="1080p-high",       # Name of the preset to use
    presets_file="presets/presets-quality.json",  # Path to the quality presets
    overwrite=True
)
```

## Example Scripts

Several example scripts are provided in the `examples` directory to demonstrate
different aspects of the API:

```bash
# Basic examples
python examples/example.py input_file output_dir

# Debug examples with detailed progress reporting
python examples/example_debug.py input_file output_dir

# Non-blocking API examples
python examples/example_nonblocking.py input_file output_dir

# Preset system examples
python examples/example_presets.py input_file output_dir
```

Each example script demonstrates different features of the library and requires:
- `input_file`: Path to an input video file to process
- `output_dir`: Directory where output files will be saved

### Basic Transcoding

```python
import effeffmpeg

# Transcode a video with hardware acceleration if available
effeffmpeg.transcode(
    input_file="input.mp4",
    output_file="output.mp4",
    codec="h264",
    scale="720p",
    audio_codec="aac",
    audio_bitrate="128k",
    allow_fallback=True,  # Allow fallback to software encoding if needed
    overwrite=True        # Overwrite output file if it exists
)
```

### Quality-Based Encoding

```python
import effeffmpeg

# Use CRF for quality-based encoding (software encoding only)
effeffmpeg.transcode(
    input_file="input.mp4",
    output_file="output.mkv",
    codec="hevc",
    scale="1080p",
    audio_codec="libopus",
    audio_bitrate="192k",
    crf=22,               # Lower CRF = higher quality
    force_software=True,  # Force software encoding
    overwrite=True
)
```

### Dry Run (Return Command Without Executing)

```python
import effeffmpeg

# Get the FFmpeg command without running it
command = effeffmpeg.transcode(
    input_file="input.mp4",
    output_file="output.mp4",
    codec="h264",
    scale="720p",
    audio_codec="aac",
    dry_run=True          # Return command without executing
)

print("FFmpeg command:")
print(" ".join(command))
```

### Using Presets Defined as Python Dictionaries

```python
import effeffmpeg

# Define presets as a Python dictionary
PRESETS = {
    "web_medium": {
        "container": ".mp4",
        "codec": "h264",
        "scale": "720p",
        "audio_codec": "aac",
        "audio_bitrate": "128k",
        "crf": 23,
        "allow_fallback": True
    },
    "web_high": {
        "container": ".mp4",
        "codec": "h264",
        "scale": "1080p",
        "audio_codec": "aac",
        "audio_bitrate": "192k",
        "crf": 20,
        "allow_fallback": True
    },
    "archive": {
        "container": ".mkv",
        "codec": "hevc",
        "audio_codec": "libopus",
        "audio_bitrate": "160k",
        "crf": 18,
        "allow_fallback": True
    }
}

# Transcode using a preset from the Python dictionary
effeffmpeg.transcode(
    input_file="input.mp4",
    output_file="output.mp4",
    preset_name="web_medium",    # Specify the preset name
    presets_data=PRESETS,        # Pass the dictionary of presets
    overwrite=True
)

# You can also override preset values
effeffmpeg.transcode(
    input_file="input.mp4",
    output_file="output_custom.mp4",
    preset_name="web_high",
    presets_data=PRESETS,
    scale="720p",                # Override the preset's scale setting
    bitrate="3M",                # Override with bitrate instead of using preset's CRF
    overwrite=True
)
```

### Hardware Capability Detection

```python
import effeffmpeg
import json

# Detect hardware acceleration capabilities
capabilities = effeffmpeg.detect_capabilities()

# Print available hardware encoders
if capabilities["hwaccel"]:
    print(f"Hardware acceleration available: {capabilities['hwaccel']}")
    print(f"Available encoders: {list(capabilities['encoders'].keys())}")
else:
    print("No hardware acceleration detected, using software encoding")

# Save capabilities to a file for future use
with open("capabilities.json", "w") as f:
    json.dump(capabilities, f, indent=2)
```

### Non-Blocking Transcoding with Progress Tracking

```python
import effeffmpeg
import time

# Define a progress callback function
def progress_handler(line, progress):
    if progress is not None:
        print(f"Progress: {progress*100:.1f}% - {line}")

# Start a non-blocking transcode
process = effeffmpeg.transcode(
    input_file="input.mp4",
    output_file="output.mkv",
    codec="hevc",
    scale="1080p",
    audio_codec="libopus",
    audio_bitrate="192k",
    overwrite=True,
    non_blocking=True,  # Enable non-blocking mode
    progress_callback=progress_handler  # Register progress callback
)

# Do other work while transcoding is in progress
while not process.finished:
    print(f"Elapsed time: {process.get_elapsed_time():.1f} seconds")
    time.sleep(1)

    # Check if the process has completed
    if process.process.poll() is not None:
        process.finished = True
        process.returncode = process.process.returncode

# Get the result when done
print(f"Transcoding completed with return code: {process.returncode}")
print(f"Last few lines of output: {process.stderr_buffer[-5:]}")
```

### Using TranscodeProcess as a Context Manager

```python
import effeffmpeg

# Define a progress callback
def progress_handler(line, progress):
    if progress is not None:
        print(f"Progress: {progress*100:.1f}%")

# Generate the FFmpeg command
command = effeffmpeg.generate_ffmpeg_command(
    input_file="input.mp4",
    output_file="output.mp4",
    codec="h264",
    scale="720p",
    audio_codec="aac",
    capabilities=effeffmpeg.detect_capabilities(quiet=True),
    allow_fallback=True,
    overwrite=True
)

# Use context manager for automatic resource cleanup
with effeffmpeg.TranscodeProcess(command, progress_handler) as process:
    # The process is automatically started when entering the context
    print("Transcoding in progress...")

    # Wait for completion
    while not process.finished:
        if process.process.poll() is not None:
            process.finished = True
            process.returncode = process.process.returncode
        time.sleep(0.5)

# Process is automatically terminated when exiting the context
print(f"Transcoding completed with return code: {process.returncode}")
```

## API Reference

### `transcode()`

```python
def transcode(
    input_file,             # Path to input video file
    output_file,            # Path to output video file
    codec=None,             # Target video codec (h264, hevc, vp9, av1)
    scale=None,             # Target resolution (360p, 480p, 720p, 1080p, 2160p)
    audio_codec=None,       # Target audio codec (copy, aac, flac, opus, libopus)
    allow_fallback=True,    # Allow software fallback if hardware encoding fails
    force_software=False,   # Force software encoding
    crf=None,               # Constant Rate Factor (0-51, lower is better)
    bitrate=None,           # Target video bitrate (e.g. "2M")
    audio_bitrate=None,     # Target audio bitrate (e.g. "128k")
    flac_compression=None,  # FLAC compression level (0-8)
    capabilities_file=None, # Path to capabilities JSON file
    dry_run=False,          # Return command without executing
    overwrite=False,        # Force overwrite of output file
    quiet=False,            # Suppress informational output
    non_blocking=False,     # Enable non-blocking operation
    progress_callback=None, # Function to call with progress updates
    preset_name=None,       # Name of the preset to use
    presets_data=None,      # Python dictionary containing preset configurations
    presets_file=None       # Path to JSON file containing preset configurations
)
```

Returns:
- If `dry_run=True`: Returns the FFmpeg command as a list of strings
- If `non_blocking=True`: Returns a `TranscodeProcess` object to manage the process
- Otherwise: Returns a `subprocess.CompletedProcess` object with the result
```

### `detect_capabilities()`

```python
def detect_capabilities(
    quiet=False             # Suppress informational output
)
```

### `generate_ffmpeg_command()`

```python
def generate_ffmpeg_command(
    input_file,             # Path to input video file
    output_file,            # Path to output video file
    capabilities,           # Dictionary of hardware capabilities
    codec=None,             # Target video codec
    scale=None,             # Target resolution
    audio_codec=None,       # Target audio codec
    allow_fallback=False,   # Allow software fallback if hardware encoding fails
    force_software=False,   # Force software encoding
    crf=None,               # Constant Rate Factor (0-51, lower is better)
    bitrate=None,           # Target video bitrate (e.g. "2M")
    audio_bitrate=None,     # Target audio bitrate (e.g. "128k")
    flac_compression=None,  # FLAC compression level (0-8)
    overwrite=False,        # Add -y flag to force overwrite
    quiet=False             # Suppress informational output
)
```

### `TranscodeProcess` Class

```python
class TranscodeProcess:
    """
    Class to manage an FFmpeg transcoding process with live output access.
    """

    def __init__(self, command, progress_callback=None, debug=False):
        # Initialize with FFmpeg command, optional progress callback, and debug flag

    def start(self):
        # Start the FFmpeg process and output capture threads

    def wait(self, timeout=None):
        # Wait for the process to complete with optional timeout

    def terminate(self):
        # Terminate the FFmpeg process

    def get_stdout(self):
        # Get the captured stdout output as a string

    def get_stderr(self):
        # Get the captured stderr output as a string

    def get_elapsed_time(self):
        # Get the elapsed time in seconds since the process was started

    # Context manager protocol support
    def __enter__(self):
        # Enter context manager (starts process if not already started)

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Exit context manager (terminates process if still running)

    # Attributes
    command          # The FFmpeg command (list of strings)
    process          # The subprocess.Popen object
    stdout_buffer    # List of captured stdout lines
    stderr_buffer    # List of captured stderr lines
    started          # Whether the process has been started
    finished         # Whether the process has finished
    returncode       # The process return code, or None if still running
```

## License

This project is open-source and available under the MIT License.