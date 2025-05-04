#!/usr/bin/env python3
"""
Example script demonstrating how to use effeffmpeg's non-blocking API with progress tracking

Usage:
    python example_nonblocking.py input_file output_dir

Arguments:
    input_file: Path to the input video file
    output_dir: Directory where output files will be saved
"""

import time
import sys
import os
from pathlib import Path
import effeffmpeg


def formatted_time(seconds):
    """Format seconds into a human-readable time string"""
    minutes, seconds = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def custom_progress_handler(line, progress):
    """
    Custom progress handler that displays a progress bar and additional information

    Args:
        line: The current line of output from FFmpeg
        progress: A float between 0.0 and 1.0 representing the progress percentage
    """
    if progress is not None:
        # Create a progress bar using ASCII characters
        bar_length = 30
        filled_length = int(bar_length * progress)
        bar = "█" * filled_length + "░" * (bar_length - filled_length)
        percent = int(progress * 100)

        # Extract estimated remaining time if available
        remaining_info = ""
        if "speed=" in line:
            # Extract the speed information (e.g., "speed=2.5x")
            speed_part = line.split("speed=")[1].split()[0]

            # Only try to calculate remaining time if we have valid speed data
            if "x" in speed_part:
                try:
                    speed = float(speed_part.replace("x", ""))
                    if speed > 0:
                        # Get video duration information if available
                        duration_match = (
                            effeffmpeg.TranscodeProcess._duration_pattern.search(line)
                        )
                        time_match = effeffmpeg.TranscodeProcess._time_pattern.search(
                            line
                        )

                        if time_match and duration_match:
                            h1, m1, s1 = map(int, duration_match.groups())
                            h2, m2, s2 = map(int, time_match.groups())
                            total_seconds = h1 * 3600 + m1 * 60 + s1
                            current_seconds = h2 * 3600 + m2 * 60 + s2
                            remaining_seconds = (
                                total_seconds - current_seconds
                            ) / speed

                            # Add remaining time to the output
                            remaining_info = (
                                f" | ETA: {formatted_time(remaining_seconds)}"
                            )
                except (ValueError, ZeroDivisionError):
                    pass  # Ignore any parsing errors

        # Create the progress output line
        sys.stdout.write(f"\r[{bar}] {percent}%{remaining_info}")
        sys.stdout.flush()


def example_blocking_with_progress(input_file, output_dir):
    """Example demonstrating blocking transcoding with progress reporting"""
    print("\nExample 1: Blocking transcoding with progress reporting")
    print("--------------------------------------------------------")

    try:
        print("Starting transcoding process with progress tracking...")

        # Use the progress_callback parameter to track progress while transcoding runs
        result = effeffmpeg.transcode(
            input_file=input_file,
            output_file=os.path.join(output_dir, "out_blocking_progress.mp4"),
            codec="h264",
            scale="720p",
            audio_codec="aac",
            audio_bitrate="128k",
            allow_fallback=True,
            overwrite=True,
            progress_callback=custom_progress_handler,
        )

        print("\n✓ Transcoding completed successfully")
        print(f"Return code: {result.returncode}")
    except Exception as e:
        print(f"\n✗ Transcoding failed: {e}")


def example_nonblocking_basic(input_file, output_dir):
    """Example demonstrating basic non-blocking transcoding"""
    print("\nExample 2: Basic non-blocking transcoding")
    print("------------------------------------------")

    try:
        print("Starting non-blocking transcoding process...")

        # Start the transcoding process in non-blocking mode
        process = effeffmpeg.transcode(
            input_file=input_file,
            output_file=os.path.join(output_dir, "out_nonblocking.mkv"),
            codec="hevc",
            scale="720p",
            audio_codec="aac",
            audio_bitrate="128k",
            allow_fallback=True,
            overwrite=True,
            non_blocking=True,  # This makes the function return immediately with a TranscodeProcess object
        )

        print("Transcoding started in the background.")
        print("Waiting for completion while doing other work...")

        # Simulate doing other work while transcoding runs in the background
        dots = 0
        while not process.finished:
            dots = (dots + 1) % 4
            sys.stdout.write(
                f"\rProcessing{'.' * dots}{' ' * (3 - dots)} | Elapsed: {formatted_time(process.get_elapsed_time())}"
            )
            sys.stdout.flush()

            # Check if process is still running or has completed
            if process.process.poll() is not None:
                process.finished = True
                process.returncode = process.process.returncode

            time.sleep(0.5)  # Check status every half second

        # Process is now finished
        print(
            f"\r✓ Transcoding completed with return code: {process.returncode}{' ' * 20}"
        )

        # You can access stdout and stderr after completion
        print("Last few lines of output:")
        for line in process.stderr_buffer[-5:]:
            print(f"  {line}")
    except Exception as e:
        print(f"\n✗ Transcoding failed: {e}")


