# PS5 Movie Converter

Make any movie file play on the **PlayStation 5 Media Player** with picture and sound.

Many movie files open on the PS5 but play with **no sound**, or don't open at all. Usually that's
because the audio is Dolby Digital Plus / Atmos, DTS or TrueHD, or the video is HEVC, 10-bit or HDR.
The PS5 Media Player handles only a small set of formats. This tool checks every stream in a file,
keeps whatever is already compatible, and converts only what isn't.

```
Movie.mkv  (H.264 video + Dolby Digital Plus Atmos audio)   ->  no sound on PS5
Movie.PS5.mp4  (same video, copied untouched + AAC 5.1)       ->  plays with sound
```

## What the PS5 plays

According to Sony's [PS5 media support page](https://www.playstation.com/en-us/support/hardware/play-video-music-discs-usb-drives/):

| Container | Video                                   | Audio  |
|-----------|-----------------------------------------|--------|
| MP4       | H.264 / AVC, High Profile up to L5.2    | AAC-LC |
| MKV       | H.264 / AVC, High Profile up to L4.2    | AAC-LC |
| WEBM      | VP9                                     | Opus   |

The maximum resolution is 3840x2160 and the player is SDR only.

**Not supported:** E-AC-3 (Dolby Digital Plus / Atmos), DTS, TrueHD, FLAC, HEVC / H.265, AV1,
10-bit video, HDR10 / HLG / Dolby Vision, and picture-based subtitles (PGS / VobSub) in MP4.

## What the converter does

| Source                                         | Result                                                       |
|------------------------------------------------|--------------------------------------------------------------|
| H.264 8-bit video                              | **Copied untouched**, so it's fast and loses no quality      |
| HEVC, AV1, VC-1, MPEG-4, 10-bit, etc.          | Re-encoded to H.264 High Profile, 8-bit (x264 CRF 19)        |
| HDR10 / HLG / Dolby Vision                     | Tone-mapped to SDR (BT.709) so colours don't look washed out |
| Larger than 3840x2160                          | Scaled down to fit 4K                                        |
| Interlaced                                     | Deinterlaced                                                 |
| Any non-AAC audio (E-AC-3, DTS, TrueHD, FLAC…) | AAC-LC 5.1 at 448 kb/s (or stereo with `--stereo`)           |
| 7.1 audio                                      | Downmixed to 5.1                                             |
| Text subtitles (SRT / ASS / WebVTT)            | Kept as MP4 text subtitles                                   |
| Picture subtitles (PGS / VobSub)               | Dropped, or burned into the picture with `--burn-subs`       |

Every audio track is kept. The preferred language (English by default) goes first and is set as
the default track. The output is `<name>.PS5.mp4` next to the original. After converting, the tool
checks the result: codecs, pixel format and duration.

## Requirements

- **Python 3.8+**
- **FFmpeg** (`ffmpeg` and `ffprobe`). Use a full build, which includes the `zscale` filter for HDR tone-mapping.

| OS      | Install                                                                                     |
|---------|---------------------------------------------------------------------------------------------|
| Windows | `winget install Gyan.FFmpeg` and `winget install Python.Python.3.12` (the launcher can do this for you) |
| macOS   | `brew install ffmpeg python`                                                                |
| Linux   | `sudo apt install ffmpeg python3`                                                           |

## Usage

### Windows: drag and drop

1. Download or clone this repository.
2. Drag one or more movie files, or a whole folder, onto **`PS5 Convert.bat`**.
   You can also put the `.bat` and `.py` in your movies folder and double-click the `.bat`
   to convert everything in that folder.
3. Copy the resulting `*.PS5.mp4` files into a folder on a USB drive and open them from **Media Gallery** on the PS5.

If Python or FFmpeg is missing on the first run, the launcher offers to install it with `winget`.

### Command line (any OS)

```bash
python ps5_convert.py "Movie.mkv"                  # one file
python ps5_convert.py "D:\Movies" -r --out E:\     # whole folder tree, write straight to the USB drive
python ps5_convert.py "Movie.mkv" --check          # just report what's incompatible
python ps5_convert.py "Movie.mkv" --sample         # 2-minute test clip to try on the PS5 first
```

### Options

| Option                         | Description                                                              |
|--------------------------------|--------------------------------------------------------------------------|
| `-o, --out DIR`                | Write output to `DIR` instead of next to each source                     |
| `-r, --recursive`              | Search folders recursively                                               |
| `--check`                      | Analyse only, don't convert                                              |
| `--sample [SECONDS]`           | Make a short test clip (default 120 s) named `.PS5-sample.mp4`           |
| `--overwrite`                  | Replace existing output files                                            |
| `--stereo`                     | Convert audio to 2.0 instead of 5.1                                      |
| `--lang CODE`                  | Preferred audio/subtitle language, put first (default `eng`)             |
| `--first-audio-only`           | Keep only the preferred audio track                                      |
| `--no-subs`                    | Leave out subtitles                                                      |
| `--burn-subs`                  | Burn the first preferred-language subtitle into the picture             |
| `--keep-chapters`              | Keep chapter markers (adds an extra data track)                          |
| `--force-video`                | Always re-encode the video                                               |
| `--max-height N`               | Downscale video, e.g. `1080` to turn 4K into 1080p                       |
| `--encoder x264\|nvenc\|qsv\|amf` | H.264 encoder for re-encodes: CPU (best quality), NVIDIA, Intel or AMD GPU |
| `--crf N`                      | Video quality, lower is better (default 19)                              |
| `--preset NAME`                | x264 speed preset (default `medium`)                                     |
| `--audio-bitrate-51 RATE`      | AAC 5.1 bitrate (default `448k`)                                         |
| `--audio-bitrate-20 RATE`      | AAC stereo bitrate (default `192k`)                                      |
| `--delete-original`            | Delete the source after a successful conversion                          |
| `-v, --verbose`                | Print the FFmpeg command                                                 |

## Troubleshooting

- **The file is over 4 GB and won't copy to the USB drive:** format the drive as **exFAT**. FAT32 can't hold files over 4 GB.
- **Still no sound:** run again with `--stereo`. Some setups only handle stereo AAC.
- **Subtitles don't show:** run with `--burn-subs` to put them into the picture.
- **Converting 4K HEVC is slow:** use `--encoder nvenc`, `qsv` or `amf` to encode on your graphics card, or `--max-height 1080`.
- **HDR colours look washed out:** your FFmpeg build has no `zscale` filter. Install a full build, for example `winget install Gyan.FFmpeg`.

## Limitations

- Dolby Atmos object metadata is dropped. You get the 5.1 bed as AAC 5.1.
- Dolby Vision profile 5 files without an HDR10 base layer may come out with odd colours.
- DRM-protected files can't be converted.

## License

[MIT](LICENSE) © 2026 adanglingpointer

---

*Not affiliated with or endorsed by Sony Interactive Entertainment. "PlayStation" and "PS5" are
trademarks of Sony Interactive Entertainment Inc.*
