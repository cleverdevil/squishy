"""
effeffmpeg - FFmpeg Hardware-Aware Transcoder

This module provides a wrapper around FFmpeg to simplify video transcoding
with hardware acceleration. It detects available hardware acceleration capabilities
and can fall back to software encoding when needed.

It can be used as a CLI tool or imported as a module in other Python applications.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union, Any, Callable, BinaryIO

def run_command(command: str) -> Tuple[bool, str]:
    """
    Run a shell command and return the success status and output.

    Args:
        command: The shell command to execute

    Returns:
        A tuple containing (success_status, command_output)
    """
    try:
        result = subprocess.run(command, shell=True, check=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return True, result.stderr.decode()
    except subprocess.CalledProcessError as e:
        return False, e.stderr.decode()

def parse_resolution(res: str) -> Tuple[int, int]:
    """
    Convert a resolution string to width and height dimensions.

    Args:
        res: Resolution string (e.g., "720p", "1080p")

    Returns:
        A tuple of (width, height) in pixels
    """
    presets = {
        "360p": (640, 360),
        "480p": (854, 480),
        "720p": (1280, 720),
        "1080p": (1920, 1080),
        "2160p": (3840, 2160)
    }
    return presets.get(res, (1280, 720))

def validate_quality_options(encoder, crf, bitrate, audio_codec, audio_bitrate, flac_compression, context="CLI flag", quiet=False):
    """
    Validate encoding quality options for consistency and correctness.

    Args:
        encoder: Hardware encoder to use (if any)
        crf: Constant Rate Factor value
        bitrate: Video bitrate
        audio_codec: Audio codec to use
        audio_bitrate: Audio bitrate
        flac_compression: FLAC compression level
        context: Context for error messages ("CLI flag" or "preset")
        quiet: Whether to suppress error messages

    Raises:
        ValueError: If any validation fails
    """
    errors = []

    # Only validate CRF if it's provided
    if crf is not None:
        if not isinstance(crf, int) or not (0 <= crf <= 51):
            errors.append(f"CRF must be between 0 (best) and 51 (worst). Got: {crf}")
        if encoder is not None:
            if not quiet:
                print("[!] CRF is only allowed with software encoding. CRF will be ignored when hardware encoding is used.")
        if bitrate is not None:
            errors.append("Cannot use both CRF and bitrate simultaneously.")

    if bitrate is not None:
        if not isinstance(bitrate, str) or not bitrate.endswith(('k', 'M')):
            errors.append(f"Bitrate must end with 'k' or 'M', e.g., '800k' or '2M'. Got: {bitrate}")

    if audio_bitrate is not None:
        if audio_codec == "copy":
            errors.append("Audio bitrate cannot be set when audio codec is 'copy'.")
        if not isinstance(audio_bitrate, str) or not audio_bitrate.endswith(('k', 'M')):
            errors.append(f"Audio bitrate must end with 'k' or 'M', e.g., '128k'. Got: {audio_bitrate}")
        if audio_codec not in ("aac", "opus", "libopus"):
            errors.append(f"Audio bitrate is only valid for 'aac', 'opus', and 'libopus'. Selected: '{audio_codec}'")

    if flac_compression is not None:
        if not isinstance(flac_compression, int) or not (0 <= flac_compression <= 8):
            errors.append(f"FLAC compression must be between 0 and 8. Got: {flac_compression}")
        if audio_codec != "flac":
            errors.append(f"FLAC compression is only valid when audio codec is 'flac'. Selected: '{audio_codec}'")

    if errors:
        error_msg = f"Invalid {context} settings:" + "".join(f"\n- {e}" for e in errors)
        if not quiet:
            print(f"[✗] {error_msg}")
        raise ValueError(error_msg)

def validate_codecs(container, video_codec, audio_codec, context="CLI flag", quiet=False):
    """
    Validate codec compatibility with container format.

    Args:
        container: Container format extension (e.g., ".mp4", ".mkv")
        video_codec: Video codec to use
        audio_codec: Audio codec to use
        context: Context for error messages ("CLI flag" or "preset")
        quiet: Whether to suppress error messages

    Raises:
        ValueError: If any validation fails
    """
    matrix = {
        ".mp4": {"video": ["h264", "hevc"], "audio": ["aac", "copy"], "default": ("h264", "aac")},
        ".mkv": {"video": ["h264", "hevc", "vp9"], "audio": ["aac", "flac", "opus", "libopus", "copy"], "default": ("hevc", "aac")},
        ".webm": {"video": ["vp9", "av1"], "audio": ["opus", "libopus"], "default": ("vp9", "libopus")},
        ".mov": {"video": ["h264", "hevc"], "audio": ["aac", "copy"], "default": ("h264", "aac")}
    }

    errors = []

    if container not in matrix:
        errors.append(f"Unsupported container format '{container}'. Allowed: {', '.join(matrix)}")
    else:
        valid_video = matrix[container]["video"]
        valid_audio = matrix[container]["audio"]

        if video_codec not in valid_video:
            errors.append(f"Invalid video codec '{video_codec}' for '{container}'. Valid: {', '.join(valid_video)}")

        if audio_codec not in valid_audio:
            errors.append(f"Invalid audio codec '{audio_codec}' for '{container}'. Valid: {', '.join(valid_audio)}")

    if errors:
        error_msg = f"Invalid {context} settings:" + "".join(f"\n- {e}" for e in errors)
        if not quiet:
            print(f"[✗] {error_msg}")
        raise ValueError(error_msg)

def infer_defaults_from_extension(output_file):
    ext = Path(output_file).suffix.lower()
    defaults = {
        ".mp4": ("h264", "aac"),
        ".mkv": ("hevc", "aac"),
        ".webm": ("vp9", "libopus"),
        ".mov": ("h264", "aac")
    }
    if ext not in defaults:
        print(f"[✗] Unsupported container extension '{ext}'. Must be one of: {', '.join(defaults)}")
        sys.exit(1)
    return ext, *defaults[ext]

def validate_presets_data(presets_data, quiet=False):
    """
    Validate a dictionary of presets data.

    Args:
        presets_data: Dictionary containing preset configurations
        quiet: Whether to suppress error messages

    Returns:
        True if validation succeeds

    Raises:
        ValueError: If the presets data is invalid
    """
    if not isinstance(presets_data, dict):
        error_msg = "Presets data must be a dictionary"
        if not quiet:
            print(f"[✗] {error_msg}")
        raise ValueError(error_msg)

    # Validate all presets in the dictionary
    for name, config in presets_data.items():
        validate_preset_config(name, config, quiet=quiet)
    
    return True

def load_presets(presets_file, quiet=False):
    """
    Load presets from a JSON file.

    Args:
        presets_file: Path to the presets JSON file
        quiet: Whether to suppress error messages

    Returns:
        Dictionary of preset configurations

    Raises:
        FileNotFoundError: If the presets file doesn't exist
        json.JSONDecodeError: If the presets file contains invalid JSON
        ValueError: If any preset configuration is invalid
    """
    try:
        with open(presets_file, 'r') as f:
            data = json.load(f)
        presets = data.get('presets', {})

        # Validate all presets
        validate_presets_data(presets, quiet=quiet)

        return presets
    except FileNotFoundError:
        error_msg = f"Presets file '{presets_file}' not found."
        if not quiet:
            print(f"[✗] {error_msg}")
        raise FileNotFoundError(error_msg)
    except json.JSONDecodeError:
        error_msg = f"Error parsing presets file '{presets_file}'. Invalid JSON."
        if not quiet:
            print(f"[✗] {error_msg}")
        raise

def validate_config(
    config,
    name="Configuration",
    context="configuration",
    quiet=False,
    check_container=True
):
    """
    Validate a configuration (preset or command-line options).

    This is a unified validation function that handles both preset and CLI validation
    with the same validation logic.

    Args:
        config: Dictionary of configuration settings
        name: Name for reference in error messages
        context: Context for error messages
        quiet: Whether to suppress error messages
        check_container: Whether to check for container field (required for presets only)

    Raises:
        ValueError: If any validation fails
    """
    errors = []

    # Check required fields for presets
    container = config.get('container')
    if check_container and not container:
        errors.append("Missing required 'container' field.")

    # Validate codec compatibility
    if container and 'codec' in config and config['codec'] is not None and 'audio_codec' in config and config['audio_codec'] is not None:
        try:
            validate_codecs(
                container=container,
                video_codec=config['codec'],
                audio_codec=config['audio_codec'],
                context=context,
                quiet=True  # Suppress output, we'll collect the error
            )
        except ValueError as e:
            # Extract the error message excluding the "Invalid settings:" prefix
            error_msg = str(e)
            if "Invalid" in error_msg and ":" in error_msg:
                error_details = error_msg.split(":", 1)[1].strip()
                for line in error_details.split("\n"):
                    if line.startswith("- "):
                        errors.append(line[2:])  # Remove the "- " prefix

    # Validate scale
    scale = config.get('scale')
    if scale is not None and scale not in ["360p", "480p", "720p", "1080p", "2160p"]:
        errors.append(f"Invalid scale '{scale}'. Valid values: 360p, 480p, 720p, 1080p, 2160p")

    # Validate quality options
    try:
        validate_quality_options(
            encoder=None,  # We don't know the encoder here
            crf=config.get('crf'),
            bitrate=config.get('bitrate'),
            audio_codec=config.get('audio_codec'),
            audio_bitrate=config.get('audio_bitrate'),
            flac_compression=config.get('flac_compression'),
            context=context,
            quiet=True  # Suppress output, we'll collect the error
        )
    except ValueError as e:
        # Extract the error message excluding the "Invalid settings:" prefix
        error_msg = str(e)
        if "Invalid" in error_msg and ":" in error_msg:
            error_details = error_msg.split(":", 1)[1].strip()
            for line in error_details.split("\n"):
                if line.startswith("- "):
                    errors.append(line[2:])  # Remove the "- " prefix

    if errors:
        error_msg = f"Invalid {context} '{name}':" + "".join(f"\n- {e}" for e in errors)
        if not quiet:
            print(f"[✗] {error_msg}")
        raise ValueError(error_msg)

    return True


def validate_preset_config(preset_name, config, quiet=False):
    """
    Validate a preset configuration.

    Args:
        preset_name: Name of the preset
        config: Preset configuration dictionary
        quiet: Whether to suppress error messages

    Raises:
        ValueError: If any validation fails
    """
    return validate_config(
        config=config,
        name=preset_name,
        context="preset",
        quiet=quiet,
        check_container=True
    )

def detect_capabilities(quiet: bool = False) -> Dict[str, Any]:
    """
    Detect hardware acceleration capabilities on the system.

    Tests for VAAPI hardware encoders by running small FFmpeg test commands.

    Args:
        quiet: If True, suppresses console output during detection

    Returns:
        A dictionary containing detected capabilities:
        {
            "hwaccel": Detected hardware acceleration API (or None),
            "device": Path to the hardware device,
            "encoders": Dictionary mapping codec names to hardware encoders,
            "fallback_encoders": Dictionary mapping codec names to software encoders
        }
    """
    capabilities = {
        "hwaccel": None,
        "device": "/dev/dri/renderD128",
        "encoders": {},
        "fallback_encoders": {
            "h264": "libx264",
            "hevc": "libx265",
            "vp9": "libvpx-vp9",
            "av1": "libaom-av1"
        }
    }

    device = capabilities["device"]

    if not os.path.exists(device):
        if not quiet:
            print(f"[✗] VAAPI device {device} does not exist.")
        return capabilities

    tests = {
        "h264_vaapi": (
            f"ffmpeg -hide_banner -init_hw_device vaapi=va:{device} -filter_hw_device va "
            f"-f lavfi -i testsrc=duration=1:size=1280x720:rate=30 -vf 'format=nv12,hwupload' "
            f"-c:v h264_vaapi -t 1 -f null -"
        ),
        "hevc_vaapi": (
            f"ffmpeg -hide_banner -init_hw_device vaapi=va:{device} -filter_hw_device va "
            f"-f lavfi -i testsrc=duration=1:size=1280x720:rate=30 -vf 'format=nv12,hwupload' "
            f"-c:v hevc_vaapi -t 1 -f null -"
        )
    }

    for encoder, cmd in tests.items():
        if not quiet:
            print(f"Testing {encoder}...")
        success, output = run_command(cmd)
        if success:
            if not quiet:
                print(f"[✓] {encoder} supported")
            capabilities["hwaccel"] = "vaapi"
            capabilities["encoders"][encoder.replace("_vaapi", "")] = encoder
        elif not quiet:
            print(f"[✗] {encoder} not supported:\n{output.strip()}\n")

    return capabilities

class TranscodeProcess:
    """
    Class to manage an FFmpeg transcoding process with live output access.

    This class handles starting the FFmpeg process, capturing its output,
    managing the process lifecycle, and providing access to output streams.

    Attributes:
        command (List[str]): The FFmpeg command used to start the process
        process (subprocess.Popen): The running subprocess
        stdout_thread (threading.Thread): Thread that reads from stdout
        stderr_thread (threading.Thread): Thread that reads from stderr
        stdout_buffer (List[str]): Lines captured from stdout
        stderr_buffer (List[str]): Lines captured from stderr
        progress_callback (Callable): Function to call with progress updates
        started (bool): Whether the process has been started
        finished (bool): Whether the process has finished
        returncode (Optional[int]): The process return code, or None if still running
    """

    def __init__(self, command: List[str], progress_callback: Optional[Callable[[str, Optional[float]], None]] = None, debug: bool = False):
        """
        Initialize a new TranscodeProcess.

        Args:
            command: List of strings forming the FFmpeg command
            progress_callback: Optional function to call with each line of ffmpeg output
            debug: Enable debug output for progress tracking
        """
        self.command = command
        self.process = None
        self.stdout_thread = None
        self.stderr_thread = None
        self.stdout_buffer = []
        self.stderr_buffer = []
        self.progress_callback = progress_callback
        self.started = False
        self.finished = False
        self.returncode = None
        self._start_time = None
        # Improved regex patterns for more robust detection
        # Pattern for frame number (e.g., frame=  123)
        self._progress_pattern = re.compile(r'frame=\s*(\d+)')
        # Pattern for duration (e.g., Duration: 00:05:23.45)
        self._duration_pattern = re.compile(r'Duration:\s*(\d+):(\d+):(\d+)(?:\.(\d+))?')
        # Pattern for time progress (e.g., time=00:01:23.45)
        self._time_pattern = re.compile(r'time=\s*(\d+):(\d+):(\d+)(?:\.(\d+))?')
        # Pattern for speed (e.g., speed=2.3x)
        self._speed_pattern = re.compile(r'speed=\s*([\d.]+)x')
        self._total_frames = None
        self._duration_seconds = None
        self.debug = debug

    def _read_output(self, stream: BinaryIO, buffer: List[str], is_stderr: bool = False):
        """Read output from a stream and update the appropriate buffer."""
        line_count = 0
        progress_data = {}  # Store the latest progress values
        
        while True:
            line = stream.readline()
            if not line:
                break

            try:
                line_str = line.decode('utf-8', errors='replace').rstrip()
            except UnicodeDecodeError:
                line_str = line.decode('latin-1', errors='replace').rstrip()

            buffer.append(line_str)
            line_count += 1

            # Print every line for debugging if requested
            if self.debug and line_count % 20 == 0:
                stream_type = "STDERR" if is_stderr else "STDOUT"
                print(f"[DEBUG] {stream_type} Line {line_count}: {line_str[:80]}")

            # First check for the duration pattern in FFmpeg output
            if self._duration_seconds is None:
                duration_match = self._duration_pattern.search(line_str)
                if duration_match:
                    h, m, s, ms = (duration_match.group(1), duration_match.group(2), 
                                  duration_match.group(3), duration_match.group(4) or '0')
                    try:
                        h, m, s = float(h), float(m), float(s)
                        ms = float('0.' + ms) if ms else 0.0
                        self._duration_seconds = h * 3600 + m * 60 + s + ms
                        if self.debug:
                            print(f"[DEBUG] Found duration: {h:.0f}h {m:.0f}m {s:.2f}s = {self._duration_seconds:.1f}s")
                    except ValueError as e:
                        if self.debug:
                            print(f"[DEBUG] Error parsing duration: {e}")

            # Process the progress information from FFmpeg's -progress output
            # This is formatted as key=value pairs with each pair on a new line
            if '=' in line_str:
                try:
                    key, value = line_str.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    
                    # Store this key-value pair
                    progress_data[key] = value
                    
                    if self.debug and key in ['out_time', 'progress', 'speed', 'total_size']:
                        print(f"[DEBUG] Progress info: {key}={value}")
                    
                    # If we get a "progress" marker, this is the end of a progress chunk
                    # This is a good time to calculate and report progress
                    if key == 'progress' and value == 'end':
                        # End of the file, set progress to 100%
                        if self.progress_callback:
                            status = "Transcoding completed!"
                            self.progress_callback(status, 1.0)
                            if self.debug:
                                print(f"[DEBUG] End of transcoding reached")
                    
                    # Check if we've accumulated enough information to calculate progress
                    elif key == 'out_time' and self._duration_seconds and self.progress_callback:
                        # out_time is in format HH:MM:SS.MS
                        try:
                            time_parts = value.split(':')
                            if len(time_parts) == 3:
                                h, m, s_parts = time_parts
                                s = float(s_parts)
                                h, m = float(h), float(m)
                                
                                current_seconds = h * 3600 + m * 60 + s
                                progress_percent = min(current_seconds / self._duration_seconds, 1.0)
                                
                                # Create a status message with useful information
                                speed = progress_data.get('speed', 'N/A')
                                frame = progress_data.get('frame', 'N/A')
                                fps = progress_data.get('fps', 'N/A')
                                total_size = progress_data.get('total_size', 'N/A')
                                
                                # Calculate ETA if speed is available
                                eta_str = "ETA: unknown"
                                if speed != 'N/A' and speed.endswith('x'):
                                    try:
                                        speed_val = float(speed.rstrip('x'))
                                        remaining = (self._duration_seconds - current_seconds) / max(speed_val, 0.1)
                                        minutes, seconds = divmod(int(remaining), 60)
                                        hours, minutes = divmod(minutes, 60)
                                        eta_str = f"ETA: {hours:02d}:{minutes:02d}:{seconds:02d}"
                                    except (ValueError, ZeroDivisionError):
                                        pass
                                
                                status = (f"Time: {int(h):02d}:{int(m):02d}:{s:.2f}/{int(self._duration_seconds/3600):02d}:"
                                          f"{int((self._duration_seconds%3600)/60):02d}:{self._duration_seconds%60:.2f}, "
                                          f"Frame: {frame}, FPS: {fps}, Speed: {speed}, {eta_str}")
                                
                                # Call progress callback with calculated percentage
                                if self.debug:
                                    print(f"[DEBUG] Progress: {progress_percent:.1%} - {status}")
                                
                                self.progress_callback(status, progress_percent)
                        except (ValueError, IndexError) as e:
                            if self.debug:
                                print(f"[DEBUG] Error parsing out_time: {value} - {e}")
                
                except Exception as e:
                    if self.debug:
                        print(f"[DEBUG] Error processing progress line: {line_str} - {e}")
            
            # As a fallback, try to extract progress from regular FFmpeg output patterns
            # This handles the case where -progress isn't working as expected
            elif self._duration_seconds and self.progress_callback and not is_stderr:
                # For time pattern in normal ffmpeg output (fallback)
                time_match = self._time_pattern.search(line_str)
                frame_match = self._progress_pattern.search(line_str)
                
                if time_match:
                    try:
                        h, m, s, ms = (time_match.group(1), time_match.group(2), 
                                      time_match.group(3), time_match.group(4) or '0')
                        h, m, s = float(h), float(m), float(s)
                        ms = float('0.' + ms) if ms else 0.0
                        current_seconds = h * 3600 + m * 60 + s + ms
                        progress_percent = min(current_seconds / self._duration_seconds, 1.0)
                        
                        if self.debug:
                            print(f"[DEBUG] Fallback time found: {h:02.0f}:{m:02.0f}:{s:.2f} - Progress: {progress_percent:.1%}")
                        
                        self.progress_callback(line_str, progress_percent)
                    except (ValueError, IndexError) as e:
                        if self.debug:
                            print(f"[DEBUG] Error parsing fallback time: {e}")

    def _extract_duration_from_output(self, stderr_output):
        """
        Extract the duration from the initial stderr output of FFmpeg.

        FFmpeg usually outputs the duration information at the beginning when it analyzes the input file.
        This method tries to find and extract that information.
        """
        # Scan the output for duration information
        for line in stderr_output.split('\n'):
            duration_match = self._duration_pattern.search(line)
            if duration_match:
                h, m, s, ms = (duration_match.group(1), duration_match.group(2), 
                              duration_match.group(3), duration_match.group(4) or '0')
                try:
                    h, m, s = float(h), float(m), float(s)
                    ms = float('0.' + ms) if ms else 0.0
                    self._duration_seconds = h * 3600 + m * 60 + s + ms
                    if self.debug:
                        print(f"[DEBUG] Found duration: {h:.0f}h {m:.0f}m {s:.2f}s = {self._duration_seconds:.2f}s")
                    return True
                except (ValueError, IndexError) as e:
                    if self.debug:
                        print(f"[DEBUG] Error parsing duration: {e}")
        
        if self.debug:
            print("[DEBUG] Could not find duration in FFmpeg output")
        
        return False

    def start(self):
        """Start the FFmpeg process and output capture threads."""
        if self.started:
            raise RuntimeError("Process already started")

        self._start_time = time.time()

        # Always try to extract duration information from the input file
        # This is critical for accurate progress reporting
        if not self._duration_seconds and len(self.command) > 2 and "-i" in self.command:
            input_index = self.command.index("-i")
            if input_index + 1 < len(self.command):
                input_file = self.command[input_index + 1]
                if self.debug:
                    print(f"[DEBUG] Extracting duration from input file: {input_file}")
                # Run ffmpeg with just the input file to get duration information
                try:
                    # Use ffprobe for more reliable duration extraction
                    info_cmd = ["ffprobe", "-v", "error", "-show_entries", 
                               "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", input_file]
                    if self.debug:
                        print(f"[DEBUG] Running duration detection: {' '.join(info_cmd)}")
                    
                    result = subprocess.run(info_cmd, capture_output=True, text=True)
                    
                    if result.returncode == 0 and result.stdout.strip():
                        try:
                            # ffprobe returns duration in seconds as a float
                            self._duration_seconds = float(result.stdout.strip())
                            if self.debug:
                                print(f"[DEBUG] ffprobe found duration: {self._duration_seconds:.2f}s")
                        except (ValueError, TypeError) as e:
                            if self.debug:
                                print(f"[DEBUG] Error parsing ffprobe duration: {e}")
                    
                    # If ffprobe fails, fall back to ffmpeg
                    if not self._duration_seconds:
                        if self.debug:
                            print("[DEBUG] Falling back to ffmpeg for duration detection")
                        info_cmd = ["ffmpeg", "-i", input_file]
                        result = subprocess.run(info_cmd, capture_output=True, text=False)
                        stderr_output = result.stderr.decode('utf-8', errors='replace')
                        self._extract_duration_from_output(stderr_output)
                
                except Exception as e:
                    if self.debug:
                        print(f"[DEBUG] Error extracting duration: {e}")
        
        if self._duration_seconds and self.debug:
            print(f"[DEBUG] Final duration detection: {self._duration_seconds:.2f}s")

        # Start the actual process
        self.process = subprocess.Popen(
            self.command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=-1,  # Use the default buffer size
            universal_newlines=False  # Binary mode for better handling of unusual output
        )

        self.started = True

        # Start threads to read output
        self.stdout_thread = threading.Thread(
            target=self._read_output,
            args=(self.process.stdout, self.stdout_buffer, False),
            daemon=True
        )
        self.stderr_thread = threading.Thread(
            target=self._read_output,
            args=(self.process.stderr, self.stderr_buffer, True),
            daemon=True
        )

        self.stdout_thread.start()
        self.stderr_thread.start()

        return self

    def wait(self, timeout: Optional[float] = None) -> int:
        """
        Wait for the process to complete.

        Args:
            timeout: Maximum time to wait in seconds, or None to wait indefinitely

        Returns:
            The process return code

        Raises:
            TimeoutError: If the timeout is reached before the process completes
            RuntimeError: If the process hasn't been started
        """
        if not self.started:
            raise RuntimeError("Process not started")

        if self.finished:
            return self.returncode

        try:
            self.returncode = self.process.wait(timeout=timeout)
            self.finished = True

            # Make sure we've captured all output
            self.stdout_thread.join()
            self.stderr_thread.join()

            return self.returncode
        except subprocess.TimeoutExpired as e:
            # Don't raise a TimeoutError, just pass the timeout along
            # This is expected when monitoring a long-running process
            # and we're just checking if it's done yet
            return None

    def terminate(self):
        """Terminate the FFmpeg process."""
        if self.process and not self.finished:
            self.process.terminate()
            self.wait(timeout=5)  # Give it a chance to terminate gracefully
            if not self.finished:
                self.process.kill()  # Force kill if it didn't terminate

    def get_stdout(self) -> str:
        """Get the captured stdout output."""
        return '\n'.join(self.stdout_buffer)

    def get_stderr(self) -> str:
        """Get the captured stderr output."""
        return '\n'.join(self.stderr_buffer)

    def get_elapsed_time(self) -> float:
        """Get the elapsed time in seconds since the process was started."""
        if not self._start_time:
            return 0.0
        return time.time() - self._start_time

    def __enter__(self):
        """Support for context manager protocol."""
        if not self.started:
            self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Ensure the process is terminated when exiting the context."""
        if not self.finished:
            self.terminate()
            
        # If we have a progress callback, ensure it gets a final progress update
        if self.progress_callback and not exc_type:
            try:
                # Call with 100% completion if we exited normally
                self.progress_callback("Transcoding completed", 1.0)
            except Exception as e:
                # Suppress any exceptions from the callback
                if self.debug:
                    print(f"[DEBUG] Error in final progress callback: {e}")

