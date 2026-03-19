"""Convert logo.svg to a C header XBM bitmap for ESP32 TFT_eSPI display.
Pure Pillow approach — parses SVG path data directly (all paths are line segments)."""
from PIL import Image, ImageDraw
import xml.etree.ElementTree as ET
import math
import re

# Target display: 480x320, want small margin
MARGIN = 20
MAX_W = 480 - 2 * MARGIN  # 440
MAX_H = 320 - 2 * MARGIN  # 280

SVG_PATH = "../../images/logo.svg"

# ─── SVG Path Parser ────────────────────────────────────────────────────────

def parse_svg_path(d):
    """Parse SVG path d attribute into list of sub-paths (list of (x,y) tuples).
    Handles: M/m L/l H/h V/v Z/z and implicit lineto after moveto."""
    # Tokenize: split into commands and numbers
    tokens = re.findall(r'[MmLlHhVvZz]|[-+]?(?:\d+\.?\d*|\.\d+)', d)

    sub_paths = []
    current_path = []
    cx, cy = 0.0, 0.0  # current point
    sx, sy = 0.0, 0.0  # sub-path start

    i = 0
    cmd = None
    while i < len(tokens):
        t = tokens[i]
        if t in 'MmLlHhVvZz':
            cmd = t
            i += 1
            if cmd in 'Zz':
                cx, cy = sx, sy
                if current_path:
                    current_path.append((cx, cy))
                    sub_paths.append(current_path)
                    current_path = []
                continue
        else:
            # Implicit command: after M→L, after m→l
            if cmd == 'M':
                cmd = 'L'
            elif cmd == 'm':
                cmd = 'l'

        if cmd in 'Mm':
            x = float(tokens[i]); i += 1
            y = float(tokens[i]); i += 1
            if cmd == 'm':
                cx += x; cy += y
            else:
                cx, cy = x, y
            sx, sy = cx, cy
            if current_path:
                sub_paths.append(current_path)
            current_path = [(cx, cy)]
        elif cmd in 'Ll':
            x = float(tokens[i]); i += 1
            y = float(tokens[i]); i += 1
            if cmd == 'l':
                cx += x; cy += y
            else:
                cx, cy = x, y
            current_path.append((cx, cy))
        elif cmd in 'Hh':
            x = float(tokens[i]); i += 1
            if cmd == 'h':
                cx += x
            else:
                cx = x
            current_path.append((cx, cy))
        elif cmd in 'Vv':
            y = float(tokens[i]); i += 1
            if cmd == 'v':
                cy += y
            else:
                cy = y
            current_path.append((cx, cy))

    if current_path:
        sub_paths.append(current_path)
    return sub_paths


def rotate_point(x, y, angle_deg, ox, oy):
    """Rotate (x,y) around (ox,oy) by angle_deg degrees."""
    a = math.radians(angle_deg)
    dx, dy = x - ox, y - oy
    return (ox + dx * math.cos(a) - dy * math.sin(a),
            oy + dx * math.sin(a) + dy * math.cos(a))


# ─── Parse SVG ──────────────────────────────────────────────────────────────

ns = {'svg': 'http://www.w3.org/2000/svg'}
tree = ET.parse(SVG_PATH)
root = tree.getroot()

# viewBox
vb = root.get('viewBox').split()
vb_x, vb_y, vb_w, vb_h = float(vb[0]), float(vb[1]), float(vb[2]), float(vb[3])

# Get the transform from the <g> element
g = root.find('.//svg:g', ns)
transform = g.get('transform', '')
rot_match = re.search(r'rotate\(([\d.]+),([\d.]+),([\d.]+)\)', transform)
rot_angle = float(rot_match.group(1)) if rot_match else 0
rot_ox = float(rot_match.group(2)) if rot_match else 0
rot_oy = float(rot_match.group(3)) if rot_match else 0

print(f"SVG viewBox: {vb_w}x{vb_h}, rotation: {rot_angle}° around ({rot_ox},{rot_oy})")

# Parse all paths
all_sub_paths = []
for path_el in g.findall('svg:path', ns):
    d = path_el.get('d', '')
    subs = parse_svg_path(d)
    all_sub_paths.extend(subs)

print(f"Found {len(all_sub_paths)} sub-paths")

# Apply rotation transform to all points
for j, sp in enumerate(all_sub_paths):
    all_sub_paths[j] = [rotate_point(x, y, rot_angle, rot_ox, rot_oy) for x, y in sp]

# Compute bounding box of all rotated points
all_pts = [p for sp in all_sub_paths for p in sp]
min_x = min(p[0] for p in all_pts)
max_x = max(p[0] for p in all_pts)
min_y = min(p[0] for p in all_pts)
max_y = max(p[1] for p in all_pts)
min_y = min(p[1] for p in all_pts)

