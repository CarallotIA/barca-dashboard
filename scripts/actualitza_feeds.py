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


FOTMOB = "https://www.fotmob.com/api/data/"
PS_FILE = DATA / "pstats.json"
PS_MAX_AGE = 6 * 3600  # les estadístiques de temporada canvien poc: es refresquen cada 6 h


def _json(url):
    return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30).read())


def _num(x):
    try:
        return float(str(x).replace(",", "."))
    except Exception:
        return None


def pstats():
    """Regats i % de passades de cada jugador (FotMob, temporada de LaLiga). Retorna {dorsal: {...}}."""
    old = {}
    if PS_FILE.exists():
        try:
            old = json.loads(PS_FILE.read_text(encoding="utf-8"))
        except Exception:
            old = {}
    if old.get("generated") and (datetime.now(timezone.utc) - datetime.fromisoformat(old["generated"].replace("Z", "+00:00"))).total_seconds() < PS_MAX_AGE:
        print("  (estadístiques de jugador recents: es reutilitzen)")
        return old.get("players", {})
    out = {}
    try:
        team = _json(FOTMOB + "teams?id=8634&ccode3=ESP")
        members = [m for g in team["squad"]["squad"] if g.get("title") != "coach" for m in g["members"]]
        for m in members:
            try:
                j = _json(FOTMOB + f"playerData?id={m['id']}")
                items = {}
                for sec in (j.get("firstSeasonStats") or {}).get("statsSection", {}).get("items", []):
                    for it in sec.get("items", []):
                        items[it["title"]] = it.get("statValue")
                d = {
                    "dr": _num(items.get("Dribbles")),
                    "drp": _num(items.get("Dribbles success rate")),
                    "pa": _num(items.get("Accurate passes")),
                    "pp": _num(items.get("Pass accuracy")),
                }
                if any(v is not None for v in d.values()):
                    out[str(m["shirtNumber"])] = {"name": m["name"], **d}
            except Exception as ex:
                print(f"  ✗ {m.get('name')}: {ex}")
        print(f"  ✓ {len(out)} jugadors")
    except Exception as ex:
        print("  ✗ FotMob:", ex)
        return old.get("players", {})
    if out:
        PS_FILE.write_text(json.dumps({"generated": iso(datetime.now(timezone.utc)), "players": out}, ensure_ascii=False), encoding="utf-8")
    return out or old.get("players", {})


ITUNES = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"
PODS_FILE = DATA / "pods.json"
PODS_MAX_AGE = 20 * 60
# Programes de ràdio/podcast sobre el Barça (RSS públics). only = text que ha de portar el títol de l'episodi.
PODS = [
    {"key": "sotana", "name": "La Sotana", "net": "Programa del Barça", "url": "https://anchor.fm/s/10e30d900/podcast/rss", "site": ""},
    {"key": "tercer", "name": "LaTdT · El tercer temps (post-partit)", "net": "Catalunya Ràdio", "url": "https://dinamics.3cat.cat/public/podcast/catradio/xml/3/4/podseccio6343.xml", "site": "https://www.ccma.cat/catradio/latdt/"},
    {"key": "queth", "name": "Què t'hi jugues! (programa complet)", "net": "Cadena SER", "url": "https://fapi-top.prisasd.com/api/v2/feed-rss/playser/que-t-hi-jugues/itunestfp", "site": "https://cadenaser.com/cat/programa/que-t-hi-jugues/", "only": "complet"},
    {"key": "tudiras", "keep": 14, "name": "Tu diràs", "net": "RAC1", "url": "https://api.audioteca.rac1.cat/rss/tu-diras/", "site": "https://www.rac1.cat/tu-diras/"},
    {"key": "reservat", "name": "Barça reservat", "net": "Catalunya Ràdio", "url": "https://dinamics.3cat.cat/public/podcast/catradio/xml/2/3/podprograma2032.xml", "site": "https://www.ccma.cat/catradio/barca-reservat/"},
    {"key": "mitjanit", "name": "El club de la mitjanit", "net": "Catalunya Ràdio", "url": "https://dinamics.3cat.cat/public/podcast/catradio/xml/8/1/podprograma1218.xml", "site": "https://www.ccma.cat/catradio/el-club-de-la-mitjanit/"},
    {"key": "elbar", "name": "El Bar", "net": "Cadena SER", "url": "https://fapi-top.prisasd.com/api/v2/feed-rss/playser/el-bar/itunestfp", "site": "https://cadenaser.com/programa/el-bar/"},
    {"key": "totcosta", "keep": 14, "name": "Tot costa", "net": "Catalunya Ràdio", "url": "https://dinamics.3cat.cat/public/podcast/catradio/xml/4/3/podprograma1734.xml", "site": "https://www.ccma.cat/catradio/tot-costa/"},
]


