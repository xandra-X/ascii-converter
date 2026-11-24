#!/usr/bin/env python3
"""Convert a local video or image into detailed, colored ASCII art (video -> .mp4, image -> .png).

Usage:
    python3 ascii_video.py                      # opens a file picker
    python3 ascii_video.py input.mp4            # -> input_ascii.mp4
    python3 ascii_video.py photo.jpg            # -> photo_ascii.png
    python3 ascii_video.py input.mp4 --cols 240 --font-size 10 -o out.mp4

Needs: pip install opencv-python numpy pillow   (ffmpeg optional, keeps audio)
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

# Wide charset = more detail; it gets sorted by real ink density below.
CHARSET = " .'`^\",:;Il!i><~+_-?][}{1)(|\\/tfjrxnuvczXYUJCLQ0OZmwqpdbkhao*#MW&8%B@$"
FONTS = ["/System/Library/Fonts/Menlo.ttc", "/Library/Fonts/Courier New.ttf",
         "C:/Windows/Fonts/consola.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"]

# HEIC is listed so it gets a clear error: OpenCV cannot decode it.
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".heif")


def load_font(size):
    for path in FONTS:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def build_glyphs(font, gap=0):
    """Render each char to a mask; return (masks sorted dark->bright, cell_w, cell_h). gap = empty px around chars."""
    left, top, right, bottom = font.getbbox("@")
    cw, ch = right - left + gap, int(font.size * 1.2) + gap
    masks = []
    for c in CHARSET:
        img = Image.new("L", (cw, ch), 0)
        ImageDraw.Draw(img).text((gap // 2 - left, (ch - font.size) // 2), c, font=font, fill=255)
        masks.append(np.asarray(img, np.float32) / 255.0)
    masks = np.stack(masks)
    order = np.argsort(masks.mean(axis=(1, 2)), kind="stable")
    return masks[order], cw, ch


BAND = 4  # Matrix mode swaps among chars within +-BAND density steps, so shapes stay readable


def frame_to_ascii(frame, masks, cols, rows, gamma, jitter=None, rng=None, flicker=0.15):
    """jitter/rng given = Matrix mode: chars still follow brightness but keep swapping to look-alikes."""
    small = cv2.resize(frame, (cols, rows), interpolation=cv2.INTER_AREA)
    lum = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
    # Stretch contrast per frame so dark videos don't turn into dim noise.
    lo, hi = np.percentile(lum, (2, 98))
    # Limit the stretch so nearly all-white or all-black frames don't go blank or turn into noise.
    lo, hi = min(lo, 0.2), max(hi, 0.3)
    lum = np.clip((lum - lo) / (hi - lo), 0, 1) ** gamma
    color = small.astype(np.float32) / hi
    idx = (lum * (len(masks) - 1)).astype(np.intp)
    if jitter is not None:
        flip = rng.random(jitter.shape) < flicker
        jitter[flip] = rng.integers(-BAND, BAND + 1, flip.sum())
        idx = np.where(lum > 0.1, np.clip(idx + jitter, 1, len(masks) - 1), 0)  # index 0 is space
    color = np.clip(color * 1.2 + 20, 0, 255)
    tiles = masks[idx][..., None] * color[:, :, None, None, :]  # rows, cols, ch, cw, 3
    r, c, h, w, _ = tiles.shape
    return tiles.transpose(0, 2, 1, 3, 4).reshape(r * h, c * w, 3).astype(np.uint8)


def pick_file():
    import tkinter as tk
    from tkinter import filedialog
    tk.Tk().withdraw()
    return filedialog.askopenfilename(
        title="Choose a video or image",
        filetypes=[("Video or image", "*.mp4 *.mov *.avi *.mkv *.webm *.m4v *.gif *" + " *".join(IMAGE_EXTS)),
                   ("All", "*.*")])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", nargs="?", help="video or image file (omit to open a file picker)")
    ap.add_argument("-o", "--output", help="output file (default: <input>_ascii.mp4, or .png for images)")
    ap.add_argument("--cols", type=int, default=100, help="characters per row; lower = bigger chars (default 100)")
    ap.add_argument("--font-size", type=int, default=16, help="font size in px (default 16)")
    ap.add_argument("--spacing", type=int, default=4, help="empty px between chars (default 4)")
    ap.add_argument("--gamma", type=float, default=0.8, help="<1 brighter/fuller, >1 darker/sparser (default 0.8)")
    ap.add_argument("--flicker", type=float, default=0.15, help="share of chars that change each frame, 0-1 (default 0.15)")
    ap.add_argument("--classic", action="store_true", help="no random flicker: chars picked by brightness")
    args = ap.parse_args()

    src = args.input or pick_file()
    if not src or not os.path.isfile(src):
        sys.exit(f"No such file: {src!r}")
    base, ext = os.path.splitext(src)
    is_image = ext.lower() in IMAGE_EXTS
    out = args.output or base + ("_ascii.png" if is_image else "_ascii.mp4")
    if os.path.realpath(out) == os.path.realpath(src):
        sys.exit("Output would overwrite the input file; choose another -o name.")
    if is_image and not cv2.haveImageWriter(out):
        sys.exit(f"Can't save an image as {out!r}; use a name ending in .png or .jpg.")

    if is_image:
        image = cv2.imread(src)
        if image is None:
            sys.exit(f"Could not open image: {src} (HEIC photos: export as JPG first)")
        vh, vw = image.shape[:2]
    else:
        cap = cv2.VideoCapture(src)
        if not cap.isOpened():
            sys.exit(f"Could not open video: {src}")
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        vw, vh = cap.get(cv2.CAP_PROP_FRAME_WIDTH), cap.get(cv2.CAP_PROP_FRAME_HEIGHT)

    masks, cw, ch = build_glyphs(load_font(args.font_size), args.spacing)
    rows = max(1, round(args.cols * (vh / vw) * (cw / ch)))
    W, H = args.cols * cw, rows * ch
    print(f"{src} -> {out}\n{args.cols}x{rows} chars, {W}x{H}px" + ("" if is_image else f", {fps:.2f} fps, {total} frames"))

    rng = np.random.default_rng()
    jitter = None if args.classic else rng.integers(-BAND, BAND + 1, (rows, args.cols))
    if is_image:
        if not cv2.imwrite(out, frame_to_ascii(image, masks, args.cols, rows, args.gamma, jitter, rng, args.flicker)):
            sys.exit(f"Could not save: {out}")
        print(f"Done: {out}")
        return

    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False).name
    writer = cv2.VideoWriter(tmp, cv2.VideoWriter_fourcc(*"mp4v"), fps, (W, H))
    n = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        writer.write(frame_to_ascii(frame, masks, args.cols, rows, args.gamma, jitter, rng, args.flicker))
        n += 1
        if n % 10 == 0 or n == total:
            print(f"\rframe {n}/{total}", end="", flush=True)
    cap.release()
    writer.release()
    print()
    if n == 0:
        os.remove(tmp)
        sys.exit("No frames could be read from the video.")

    if shutil.which("ffmpeg"):
        # Re-encode to H.264 (plays everywhere) and copy the original audio if any.
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", tmp, "-i", src, "-map", "0:v", "-map", "1:a?",
               "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
               "-c:a", "aac", out]
        if subprocess.run(cmd).returncode == 0:
            os.remove(tmp)
            print(f"Done: {out}")
            return
        print("ffmpeg failed; saving silent video instead.")
    shutil.move(tmp, out)
    print(f"Done (no audio, install ffmpeg to keep it): {out}")


if __name__ == "__main__":
    main()
