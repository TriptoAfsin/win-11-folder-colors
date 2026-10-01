"""Recolor the Windows 11 folder icons that live in imageres.dll.mun.

Explorer draws every folder from five icon groups:
  3, 4  closed folder (empty folders, small/details view)
  5     back panel of a folder that has contents
  6     front panel (content thumbnails are drawn between 5 and 6)
  162   folder with a sheet of paper

Recoloring those groups (instead of using desktop.ini custom icons) keeps the
content thumbnails working. All work here is done on copies; the elevated swap
into C:\\Windows\\SystemResources is handled by apply.ps1.

Usage:
  python folder_colors.py list
  python folder_colors.py patch <color> <pristine.mun> <out.mun>
  python folder_colors.py export [color ...]     # icons/ + docs/all-colors.png
"""
import io
import os
import struct
import sys

import numpy as np
import pefile
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
GROUPS = (3, 4, 5, 6, 162)
RT_ICON, RT_GROUP_ICON = 3, 14

# (dark, light) endpoints of the folder gradient, sRGB 0-255.
# The original amber gradient is remapped onto this by lightness.
PALETTES = {
    "blue":     ((0, 84, 184),   (158, 217, 255)),
    "green":    ((6, 110, 68),   (140, 228, 176)),
    "purple":   ((88, 40, 190),  (204, 176, 255)),
    "black":    ((22, 22, 25),   (88, 90, 97)),
    "gray":     ((88, 94, 104),  (206, 211, 219)),
    "teal":     ((0, 106, 118),  (132, 224, 226)),
    "red":      ((178, 28, 40),  (255, 164, 164)),
    "orange":   ((196, 78, 0),   (255, 192, 122)),
    "pink":     ((186, 38, 118), (255, 174, 214)),
    "yellow":   None,  # stock Windows look
}


# ---------- reading ----------

def load_groups(mun_path):
    """Return {group_id: [(entry_dict, PIL.Image, is_png), ...]} from a .mun/.dll."""
    pe = pefile.PE(mun_path, fast_load=True)
    pe.parse_data_directories(
        directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]])
    mm = pe.get_memory_mapped_image()

    def raw(entry):
        d = entry.directory.entries[0].data.struct
        return mm[d.OffsetToData:d.OffsetToData + d.Size]

    icons, groups = {}, {}
    for t in pe.DIRECTORY_ENTRY_RESOURCE.entries:
        if t.id == RT_ICON:
            icons = {e.id: e for e in t.directory.entries}
        elif t.id == RT_GROUP_ICON:
            groups = {e.id: e for e in t.directory.entries}

    out = {}
    for gid in GROUPS:
        g = raw(groups[gid])
        _, _, n = struct.unpack("<HHH", g[:6])
        items = []
        for i in range(n):
            w, h, cc, rs, planes, bits, size, iid = struct.unpack(
                "<BBBBHHIH", g[6 + 14 * i:20 + 14 * i])
            data = raw(icons[iid])
            is_png = data[:4] == b"\x89PNG"
            if is_png:
                img = Image.open(io.BytesIO(data)).convert("RGBA")
            else:
                ico = struct.pack("<HHH", 0, 1, 1) + struct.pack(
                    "<BBBBHHII", w, h, 0, 0, 1, 32, len(data), 22) + data
                img = Image.open(io.BytesIO(ico)).convert("RGBA")
            items.append(({"w": w or 256, "h": h or 256, "id": iid,
                           "planes": planes, "bits": bits}, img, is_png))
        out[gid] = items
    pe.close()
    return out


# ---------- recolor ----------

