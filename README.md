# Squishy: Media Transcoding Made Simple

Digital packrats often have media libraries that are filled with high resolution
movies and TV shows. When you are watching on the big screen in your home
theater, you want the best possible quality in the form of Bluray rips and
remuxes. That quality comes at a cost -- file size. 4K HDR remuxes are generally
in the 30-100 GB range. When traveling, downloading media to your phone with
such files results in long downloads and limited storage space. Enter Squishy,
which makes transcoding and downloading your media simple by automating the
on-demand transcoding process, compressing your large media files to much more
reasonable sizes for watching movies and TV shows on smaller devices like phones
and tablets.

## Features

Squishy has a focused set of features designed to make the process of selecting,
transcoding, and downloading your media as frictionless as possible:

* Attractive web interface to browse your media and transcoded files, including
  poster art.
* Integration with Jellyfin and Plex media servers to quickly add your media
  library to Squishy.
* Flexible transcoding profiles, giving you the ability to optimize for your use
  case. Profiles define a target resolution, codec, and quality. Squishy comes
  with default profiles: high, medium, low, and potato, which target H.264 videos in
  either MKV or MP4 with 4K, 1080p, 720p, and 480p respectively.
* Customize and create profiles to let you dial-in your personal preferences by
  selecting custom resolutions, bitrates, and codecs such as HEVC and AV1.
* Hardware acceleration support with automatic failover to software encoding when
  hardware acceleration fails. Configurable per transcoding profile to either allow
  or prevent failover based on your requirements.
* Direct download links for your transcoded media that work with any browser or
  media player app.

## Installation

Squishy can be run manually from source, but the recommended installation method
is to run Squishy as a Docker Container. The repository includes a
`docker-compose.yml` file for your convenience.

### Running with Docker

1. Clone this repository:
```bash
git clone https://github.com/yourusername/squishy.git
cd squishy
```

2. Configure Squishy:
   - Copy the example configuration:
   ```bash
   cp config/config.example.json config/config.json
   ```
   - Edit `config/config.json` to set up your media paths, Jellyfin or Plex server details, and path mappings.

3. Modify docker-compose.yml:
   - Uncomment and edit the media path volume mounts in both Squishy and Jellyfin/Plex services
   - Uncomment the appropriate GPU/hardware acceleration settings if needed
   - Choose either Jellyfin or Plex (comment out the one you don't use)

4. Start the containers:
```bash
docker-compose up -d
```

5. Access Squishy:
   - Open your browser and navigate to `http://localhost:5101`
   - If you included Jellyfin, it will be available at `http://localhost:8096`
   - If you included Plex, it will be available at `http://localhost:32400/web`

### Environment Variables

You can customize the Docker setup with the following environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `TRANSCODES_PATH` | Path where transcoded files will be stored | `./transcodes` |
| `LOG_LEVEL` | Logging level (DEBUG, INFO, WARNING, ERROR) | `INFO` |
| `DEBUG` | Enable Flask debug mode | `false` |
| `SECRET_KEY` | Flask secret key | `default_development_key` |
| `TZ` | Timezone | `UTC` |

Example using environment variables:
```bash
TRANSCODES_PATH=/mnt/data/transcodes TZ=America/New_York docker-compose up -d
```

### Hardware Acceleration

To enable hardware acceleration:

1. For NVIDIA GPUs:
   - Uncomment the `deploy` section in docker-compose.yml
   - Make sure you have the NVIDIA Container Toolkit installed on your host

2. For Intel/AMD GPUs (VA-API):
   - Uncomment the `devices` section to pass through `/dev/dri` 
   - Set the appropriate `hw_accel` in your transcoding profiles
