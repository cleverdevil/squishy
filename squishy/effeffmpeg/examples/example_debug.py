#!/usr/bin/env python3
"""
Simple example script demonstrating progress tracking with debug output enabled

Usage:
    python example_debug.py input_file output_dir

Arguments:
    input_file: Path to the input video file
    output_dir: Directory where output files will be saved
"""

import effeffmpeg
import sys
import time
import os
from pathlib import Path


# Create a simple progress handler that prints progress percentage
def progress_handler(line, progress):
    # Print raw progress value for debugging
    print(f"Raw progress value: {progress}")

    if progress is not None:
        percent = int(progress * 100)
        sys.stdout.write(f"\rProgress: {percent}% | {line}")
        sys.stdout.flush()
    else:
        # If progress is None, report the issue
        print(f"Warning: Progress is None for line: {line[:50]}...")


# Define the main function
def main(input_file, output_dir):
    # Display the paths being used
    print(f"Input file: {input_file}")
    print(f"Output directory: {output_dir}")

    print("Transcode Progress Debug Example")
    print("===============================")
    print("Starting transcoding process with debug output...")

    try:
        # Use non-blocking transcode with debug enabled
        print("Method 1: Using non-blocking transcode API directly")
        process = effeffmpeg.transcode(
            input_file=input_file,
            output_file=os.path.join(output_dir, "out_debug.mp4"),
            codec="h264",
            scale="720p",
            audio_codec="aac",
            audio_bitrate="128k",
            allow_fallback=True,
            overwrite=True,
            non_blocking=True,
            progress_callback=progress_handler,
            quiet=False,  # Enable full output to see progress messages
        )

        # Enable debug mode explicitly
        process.debug = True

        print("Transcoding started, waiting for completion...")

        # Wait for completion, checking status periodically
        while not process.finished:
            if process.process.poll() is not None:
                process.finished = True
                process.returncode = process.process.returncode

            # Sleep to avoid using too much CPU
            time.sleep(0.5)

        print(f"\n✓ Transcoding completed with return code: {process.returncode}")

        # Method 2: Create a process directly
        print("\nMethod 2: Using TranscodeProcess directly")

        command = effeffmpeg.transcode(
            input_file=input_file,
            output_file=os.path.join(output_dir, "out_debug2.mp4"),
            codec="h264",
            scale="720p",
            audio_codec="aac",
            audio_bitrate="128k",
            allow_fallback=True,
            overwrite=True,
            dry_run=True,  # Just get the command, don't execute
        )

        print(
            "Command:",
            " ".join(command[:5]) + "..." if len(command) > 5 else " ".join(command),
        )

        # Explicitly enable debug mode for debugging
        process = effeffmpeg.TranscodeProcess(command, progress_handler, debug=True)
        process.start()

        print("Second transcoding started, waiting for completion...")

        # Wait for completion, checking status periodically
        while not process.finished:
            if process.process.poll() is not None:
                process.finished = True
                process.returncode = process.process.returncode

            time.sleep(0.5)

        print(
            f"\n✓ Second transcoding completed with return code: {process.returncode}"
        )

    except Exception as e:
        print(f"\n✗ Error: {e}")


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
