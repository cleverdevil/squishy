<center><img src="https://raw.githubusercontent.com/cleverdevil/squishy/main/squishy/static/img/splash.png"></center>

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
* Flexible transcoding presets, giving you the ability to optimize for your use
  case. Presets define a target resolution, codec, and quality. Squishy comes
  with default presets, along with additional preset libraries for different
  tradeoffs.
* Customize and create your own presets to let you dial-in your personal preferences by
  selecting custom resolutions, bitrates, and codecs.
* Hardware acceleration support with automatic failover to software encoding when
  hardware acceleration fails.
* Direct download links for your transcoded media that work with any browser or
  media player app.

## Installation

Squishy can be run manually from source, but the recommended installation method
is to run Squishy as a Docker Container. The repository includes a
`docker-compose.yml` file for your convenience.

### Running with Docker

1. Clone this repository:
```bash
git clone https://github.com/cleverdevil/squishy.git
cd squishy
```
2. Modify docker-compose.yml:
   - Uncomment and edit the media path volume mounts in both Squishy and Jellyfin/Plex services
   - Uncomment the appropriate GPU/hardware acceleration settings if needed
   - Choose either Jellyfin or Plex (comment out the one you don't use)

3. Start the containers:
```bash
docker compose up --build
```

4. Access Squishy:

Open your browser and navigate to `http://your-host:5101`. Squishy will guide
you through the rest of the setup process!

### Hardware Acceleration

Squishy currently supports VA-API for hardware accelerated transcoding. Support
for other acceleration methods could be added if there is a strong demand from
users.

Under the hood, Squishy uses an embedded project called `effeffmpeg`, which
handles all of the transcoding and interfacing with ffmpeg. More detail is
available in the [effeffmpeg README.md](https://github.com/cleverdevil/squishy/blob/main/squishy/effeffmpeg/README.md) in the source tree.
