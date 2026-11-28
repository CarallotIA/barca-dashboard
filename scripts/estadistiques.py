#!/usr/bin/env python3
"""Estadístiques d'equip i de jugador del Barça per temporada i competició (font: FotMob) → stats.json.

FotMob publica per cada competició i temporada un rànquing complet de cada estadística (data.fotmob.com/stats/<lliga>/season/<temporada>/<estadística>.json).
Aquí es queda només el que és del Barça (valor + posició al rànquing). La puntuació «FotMob rating» NO es recull.
Les temporades passades no canvien: es reutilitzen de l'execució anterior. La temporada en curs es refà cada 5 h.

Ús: DATA_DIR=<carpeta> python scripts/estadistiques.py
"""
import gzip, json, os, re, sys, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

DATA = Path(os.environ.get("DATA_DIR") or Path(__file__).parent.parent)
OUT = DATA / "stats.json"
UA = {"User-Agent": "Mozilla/5.0", "Accept-Encoding": "gzip"}
TEAM = 8634
COMPS = {"87": ("liga", "LaLiga"), "42": ("ucl", "Champions"), "138": ("copa", "Copa del Rei"), "139": ("super", "Supercopa")}
N_SEASONS = 3          # temporada en curs + 2 anteriors
REFRESH_H = 5

PLAYER_STATS = ["mins_played"]   # només per saber qui ha jugat amb el Barça a cada competició-temporada
TEAM_STATS = ["goals_team_match", "goals_conceded_team_match", "possession_percentage_team", "clean_sheet_team", "expected_goals_team",
              "_xg_diff_team", "ontarget_scoring_att_team", "big_chance_team", "big_chance_missed_team", "accurate_pass_team",
              "accurate_long_balls_team", "accurate_cross_team", "penalty_won_team", "touches_in_opp_box_team", "corner_taken_team",
              "_set_piece_goals_team", "expected_goals_conceded_team", "interception_team", "total_tackle_team", "effective_clearance_team",
              "poss_won_att_3rd_team", "_set_piece_goals_conceded_team", "saves_team", "fk_foul_lost_team", "total_yel_card_team", "total_red_card_team"]


def get(url):
    for i in range(3):
        try:
            r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40)
            b = r.read()
            if b[:2] == b"\x1f\x8b":
                b = gzip.decompress(b)
            return b
        except Exception as ex:
            err = ex
    raise err


def jget(url):
    return json.loads(get(url))


def fetch_stat(league, sid, stat):
    try:
        j = jget(f"https://data.fotmob.com/stats/{league}/season/{sid}/{stat}.json")
        return stat, (j.get("TopLists") or [{}])[0].get("StatList") or []
    except Exception:
        return stat, None


def season_block(league, sid):
    """Equip (valor, subvalor, posició, n equips, partits) i identificadors dels jugadors que hi han jugat."""
    with ThreadPoolExecutor(8) as ex:
        pl = dict(ex.map(lambda s: fetch_stat(league, sid, s), PLAYER_STATS))
        tm = dict(ex.map(lambda s: fetch_stat(league, sid, s), TEAM_STATS))
    team = {}
    for k, lst in tm.items():
        if not lst:
            continue
        row = next((x for x in lst if x.get("TeamId") == TEAM), None)
        if row:
            team[k] = [row["StatValue"], row.get("SubStatValue"), row["Rank"], len(lst), row.get("MatchesPlayed")]
    ids = sorted({str(x["ParticiantId"]) for x in pl.get("mins_played") or [] if x.get("TeamId") == TEAM})
    if not team and not ids:
        return None
    return {"team": team, "ids": ids}


def fnum(x):
    try:
        return float(str(x).replace(",", "."))
    except Exception:
        return None


def pos_group(pd):
    """G / D / M / F a partir de la posició principal de FotMob."""
    try:
        ps = pd["positions"]
        main = next((p for p in ps if p.get("isMainPosition")), ps[0])["strPos"]["key"]
    except Exception:
        return None
    if "keeper" in main:
        return "G"
    if "back" in main or "centre" in main and "mid" not in main:
        return "D"
    if "midfield" in main:
        return "M"
    return "F"