svg_actual_w = max_x - min_x
svg_actual_h = max_y - min_y
print(f"Bounding box: ({min_x:.0f},{min_y:.0f}) to ({max_x:.0f},{max_y:.0f}) = {svg_actual_w:.0f}x{svg_actual_h:.0f}")

# ─── Scale and Render ───────────────────────────────────────────────────────

svg_aspect = svg_actual_w / svg_actual_h
target_w = MAX_W
target_h = int(target_w / svg_aspect)
if target_h > MAX_H:
    target_h = MAX_H
    target_w = int(target_h * svg_aspect)

# XBM width must be multiple of 8
target_w = (target_w // 8) * 8

print(f"Target bitmap: {target_w}x{target_h}")

# Render at 4x for anti-aliasing
SCALE = 4
render_w = target_w * SCALE
render_h = target_h * SCALE

# Scale factor from SVG coords to render coords (with small padding)
pad = 2 * SCALE
sx = (render_w - 2 * pad) / svg_actual_w
sy = (render_h - 2 * pad) / svg_actual_h
s = min(sx, sy)
off_x = pad + (render_w - 2 * pad - svg_actual_w * s) / 2 - min_x * s
off_y = pad + (render_h - 2 * pad - svg_actual_h * s) / 2 - min_y * s

# Render each sub-path as filled polygon using even-odd rule
# Strategy: render each sub-path on a separate layer, XOR them together
img = Image.new("L", (render_w, render_h), 0)

for sp in all_sub_paths:
    if len(sp) < 3:
        continue
    scaled = [(x * s + off_x, y * s + off_y) for x, y in sp]
    layer = Image.new("L", (render_w, render_h), 0)
    draw = ImageDraw.Draw(layer)
    draw.polygon(scaled, fill=255)
    # XOR with accumulated image (even-odd fill rule)
    img = Image.eval(Image.merge("L", [
        Image.eval(img, lambda a: a),
    ]).split()[0], lambda a: a)
    # XOR: result = img XOR layer
    import numpy as np
    arr_img = bytearray(img.tobytes())
    arr_lay = layer.tobytes()
    for k in range(len(arr_img)):
        arr_img[k] = arr_img[k] ^ arr_lay[k]
    img = Image.frombytes("L", (render_w, render_h), bytes(arr_img))

# Downscale to target size (anti-aliasing via averaging)
img = img.resize((target_w, target_h), Image.LANCZOS)

# Threshold
threshold = 64  # Lower threshold since anti-aliasing dims edges
pixels = img.load()

# ─── Build XBM ──────────────────────────────────────────────────────────────

xbm_bytes = []
for y in range(target_h):
    for x_byte in range(target_w // 8):
        byte_val = 0
        for bit in range(8):
            x = x_byte * 8 + bit
            if pixels[x, y] > threshold:
                byte_val |= (1 << bit)  # XBM is LSB first
        xbm_bytes.append(byte_val)

print(f"Total bytes: {len(xbm_bytes)} ({len(xbm_bytes)/1024:.1f} KB)")

# Write C header
with open("logo_bitmap.h", "w") as f:
    f.write(f"// Auto-generated from logo.svg — {target_w}x{target_h} XBM bitmap\n")
    f.write(f"// Use with tft.drawXBitmap(x, y, logo_bitmap, LOGO_WIDTH, LOGO_HEIGHT, color)\n\n")
    f.write("#pragma once\n")
    f.write("#include <pgmspace.h>\n\n")
    f.write(f"#define LOGO_WIDTH  {target_w}\n")
    f.write(f"#define LOGO_HEIGHT {target_h}\n\n")
    f.write(f"static const uint8_t logo_bitmap[] PROGMEM = {{\n")

    for i, b in enumerate(xbm_bytes):
        if i % 16 == 0:
            f.write("    ")
        f.write(f"0x{b:02x}")
        if i < len(xbm_bytes) - 1:
            f.write(", ")
        if i % 16 == 15:
            f.write("\n")

    if len(xbm_bytes) % 16 != 0:
        f.write("\n")
    f.write("};\n")

print(f"Written logo_bitmap.h ({target_w}x{target_h})")

# Preview PNG
img_preview = Image.new("RGB", (target_w, target_h), (0, 0, 0))
for y in range(target_h):
    for x in range(target_w):
        if pixels[x, y] > threshold:
            img_preview.putpixel((x, y), (255, 0, 0))
img_preview.save("logo_preview.png")
print("Written logo_preview.png")
