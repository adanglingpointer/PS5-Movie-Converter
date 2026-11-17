#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 adanglingpointer
"""
ps5_convert.py - make any movie file play on the PlayStation 5 Media Player.

The PS5 Media Player (USB / Media Gallery) officially supports:
    MP4  : H.264 (High Profile, up to Level 5.2)  +  AAC-LC audio
    MKV  : H.264 (High Profile, up to Level 4.2)  +  AAC-LC audio
    max resolution 3840x2160, 8-bit SDR only (no HDR)

Anything else (E-AC-3 / Dolby Digital Plus, Atmos, DTS, TrueHD, FLAC, Opus,
HEVC/H.265, AV1, 10-bit, HDR, Dolby Vision, interlaced video, PGS subtitles...)
either won't play or plays without sound/picture.

This script inspects every stream with ffprobe and only re-encodes what the
PS5 can't handle. A file whose video is already H.264 8-bit keeps its video
untouched (fast, no quality loss) and only the audio gets converted.

Output: "<name>.PS5.mp4" next to the original (or in --out folder).

Requires FFmpeg (ffmpeg + ffprobe) on PATH.
    Windows:  winget install Gyan.FFmpeg
    macOS:    brew install ffmpeg
    Linux:    sudo apt install ffmpeg

Usage examples:
    python ps5_convert.py "Movie.mkv"
    python ps5_convert.py "D:\\Movies"                 (every video in the folder)
    python ps5_convert.py "D:\\Movies" -r --out E:\\    (recursive, write to USB drive)
    python ps5_convert.py Movie.mkv --check           (just report what's wrong)
    python ps5_convert.py Movie.mkv --stereo          (2.0 audio instead of 5.1)
    python ps5_convert.py Movie.mkv --burn-subs       (burn subtitles into picture)
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

VERSION = "1.0"

VIDEO_EXTS = {".mkv", ".mp4", ".m4v", ".avi", ".mov", ".wmv", ".flv", ".webm",
              ".ts", ".m2ts", ".mts", ".mpg", ".mpeg", ".vob", ".ogv", ".3gp",
              ".divx", ".xvid", ".rmvb", ".asf", ".f4v"}

TEXT_SUBS = {"subrip", "srt", "ass", "ssa", "mov_text", "webvtt", "text", "tx3g"}
IMAGE_SUBS = {"hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle", "xsub", "pgssub"}

HDR_TRANSFERS = {"smpte2084", "arib-std-b67"}
OK_PIX_FMTS = {"yuv420p", "yuvj420p"}
OK_H264_PROFILES = {"high", "main", "constrained baseline", "baseline"}

MAX_W, MAX_H = 3840, 2160
MAX_LEVEL_MP4 = 52          # Sony: MP4 H.264 High Profile up to Level 5.2
FAT32_LIMIT = 4 * 1024 ** 3 - 1


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def say(msg=""):
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode(), flush=True)


def find_tool(name):
    exe = shutil.which(name)
    if exe:
        return exe
    # Common Windows install spots (winget / chocolatey / manual)
    if os.name == "nt":
        cands = [
            Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links" / f"{name}.exe",
            Path("C:/ffmpeg/bin") / f"{name}.exe",
            Path("C:/ProgramData/chocolatey/bin") / f"{name}.exe",
            Path(__file__).resolve().parent / f"{name}.exe",
            Path(__file__).resolve().parent / "bin" / f"{name}.exe",
        ]
        pkgs = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
        if pkgs.is_dir():
            cands += list(pkgs.glob(f"Gyan.FFmpeg*/**/bin/{name}.exe"))
        for c in cands:
            if c.is_file():
                return str(c)
    return None


def probe(ffprobe, path):
    cmd = [ffprobe, "-v", "error", "-print_format", "json",
           "-show_format", "-show_streams", "-show_chapters", str(path)]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or "ffprobe failed")
    return json.loads(r.stdout)


def ffmpeg_has_filter(ffmpeg, name):
    r = subprocess.run([ffmpeg, "-hide_banner", "-filters"], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    return any(line.split()[1:2] == [name] for line in r.stdout.splitlines() if line.strip())


def ffmpeg_has_encoder(ffmpeg, name):
    r = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    return any(line.split()[1:2] == [name] for line in r.stdout.splitlines() if line.strip())


def lang_of(s):
    return (s.get("tags", {}) or {}).get("language", "und").lower()


def title_of(s):
    return (s.get("tags", {}) or {}).get("title", "")


def fmt_time(sec):
    sec = max(0, int(sec))
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def human_size(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


# --------------------------------------------------------------------------- #
# analysis
# --------------------------------------------------------------------------- #

def analyse_video(v):
    """Return list of reasons the video stream must be re-encoded (empty = copy)."""
    reasons = []
    codec = v.get("codec_name", "")
    if codec != "h264":
        reasons.append(f"video codec {codec.upper()} not supported (needs H.264)")
    pix = v.get("pix_fmt", "")
    if pix and pix not in OK_PIX_FMTS:
        reasons.append(f"pixel format {pix} (needs 8-bit yuv420p)")
    if codec == "h264":
        prof = (v.get("profile") or "").lower()
        if prof and prof not in OK_H264_PROFILES:
            reasons.append(f"H.264 profile '{v.get('profile')}' not supported")
        lvl = v.get("level") or 0
        if lvl and lvl > MAX_LEVEL_MP4:
            reasons.append(f"H.264 level {lvl / 10:.1f} too high (max 5.2)")
    if v.get("color_transfer") in HDR_TRANSFERS:
        reasons.append("HDR video (PS5 media player is SDR only) - will tone-map")
    if any(sd.get("side_data_type", "").startswith("DOVI") for sd in v.get("side_data_list", []) or []):
        if "HDR video (PS5 media player is SDR only) - will tone-map" not in reasons:
            reasons.append("Dolby Vision video - will convert to SDR")
    w, h = v.get("width", 0) or 0, v.get("height", 0) or 0
    if w > MAX_W or h > MAX_H:
        reasons.append(f"resolution {w}x{h} above 3840x2160")
    fo = v.get("field_order", "progressive")
    if fo not in ("progressive", "unknown", ""):
        reasons.append(f"interlaced video ({fo}) - will deinterlace")
    return reasons


def audio_needs_convert(a, want_channels):
    if a.get("codec_name") != "aac":
        return True
    if (a.get("profile") or "").upper() not in ("LC", ""):
        return True                      # HE-AAC / HE-AACv2 etc.
    ch = a.get("channels", 2) or 2
    if ch > want_channels:
        return True
    return False


def pick_order(streams, lang):
    """Put streams in preferred language first, keep original order otherwise."""
    if not lang:
        return streams
    lang = lang.lower()
    first = [s for s in streams if lang_of(s).startswith(lang[:2])]
    rest = [s for s in streams if s not in first]
    return first + rest


# --------------------------------------------------------------------------- #
# command building
# --------------------------------------------------------------------------- #

def build_command(ffmpeg, src, dst_tmp, info, args, caps, workdir):
    streams = info.get("streams", [])
    videos = [s for s in streams if s.get("codec_type") == "video"
              and not (s.get("disposition", {}) or {}).get("attached_pic")]
    audios = [s for s in streams if s.get("codec_type") == "audio"]
    subs = [s for s in streams if s.get("codec_type") == "subtitle"]

    if not videos:
        raise RuntimeError("no video stream found")
    v = videos[0]

    plan = []          # human readable plan
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
           "-progress", "pipe:1", "-nostats"]
    if args.sample:
        cmd += ["-ss", str(args.sample_start), "-t", str(args.sample)]
    cmd += ["-fflags", "+genpts", "-i", str(src)]

    # ---------------- subtitles to burn ---------------------------------- #
    burn = None
    if args.burn_subs and subs:
        ordered = pick_order(subs, args.lang)
        # prefer a 'forced' track if asked for forced-only, otherwise first in language
        burn = ordered[0]
        if burn.get("codec_name") in TEXT_SUBS:
            # Extract to work dir so the subtitles filter needs no path escaping
            sub_file = Path(workdir) / "burn.ass"
            r = subprocess.run([ffmpeg, "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
                                "-i", str(src), "-map", f"0:{burn['index']}", str(sub_file)],
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
            if r.returncode != 0:
                say(f"   ! could not extract subtitle for burning: {r.stderr.strip()[:200]}")
                burn = None
        elif burn.get("codec_name") not in IMAGE_SUBS:
            burn = None

    # ---------------- video ---------------------------------------------- #
    reasons = analyse_video(v)
    if burn is not None:
        reasons.append("burning in subtitles")
    if args.force_video:
        reasons.append("--force-video given")

    if not reasons:
        cmd_v_map = ["-map", f"0:{v['index']}"]
        cmd_v = ["-c:v", "copy"]
        plan.append(f"video : H.264 {v.get('width')}x{v.get('height')} -> copy (already compatible)")
        filter_complex = None
    else:
        hdr = v.get("color_transfer") in HDR_TRANSFERS or \
            any(sd.get("side_data_type", "").startswith("DOVI") for sd in v.get("side_data_list", []) or [])
        chain = []
        fo = v.get("field_order", "progressive")
        if fo not in ("progressive", "unknown", ""):
            chain.append("yadif=mode=send_frame:deint=interlaced")
        if hdr:
            if caps["zscale"]:
                chain.append("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
                             "tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p")
            else:
                say("   ! your FFmpeg lacks 'zscale' - HDR colours may look washed out."
                    " (Use a full FFmpeg build, e.g. winget install Gyan.FFmpeg)")
        w, h = v.get("width", 0) or 0, v.get("height", 0) or 0
        post = []
        if w > MAX_W or h > MAX_H:
            post.append(f"scale=w={MAX_W}:h={MAX_H}:force_original_aspect_ratio=decrease:"
                        "force_divisible_by=2")
            out_w, out_h = MAX_W, MAX_H
        else:
            out_w, out_h = w, h
        if args.max_height and out_h > args.max_height:
            post.append(f"scale=-2:{args.max_height}")
            out_h = args.max_height
        post.append("format=yuv420p")

        if burn is not None and burn.get("codec_name") in IMAGE_SUBS:
            pre = ",".join(chain) if chain else "null"
            filter_complex = (f"[0:{v['index']}]{pre}[base];"
                              f"[base][0:{burn['index']}]overlay=eof_action=pass:repeatlast=0[sub];"
                              f"[sub]{','.join(post)}[vout]")
        else:
            if burn is not None:
                chain.append("subtitles=burn.ass")
            filter_complex = f"[0:{v['index']}]{','.join(chain + post)}[vout]"
        cmd_v_map = ["-map", "[vout]"]

        big = out_h > 1088 or out_w > 1920
        level = "5.1" if big else "4.1"
        enc = args.encoder
        if enc == "nvenc":
            cmd_v = ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", str(args.crf + 2),
                     "-b:v", "0", "-maxrate", "60M" if big else "25M", "-bufsize", "120M" if big else "50M",
                     "-profile:v", "high", "-level:v", level]
        elif enc == "qsv":
            cmd_v = ["-c:v", "h264_qsv", "-preset", "slow", "-global_quality", str(args.crf + 2),
                     "-profile:v", "high", "-level", level]
        elif enc == "amf":
            cmd_v = ["-c:v", "h264_amf", "-quality", "quality", "-rc", "cqp",
                     "-qp_i", str(args.crf), "-qp_p", str(args.crf + 2), "-qp_b", str(args.crf + 4),
                     "-profile:v", "high", "-level", level]
        else:
            cmd_v = ["-c:v", "libx264", "-preset", args.preset, "-crf", str(args.crf),
                     "-profile:v", "high", "-level:v", level,
                     "-maxrate", "60M" if big else "25M", "-bufsize", "120M" if big else "50M"]
        cmd_v += ["-pix_fmt", "yuv420p", "-color_primaries", "bt709", "-color_trc", "bt709",
                  "-colorspace", "bt709"]
        plan.append(f"video : {v.get('codec_name','?').upper()} {w}x{h} -> re-encode H.264 ({enc}); "
                    + "; ".join(reasons))

    # ---------------- audio ---------------------------------------------- #
    want_ch = 2 if args.stereo else 6
    cmd_a_map, cmd_a = [], []
    a_ordered = pick_order(audios, args.lang)
    if args.first_audio_only and a_ordered:
        a_ordered = a_ordered[:1]
    if not a_ordered:
        plan.append("audio : none in source")
    for out_i, a in enumerate(a_ordered):
        cmd_a_map += ["-map", f"0:{a['index']}"]
        ch = a.get("channels", 2) or 2
        desc = f"{a.get('codec_name','?').upper()} {ch}ch [{lang_of(a)}]"
        if title_of(a):
            desc += f" '{title_of(a)}'"
        if audio_needs_convert(a, want_ch):
            out_ch = min(ch, want_ch)
            if out_ch >= 6:
                layout, br = "5.1", args.audio_bitrate_51
            elif out_ch == 1:
                layout, br = "mono", "128k"
            else:
                layout, out_ch, br = "stereo", 2, args.audio_bitrate_20
            cmd_a += [f"-c:a:{out_i}", "aac", f"-b:a:{out_i}", br,
                      f"-filter:a:{out_i}", f"aresample=async=1:first_pts=0,aformat=channel_layouts={layout}"]
            plan.append(f"audio{out_i}: {desc} -> AAC-LC {layout} {br}")
        else:
            cmd_a += [f"-c:a:{out_i}", "copy"]
            plan.append(f"audio{out_i}: {desc} -> copy (already AAC-LC)")
        cmd_a += [f"-disposition:a:{out_i}", "default" if out_i == 0 else "0"]

    # ---------------- subtitles (soft) ----------------------------------- #
    cmd_s_map, cmd_s = [], []
    if not args.no_subs and burn is None:
        s_out = 0
        for s in pick_order(subs, args.lang):
            c = s.get("codec_name", "")
            if c in TEXT_SUBS:
                cmd_s_map += ["-map", f"0:{s['index']}"]
                cmd_s += [f"-c:s:{s_out}", "mov_text", f"-disposition:s:{s_out}", "0"]
                plan.append(f"sub{s_out}  : {c} [{lang_of(s)}]{' ' + title_of(s) if title_of(s) else ''}"
                            " -> MP4 text subtitle")
                s_out += 1
            else:
                plan.append(f"sub   : {c} [{lang_of(s)}] -> dropped (picture subtitles can't go in MP4;"
                            " use --burn-subs)")
    elif burn is not None:
        plan.append(f"sub   : {burn.get('codec_name')} [{lang_of(burn)}] -> burned into picture")

    if filter_complex:
        cmd += ["-filter_complex", filter_complex]
    cmd += cmd_v_map + cmd_a_map + cmd_s_map + cmd_v + cmd_a + cmd_s
    if args.sample:
        cmd += ["-t", str(args.sample)]
    cmd += ["-map_metadata", "0", "-map_chapters", "0" if args.keep_chapters else "-1",
            "-max_muxing_queue_size", "9999", "-avoid_negative_ts", "make_zero",
            "-movflags", "+faststart", "-f", "mp4", str(dst_tmp)]
    return cmd, plan, bool(reasons)


# --------------------------------------------------------------------------- #
# running
# --------------------------------------------------------------------------- #

def run_ffmpeg(cmd, duration, workdir):
    start = time.time()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace", cwd=workdir)
    err_lines = []

    import threading

    def read_err():
        for line in proc.stderr:
            err_lines.append(line.rstrip())
    t = threading.Thread(target=read_err, daemon=True)
    t.start()

    last_print = 0
    speed = ""
    for line in proc.stdout:
        key, _, val = line.strip().partition("=")
        if key == "speed":
            speed = val
        if key in ("out_time_us", "out_time_ms") and val.lstrip("-").isdigit():
            done = int(val) / 1_000_000
            now = time.time()
            if duration and now - last_print > 1:
                pct = max(0.0, min(100.0, done / duration * 100))
                elapsed = now - start
                eta = (elapsed / pct * (100 - pct)) if pct > 0.5 else 0
                sys.stdout.write(f"\r   {pct:5.1f}%  {fmt_time(done)} / {fmt_time(duration)}"
                                 f"  speed {speed:>7}  ETA {fmt_time(eta)}   ")
                sys.stdout.flush()
                last_print = now
    proc.wait()
    t.join(timeout=2)
    sys.stdout.write("\r" + " " * 78 + "\r")
    return proc.returncode, err_lines, time.time() - start


def collect_inputs(paths, recursive):
    files = []
    for p in paths:
        p = Path(p).expanduser().resolve()
        if p.is_dir():
            it = p.rglob("*") if recursive else p.iterdir()
            for f in sorted(it):
                if f.is_file() and f.suffix.lower() in VIDEO_EXTS and not f.name.lower().endswith(".ps5.mp4") \
                        and not f.name.lower().endswith(".part"):
                    files.append(f)
        elif p.is_file():
            files.append(p)
        else:
            say(f"!! not found: {p}")
    return files


def convert_one(src, args, tools, caps):
    ffmpeg, ffprobe = tools
    say("=" * 78)
    say(f"{src.name}")
    try:
        info = probe(ffprobe, src)
    except Exception as e:
        say(f"   !! cannot read file: {e}")
        return "error"

    out_dir = Path(args.out).expanduser().resolve() if args.out else src.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = src.stem
    tag = "PS5-sample" if args.sample else "PS5"
    dst = out_dir / f"{stem}.{tag}.mp4"
    dst_tmp = out_dir / f"{stem}.{tag}.mp4.part"

    duration = float(info.get("format", {}).get("duration") or 0)
    if args.sample:
        # start a few minutes in (past studio logos) unless burning subs,
        # where input seeking would shift subtitle timing
        args.sample_start = 0 if args.burn_subs else int(min(600, duration / 4))
        duration = max(1.0, min(float(args.sample), duration - args.sample_start))

    with tempfile.TemporaryDirectory(prefix="ps5conv_") as workdir:
        try:
            cmd, plan, reencode_video = build_command(ffmpeg, src, dst_tmp, info, args, caps, workdir)
        except Exception as e:
            say(f"   !! {e}")
            return "error"

        for line in plan:
            say(f"   {line}")

        if args.check:
            fine = all("copy" in l or "none in source" in l or "MP4 text" in l for l in plan
                       if l.startswith(("video", "audio")))
            if fine and src.suffix.lower() in (".mp4", ".m4v"):
                say("   => already PS5 compatible")
            else:
                say("   => needs conversion")
            return "checked"

        if dst.exists() and not args.overwrite:
            say(f"   -> skipped, {dst.name} already exists (use --overwrite)")
            return "skipped"

        say(f"   -> {dst}")
        if reencode_video:
            say("   (video re-encode: this can take a while)")
        if args.verbose:
            say("   " + " ".join(f'"{c}"' if " " in c else c for c in cmd))

        try:
            rc, errs, took = run_ffmpeg(cmd, duration, workdir)
        except KeyboardInterrupt:
            say("\n   interrupted")
            try:
                dst_tmp.unlink()
            except OSError:
                pass
            raise

    if rc != 0:
        say(f"   !! FFmpeg failed (code {rc}):")
        for l in errs[-15:]:
            say(f"      {l}")
        try:
            dst_tmp.unlink()
        except OSError:
            pass
        return "error"

    os.replace(dst_tmp, dst)

    # verify
    try:
        out = probe(ffprobe, dst)
        od = float(out.get("format", {}).get("duration") or 0)
        vs = [s for s in out["streams"] if s["codec_type"] == "video"]
        as_ = [s for s in out["streams"] if s["codec_type"] == "audio"]
        ok = vs and vs[0]["codec_name"] == "h264" and vs[0].get("pix_fmt") in OK_PIX_FMTS \
            and all(a["codec_name"] == "aac" for a in as_)
        if duration and abs(od - duration) > max(5, duration * 0.01):
            say(f"   ! duration differs: source {fmt_time(duration)}, output {fmt_time(od)}")
            ok = False
        size = dst.stat().st_size
        say(f"   {'OK' if ok else 'WARNING'}: {human_size(size)}, {fmt_time(od)}, done in {fmt_time(took)}")
        if size > FAT32_LIMIT:
            say("   note: file is over 4 GB - format your USB drive as exFAT (FAT32 can't hold it)")
    except Exception as e:
        say(f"   ! could not verify output: {e}")
    if args.delete_original and not args.sample:
        try:
            src.unlink()
            say("   original deleted")
        except OSError as e:
            say(f"   ! could not delete original: {e}")
    return "ok"


def main():
    ap = argparse.ArgumentParser(
        description="Convert movies so they play on the PlayStation 5 Media Player "
                    "(MP4, H.264 8-bit SDR, AAC-LC audio).")
    ap.add_argument("inputs", nargs="+", help="video files and/or folders")
    ap.add_argument("-o", "--out", help="output folder (default: next to each source file)")
    ap.add_argument("-r", "--recursive", action="store_true", help="search folders recursively")
    ap.add_argument("--check", action="store_true", help="only report compatibility, don't convert")
    ap.add_argument("--overwrite", action="store_true", help="replace existing .PS5.mp4 files")
    ap.add_argument("--sample", type=int, metavar="SECONDS", nargs="?", const=120,
                    help="make only a short test clip (default 120 s) named .PS5-sample.mp4 "
                         "to try on the PS5 before converting the whole movie")
    ap.add_argument("--stereo", action="store_true", help="convert audio to 2.0 instead of 5.1")
    ap.add_argument("--lang", default="eng",
                    help="preferred audio/subtitle language, put first & default (default: eng)")
    ap.add_argument("--first-audio-only", action="store_true",
                    help="keep only the preferred audio track (drops commentary etc.)")
    ap.add_argument("--no-subs", action="store_true", help="don't include subtitles")
    ap.add_argument("--burn-subs", action="store_true",
                    help="burn the first subtitle track (preferred language) into the picture "
                         "(forces a video re-encode)")
    ap.add_argument("--keep-chapters", action="store_true",
                    help="keep chapter markers (adds an extra data track some players dislike)")
    ap.add_argument("--force-video", action="store_true", help="always re-encode video")
    ap.add_argument("--max-height", type=int, help="downscale video to this height (e.g. 1080)")
    ap.add_argument("--encoder", choices=["x264", "nvenc", "qsv", "amf"], default="x264",
                    help="H.264 encoder when video must be re-encoded: x264 (CPU, best quality), "
                         "nvenc (NVIDIA), qsv (Intel), amf (AMD). Default x264")
    ap.add_argument("--crf", type=int, default=19, help="video quality, lower = better (default 19)")
    ap.add_argument("--preset", default="medium", help="x264 speed preset (default medium)")
    ap.add_argument("--audio-bitrate-51", default="448k", help="AAC 5.1 bitrate (default 448k)")
    ap.add_argument("--audio-bitrate-20", default="192k", help="AAC stereo bitrate (default 192k)")
    ap.add_argument("--delete-original", action="store_true",
                    help="delete the source after a successful conversion")
    ap.add_argument("-v", "--verbose", action="store_true", help="print the ffmpeg command")
    ap.add_argument("--version", action="version", version=f"ps5_convert {VERSION}")
    args = ap.parse_args()

    ffmpeg, ffprobe = find_tool("ffmpeg"), find_tool("ffprobe")
    if not ffmpeg or not ffprobe:
        say("FFmpeg was not found. Install it and try again:")
        say("   Windows : winget install Gyan.FFmpeg   (then open a new window)")
        say("   macOS   : brew install ffmpeg")
        say("   Linux   : sudo apt install ffmpeg")
        return 2

    enc_name = {"x264": "libx264", "nvenc": "h264_nvenc", "qsv": "h264_qsv", "amf": "h264_amf"}[args.encoder]
    if not ffmpeg_has_encoder(ffmpeg, enc_name):
        say(f"Your FFmpeg has no '{enc_name}' encoder; falling back to libx264.")
        args.encoder = "x264"
    caps = {"zscale": ffmpeg_has_filter(ffmpeg, "zscale")}

    files = collect_inputs(args.inputs, args.recursive)
    if not files:
        say("No video files found.")
        return 1

    say(f"PS5 converter {VERSION} - {len(files)} file(s)")
    results = {}
    try:
        for f in files:
            r = convert_one(f, args, (ffmpeg, ffprobe), caps)
            results[r] = results.get(r, 0) + 1
    except KeyboardInterrupt:
        say("\nStopped by user.")
        return 130
    say("=" * 78)
    say("Done: " + ", ".join(f"{v} {k}" for k, v in results.items()))
    return 1 if results.get("error") else 0


if __name__ == "__main__":
    sys.exit(main())