def parse_player(j):
    """Seccions de playerStats → {mp, st, min, v:{id:[valor, per90]}}. La puntuació (rating) NO es recull."""
    o = {"v": {}}
    for it in (j.get("topStatCard") or {}).get("items") or []:
        k = it.get("localizedTitleId")
        if k == "matches_uppercase":
            o["mp"] = int(fnum(it.get("statValue")) or 0)
        elif k == "player_started_matches":
            o["st"] = int(fnum(it.get("statValue")) or 0)
        elif k == "minutes_played":
            o["min"] = int(fnum(it.get("statValue")) or 0)
    for sec in (j.get("statsSection") or {}).get("items") or []:
        for it in sec.get("items") or []:
            k = it.get("localizedTitleId")
            v = fnum(it.get("statValue"))
            if not k or v is None or "rating" in k:
                continue
            p90 = it.get("per90")
            o["v"][k] = [round(v, 2), round(p90, 2) if isinstance(p90, (int, float)) else None]
    cells = {}
    for pt in ((j.get("heatmap") or {}).get("coordinates")) or []:
        i = min(13, int(pt["y"] // 5)) * 21 + min(20, int(pt["x"] // 5))   # quadrícula 21×14 (cel·les de 5 m) sobre un camp de 105×68
        cells[i] = cells.get(i, 0) + 1
    if cells:
        o["hm"] = [x for i, c in sorted(cells.items()) for x in (i, c)]
    return o if o["v"] or o.get("mp") else None


def parse_meta(pd):
    """Trajectòria, trofeus, valor de mercat i traspassos d'un jugador (playerData)."""
    car = []
    for e in (((pd.get("careerHistory") or {}).get("careerItems") or {}).get("senior") or {}).get("teamEntries") or []:
        car.append([e.get("team"), e.get("teamId"), (e.get("startDate") or "")[:7], (e.get("endDate") or "")[:7] or None,
                    fnum(e.get("appearances")), fnum(e.get("goals")), fnum(e.get("assists"))])
    tro = []
    for tm in (pd.get("trophies") or {}).get("playerTrophies") or []:
        for tn in tm.get("tournaments") or []:
            tro.append([tm.get("teamName"), tn.get("leagueName"), tn.get("seasonsWon") or [], tn.get("seasonsRunnerUp") or []])
    mv = [[(x.get("date") or "")[:7], x.get("value")] for x in (pd.get("marketValues") or {}).get("values") or [] if x.get("value")]
    tr = [[x.get("fromClub"), x.get("toClub"), x.get("transferDate"), (x.get("fee") or {}).get("value"), bool(x.get("onLoan"))] for x in pd.get("transfers") or []]
    return {"car": car, "tro": tro, "mv": mv, "tr": tr}


def players_block(old_pl, blocks, seasons, squad):
    """Per cada jugador del Barça: estadístiques completes per temporada i competició (playerStats)."""
    ids = {}   # pid -> {season: {code}}
    for season, comps in blocks.items():
        for code, blk in comps.items():
            for pid, p in blk["players"].items():
                ids.setdefault(pid, {}).setdefault(season, set()).add(code)
    cur = seasons[0]
    out = {}

    def one(pid):
        o = old_pl.get(pid) or {"n": None, "pos": None, "s": {}}
        try:
            pd = jget(f"https://www.fotmob.com/api/data/playerData?id={pid}")
        except Exception:
            return pid, (o if o["s"] else None)
        o["n"] = pd.get("name") or o["n"]
        o.update(parse_meta(pd))
        o["pos"] = squad.get(pid) or pos_group(pd.get("positionDescription")) or o["pos"]
        tmap = {}
        for ss in pd.get("statSeasons") or []:
            for tr in ss.get("tournaments") or []:
                tmap[(ss["seasonName"], str(tr["tournamentId"]))] = tr["entryId"]
        for season, codes in ids[pid].items():
            for code in codes:
                have = o["s"].get(season, {}).get(code)
                if have and "hm" in have and season != cur and "force" not in sys.argv:
                    continue
                tid = next(k for k, v in COMPS.items() if v[0] == code)
                eid = tmap.get((season.replace("/", "/"), tid))
                if not eid:
                    continue
                try:
                    j = jget(f"https://www.fotmob.com/api/data/playerStats?playerId={pid}&seasonId={eid}")
                except Exception:
                    continue
                r = parse_player(j)
                if r:
                    o["s"].setdefault(season, {})[code] = r
        return pid, (o if o["s"] else None)

    with ThreadPoolExecutor(6) as ex:
        for pid, o in ex.map(one, list(ids)):
            if o:
                out[pid] = o
    return out


def espn_records():
    """Resultats (PJ, V, E, D, GF, GC) per temporada i competició (ESPN)."""
    names = {"Spanish LALIGA": "liga", "UEFA Champions League": "ucl", "Spanish Copa del Rey": "copa", "Spanish Supercopa": "super"}
    now = datetime.now(timezone.utc)
    cur = now.year if now.month >= 7 else now.year - 1
    rec = {}
    for s in range(cur - N_SEASONS + 1, cur + 1):
        try:
            d = jget(f"https://site.api.espn.com/apis/site/v2/sports/soccer/all/teams/83/schedule?season={s}")
        except Exception:
            continue
        lab = f"{s}/{s + 1}"
        for e in d.get("events", []):
            c = e["competitions"][0]
            code = names.get((e.get("league") or {}).get("name") or e.get("seasonType", {}).get("name"))
            if not code or not c["status"]["type"].get("completed"):
                continue
            me = next(x for x in c["competitors"] if x["team"]["id"] == "83")
            op = next(x for x in c["competitors"] if x["team"]["id"] != "83")
            sc = lambda x: int(float(x["score"]["displayValue"] if isinstance(x["score"], dict) else x["score"]))
            gf, gc = sc(me), sc(op)
            r = rec.setdefault(lab, {}).setdefault(code, {"pj": 0, "v": 0, "e": 0, "d": 0, "gf": 0, "gc": 0})
            r["pj"] += 1
            r["v" if gf > gc else "d" if gf < gc else "e"] += 1
            r["gf"] += gf
            r["gc"] += gc
    return rec


def main():
    old = {}
    if OUT.exists():
        try:
            old = json.loads(OUT.read_text(encoding="utf-8"))
        except Exception:
            old = {}
    if old.get("v") != 2:
        old = {}
    age_h = 1e9
    if old.get("generated"):
        age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(old["generated"].replace("Z", "+00:00"))).total_seconds() / 3600
    team = jget("https://www.fotmob.com/api/data/teams?id=8634&ccode3=ESP")
    ts = [x for x in team["stats"]["tournamentSeasons"] if x["parentLeagueId"] in COMPS]
    seasons = sorted({x["season"] for x in ts}, reverse=True)[:N_SEASONS]
    squad = {}
    for grp in team["squad"]["squad"]:
        for m in grp["members"]:
            g = {"keepers": "G", "defenders": "D", "midfielders": "M", "attackers": "F"}.get(grp["title"])
            if g:
                squad[str(m["id"])] = g
    data = {s: {c: {"team": tm, "ids": old.get("ids", {}).get(s, {}).get(c, [])} for c, tm in cs.items()} for s, cs in old.get("team", {}).items()}
    force = "force" in sys.argv
    for season in seasons:
        for x in ts:
            if x["season"] != season:
                continue
            code = COMPS[x["parentLeagueId"]][0]
            have = data.get(season, {}).get(code)
            current = season == seasons[0]
            if have and not (current and age_h >= REFRESH_H) and not force:
                continue
            print(f"  · {COMPS[x['parentLeagueId']][1]} {season}…", end=" ", flush=True)
            blk = season_block(x["parentLeagueId"], x["tournamentId"])
            print("sense dades" if not blk else f"{len(blk['ids'])} jugadors, {len(blk['team'])} estadístiques d'equip")
            if blk:
                data.setdefault(season, {})[code] = blk
    # només cal refer jugadors si hi ha dades noves (temporada en curs vella) o falta alguna cosa
    refresh = age_h >= REFRESH_H or force or not old.get("players")
    players = old.get("players", {})
    if refresh:
        print("  · jugadors (playerStats)…", end=" ", flush=True)
        blocks = {s: {c: {"players": {i: 1 for i in b["ids"]}} for c, b in cs.items()} for s, cs in data.items() if s in seasons}
        players = players_block(players, blocks, seasons, squad)
        print(f"{len(players)} jugadors")
    out = {"v": 2, "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if refresh else old.get("generated"), "seasons": seasons,
           "comps": [{"code": c, "name": n} for c, n in COMPS.values()],
           "team": {s: {c: b["team"] for c, b in cs.items()} for s, cs in data.items() if s in seasons},
           "ids": {s: {c: b["ids"] for c, b in cs.items()} for s, cs in data.items() if s in seasons},
           "players": players, "rec": espn_records()}
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"OK: {OUT.name} {OUT.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
