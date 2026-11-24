"""Run: python3 test_ascii_video.py"""
import os, subprocess, sys, tempfile
import cv2, numpy as np
import ascii_video as a

script = os.path.abspath(a.__file__)
run = lambda *args: subprocess.run([sys.executable, script, *args], capture_output=True, text=True)

masks, _, _ = a.build_glyphs(a.load_font(16), 4)
assert masks[0].max() == 0, "darkest glyph must be the space"
page = np.full((200, 200, 3), 255, np.uint8)
page[95:105, 95:105] = 0
assert a.frame_to_ascii(page, masks, 40, 20, 0.8).max() > 200, "white page went blank"
assert a.frame_to_ascii(np.full_like(page, 2), masks, 40, 20, 0.8).max() < 60, "black frame turned into noise"

with tempfile.TemporaryDirectory() as d:
    p = lambda name: os.path.join(d, name)
    img = np.zeros((150, 300, 3), np.uint8)
    img[:, 150:] = (0, 0, 255)  # left black, right red (BGR)
    for ext in ("png", "jpg", "JPEG", "webp", "bmp", "tiff"):
        src = p(f"in_{ext}.{ext}")
        assert cv2.imwrite(src, img)
        res = run(src)
        assert res.returncode == 0, res.stderr
        got = cv2.imread(p(f"in_{ext}_ascii.png")).astype(int)
        half = got.shape[1] // 2
        assert abs(got.shape[1] / got.shape[0] - 2) < 0.1, "aspect ratio"
        assert got[:, half + 30:, 2].mean() > 3 * got[:, half + 30:, 0].mean(), "right half should be red"
        assert got[:, : half - 30].mean() < 5, "left half should be blank"

    src = p("in_png.png")
    before = open(src, "rb").read()
    assert run(src, "-o", src).returncode != 0 and open(src, "rb").read() == before, "input overwritten"
    assert run(src, "-o", p("x.mp4")).returncode != 0
    assert run(src, "-o", p("nodir/x.png")).returncode != 0
    open(p("bad.png"), "w").write("not an image")
    open(p("photo.heic"), "w").write("x")
    for bad in ("bad.png", "photo.heic"):
        res = run(p(bad))
        assert res.returncode != 0 and "Could not open image" in res.stderr, res.stderr
print("ok")
