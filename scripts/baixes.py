"""Detecta automàticament lesions, sancions i recuperacions dels jugadors a partir de les notícies.

No cal validar res: cada vegada que s'executa actualitza_feeds.py es llegeixen les notícies noves,
es classifica què diu cada frase de cada jugador (baixa / dubte / torna) i es manté un estat
a baixes_estat.json. L'estat caduca sol: quan el jugador torna a jugar (ESPN suma un partit),
quan passa el temps previst o quan una notícia més recent diu que ha tornat.
"""
import json, re, unicodedata, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import os
HERE = Path(os.environ.get("DATA_DIR") or Path(__file__).parent.parent)
STATE = HERE / "baixes_estat.json"
ESPN = "https://site.api.espn.com/apis/site/v2/sports/soccer/esp.1/teams/83/roster"
UA = {"User-Agent": "Mozilla/5.0"}
COMMON = {"lopez", "garcia", "martin", "rodriguez", "gonzalez", "hernandez", "alonso", "perez"}  # cognoms que confonen amb altra gent
NUM = {"un": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5}

RETURN = re.compile(r"vuelve|vuelta|regresa|reaparece|recupera|recuperad|recibe el alta|alta medica|convocad|disponible|listo para|supera la lesion|superada|ya esta bien|ya entrena|entrena con el grupo")
DOUBT = re.compile(r"duda|dudos|optimismo|pendiente de evolucion|molestias|podria volver|posibles? retornos?|en el aire|llega justo|se llega|evolucion")
OUT = re.compile(r"lesion|lesionad|baja\b|bajas\b|causa baja|esguince|rotura|fractura|sancion|sancionad|no jugara|se pierde|se perdera|descartad|operad|contractura|distension|tendinitis|cirugia|sindesmosis")
PAST = re.compile(r"fruto de|tras las lesiones|pese a las lesiones|ausencias de|con las bajas|debido a las lesiones")  # mencions de fons, no notícia


def norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", unicodedata.normalize("NFD", (s or "").lower()).encode("ascii", "ignore").decode())).strip()


def roster():
    d = json.loads(urllib.request.urlopen(urllib.request.Request(ESPN, headers=UA), timeout=30).read())
    out = []
    for a in d["athletes"]:
        if not a.get("jersey"):
            continue
        g = {s["name"]: s["value"] for c in a.get("statistics", {}).get("splits", {}).get("categories", []) for s in c["stats"]}
        out.append({"j": str(a["jersey"]), "name": a["displayName"], "apps": int(g.get("appearances", 0))})
    return out


def aliases(players):
    toks = {}
    for p in players:
        for t in norm(p["name"]).split():
            toks.setdefault(t, set()).add(p["j"])
    al = {}
    for p in players:
        a = {norm(p["name"])}
        for t in norm(p["name"]).split():
            if len(t) >= 4 and len(toks[t]) == 1 and t not in COMMON:
                a.add(t)
        al[p["j"]] = a
    return al


def classify(window):
    if PAST.search(window):
        return None
    if RETURN.search(window):
        return "return"
    if DOUBT.search(window):
        return "doubt"
    if OUT.search(window):
        return "out"
    return None


def detect(news, players):
    """Retorna {dorsal: (data, tipus, motiu, fins)} amb la notícia més recent de cada jugador."""
    al = aliases(players)
    flat = [(a, j) for j, s in al.items() for a in s]
    flat.sort(key=lambda x: -len(x[0]))
    found = {}
    for n in news:
        try:
            date = datetime.fromisoformat(n["date"].replace("Z", "+00:00"))
        except Exception:
            continue
        for part in (n["title"], n.get("desc", "")):
            text = norm(part)
            if not text:
                continue
            hits = []  # (inici, final, dorsal)
            for a, j in flat:
                for m in re.finditer(r"\b" + re.escape(a) + r"\b", text):
                    if not any(s <= m.start() < e for s, e, _ in hits):
                        hits.append((m.start(), m.end(), j))
            hits.sort()
            if not hits or PAST.search(text):
                continue
            # cada paraula clau s'assigna només al jugador més proper (màx. 55 caràcters)
            per = {}
            for kind, rx in (("return", RETURN), ("doubt", DOUBT), ("out", OUT)):
                for m in rx.finditer(text):
                    def dist(h):
                        return 0 if h[0] <= m.start() < h[1] else (m.start() - h[1] if m.start() >= h[1] else h[0] - m.end())
                    h = min(hits, key=dist)
                    if dist(h) <= 55:
                        per.setdefault(h[2], set()).add(kind)
            # llistes tipus «Rodri y Christensen»: el que val per a un val per als enllaçats amb «y/e»
            for _ in range(3):
                for x in range(len(hits) - 1):
                    gap = text[hits[x][1]:hits[x + 1][0]]
                    if re.fullmatch(r" (y|e) ", gap) or gap == " ":
                        l, r = hits[x][2], hits[x + 1][2]
                        if l in per and r not in per:
                            per[r] = set(per[l])
                        elif r in per and l not in per:
                            per[l] = set(per[r])
            for j, kinds in per.items():
                kind = "return" if "return" in kinds else "doubt" if "doubt" in kinds else "out"
                until = None
                if kind == "out" and "sancion" in text:
                    m = re.search(r"(\d+|un|dos|tres|cuatro|cinco) partidos?", text)
                    k = (int(m.group(1)) if m.group(1).isdigit() else NUM.get(m.group(1), 1)) if m else 1
                    until = (date + timedelta(days=7 * k + 1)).isoformat()
                cur = found.get(j)
                pri = {"out": 2, "doubt": 1, "return": 0}
                if not cur or date > cur[0] or (date == cur[0] and pri[kind] > pri[cur[1]]):
                    found[j] = (date, kind, n["title"][:110], until)
    return found


def update(news):
    """Combina les notícies noves amb l'estat desat i retorna {dorsal: motiu} de qui és baixa o dubtós."""
    now = datetime.now(timezone.utc)
    try:
        players = roster()
    except Exception as ex:
        print("  (baixes: sense roster d'ESPN:", ex, ")")
        return {}
    apps = {p["j"]: p["apps"] for p in players}
    names = {p["j"]: p["name"] for p in players}
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    for j, (date, kind, title, until) in detect(news, players).items():
        old = state.get(j)
        if old and datetime.fromisoformat(old["data"]) >= date:
            continue
        if kind == "return":
            state.pop(j, None)
        else:
            state[j] = {"data": date.isoformat(), "tipus": kind, "motiu": title, "apps": apps.get(j, 0), "fins": until}
    result = {}
    for j in list(state):
        s = state[j]
        age = now - datetime.fromisoformat(s["data"])
        limit = timedelta(days=5) if s["tipus"] == "doubt" else timedelta(days=60)
        if j not in apps or age > limit or (s.get("fins") and now > datetime.fromisoformat(s["fins"])) or apps[j] > s.get("apps", 0) and age > timedelta(hours=30):
            del state[j]
            continue
        result[j] = ("Dubtós" if s["tipus"] == "doubt" else "Baixa") + " · " + s["motiu"]
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    for j, m in result.items():
        print(f"  ⚕ {names.get(j, j)}: {m}")
    return result