def generate_ffmpeg_command(
    input_file: Union[str, Path],
    output_file: Union[str, Path],
    capabilities: Dict[str, Any],
    codec: Optional[str] = None,
    scale: Optional[str] = None,
    audio_codec: Optional[str] = None,
    allow_fallback: bool = False,
    force_software: bool = False,
    crf: Optional[int] = None,
    bitrate: Optional[str] = None,
    audio_bitrate: Optional[str] = None,
    flac_compression: Optional[int] = None,
    overwrite: bool = False,
    quiet: bool = False,
    progress: bool = False
) -> List[str]:
    """
    Generate an FFmpeg command for transcoding video with hardware acceleration awareness.

    This function creates an FFmpeg command that optimally utilizes available hardware
    acceleration on the system when possible, falling back to software encoding when needed.

    Args:
        input_file: Path to the input video file
        output_file: Path to the output video file
        capabilities: Dictionary of hardware capabilities (from detect_capabilities())
        codec: Target video codec (h264, hevc, vp9, av1)
        scale: Target resolution (360p, 480p, 720p, 1080p, 2160p)
        audio_codec: Target audio codec (copy, aac, flac, opus, libopus)
        allow_fallback: Allow falling back to software encoding if hardware encoding fails
        force_software: Force software encoding even if hardware acceleration is available
        crf: Constant Rate Factor for quality-based encoding (0-51, lower is better)
        bitrate: Target video bitrate (e.g. "2M")
        audio_bitrate: Target audio bitrate (e.g. "128k")
        flac_compression: FLAC compression level (0-8)
        overwrite: Add -y flag to force overwriting output file
        quiet: Suppress informational output

    Returns:
        A list of strings forming the FFmpeg command

    Raises:
        ValueError: If the provided parameters are invalid or incompatible
    """
    container_ext, default_video, default_audio = infer_defaults_from_extension(output_file)
    video_codec = codec or default_video
    audio_codec = audio_codec or default_audio

    # Create a configuration to validate
    config = {
        'codec': video_codec,
        'audio_codec': audio_codec,
        'scale': scale,
        'crf': crf,
        'bitrate': bitrate,
        'audio_bitrate': audio_bitrate,
        'flac_compression': flac_compression
    }

    # Validate configuration without checking for container (CLI doesn't require it)
    try:
        validate_config(
            config=config,
            name="transcode options",
            context="CLI options",
            quiet=quiet,
            check_container=False
        )

        # Validate codec compatibility with container
        validate_codecs(container_ext, video_codec, audio_codec, context="CLI options", quiet=quiet)
    except ValueError:
        # Validation errors are already printed by validate_config/validate_codecs if quiet=False
        raise

    encoder = capabilities["encoders"].get(video_codec) if not force_software else None
    fallback = capabilities["fallback_encoders"][video_codec]
    hwaccel = capabilities.get("hwaccel")
    device = capabilities.get("device", "/dev/dri/renderD128")

    if force_software and not quiet:
        print("[!] Forcing software encoding. Hardware acceleration will not be used.")

    if not encoder and not (allow_fallback or force_software):
        error_msg = f"No hardware-accelerated encoder available for codec '{video_codec}'. Use allow_fallback=True to enable software encoding."
        if not quiet:
            print(f"[✗] {error_msg}")
        raise ValueError(error_msg)

    # Using hardware is a runtime decision that affects how CRF is handled
    using_hardware = encoder and hwaccel == "vaapi"
    if using_hardware and crf is not None and not quiet:
        print("[!] CRF is only allowed with software encoding. CRF will be ignored when hardware encoding is used.")

    filters = []
    command = ["ffmpeg"]

    # Add -y flag to force overwrite without prompting if requested
    if overwrite:
        command.append("-y")

    if using_hardware:
        if not quiet:
            print(f"[✓] Using hardware acceleration with encoder '{encoder}'")
        command += [
            "-hwaccel", "vaapi",
            "-hwaccel_device", device,
            "-init_hw_device", f"vaapi=va:{device}",
            "-filter_hw_device", "va",
            "-i", str(input_file)
        ]
        if scale:
            width, height = parse_resolution(scale)
            filters.append(f"format=nv12,hwupload,scale_vaapi=w={width}:h={height}")
        else:
            filters.append("format=nv12,hwupload")
        command += ["-vf", ",".join(filters), "-c:v", encoder]
        if bitrate:
            command += ["-b:v", bitrate]
    else:
        command += ["-i", str(input_file)]
        if scale:
            width, height = parse_resolution(scale)
            filters.append(f"scale={width}:{height}")
            command += ["-vf", ",".join(filters)]
        command += ["-c:v", fallback]
        if crf is not None:
            command += ["-crf", str(crf)]
        elif bitrate:
            command += ["-b:v", bitrate]
        else:
            command += ["-crf", "28"]

    if audio_codec == "copy":
        command += ["-c:a", "copy"]
    else:
        command += ["-c:a", audio_codec]

        # Handle audio channel mapping issues
        if audio_codec in ["opus", "libopus"]:
            # Add channel layout conversion for opus to ensure compatibility with multichannel audio
            command += ["-ac", "2"]  # Convert to stereo (2 channels) for maximum compatibility

        if audio_codec in ["aac", "opus", "libopus"] and audio_bitrate:
            command += ["-b:a", audio_bitrate]
        if audio_codec == "flac" and flac_compression is not None:
            command += ["-compression_level", str(flac_compression)]
    
    # Add progress reporting option if requested
    # FFmpeg can output machine-readable progress information
    if progress:
        # Use -progress pipe:1 to write progress info to stdout
        # pipe:1 refers to stdout, pipe:2 would be stderr
        # Don't use -stats which outputs human-readable progress to stderr
        command += ["-progress", "pipe:1", "-nostats"]
    
    command.append(str(output_file))
    return command