def _dur(s):
    s = (s or "").strip()
    try:
        if ":" in s:
            p = [int(x) for x in s.split(":")]
            sec = p[0] * 3600 + p[1] * 60 + p[2] if len(p) == 3 else p[0] * 60 + p[1]
        else:
            sec = int(float(s))
    except Exception:
        return ""
    h, m = divmod(sec // 60, 60)
    return (f"{h} h {m:02d} min" if h else f"{m} min") if sec else ""


SPOTIFY_SHOWS = [{"key": "spc", "name": "Sólo para culés", "net": "El Chiringuito · Spotify", "id": "0WDMdLQFO7wThN6JGpcMeI"}]


def spotify_show(s):
    """Últims episodis d'un programa que només és a Spotify: IDs de la pàgina pública i dades de l'embed oficial de cada episodi."""
    page = get(f"https://open.spotify.com/show/{s['id']}").decode("utf-8", "ignore")
    ids = list(dict.fromkeys(re.findall(r"spotify:episode:([A-Za-z0-9]{22})|/episode/([A-Za-z0-9]{22})", page)))
    ids = [a or b for a, b in ids][:6]
    eps, cover = [], ""
    for i in ids:
        try:
            h = get(f"https://open.spotify.com/embed/episode/{i}").decode("utf-8", "ignore")
            m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', h, re.S)
            ent = json.loads(m.group(1))["props"]["pageProps"]["state"]["data"]["entity"]
            if ent.get("relatedEntityUri") != f"spotify:show:{s['id']}":
                continue
            if not cover:
                cover = next((c["url"] for c in ent.get("relatedEntityCoverArt", []) if c.get("maxWidth") == 300), "")
            eps.append({"title": plain(ent["title"]), "date": ent["releaseDate"]["isoString"], "sec": int(ent.get("duration", 0) / 1000), "dur": _dur(str(int(ent.get("duration", 0) / 1000))),
                        "spot": i, "link": f"https://open.spotify.com/episode/{i}"})
        except Exception as ex:
            print(f"  ✗ episodi {i}: {ex}")
    eps.sort(key=lambda e: e["date"], reverse=True)
    return {"key": s["key"], "name": s["name"], "net": s["net"], "site": f"https://open.spotify.com/show/{s['id']}", "img": cover, "eps": eps[:4]} if eps else None


def _sec(s):
    s = (s or "").strip()
    try:
        if ":" in s:
            p = [int(x) for x in s.split(":")]
            return p[0] * 3600 + p[1] * 60 + p[2] if len(p) == 3 else p[0] * 60 + p[1]
        return int(float(s))
    except Exception:
        return 0


def pods():
    """Últims episodis de cada programa a partir del seu RSS públic."""
    if PODS_FILE.exists():
        try:
            old = json.loads(PODS_FILE.read_text(encoding="utf-8"))
            if (datetime.now(timezone.utc) - datetime.fromisoformat(old["generated"].replace("Z", "+00:00"))).total_seconds() < PODS_MAX_AGE:
                print("  (podcasts recents: es reutilitzen)")
                return old["pods"]
        except Exception:
            old = None
    else:
        old = None
    out = []
    for s in SPOTIFY_SHOWS:
        try:
            r = spotify_show(s)
            if r:
                out.append(r)
        except Exception as ex:
            print(f"  ✗ {s['name']}: {ex}")
            prev = next((x for x in (old or {}).get("pods", []) if x["key"] == s["key"]), None)
            if prev:
                out.append(prev)
    for p in PODS:
        try:
            ch = ET.fromstring(get(p["url"])).find("channel")
        except Exception as ex:
            print(f"  ✗ {p['name']}: {ex}")
            prev = next((x for x in (old or {}).get("pods", []) if x["key"] == p["key"]), None)
            if prev:
                out.append(prev)
            continue
        img = ch.find(ITUNES + "image")
        eps = []
        for it in ch.findall("item"):
            title = plain(it.findtext("title") or "")
            if p.get("only") and p["only"].lower() not in title.lower():
                continue
            enc = it.find("enclosure")
            if enc is None or not enc.get("url", "").startswith("https://"):
                continue
            try:
                date = iso(parsedate_to_datetime(it.findtext("pubDate")))
            except Exception:
                continue
            eps.append({"title": title, "date": date, "sec": _sec(it.findtext(ITUNES + "duration")), "dur": _dur(it.findtext(ITUNES + "duration")), "audio": enc.get("url"), "link": it.findtext("link") or p["site"]})
            if len(eps) >= p.get("keep", 4):
                break
        if eps:
            out.append({"key": p["key"], "name": p["name"], "net": p["net"], "rss": p["url"], "site": p["site"] or ch.findtext("link") or "",
                        "img": (img.get("href") if img is not None else "") or (ch.findtext("image/url") or ""), "eps": eps})
    if out:
        PODS_FILE.write_text(json.dumps({"generated": iso(datetime.now(timezone.utc)), "pods": out}, ensure_ascii=False), encoding="utf-8")
    print(f"  ✓ {len(out)} programes, {sum(len(x['eps']) for x in out)} episodis")
    return out or (old or {}).get("pods", [])


DV_URL = "https://dondeverlo.com/equipo/fc-barcelona/"
TV_FILE = DATA / "tv.json"
TV_MAX_AGE = 3 * 3600  # una sola consulta cada 3 h: la web ho permet (robots.txt) i les dades canvien poc
MESOS = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6, "jul": 7, "ago": 8, "sep": 9, "oct": 10, "nov": 11, "dic": 12}
CANAL = [  # (text del canal a dondeverlo, plataforma mostrada)
    ("dazn", "DAZN"), ("m+", "Movistar+"), ("movistar", "Movistar+"), ("orange", "Orange TV"), ("youtube", "YouTube"),
    ("rtve", "RTVE"), ("tve", "RTVE"), ("tv3", "TV3"), ("3cat", "3Cat"), ("prime", "Prime Video"), ("amazon", "Prime Video"),
]