def recolor(img, color):
    pal = PALETTES[color]
    if pal is None:
        return img.copy()
    a = np.asarray(img.convert("RGBA")).astype(np.float32) / 255
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    mx, mn = a[..., :3].max(-1), a[..., :3].min(-1)
    d = mx - mn + 1e-6
    l = (mx + mn) / 2
    s = np.where(mx == mn, 0, (mx - mn) / (1 - np.abs(2 * l - 1) + 1e-6))
    h = np.where(mx == r, ((g - b) / d) % 6,
                 np.where(mx == g, (b - r) / d + 2, (r - g) / d + 4)) * 60
    amber = (h > 20) & (h < 70) & (s > 0.15)   # leaves white paper / shadows alone
    t = np.clip((l - 0.38) / 0.50, 0, 1) ** 0.9
    dark, light = (np.array(c, np.float32) / 255 for c in pal)
    rgb = dark * (1 - t[..., None]) + light * t[..., None]
    out = a.copy()
    out[..., :3] = np.where(amber[..., None], rgb, a[..., :3])
    return Image.fromarray((out * 255).round().astype(np.uint8))


# ---------- encoding ----------

def to_png(img):
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def to_dib(img):
    """32-bit BGRA DIB + AND mask, as stored in RT_ICON."""
    w, h = img.size
    px = np.asarray(img.convert("RGBA"))
    bgra = px[..., [2, 1, 0, 3]][::-1].tobytes()
    row = ((w + 31) // 32) * 4
    mask = bytearray()
    for y in range(h - 1, -1, -1):
        bits = np.packbits(px[y, :, 3] == 0).tobytes()
        mask += bits + b"\x00" * (row - len(bits))
    hdr = struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0,
                      len(bgra) + len(mask), 0, 0, 0, 0)
    return hdr + bgra + bytes(mask)


def recolored_groups(pristine, color):
    """{gid: [(entry, recolored_img, is_png)]}"""
    src = load_groups(pristine)
    return {gid: [(e, recolor(im, color), png) for e, im, png in items]
            for gid, items in src.items()}


# ---------- patching (Resource Hacker on a copy) ----------
# Win32 UpdateResource refuses .mun files (ERROR_NOT_SUPPORTED), so this uses
# Resource Hacker, same as LesFerch/FolderThumbnailFix.

RH = os.path.join(HERE, "tools", "ResourceHacker", "ResourceHacker.exe")


def need_rh():
    if not os.path.exists(RH):
        sys.exit("Resource Hacker not found. Run setup.cmd first.")


def to_ico(items):
    """Build a .ico keeping each entry's original format (PNG vs DIB)."""
    blobs = [to_png(img) if is_png else to_dib(img) for _, img, is_png in items]
    out = struct.pack("<HHH", 0, 1, len(items))
    off = 6 + 16 * len(items)
    for (e, _, _), data in zip(items, blobs):
        out += struct.pack("<BBBBHHII", e["w"] % 256, e["h"] % 256, 0, 0,
                           e["planes"], e["bits"], len(data), off)
        off += len(data)
    return out + b"".join(blobs)


def patch(color, pristine, out_path, lang=1033):
    import shutil, subprocess, tempfile
    need_rh()
    groups = recolored_groups(pristine, color)
    work = tempfile.mkdtemp(prefix="foldercolors-")
    shutil.copyfile(pristine, out_path)
    for gid, items in groups.items():
        ico = os.path.join(work, f"g{gid}.ico")
        with open(ico, "wb") as f:
            f.write(to_ico(items))
        log = os.path.join(work, f"g{gid}.log")
        subprocess.run([RH, "-open", out_path, "-save", out_path, "-action", "addoverwrite",
                        "-resource", ico, "-mask", f"ICONGROUP,{gid},{lang}", "-log", log],
                       check=True)
        txt = open(log, encoding="utf-16-le", errors="ignore").read() if os.path.exists(log) else ""
        if "success" not in txt.lower():
            raise RuntimeError(f"Resource Hacker failed on group {gid}: {txt}")

    # sanity check: re-read the patched file and confirm colors changed
    check = load_groups(out_path)
    for g in GROUPS:
        assert len(check[g]) == len(groups[g]), f"group {g} entry count changed"
    shutil.rmtree(work, ignore_errors=True)
    print(f"patched {color} -> {out_path}")


# ---------- exports + previews ----------

