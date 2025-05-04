#!/usr/bin/env python3
"""
Example script demonstrating how to use presets with effeffmpeg,
including defining presets directly as Python dictionaries.

Usage:
    python example_presets.py input_file output_dir

Arguments:
    input_file: Path to the input video file
    output_dir: Directory where output files will be saved
"""

import os
import sys
import time
import effeffmpeg

# Define presets directly as a Python dictionary
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

def progress_handler(line, progress):
    """Progress handler for displaying transcoding progress."""
    if progress is not None:
        percent = int(progress * 100)
        sys.stdout.write(f"\rProgress: {percent}% | {line}")
        sys.stdout.flush()

def main(input_file, output_dir):
    """Run the preset examples."""
    # Display the paths being used
    print(f"Input file: {input_file}")
    print(f"Output directory: {output_dir}")

    print("effeffmpeg Presets Example")
    print("=========================")

    # Example 1: Using a preset from the dictionary
    print("\nExample 1: Using a preset defined as a Python dictionary")
    print("-------------------------------------------------------")
    try:
        # Use the 'web_medium' preset defined in our PRESETS dictionary
        result = effeffmpeg.transcode(
            input_file=input_file,
            output_file=os.path.join(output_dir, "out_preset_dict.mp4"),
            preset_name="web_medium",
            presets_data=PRESETS,
            overwrite=True,
            progress_callback=progress_handler
        )

        print("\n✓ Transcoding with preset from dictionary completed successfully")
    except Exception as e:
        print(f"\n✗ Transcoding failed: {e}")

    # Example 2: Using a preset with some custom overrides
    print("\nExample 2: Using a preset with custom parameter overrides")
    print("--------------------------------------------------------")
    try:
        # Use the 'web_high' preset but override the scale to 720p
        result = effeffmpeg.transcode(
            input_file=input_file,
            output_file=os.path.join(output_dir, "out_preset_override.mp4"),
            preset_name="web_high",
            presets_data=PRESETS,
            scale="720p",  # Override the scale
            bitrate="3M",  # Override with bitrate instead of CRF
            overwrite=True,
            progress_callback=progress_handler
        )

        print("\n✓ Transcoding with preset and overrides completed successfully")
    except Exception as e:
        print(f"\n✗ Transcoding failed: {e}")

    # Example 3: Using a preset with non-blocking mode
    print("\nExample 3: Using a preset with non-blocking mode")
    print("-----------------------------------------------")
    try:
        # Use the 'archive' preset with non-blocking mode
        process = effeffmpeg.transcode(
            input_file=input_file,
            output_file=os.path.join(output_dir, "out_preset_nonblocking.mkv"),
            preset_name="archive",
            presets_data=PRESETS,
            overwrite=True,
            non_blocking=True,  # Use non-blocking mode
            progress_callback=progress_handler
        )

        print("Transcoding with preset in non-blocking mode started")
        print("Waiting for completion...")

        # Wait for completion
        while not process.finished:
            if process.process.poll() is not None:
                process.finished = True
                process.returncode = process.process.returncode

            # Sleep to avoid using too much CPU
            import time
            time.sleep(0.5)

        print(f"\n✓ Non-blocking transcoding completed with return code: {process.returncode}")
    except Exception as e:
        print(f"\n✗ Transcoding failed: {e}")

    print("\nAll preset examples completed!")

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