def example_nonblocking_with_progress(input_file, output_dir):
    """Example demonstrating non-blocking transcoding with progress tracking"""
    print("\nExample 3: Non-blocking transcoding with progress tracking")
    print("----------------------------------------------------------")

    try:
        print("Starting non-blocking transcoding with progress tracking...")

        # Start the transcoding process in non-blocking mode with progress callback
        process = effeffmpeg.transcode(
            input_file=input_file,
            output_file=os.path.join(output_dir, "out_nonblocking_progress.mp4"),
            codec="h264",
            scale="1080p",
            audio_codec="aac",
            audio_bitrate="192k",
            allow_fallback=True,
            overwrite=True,
            non_blocking=True,
            progress_callback=custom_progress_handler,
        )

        print("Transcoding started in the background.")

        # Simulate an application that's doing other work while monitoring progress
        while not process.finished:
            # The progress is already being reported by our callback function
            # Here we can do other application work

            # For this example, we're just checking if the process is still running
            if process.process.poll() is not None:
                process.finished = True
                process.returncode = process.process.returncode

            # Sleep to avoid consuming too much CPU
            time.sleep(0.1)

        print(f"\n✓ Transcoding completed with return code: {process.returncode}")
        print(f"Total time elapsed: {formatted_time(process.get_elapsed_time())}")
    except Exception as e:
        print(f"\n✗ Transcoding failed: {e}")


def example_context_manager(input_file, output_dir):
    """Example demonstrating use of context manager for resource management"""
    print("\nExample 4: Using TranscodeProcess as a context manager")
    print("------------------------------------------------------")

    try:
        print("Starting transcoding with context manager...")

        # Create the FFmpeg command
        command = effeffmpeg.generate_ffmpeg_command(
            input_file=input_file,
            output_file=os.path.join(output_dir, "out_context_manager.mp4"),
            codec="h264",
            scale="720p",
            audio_codec="aac",
            capabilities=effeffmpeg.detect_capabilities(quiet=True),
            allow_fallback=True,
            overwrite=True,
        )

        # Use the context manager to ensure proper cleanup
        with effeffmpeg.TranscodeProcess(command, custom_progress_handler) as process:
            print("Transcoding started via context manager.")

            # Polling loop - in a real application, you'd do useful work here
            while not process.finished:
                # Check if process completed
                if process.process.poll() is not None:
                    process.finished = True
                    process.returncode = process.process.returncode

                time.sleep(0.1)

        # Process is automatically terminated when exiting the context
        print(f"\n✓ Transcoding completed with return code: {process.returncode}")
    except Exception as e:
        print(f"\n✗ Transcoding failed: {e}")


def example_advanced_usage(input_file, output_dir):
    """Example demonstrating more advanced usage with explicit process control"""
    print("\nExample 5: Advanced usage with explicit process control")
    print("-------------------------------------------------------")

    try:
        print("Starting transcoding with manual process management...")

        # Create and start the process directly
        process = effeffmpeg.TranscodeProcess(
            command=effeffmpeg.transcode(
                input_file=input_file,
                output_file=os.path.join(output_dir, "out_advanced.mkv"),
                codec="hevc",
                scale="1080p",
                audio_codec="libopus",
                audio_bitrate="192k",
                allow_fallback=True,
                overwrite=True,
                dry_run=True,  # Just get the command, don't run it
            ),
            progress_callback=custom_progress_handler,
        )

        # Start the process manually
        process.start()

        print("Process started manually.")
        print("Press Ctrl+C to cancel or wait for completion...")

        try:
            # Wait for completion with a timeout
            process.wait(timeout=300)  # 5-minute timeout
            print(f"\n✓ Transcoding completed with return code: {process.returncode}")
        except KeyboardInterrupt:
            print("\nProcess interrupted by user. Terminating...")
            process.terminate()
            print(
                f"Process terminated. Elapsed time: {formatted_time(process.get_elapsed_time())}"
            )
        except TimeoutError:
            print("\nProcess timed out after 5 minutes. Terminating...")
            process.terminate()
            print("Process terminated due to timeout.")
    except Exception as e:
        print(f"\n✗ Transcoding setup failed: {e}")


def main(input_file, output_dir):
    print("effeffmpeg Non-Blocking API Examples")
    print("===================================")
    print(f"Input file: {input_file}")
    print(f"Output directory: {output_dir}")

    # Run examples one by one (comment out the ones you don't want to run)
    example_blocking_with_progress(input_file, output_dir)
    example_nonblocking_basic(input_file, output_dir)
    example_nonblocking_with_progress(input_file, output_dir)
    example_context_manager(input_file, output_dir)
    example_advanced_usage(input_file, output_dir)

    print("\nAll examples completed!")


if __name__ == "__main__":
    # Check command line arguments
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} input_file output_dir")
        sys.exit(1)
    
    # Get input file and output directory from command line
    input_file = sys.argv[1]
    output_dir = sys.argv[2]
    
    # Validate input file exists
    if not os.path.exists(input_file):
        print(f"Error: Input file '{input_file}' does not exist.")
        sys.exit(1)
    
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    # Run the examples
    main(input_file, output_dir)