def transcode(
    input_file: Union[str, Path],
    output_file: Union[str, Path],
    codec: Optional[str] = None,
    scale: Optional[str] = None,
    audio_codec: Optional[str] = None,
    allow_fallback: bool = True,
    force_software: bool = False,
    crf: Optional[int] = None,
    bitrate: Optional[str] = None,
    audio_bitrate: Optional[str] = None,
    flac_compression: Optional[int] = None,
    capabilities_file: Optional[str] = None,
    dry_run: bool = False,
    overwrite: bool = False,
    quiet: bool = False,
    non_blocking: bool = False,
    progress_callback: Optional[Callable[[str, Optional[float]], None]] = None,
    preset_name: Optional[str] = None,
    presets_data: Optional[Dict[str, Dict[str, Any]]] = None,
    presets_file: Optional[str] = None
) -> Union[List[str], subprocess.CompletedProcess, TranscodeProcess]:
    """
    Transcode a video file using FFmpeg with optimal hardware acceleration settings.

    This is the main API function for the effeffmpeg module. It handles hardware detection,
    command generation, and execution with options for blocking or non-blocking operation
    and progress callbacks.

    Args:
        input_file: Path to the input video file
        output_file: Path to the output video file
        codec: Target video codec (h264, hevc, vp9, av1)
        scale: Target resolution (360p, 480p, 720p, 1080p, 2160p)
        audio_codec: Target audio codec (copy, aac, flac, opus, libopus)
        allow_fallback: Allow falling back to software encoding if hardware encoding fails
        force_software: Force software encoding even if hardware acceleration is available
        crf: Constant Rate Factor for quality-based encoding (0-51, lower is better)
        bitrate: Target video bitrate (e.g. "2M")
        audio_bitrate: Target audio bitrate (e.g. "128k")
        flac_compression: FLAC compression level (0-8)
        capabilities_file: Path to a JSON file with hardware capabilities (if None, detection will be performed)
        dry_run: If True, returns the command without executing it
        overwrite: Add -y flag to force overwriting output file
        quiet: Suppress informational output
        non_blocking: If True, start the process and return a TranscodeProcess object to manage it
        progress_callback: Optional function taking (line, progress) to receive process output and progress updates
        preset_name: Name of the preset to use from either presets_data or presets_file
        presets_data: Dictionary containing preset configurations (overrides presets_file)
        presets_file: Path to a JSON file containing preset configurations

    Returns:
        If dry_run is True, returns the FFmpeg command as a list of strings.
        If non_blocking is True, returns a TranscodeProcess object.
        Otherwise, returns the subprocess.CompletedProcess object from running the command.

    Raises:
        ValueError: If the provided parameters are invalid or incompatible
        subprocess.CalledProcessError: If the FFmpeg command fails in blocking mode
        KeyError: If the specified preset_name doesn't exist in presets_data or presets_file
    """
    # Process preset if specified
    preset_config = {}
    if preset_name:
        # First, try to get preset from presets_data if provided
        if presets_data is not None:
            # Validate the entire presets data structure
            validate_presets_data(presets_data, quiet=quiet)
            
            if preset_name not in presets_data:
                raise KeyError(f"Preset '{preset_name}' not found in presets_data")
            
            preset_config = presets_data[preset_name]
            if not quiet:
                print(f"Using preset '{preset_name}' from provided presets_data")
        
        # If no presets_data or preset not found, try loading from file
        elif presets_file:
            try:
                loaded_presets = load_presets(presets_file, quiet=quiet)
                if preset_name not in loaded_presets:
                    raise KeyError(f"Preset '{preset_name}' not found in presets_file '{presets_file}'")
                preset_config = loaded_presets[preset_name]
                if not quiet:
                    print(f"Using preset '{preset_name}' from '{presets_file}'")
            except Exception as e:
                if not quiet:
                    print(f"Error loading preset: {e}")
                raise
        else:
            raise ValueError("Either presets_data or presets_file must be provided when using preset_name")
        
        # Validate the preset configuration
        try:
            validate_preset_config(preset_name, preset_config, quiet=quiet)
        except ValueError as e:
            if not quiet:
                print(f"Invalid preset configuration: {e}")
            raise

    # Command-line args take precedence over preset values
    codec_val = codec or preset_config.get('codec')
    scale_val = scale or preset_config.get('scale')
    audio_codec_val = audio_codec or preset_config.get('audio_codec')
    crf_val = crf if crf is not None else preset_config.get('crf')
    bitrate_val = bitrate or preset_config.get('bitrate')
    audio_bitrate_val = audio_bitrate or preset_config.get('audio_bitrate')
    flac_compression_val = flac_compression if flac_compression is not None else preset_config.get('flac_compression')
    allow_fallback_val = allow_fallback or preset_config.get('allow_fallback', False)
    force_software_val = force_software or preset_config.get('force_software', False)

    # Get hardware capabilities
    capabilities = None
    if capabilities_file and os.path.exists(capabilities_file):
        try:
            with open(capabilities_file, 'r') as f:
                capabilities = json.load(f)
            if not quiet:
                print(f"Loaded capabilities from {capabilities_file}")
        except Exception as e:
            if not quiet:
                print(f"Error loading capabilities file: {e}")

    # If no capabilities file or loading failed, detect capabilities
    if capabilities is None:
        capabilities = detect_capabilities(quiet=quiet)

    # Generate the FFmpeg command
    command = generate_ffmpeg_command(
        input_file=input_file,
        output_file=output_file,
        capabilities=capabilities,
        codec=codec_val,
        scale=scale_val,
        audio_codec=audio_codec_val,
        allow_fallback=allow_fallback_val,
        force_software=force_software_val,
        crf=crf_val,
        bitrate=bitrate_val,
        audio_bitrate=audio_bitrate_val,
        flac_compression=flac_compression_val,
        overwrite=overwrite,
        quiet=quiet,
        progress=(non_blocking or progress_callback is not None)  # Enable progress reporting if we need it
    )

    # Return the command if dry_run is True
    if dry_run:
        return command

    # Print the command for visibility if not in quiet mode
    if not quiet:
        print("Running FFmpeg command:")
        print(" \\\n  ".join(command))

    # Handle non-blocking mode with the TranscodeProcess class
    if non_blocking or progress_callback is not None:
        # Default to no debug output unless explicitly requested
        process = TranscodeProcess(command, progress_callback, debug=False)
        process.start()

        # If non-blocking, return the process object
        if non_blocking:
            return process

        # Otherwise, wait for completion and handle result
        try:
            process.wait()
            
            # Ensure we call the progress callback with 100% at the end if successful
            if process.returncode == 0 and progress_callback and process._duration_seconds:
                try:
                    progress_callback("Transcoding completed successfully", 1.0)
                except Exception as e:
                    # Suppress callback errors
                    if not quiet:
                        print(f"[!] Warning: Error in final progress callback: {e}")
            
            if not quiet and process.returncode == 0:
                print("\n[✓] Transcoding completed successfully!")
            elif not quiet and process.returncode != 0:
                print(f"\n[✗] Transcoding failed with error code {process.returncode}")
            
            return subprocess.CompletedProcess(
                args=command,
                returncode=process.returncode,
                stdout=process.get_stdout(),
                stderr=process.get_stderr()
            )
        except Exception as e:
            # Make sure to clean up in case of error
            process.terminate()
            
            # Call progress callback with error information if available
            if progress_callback:
                try:
                    progress_callback(f"Error during transcoding: {str(e)}", None)
                except Exception:
                    # Ignore errors in the callback itself
                    pass
            
            raise

    # For regular blocking mode without callbacks, use standard subprocess
    try:
        result = subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        if not quiet:
            print("\n[✓] Transcoding completed successfully!")

        return result
    except subprocess.CalledProcessError as e:
        if not quiet:
            print(f"\n[✗] Transcoding failed with error code {e.returncode}")
        raise

