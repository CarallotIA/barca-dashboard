#!/usr/bin/env python3
"""Recopila notícies i vídeos de totes les fonts i ho desa a feeds.json (carpeta DATA_DIR o l'arrel del repo).

Per què existeix: els RSS de mitjans i de YouTube no es poden llegir directament des del
navegador (no tenen CORS) i els proxys gratuïts es bloquegen (error 429). Aquest script els
llegeix directament i el dashboard només ha de carregar feeds.js (funciona també obrint
l'HTML des del disc).

Ús:        python actualitza_feeds.py
Programar: cada 15 min amb el Programador de tasques de Windows (veure LLEGEIX.md).
Afegir una font: edita NEWS o YT aquí sota.
"""
import json, re, sys, time, urllib.parse, urllib.request, html
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import os
DATA = Path(os.environ.get("DATA_DIR") or Path(__file__).parent.parent)
OUT = DATA / "feeds.json"
UA = {"User-Agent": "Mozilla/5.0 (compatible; dashboard-barca/1.0)"}


def gn(q, lang="es"):
    tail = "&hl=ca&gl=ES&ceid=ES:ca" if lang == "ca" else "&hl=es&gl=ES&ceid=ES:es"
    return "https://news.google.com/rss/search?q=" + urllib.parse.quote(q) + tail


# name = etiqueta de la font; gn=True -> Google Notícies (la font real és al final del títol)
NEWS = [
    {"name": "Mundo Deportivo", "url": "https://www.mundodeportivo.com/rss/futbol/fc-barcelona.xml"},
    {"name": "SPORT", "url": gn("site:sport.es (Barça OR Flick OR Lamine OR Pedri OR Raphinha OR Gavi) -Euroliga -baloncesto -basket when:7d"), "gn": True, "max": 20},
    {"name": "Premsa catalana", "url": gn("FC Barcelona Flick OR Lamine OR Pedri when:2d", "ca"), "gn": True},
    {"name": "Altres mitjans", "url": gn("FC Barcelona (Flick OR Lamine OR Pedri) -site:sport.es -site:mundodeportivo.com when:2d"), "gn": True},
]
# filter=True -> només vídeos que parlin del Barça (canals generalistes)
YT = [
    {"key": "fcb", "id": "UC14UlmYlSNiQCBe9Eookf_A"},                 # FC Barcelona (oficial)
    {"key": "laliga", "id": "UCTv-XvfzLX3i4IGWAm4sbmA", "filter": True},  # LALIGA EA SPORTS
    {"key": "sport", "id": "UC-KNOeH9Cz2Ch3HMujlaTow", "filter": True},   # SPORT
    {"key": "md", "id": "UCWSZJ4r3s5xk8zICXEveFpg", "filter": True},      # Mundo Deportivo
    {"key": "gr", "id": "UC0Cbaofl1u2ZSCUjZ9yy-wg"},                     # Gerard Romero (Jijantes)
]
MAX_PER_FEED = 25
EXCLUDE = {"Barça Official Store"}
BARCA = re.compile(r"bar[cç]a|barcelona|culers?|lamine|yamal|pedri|raphinha|gavi|flick|f[eé]rm[ií]n|olmo|kound[eé]|cubars[ií]|balde|gordon|de jong|rodri\b|laporta|camp nou", re.I)
NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015", "media": "http://search.yahoo.com/mrss/"}


def get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30).read()


def txt(el, tag):
    x = el.find(tag)
    return (x.text or "").strip() if x is not None else ""


def plain(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def iso(d):
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def news():
    out = []
    for s in NEWS:
        try:
            root = ET.fromstring(get(s["url"]))
        except Exception as e:
            print(f"  ✗ {s['name']}: {e}")
            continue
        n = 0
        for it in root.iter("item"):
            title, link = plain(txt(it, "title")), txt(it, "link")
            try:
                date = iso(parsedate_to_datetime(txt(it, "pubDate")))
            except Exception:
                continue
            src, desc, img = s["name"], "", ""
            if s.get("gn"):
                k = title.rfind(" - ")
                if k > 10:
                    src, title = title[k + 3:].strip() or src, title[:k]
            else:
                desc = plain(txt(it, "description"))
                enc = it.find("enclosure")
                img = enc.get("url", "") if enc is not None else ""
            if src in EXCLUDE:
                continue
            if n >= s.get('max', MAX_PER_FEED):
                break
            if title and link:
                out.append({"srcName": src, "title": title, "desc": desc, "img": img, "url": link, "date": date})
                n += 1
        print(f"  ✓ {s['name']}: {n}")
    return out


def videos():
    out = []
    for c in YT:
        try:
            root = ET.fromstring(get("https://www.youtube.com/feeds/videos.xml?channel_id=" + c["id"]))
        except Exception as e:
            print(f"  ✗ {c['key']}: {e}")
            continue
        n = 0
        for e in root.findall("a:entry", NS):
            vid = e.findtext("yt:videoId", namespaces=NS)
            title = (e.findtext("a:title", namespaces=NS) or "").strip()
            pub = e.findtext("a:published", namespaces=NS) or ""
            link = e.find("a:link", NS)
            href = link.get("href", "") if link is not None else ""
            if not vid or (c.get("filter") and not BARCA.search(title)):
                continue
            out.append({"id": vid, "title": title, "date": iso(datetime.fromisoformat(pub)), "src": c["key"],
                        "short": "/shorts/" in href,
                        "live": bool(re.search(r"^\s*🔴|\bLIVE\b|DIRECTE|EN DIRECTO", title, re.I))})
            n += 1
        print(f"  ✓ {c['key']}: {n}")
    return out


def main():
    print("Notícies:")
    n = news()
    print("Vídeos:")
    v = videos()
    if not n and not v:
        sys.exit("Cap font ha respost; no es modifica feeds.js.")
    print("Baixes (detecció automàtica):")
    try:
        import baixes
        bx = baixes.update(n)
    except Exception as ex:
        print("  (baixes no disponibles:", ex, ")")
        bx = None
    data = {"generated": iso(datetime.now(timezone.utc)), "news": n, "videos": v, "baixes": bx}
    OUT.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"OK: {len(n)} notícies i {len(v)} vídeos a {OUT.name}")


if __name__ == "__main__":
    main()