def _plat(title):
    low = title.lower()
    if "solo para bares" in low:  # LaLiga TV Bar: només locals, no és per a l'afició
        return None
    for k, v in CANAL:
        if k in low:
            return v
    return title.strip()


def tv():
    """On veure els pròxims partits a Espanya (DóndeVerlo). Retorna {'AAAA-MM-DD HH:MM': [plataformes] | []}."""
    if TV_FILE.exists():
        try:
            old = json.loads(TV_FILE.read_text(encoding="utf-8"))
            if (datetime.now(timezone.utc) - datetime.fromisoformat(old["generated"].replace("Z", "+00:00"))).total_seconds() < TV_MAX_AGE:
                print("  (canals recents: es reutilitzen)")
                return old["tv"]
        except Exception:
            pass
    else:
        old = None
    try:
        raw = urllib.request.urlopen(urllib.request.Request(DV_URL, headers={"User-Agent": "dashboard-barca/1.0 (projecte personal; lectura puntual)"}), timeout=30).read().decode("utf-8", "ignore")
    except Exception as ex:
        print("  ✗ DóndeVerlo:", ex)
        return (old or {}).get("tv", {})
    out = {}
    def plats(chunk):
        res = []
        for ttl in re.findall(r'class="dv-ch[^"]*"[^>]*title="([^"]+)"', chunk):
            p = _plat(ttl)
            if p and p not in res:
                res.append(p)
        return res
    # partit destacat (el proper)
    m = re.search(r'data-start="(\d{4}-\d\d-\d\d)T(\d\d:\d\d)[^"]*".*?<div class="fc-providers">(.*?)</div>', raw, re.S)
    if m:
        out[f"{m.group(1)} {m.group(2)}"] = plats(m.group(3))
    # llista de pròxims partits: cada fila porta data, hora i (si es coneix) els canals
    for blk in raw.split('<div class="match-row"')[1:]:
        d = re.search(r'data-date="(\d{4}-\d\d-\d\d)"', blk)
        h = re.search(r'<span class="time">(\d\d:\d\d)</span>', blk)
        if not (d and h):
            continue
        pv = re.search(r'class="match-providers">(.*?)</div>', blk, re.S)
        out.setdefault(f"{d.group(1)} {h.group(1)}", plats(pv.group(1)) if pv else [])
    if out:
        TV_FILE.write_text(json.dumps({"generated": iso(datetime.now(timezone.utc)), "tv": out}, ensure_ascii=False), encoding="utf-8")
    print(f"  ✓ {len(out)} partits, {sum(1 for v in out.values() if v)} amb canal")
    return out or (old or {}).get("tv", {})


