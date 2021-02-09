"""
Given a TOML playlist configuration, rips a Widevine DRM-encrypted DASH stream by parsing
the MPD configuration, decrypting audio and video parts individually, then
combining them into a single video file.
"""
import os
import sys
from enum import Enum
from typing import Dict, List, Optional, Union

import requests
import toml
import xmltodict
import ffmpeg
from pydantic import BaseModel, Field


class ContentType(str, Enum):
    video = "video"
    audio = "audio"


class Source(BaseModel):
    base: str = Field(...)
    mpd: str = Field(...)


class Episode(BaseModel):
    id: str = Field(...)
    keys: Dict[str, str] = Field(...)


class Chapter(BaseModel):
    episodes: Dict[str, Episode] = Field({})


class Playlist(BaseModel):
    source: Source = Field(...)
    chapters: Dict[str, Chapter] = Field({})


class ContentProtection(BaseModel):
    scheme_id_uri: str = Field(..., alias="@schemeIdUri")
    value: Optional[str] = Field(None, alias="@value")
    cenc_kid: Optional[str] = Field(None, alias="@cenc:default_KID")
    cenc_pssh: Optional[str] = Field(None, alias="cenc:pssh")


class Initialization(BaseModel):
    init_range: str = Field(..., alias="@range")


class SegmentBase(BaseModel):
    index_range: str = Field(..., alias="@indexRange")
    timescale: int = Field(..., alias="@timescale")
    init: Initialization = Field(..., alias="Initialization")


class Representation(BaseModel):
    bandwidth: int = Field(..., alias="@bandwidth")
    codecs: str = Field(..., alias="@codecs")
    mime_type: str = Field(..., alias="@mimeType")
    base_url: str = Field(..., alias="BaseURL")
    segments: SegmentBase = Field(..., alias="SegmentBase")


class AdaptationSet(BaseModel):
    content_type: ContentType = Field(..., alias="@contentType")
    width: Optional[int] = Field(None, alias="@width")
    height: Optional[int] = Field(None, alias="@height")
    par: Optional[str] = Field(None, alias="@par")
    protections: List[ContentProtection] = Field(..., alias="ContentProtection")
    representation: Union[Representation, List[Representation]] = Field(
        ..., alias="Representation"
    )


class Period(BaseModel):
    adaptation_set: List[AdaptationSet] = Field(..., alias="AdaptationSet", min_items=1)


class MPDMeta(BaseModel):
    period: Period = Field(..., alias="Period")


class MPDFile(BaseModel):
    meta: MPDMeta = Field(..., alias="MPD")


def urljoin(*args):
    return "/".join(map(lambda x: str(x).rstrip("/"), args))


def fetch_mpd(mpd_url: str) -> MPDFile:
    """
    Fetches an MPD file and parses it.
    """
    print("fetching MPD: %s" % mpd_url)
    mpd_resp = requests.get(mpd_url)
    mpd_resp.raise_for_status()
    print("parsing MPD")
    return MPDFile.parse_obj(xmltodict.parse(mpd_resp.text))


def fetch_file(url: str, filename: str):
    """
    Fetches a file.
    """
    if not os.path.exists(filename):
        print("fetching file: %s" % url)
        resp = requests.get(url)
        resp.raise_for_status()
        with open(filename, "wb+") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)


def download_episode(episode: Episode, base: str, mpd: str, dir: str, name: str):
    """
    Downloads a single episode.
    """
    combined_filename = os.path.join(dir, name + ".mp4")
    video_filename = os.path.join(dir, name + ".video.mp4")
    audio_filename = os.path.join(dir, name + ".audio.mp4")
    # don't redownload if already exists
    if not os.path.exists(combined_filename):
        print("downloading episode: %s" % name)
        # fetch MPD
        mpd_data = fetch_mpd(urljoin(base, episode.id, mpd))
        # extract audio/video fragment locations
        video = mpd_data.meta.period.adaptation_set[0]
        audio = mpd_data.meta.period.adaptation_set[1]
        assert isinstance(video.representation, list)
        assert isinstance(audio.representation, Representation)
        # fetch video
        video_url = urljoin(base, episode.id, video.representation[-1].base_url)
        fetch_file(video_url, video_filename)
        # fetch audio
        audio_url = urljoin(base, episode.id, audio.representation.base_url)
        fetch_file(audio_url, audio_filename)
        # decrypt and combine
        if not os.path.exists(combined_filename):
            print("decrypting and recombining video/audio files")
            assert video.protections[0].cenc_kid is not None
            assert audio.protections[0].cenc_kid is not None
            video_key_id = video.protections[0].cenc_kid.replace("-", "")
            audio_key_id = audio.protections[0].cenc_kid.replace("-", "")
            video_key = episode.keys[video_key_id]
            audio_key = episode.keys[audio_key_id]
            video_input = ffmpeg.input(video_filename, decryption_key=video_key).video
            audio_input = ffmpeg.input(audio_filename, decryption_key=audio_key).audio
            ffmpeg.output(
                video_input,
                audio_input,
                combined_filename,
                acodec="copy",
                vcodec="copy",
            ).overwrite_output().run()
    # remove encrypted files
    try:
        os.remove(video_filename)
    except:
        pass
    try:
        os.remove(audio_filename)
    except:
        pass


def download_playlist(playlist: Playlist):
    """
    Downloads an entire playlist.
    """
    print("downloading playlist")
    for chapter_name, chapter in playlist.chapters.items():
        chapter_name = chapter_name.replace("/", "-")
        print("creating chapter dir: %s" % chapter_name)
        os.makedirs(chapter_name, exist_ok=True)
        for episode_name, episode in chapter.episodes.items():
            episode_name = episode_name.replace("/", "-")
            download_episode(
                episode,
                base=playlist.source.base,
                mpd=playlist.source.mpd,
                dir=chapter_name,
                name=episode_name,
            )


if __name__ == "__main__":
    playlist: Playlist = Playlist.parse_obj(toml.load(sys.argv[1]))
    download_playlist(playlist)
