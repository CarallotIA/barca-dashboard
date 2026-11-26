#!/usr/bin/env python3
"""Actualitza les fotos oficials del dashboard a partir de fcbarcelona.com.

La web del club no permet llegir-la des del navegador (no té CORS), així que
aquest script llegeix la pàgina de la plantilla, associa cada foto al dorsal i
escriu el resultat dins de dashboard-barca.html (entre /*FCB_START*/ i /*FCB_END*/).

Ús:   python actualitza_fotos.py
Quan executar-lo: quan hi hagi altes/baixes a la plantilla o canviïn les fotos.
"""
import html, json, re, sys, urllib.request
from pathlib import Path

PAGE = "https://www.fcbarcelona.com/en/football/first-team/players"
ESPN = "https://site.api.espn.com/apis/site/v2/sports/soccer/esp.1/teams/83/roster"
FILE = Path(__file__).parent.parent / "index.html"
UA = {"User-Agent": "Mozilla/5.0"}


def get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30).read().decode("utf-8", "ignore")


def main():
    t = get(PAGE)
    players, coach = {}, None
    for blk in t.split('<a href="https://www.fcbarcelona.com/en/football/first-team/')[1:]:
        m = re.match(r'(players|staff)/(\d+)/([^"]+)"', blk)
        if not m:
            continue
        kind, pid, slug = m.groups()
        img = re.search(r'data-img-src="([^"]+)"', blk)
        if not img:
            continue
        num = re.search(r'team-person__number"[^>]*>(\d*)', blk)
        ln = re.search(r'last-name[^>]*>\s*([^<]*?)\s*</span>', blk)
        fn = re.search(r'first-name[^>]*>\s*([^<]*?)\s*</span>', blk)
        name = html.unescape(((fn.group(1) if fn else "") + " " + (ln.group(1) if ln else "")).strip())
        item = {"name": name, "img": img.group(1), "url": f"https://www.fcbarcelona.com/en/football/first-team/{kind}/{pid}/{slug}"}
        if kind == "staff":
            if "coach" in blk.lower()[:2500] and not coach:
                coach = item
        elif num and num.group(1):
            players[num.group(1)] = item
    if not players:
        sys.exit("No s'han trobat jugadors: potser ha canviat l'estructura de la web.")

    # Jugadors del filial que entrenen amb el primer equip: es busquen a la pàgina del Barça Atlètic i s'associen pel nom
    try:
        import unicodedata
        norm = lambda s: re.sub(r"[^a-z ]", "", unicodedata.normalize("NFD", s.lower()).encode("ascii", "ignore").decode())
        espn_all = json.loads(get(ESPN))["athletes"]
        at = get("https://www.fcbarcelona.com/en/football/barca-atletic/players")
        for blk in at.split('<li class="team-list__person-container">')[1:]:
            u = re.search(r'href="([^"]+/players/\d+/[^"]+)"', blk)
            img = re.search(r'data-img-src="([^"]+)"', blk)
            ln = re.search(r'last-name[^>]*>\s*([^<]*?)\s*</span>', blk)
            if not (u and img and ln):
                continue
            ct = set(norm(html.unescape(ln.group(1))).split())
            for a in espn_all:
                j = str(a.get("jersey") or "")
                if j and j not in players and ct and ct <= set(norm(a["displayName"]).split()):
                    players[j] = {"name": a["displayName"], "img": img.group(1), "url": u.group(1)}
    except Exception as ex:
        print("  (filial no disponible:", ex, ")")

    # Comprovació creuada amb ESPN (dorsal -> nom) per detectar dorsals que no quadren
    try:
        esp = {str(a.get("jersey")): a["displayName"] for a in json.loads(get(ESPN))["athletes"] if a.get("jersey")}
        for n, p in players.items():
            e = esp.get(n, "")
            if e and e.split()[-1].lower()[:4] not in p["name"].lower().replace("í", "i").replace("é", "e"):
                print(f"  ⚠ dorsal {n}: club='{p['name']}' ESPN='{e}'")
    except Exception as ex:  # no és crític
        print("  (no s'ha pogut comparar amb ESPN:", ex, ")")

    data = {"coach": coach, "players": players}
    src = FILE.read_text(encoding="utf-8")
    new = "/*FCB_START*/const FCB=" + json.dumps(data, ensure_ascii=False) + ";/*FCB_END*/"
    out, n = re.subn(r"/\*FCB_START\*/.*?/\*FCB_END\*/", lambda _: new, src, flags=re.S)
    if n != 1:
        sys.exit("No trobo els marcadors /*FCB_START*/ ... /*FCB_END*/ dins l'HTML.")
    FILE.write_text(out, encoding="utf-8")
    print(f"OK: {len(players)} jugadors i {'entrenador' if coach else 'sense entrenador'} actualitzats.")


if __name__ == "__main__":
    main()