COMP = {"Spanish LALIGA": "LaLiga", "UEFA Champions League": "Champions", "Spanish Copa del Rey": "Copa del Rei", "Spanish Supercopa": "Supercopa"}
TROPHY = {"LaLiga": "LaLiga", "Copa del Rey": "Copa del Rei", "Supercopa de España": "Supercopa", "Trofeo Joan Gamper": "Trofeu Joan Gamper", "Champions League": "Champions"}
COACH_ID = 131509  # Hansi Flick a FotMob
COACH_SINCE = datetime(2024, 5, 29, tzinfo=timezone.utc)


def coach():
    """Estadístiques de l'entrenador amb el Barça per competició (ESPN) i trofeus (FotMob)."""
    comps, total = {}, {"pj": 0, "v": 0, "e": 0, "d": 0, "gf": 0, "gc": 0}
    seasons = [2024, 2025, datetime.now(timezone.utc).year if datetime.now(timezone.utc).month >= 7 else datetime.now(timezone.utc).year - 1]
    seen = set()
    for s in sorted(set(seasons)):
        try:
            d = _json(f"https://site.api.espn.com/apis/site/v2/sports/soccer/all/teams/83/schedule?season={s}")
        except Exception as ex:
            print(f"  ✗ temporada {s}: {ex}")
            continue
        for e in d.get("events", []):
            c = e["competitions"][0]
            name = COMP.get((e.get("league") or {}).get("name") or e.get("seasonType", {}).get("name"))
            if not name or not c["status"]["type"].get("completed") or e["id"] in seen:
                continue
            if datetime.fromisoformat(e["date"].replace("Z", "+00:00")) < COACH_SINCE:
                continue
            seen.add(e["id"])
            me = next(x for x in c["competitors"] if x["team"]["id"] == "83")
            op = next(x for x in c["competitors"] if x["team"]["id"] != "83")
            gf, gc = int(float(me["score"]["displayValue"] if isinstance(me["score"], dict) else me["score"])), int(float(op["score"]["displayValue"] if isinstance(op["score"], dict) else op["score"]))
            k = "v" if gf > gc else "d" if gf < gc else "e"
            for tgt in (comps.setdefault(name, {"pj": 0, "v": 0, "e": 0, "d": 0, "gf": 0, "gc": 0}), total):
                tgt["pj"] += 1
                tgt[k] += 1
                tgt["gf"] += gf
                tgt["gc"] += gc
    trophies = []
    try:
        j = _json(FOTMOB + f"playerData?id={COACH_ID}")
        for team in (j.get("trophies") or {}).get("coachTrophies", []):
            if team.get("teamId") != 8634:
                continue
            for tr in team["tournaments"]:
                if tr.get("seasonsWon"):
                    trophies.append({"name": TROPHY.get(tr["leagueName"], tr["leagueName"]), "won": sorted(tr["seasonsWon"])})
    except Exception as ex:
        print("  ✗ trofeus:", ex)
    print(f"  ✓ {total['pj']} partits oficials · {len(trophies)} tipus de trofeus")
    return {"name": "Hansi Flick", "since": COACH_SINCE.date().isoformat(), "total": total, "comps": comps, "trophies": trophies} if total["pj"] else None


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
    print("Podcasts:")
    try:
        pd = pods()
    except Exception as ex:
        print("  ✗", ex)
        pd = None
    print("On veure els partits (DóndeVerlo):")
    try:
        tvd = tv()
    except Exception as ex:
        print("  ✗", ex)
        tvd = None
    print("Entrenador:")
    try:
        co = coach()
    except Exception as ex:
        print("  ✗", ex)
        co = None
    print("Estadístiques de jugador (FotMob):")
    ps = pstats()
    data = {"generated": iso(datetime.now(timezone.utc)), "news": n, "videos": v, "baixes": bx, "pstats": ps, "coach": co, "tv": tvd, "pods": pd}
    OUT.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"OK: {len(n)} notícies i {len(v)} vídeos a {OUT.name}")


if __name__ == "__main__":
    main()
