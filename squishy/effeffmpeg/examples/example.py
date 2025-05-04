#!/usr/bin/env python3
"""
Example script demonstrating how to use effeffmpeg as a Python module

Usage:
    python example.py input_file output_dir

Arguments:
    input_file: Path to the input video file
    output_dir: Directory where output files will be saved
"""

import effeffmpeg
import os
import sys
from pathlib import Path


def main(input_file, output_dir):
    # Example 1: Basic Transcoding
    print("Example 1: Basic transcoding to H.264 720p")
    try:
        # Perform hardware-accelerated transcoding with fallback to software if needed
        effeffmpeg.transcode(
            input_file=input_file,
            output_file=os.path.join(output_dir, "out_h264_720p.mp4"),
            codec="h264",
            scale="720p",
            audio_codec="aac",
            audio_bitrate="128k",
            # Try it as a dry run first (just outputs the command)
            dry_run=True,
            quiet=True
        )
        print("✓ Example 1 completed successfully\n")
    except Exception as e:
        print(f"✗ Example 1 failed: {e}\n")

    # Example 2: High-quality HEVC with software encoding
    print("Example 2: High-quality HEVC encoding with CRF")
    try:
        # Use CRF-based quality control with software encoding
        result = effeffmpeg.transcode(
            input_file=input_file,
            output_file=os.path.join(output_dir, "out_hevc_1080p.mkv"),
            codec="hevc",
            scale="1080p",
            audio_codec="libopus",
            audio_bitrate="192k",
            force_software=True,  # Force software encoding
            crf=22,  # Lower CRF = higher quality
            dry_run=True,
            quiet=True
        )
        print("Command that would be executed:")
        print(" ".join(result))
        print("✓ Example 2 completed successfully\n")
    except Exception as e:
        print(f"✗ Example 2 failed: {e}\n")

    # Example 3: Hardware acceleration detection
    print("Example 3: Detecting hardware acceleration capabilities")
    try:
        capabilities = effeffmpeg.detect_capabilities(quiet=True)
        print("Detected hardware acceleration capabilities:")
        print(f"  Hardware acceleration: {capabilities['hwaccel'] or 'None'}")
        print(f"  Available hardware encoders: {list(capabilities['encoders'].keys())}")
        print(f"  Software fallback encoders: {capabilities['fallback_encoders']}")
        print("✓ Example 3 completed successfully\n")
    except Exception as e:
        print(f"✗ Example 3 failed: {e}\n")


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