def list_presets(presets_file):
    """List all available presets with their configurations."""
    try:
        presets = load_presets(presets_file)
        if not presets:
            print("No presets found in the presets file.")
            return

        print(f"Available presets from '{presets_file}':\n")
        for name, config in presets.items():
            print(f"[{name}]")
            for key, value in config.items():
                print(f"  {key}: {value}")
            print()
    except Exception as e:
        print(f"Error loading presets: {e}")
        sys.exit(1)

def cli_main():
    """Command-line interface entry point."""
    parser = argparse.ArgumentParser(description="FFmpeg Hardware-Aware Transcoder")
    subparsers = parser.add_subparsers(dest="command")

    detect_parser = subparsers.add_parser("detect", help="Detect hardware acceleration capabilities")
    detect_parser.add_argument("output", help="Path to save capabilities JSON")

    presets_parser = subparsers.add_parser("presets", help="List available presets")
    presets_parser.add_argument("--file", default="presets.json", help="Path to presets JSON file")

    transcode_parser = subparsers.add_parser("transcode", help="Transcode a video file")
    transcode_parser.add_argument("input", help="Path to input file")
    transcode_parser.add_argument("output", help="Path to output file")

    # Group mutually exclusive options: either specify a preset or use manual settings
    transcode_group = transcode_parser.add_mutually_exclusive_group()
    transcode_group.add_argument("--preset", help="Use a predefined preset configuration")
    transcode_group.add_argument("--to", choices=["h264", "hevc", "vp9", "av1"], help="Target video codec")

    transcode_parser.add_argument("--presets-file", default="presets.json", help="Path to presets JSON file")
    transcode_parser.add_argument("--scale", choices=["360p", "480p", "720p", "1080p", "2160p"], help="Target resolution")
    transcode_parser.add_argument("--audio", choices=["copy", "aac", "flac", "opus", "libopus"], help="Audio codec")
    transcode_parser.add_argument("--capabilities", default="capabilities.json", help="Path to capabilities JSON")
    transcode_parser.add_argument("--run", action="store_true", help="Run the ffmpeg command")
    transcode_parser.add_argument("--allow-fallback", action="store_true", help="Allow software fallback")
    transcode_parser.add_argument("--force-software", action="store_true", help="Force software encoding (disables hardware acceleration even if available)")
    transcode_parser.add_argument("--crf", type=int, help="Set CRF value for software encoding (0–51)")
    transcode_parser.add_argument("--bitrate", help="Set video bitrate (e.g. 2M)")
    transcode_parser.add_argument("--audio-bitrate", help="Set audio bitrate (e.g. 128k)")
    transcode_parser.add_argument("--flac-compression", type=int, choices=range(0, 9), help="FLAC compression level (0–8)")

    args = parser.parse_args()

    if args.command == "detect":
        caps = detect_capabilities()
        with open(args.output, "w") as f:
            json.dump(caps, f, indent=2)
        print(f"Capabilities saved to {args.output}")
    elif args.command == "presets":
        try:
            list_presets(args.file)
        except (FileNotFoundError, json.JSONDecodeError, ValueError):
            # Error message already printed by list_presets
            sys.exit(1)
    elif args.command == "transcode":
        try:
            with open(args.capabilities) as f:
                caps = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"[✗] Error loading capabilities file: {e}")
            sys.exit(1)

        # Process preset if specified
        preset_config = {}
        if args.preset:
            try:
                presets = load_presets(args.presets_file)
                if args.preset not in presets:
                    print(f"[✗] Preset '{args.preset}' not found in presets file.")
                    print(f"Available presets: {', '.join(presets.keys())}")
                    sys.exit(1)
                preset_config = presets[args.preset]
            except (FileNotFoundError, json.JSONDecodeError, ValueError):
                # Error message already printed by load_presets
                sys.exit(1)

            # Check if the container in preset is compatible with output file
            output_ext = Path(args.output).suffix.lower()
            preset_container = preset_config.get('container')
            if preset_container and output_ext != preset_container:
                print(f"[!] Warning: Preset '{args.preset}' specifies container '{preset_container}' but output file has extension '{output_ext}'")
                print("    Output file extension will be used instead of preset container.")

        # If force_software is True, we implicitly allow fallback to software encoding
        allow_fallback = args.allow_fallback or args.force_software or preset_config.get('allow_fallback', False)
        force_software = args.force_software or preset_config.get('force_software', False)

        # Command-line args take precedence over preset values
        codec = args.to or preset_config.get('codec')
        scale = args.scale or preset_config.get('scale')
        audio_codec = args.audio or preset_config.get('audio_codec')
        crf = args.crf if args.crf is not None else preset_config.get('crf')
        bitrate = args.bitrate or preset_config.get('bitrate')
        audio_bitrate = args.audio_bitrate or preset_config.get('audio_bitrate')
        flac_compression = args.flac_compression if args.flac_compression is not None else preset_config.get('flac_compression')

        try:
            command = generate_ffmpeg_command(
                input_file=args.input,
                output_file=args.output,
                codec=codec,
                scale=scale,
                audio_codec=audio_codec,
                capabilities=caps,
                allow_fallback=allow_fallback,
                force_software=force_software,
                crf=crf,
                bitrate=bitrate,
                audio_bitrate=audio_bitrate,
                flac_compression=flac_compression,
                overwrite=args.run  # Enable overwrite when running
            )
            print("Generated FFmpeg command:\n")
            print(" \\\n  ".join(command))
            if args.run:
                print("\nRunning FFmpeg...\n")
                try:
                    # Use the new transcode function with progress tracking
                    def print_progress(line, progress):
                        if progress is not None:
                            # Only print lines with progress info
                            if "time=" in line:
                                percent = int(progress * 100)
                                print(f"\rProgress: {percent}% - {line}", end="", flush=True)

                    transcode(
                        input_file=args.input,
                        output_file=args.output,
                        codec=codec,
                        scale=scale,
                        audio_codec=audio_codec,
                        allow_fallback=allow_fallback,
                        force_software=force_software,
                        crf=crf,
                        bitrate=bitrate,
                        audio_bitrate=audio_bitrate,
                        flac_compression=flac_compression,
                        overwrite=True,
                        quiet=True,  # Suppress duplicated output
                        progress_callback=print_progress
                    )
                    print("\n[✓] Transcoding completed successfully!")
                except subprocess.CalledProcessError as e:
                    print(f"\n[✗] Transcoding failed with error code {e.returncode}")
                    sys.exit(1)
        except ValueError:
            # Error message already printed by generate_ffmpeg_command
            sys.exit(1)
    else:
        parser.print_help()

def main():
    """Legacy entry point for backward compatibility."""
    cli_main()


if __name__ == "__main__":
    cli_main()
