# DASH MPD + Widevine CENC ripper

Small utility for downloading, decrypting and combining playlists of DASH streams, usually found in video courses.

Given Widevine keys (CENC) decrypts each file part (audio, video).

Requires `ffmpeg`.

## Setup

Make sure you have `ffmpeg` installed, then `pip install -r requirements.txt` (virtualenv recommended).

## Playlist file and usage

Prepare a TOML file looking like this:

```toml
[source]
base = "https://..." # typically a S3 bucket base URL
mpd = "stream.mpd" # MPD file suffix

[chapters]

[chapters."1. first chapter"]

[chapters."1. first chapter".episodes."1. first episode"]
id = "xxxxx" # video ID used as second path segment
keys."..." = "..." # widevine CENC key, generally 16 byte hex
```

Then run `python rip.py playlist.toml`

The ripper will fetch the MPD file (`base + id + mpd`), find the highest quality audio/video segments and their key IDs and download the corresponding files (`base + id + audio/video BaseURL`), then decrypt and combine them using `ffmpeg`.

You will find a directory for each chapter, and a file for each episode.
