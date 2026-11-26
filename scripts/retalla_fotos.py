#!/usr/bin/env python3
"""Retalla les fotos oficials (treu el fons) i les desa a fotos/<dorsal>.webp amb fons transparent.

Cal executar-lo DESPRÉS d'actualitza_fotos.py, amb Python que tingui rembg i pillow:
    python retalla_fotos.py
(la 1a vegada baixa un model d'IA d'uns 170 MB). Només processa les fotos noves o canviades.
"""
import io, json, re, sys, urllib.request, hashlib
from pathlib import Path
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps
from rembg import new_session, remove

HERE = Path(__file__).parent.parent
HTML = HERE / "index.html"
OUT = HERE / "fotos"
OUT.mkdir(exist_ok=True)
CACHE = OUT / "_origen.json"

m = re.search(r"const FCB=(\{.*?\});/\*FCB_END", HTML.read_text(encoding="utf-8"), re.S)
data = json.loads(m.group(1))
items = {n: p["img"] for n, p in data["players"].items()}
if data.get("coach", {}).get("img"):
    items["coach"] = data["coach"]["img"]
seen = json.loads(CACHE.read_text()) if CACHE.exists() else {}
sess = None
for n, url in items.items():
    dest = OUT / f"{n}.webp"
    if dest.exists() and seen.get(n) == url:
        continue
    raw = urllib.request.urlopen(urllib.request.Request(url + "?width=640&height=640", headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read()
    im = Image.open(io.BytesIO(raw)).convert("RGBA")
    a = im.getchannel("A")
    if a.getextrema()[0] < 20:          # ja té transparència real: es manté
        out = im
    else:
        sess = sess or new_session("u2net_human_seg")
        cut = remove(im, session=sess, alpha_matting=False)
        # omple els forats interiors (p. ex. el logo de la samarreta) i conserva els colors originals
        m = cut.getchannel("A").point(lambda v: 255 if v > 24 else 0)
        pad = ImageOps.expand(m, border=1, fill=0)
        ImageDraw.floodfill(pad, (0, 0), 128)
        solid = pad.crop((1, 1, pad.width - 1, pad.height - 1)).point(lambda v: 0 if v == 128 else 255)
        alpha = ImageChops.lighter(solid, cut.getchannel("A")) if False else ImageChops.lighter(solid.filter(ImageFilter.GaussianBlur(0.6)), cut.getchannel("A"))
        out = im.copy(); out.putalpha(alpha)
    bbox = out.getchannel("A").point(lambda v: 255 if v > 24 else 0).getbbox()
    if bbox:
        out = out.crop(bbox)
    out.thumbnail((420, 620))
    out.save(dest, 'WEBP', quality=82, method=4)
    seen[n] = url
    print("OK", n, out.size)
CACHE.write_text(json.dumps(seen))
print(f"{len(list(OUT.glob('*.webp')))} fotos a {OUT}")