def big(items, size):
    """Best image for a requested size (exact if present, else downscale 256 / upscale)."""
    by = {e["w"]: im for e, im, _ in items}
    if size in by:
        return by[size]
    return by[256].resize((size, size), Image.LANCZOS)


def with_contents(groups, s, thumb):
    c = Image.new("RGBA", (s, s))
    c.alpha_composite(big(groups[5], s))
    tw, th = int(s * 0.62), int(s * 0.50)
    sh = Image.new("RGBA", (tw + 8, th + 8))
    ImageDraw.Draw(sh).rectangle([4, 4, tw + 4, th + 4], fill=(0, 0, 0, 90))
    c.alpha_composite(sh.filter(ImageFilter.GaussianBlur(3)), (int(s * .19) - 4, int(s * .22) - 3))
    c.alpha_composite(thumb(tw, th), (int(s * .19), int(s * .22)))
    c.alpha_composite(big(groups[6], s))
    return c


def sample_photo(w, h):
    im = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(im)
    for y in range(h):
        k = y / h
        d.line([(0, y), (w, y)], fill=(int(255 - 90 * k), int(170 - 60 * k), int(90 + 80 * k)))
    d.polygon([(0, h), (w * .35, h * .45), (w * .6, h * .75), (w * .8, h * .5), (w, h)], fill=(40, 50, 70))
    d.ellipse([w * .62, h * .12, w * .78, h * .32], fill=(255, 240, 200))
    return im.convert("RGBA")


def export(pristine, colors):
    font = lambda s: ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", s)
    os.makedirs(os.path.join(HERE, "docs"), exist_ok=True)
    sheet_rows = []
    for color in colors:
        g = recolored_groups(pristine, color)
        d = os.path.join(HERE, "icons", color)
        os.makedirs(d, exist_ok=True)
        sizes = [16, 32, 48, 128, 256, 512]
        for s in sizes:
            big(g[3], s).save(os.path.join(d, f"folder-{s}.png"))
            with_contents(g, s, sample_photo).save(os.path.join(d, f"folder-contents-sample-{s}.png"))
        big(g[3], 256).save(os.path.join(d, "folder.ico"),
                            sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (40, 40),
                                   (48, 48), (64, 64), (128, 128), (256, 256)])
        sheet_rows.append((color, g))
        print(f"exported {color}")

    if set(colors) != set(PALETTES):
        return  # the shared palette sheet only makes sense with every color
    W, RH = 760, 150
    sheet = Image.new("RGBA", (W, 20 + RH * len(sheet_rows)), (25, 25, 25, 255))
    dr = ImageDraw.Draw(sheet)
    for i, (color, g) in enumerate(sheet_rows):
        y = 20 + i * RH
        dr.text((20, y + 45), color, font=font(22), fill=(235, 235, 235))
        x = 150
        for s in (16, 32, 48):
            sheet.alpha_composite(big(g[3], s), (x, y + 96 - s)); x += s + 24
        sheet.alpha_composite(big(g[3], 112), (x, y)); x += 136
        sheet.alpha_composite(with_contents(g, 112, sample_photo), (x, y)); x += 136
        sheet.alpha_composite(big(g[162], 112), (x, y))
    sheet = sheet.convert("RGB")
    sheet.save(os.path.join(HERE, "docs", "all-colors.png"))
    # also at the root, so the project folder's own Explorer thumbnail shows the palettes
    sheet.save(os.path.join(HERE, "preview.png"))


def main(argv):
    if not argv or argv[0] == "list":
        print(" ".join(PALETTES))
        return
    cmd = argv[0]
    if cmd == "patch":
        color, pristine, out = argv[1:4]
        if color not in PALETTES:
            sys.exit(f"unknown color '{color}'. choose: {' '.join(PALETTES)}")
        patch(color, pristine, out)
    elif cmd == "export":
        pristine = os.path.join(HERE, "backup", "imageres.dll.mun.original")
        if not os.path.exists(pristine):
            pristine = r"C:\Windows\SystemResources\imageres.dll.mun"
        export(pristine, argv[1:] or list(PALETTES))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
