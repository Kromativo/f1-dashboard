#!/usr/bin/env python3
"""Descarga datos públicos de F1 (Jolpica-F1) y genera data/data.js para el tablero.

Uso: python3 fetch_data.py
Solo usa la biblioteca estándar de Python.
"""
import csv
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

SEASON = 2026
API = "https://api.jolpi.ca/ergast/f1"
OPENF1 = "https://api.openf1.org/v1"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "data.js"
PRICES = ROOT / "prices" / f"{SEASON}.csv"
PRACTICE_CACHE = ROOT / "data" / "practice_cache.json"
UPGRADES = ROOT / "upgrades" / f"{SEASON}.csv"
PAUSE_S = 0.4  # la API es pública y compartida: una pausa corta entre llamadas
OPENF1_PAUSE_S = 2.2  # el plan gratuito de OpenF1 permite unas 30 llamadas por minuto


def get(path):
    """Devuelve el bloque MRData, o None si el endpoint no existe."""
    url = f"{API}/{path}.json?limit=100"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = json.load(resp)["MRData"]
    except urllib.error.HTTPError as err:
        if err.code == 404:
            return None
        raise
    time.sleep(PAUSE_S)
    return data


class OpenF1Unavailable(RuntimeError):
    """OpenF1 bloquea el acceso mientras hay una sesión en vivo."""


def get_openf1(endpoint, params):
    """Llama a OpenF1 y reintenta si nos limita por exceso de llamadas."""
    url = f"{OPENF1}/{endpoint}?{urllib.parse.urlencode(params)}"
    for _ in range(3):
        try:
            with urllib.request.urlopen(url, timeout=60) as resp:
                data = json.load(resp)
            if isinstance(data, dict) and "detail" in data:
                raise OpenF1Unavailable(data["detail"])
            time.sleep(OPENF1_PAUSE_S)
            return data
        except urllib.error.HTTPError as err:
            if err.code == 404:
                return []  # OpenF1 responde 404 cuando la sesión aún no tiene datos
            if err.code in (401, 403):
                raise OpenF1Unavailable(f"HTTP {err.code}")
            if err.code != 429:
                raise
            time.sleep(20)
    raise RuntimeError(f"OpenF1 sigue limitando las llamadas: {url}")


def load_practice_cache():
    if PRACTICE_CACHE.exists():
        return json.loads(PRACTICE_CACHE.read_text(encoding="utf-8"))
    return {}


def save_practice_cache(cache):
    PRACTICE_CACHE.parent.mkdir(exist_ok=True)
    PRACTICE_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")


def practice_sessions_for(race, sessions):
    """Sesiones de práctica del fin de semana: de tres días antes de la carrera al día de carrera."""
    race_day = date.fromisoformat(race["date"])
    found = []
    for s in sessions:
        if not (s["session_name"].startswith("Practice") or s["session_name"] == "Sprint Qualifying"):
            continue
        day = date.fromisoformat(s["date_start"][:10])
        if race_day - timedelta(days=3) <= day <= race_day:
            found.append(s)
    return sorted(found, key=lambda s: s["date_start"])


def load_practice_session(s, cache):
    """Ranking de una práctica por mejor vuelta. Solo cachea sesiones terminadas."""
    key = str(s["session_key"])
    if key in cache:
        return cache[key]

    laps = get_openf1("laps", {"session_key": key})
    drivers = get_openf1("drivers", {"session_key": key})
    info = {d["driver_number"]: (d["name_acronym"], d["team_name"]) for d in drivers}

    # Descarta vueltas incompletas o con tiempos imposibles (por ejemplo, 40 s en una pista de 90 s).
    durations = sorted(lap["lap_duration"] for lap in laps if lap.get("lap_duration"))
    median = durations[len(durations) // 2] if durations else 0

    best = {}
    for lap in laps:
        t = lap.get("lap_duration")
        n = lap["driver_number"]
        if t is None or not (0.8 * median <= t <= 1.5 * median):
            continue
        if n not in best or t < best[n]:
            best[n] = t

    ranked = sorted(best.items(), key=lambda kv: kv[1])
    result = {
        "name": s["session_name"],
        "date": s["date_start"],
        "entries": [
            {
                "code": info.get(n, (str(n), ""))[0],
                "team": info.get(n, ("", ""))[1],
                "best": round(t, 3),
                "pos": pos,
            }
            for pos, (n, t) in enumerate(ranked, start=1)
        ],
    }

    if date.fromisoformat(s["date_start"][:10]) < date.today():
        cache[key] = result
        save_practice_cache(cache)
    return result


def practice_stats(rounds, practice):
    """Cuántas veces el piloto conservó su posición de la última práctica en la clasificación."""
    per = {}
    entered = {"rondas": 0, "con_entrada": 0}
    for r in rounds:
        sessions = [s for s in practice.get(str(r["round"]), []) if s["name"].startswith("Practice") and s["entries"]]
        if not sessions:
            continue
        last = sessions[-1]
        fp = {e["code"]: e["pos"] for e in last["entries"]}
        quali = {e["code"]: e["quali"] for e in r["entries"] if e["quali"]}

        for code, p in fp.items():
            q = quali.get(code)
            if q is None:
                continue
            s = per.setdefault(code, {"n": 0, "exacta": 0, "mas_menos_1": 0})
            s["n"] += 1
            s["exacta"] += int(q == p)
            s["mas_menos_1"] += int(abs(q - p) <= 1)

        top5_practice = {c for c, p in fp.items() if p <= 5}
        top5_quali = [c for c, q in quali.items() if q <= 5]
        entered["rondas"] += 1
        entered["con_entrada"] += int(any(c not in top5_practice for c in top5_quali))
    return {"pilotos": per, "entrada_top5": entered}


def load_quali_preview(race, sessions):
    """Clasificación de un fin de semana sin carrera todavía. Jolpica la publica con retraso; OpenF1 la tiene al terminar."""
    race_day = date.fromisoformat(race["date"])
    s = next((x for x in sessions if x["session_name"] == "Qualifying" and 0 <= (race_day - date.fromisoformat(x["date_start"][:10])).days <= 3), None)
    if s is None:
        return None
    key = str(s["session_key"])
    results = get_openf1("session_result", {"session_key": key})
    if not results:
        return None
    info = {d["driver_number"]: (d["name_acronym"], d["team_name"]) for d in get_openf1("drivers", {"session_key": key})}
    entries = []
    for r in sorted(results, key=lambda r: r.get("position") or 99):
        times = r.get("duration") or []
        done = [t for t in times if t]
        code, team = info.get(r["driver_number"], (str(r["driver_number"]), ""))
        entries.append({
            "code": code,
            "team": team,
            "pos": r["position"],
            "best": round(done[-1], 3) if done else None,
            # Última fase en la que marcó tiempo: Q1, Q2 o Q3.
            "reached": f"Q{len(times) if times and times[-1] else max(1, len(done))}",
        })
    return {"name": "Qualifying", "date": s["date_start"], "entries": entries}


def parse_lap(text):
    """Convierte un tiempo tipo "1:31.123" a segundos."""
    if not text:
        return None
    minutes, seconds = text.split(":")
    return round(int(minutes) * 60 + float(seconds), 3)


def best_quali_time(q):
    """Mejor tiempo de clasificación del piloto: Q3, si no Q2, si no Q1."""
    for key in ("Q3", "Q2", "Q1"):
        if q.get(key):
            return parse_lap(q[key])
    return None


def first_race(data):
    races = data["RaceTable"]["Races"] if data else []
    return races[0] if races else None


def load_schedule():
    races = get(str(SEASON))["RaceTable"]["Races"]
    return [
        {
            "round": int(r["round"]),
            "name": r["raceName"],
            "circuit": r["Circuit"]["circuitName"],
            "country": r["Circuit"]["Location"]["country"],
            "date": r["date"],
            "sprint": "Sprint" in r,
        }
        for r in races
    ]


def load_round(race):
    rnd = race["round"]
    result_race = first_race(get(f"{SEASON}/{rnd}/results"))
    if not result_race:
        return None  # ronda todavía sin disputar

    quali_race = first_race(get(f"{SEASON}/{rnd}/qualifying"))
    quali_pos, quali_lap = {}, {}
    if quali_race:
        for q in quali_race["QualifyingResults"]:
            quali_pos[q["Driver"]["driverId"]] = int(q["position"])
            quali_lap[q["Driver"]["driverId"]] = best_quali_time(q)

    sprint_info = {}  # driverId -> (posición, puntos, vuelta más rápida en segundos)
    if race["sprint"]:
        sprint_race = first_race(get(f"{SEASON}/{rnd}/sprint"))
        if sprint_race:
            sprint_info = {
                s["Driver"]["driverId"]: (
                    int(s["position"]),
                    float(s["points"]),
                    parse_lap(s.get("FastestLap", {}).get("Time", {}).get("time")),
                )
                for s in sprint_race["SprintResults"]
            }

    entries = []
    for res in result_race["Results"]:
        drv = res["Driver"]
        grid = int(res["grid"])
        finish = int(res["position"])
        entries.append({
            "code": drv.get("code", drv["driverId"].upper()),
            "driverId": drv["driverId"],
            "team": res["Constructor"]["name"],
            "teamId": res["Constructor"]["constructorId"],
            "quali": quali_pos.get(drv["driverId"]),
            "grid": grid,
            "finish": finish,
            # Ganadas = salida - llegada. Salida 0 significa salida desde pit lane: no se calcula.
            "gained": grid - finish if grid > 0 else None,
            "points": float(res["points"]),
            "sprint_pos": sprint_info.get(drv["driverId"], (None, 0.0, None))[0],
            "points_sprint": sprint_info.get(drv["driverId"], (None, 0.0, None))[1],
            "sprint_lap": sprint_info.get(drv["driverId"], (None, 0.0, None))[2],
            "quali_lap": quali_lap.get(drv["driverId"]),
            "race_lap": parse_lap(res.get("FastestLap", {}).get("Time", {}).get("time")),
            "status": res["status"],
        })

    return {
        "round": rnd,
        "name": race["name"],
        "date": race["date"],
        "sprint": race["sprint"],
        "entries": entries,
    }


def load_driver_standings():
    data = get(f"{SEASON}/driverStandings")
    lists = data["StandingsTable"]["StandingsLists"]
    rows = lists[0]["DriverStandings"] if lists else []
    return [
        {
            "position": int(s["position"]),
            "code": s["Driver"].get("code", s["Driver"]["driverId"].upper()),
            "name": f'{s["Driver"]["givenName"]} {s["Driver"]["familyName"]}',
            "team": s["Constructors"][0]["name"],
            "points": float(s["points"]),
            "wins": int(s["wins"]),
        }
        for s in rows
    ]


def load_constructor_standings():
    data = get(f"{SEASON}/constructorStandings")
    lists = data["StandingsTable"]["StandingsLists"]
    rows = lists[0]["ConstructorStandings"] if lists else []
    return [
        {
            "position": int(c["position"]),
            "id": c["Constructor"]["constructorId"],
            "name": c["Constructor"]["name"],
            "points": float(c["points"]),
            "wins": int(c["wins"]),
        }
        for c in rows
    ]


def load_prices():
    if not PRICES.exists():
        return []
    with PRICES.open(encoding="utf-8", newline="") as f:
        return [
            {
                "round": int(r["round"]),
                "tipo": r["tipo"].strip().lower(),
                "codigo": r["codigo"].strip(),
                "precio": float(r["precio_musd"]),
                "delta": float(r["delta_musd"] or 0),
            }
            for r in csv.DictReader(f)
            if r["round"].strip()
        ]


TRACK_CACHE = ROOT / "data" / "track_cache.json"


def count_braking(brake):
    """Aproximación de curvas: cada inicio de frenada en la vuelta."""
    return sum(1 for i in range(1, len(brake)) if brake[i] and not brake[i - 1])


def count_full_throttle(throttle, min_samples=8):
    """Aproximación de zonas de aceleración: tramos de acelerador a fondo de unos 2 s o más."""
    runs, cur = 0, 0
    for t in throttle:
        if t >= 98:
            cur += 1
            continue
        runs += cur >= min_samples
        cur = 0
    return runs + (cur >= min_samples)


def count_flags(rc):
    """Banderas amarillas: una por vuelta y tipo, para no contar cada sector por separado."""
    return len({(m.get("lap_number"), m["flag"]) for m in rc if m.get("flag") in ("YELLOW", "DOUBLE YELLOW")})


def count_incidents(rc):
    return len({m["message"] for m in rc if "INCIDENT" in m.get("message", "") and not m["message"].startswith("FIA STEWARDS")})


def count_safety(rc):
    return sum(1 for m in rc if m.get("category") == "SafetyCar" and "DEPLOYED" in m.get("message", ""))


def lap_trace(session_key, driver_code):
    """Trazado y datos de conducción de la vuelta más rápida de un piloto en una sesión."""
    skey = str(session_key)
    number = next((d["driver_number"] for d in get_openf1("drivers", {"session_key": skey}) if d["name_acronym"] == driver_code), None)
    laps = [l for l in get_openf1("laps", {"session_key": skey, "driver_number": number}) if l.get("lap_duration")] if number else []
    if not laps:
        return None

    # Usa la vuelta más rápida que tenga posiciones registradas.
    loc, window = [], None
    for lap in sorted(laps, key=lambda l: l["lap_duration"])[:3]:
        start = datetime.fromisoformat(lap["date_start"])
        window = {
            "session_key": skey,
            "driver_number": number,
            "date>": start.isoformat(),
            "date<": (start + timedelta(seconds=lap["lap_duration"])).isoformat(),
        }
        loc = get_openf1("location", window)
        if loc:
            break
    cars = sorted(get_openf1("car_data", window), key=lambda c: c["date"])

    points = [(p["x"], p["y"]) for p in loc if p["x"] or p["y"]]
    step = max(1, len(points) // 250)
    return {
        "path": [list(p) for p in points[::step]],
        "corners": count_braking([c["brake"] for c in cars]),
        "accel": count_full_throttle([c["throttle"] for c in cars]),
    }


def load_track(race, sessions, winner_code):
    """Trazado de la pista y datos de la carrera. Se cachea al terminar la carrera."""
    cache = json.loads(TRACK_CACHE.read_text(encoding="utf-8")) if TRACK_CACHE.exists() else {}
    key = str(race["round"])
    if key in cache:
        return cache[key]

    race_day = date.fromisoformat(race["date"])
    s = next((x for x in sessions if x["session_name"] == "Race" and date.fromisoformat(x["date_start"][:10]) == race_day), None)
    if s is None:
        return None
    track = lap_trace(s["session_key"], winner_code)
    if track is None:
        return None

    rc = get_openf1("race_control", {"session_key": str(s["session_key"])})
    track.update({
        "yellow": count_flags(rc) if rc else None,
        "incidents": count_incidents(rc) if rc else None,
        "safety_cars": count_safety(rc) if rc else None,
    })

    if race_day < date.today():
        cache[key] = track
        TRACK_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    return track


def load_upgrades():
    """Mejoras que trajo cada escudería en cada ronda. Se llena a mano desde upgrades/2026.csv."""
    if not UPGRADES.exists():
        return []
    with UPGRADES.open(encoding="utf-8", newline="") as f:
        return [
            {
                "round": int(r["round"]),
                "equipo": r["equipo"].strip(),
                "mejoras": int(r["mejoras"]) if r.get("mejoras", "").strip() else None,
                "fallas": int(r["fallas"]) if r.get("fallas", "").strip() else None,
                "choques": int(r["choques"]) if r.get("choques", "").strip() else None,
            }
            for r in csv.DictReader(f)
            if r["round"].strip()
        ]


def main():
    today = date.today()
    schedule = load_schedule()

    all_sessions = get_openf1("sessions", {"year": SEASON})
    rounds = []
    for race in schedule:
        if race["date"] > today.isoformat():
            continue
        rnd = load_round(race)
        if rnd:
            winner = next(e["code"] for e in rnd["entries"] if e["finish"] == 1)
            rnd["track"] = load_track(race, all_sessions, winner)
            rounds.append(rnd)
        print(f"Ronda {race['round']:>2} {race['name']}: {'ok' if rnd else 'sin resultados'}")

    practice = {}
    cache = load_practice_cache()
    sessions = None
    for race in schedule:
        if date.fromisoformat(race["date"]) - timedelta(days=3) > today:
            continue  # el fin de semana todavía no empieza
        if sessions is None:
            sessions = get_openf1("sessions", {"year": SEASON})
        found = practice_sessions_for(race, sessions)
        practice[str(race["round"])] = [load_practice_session(s, cache) for s in found]
        print(f"Prácticas ronda {race['round']:>2}: {len(found)} sesiones")

    # Carreras sin resultados: trazado desde la práctica más rápida del último fin de semana disponible.
    track_preview = {}
    for race in schedule:
        if race["date"] <= today.isoformat():
            continue
        done = [s for s in practice.get(str(race["round"]), []) if s["entries"]]
        if not done:
            continue
        last = done[-1]
        skey = next((x["session_key"] for x in all_sessions if x["date_start"] == last["date"]), None)
        if skey is not None:
            track_preview[str(race["round"])] = lap_trace(skey, last["entries"][0]["code"])

    quali_preview = {}
    done_rounds = {r["round"] for r in rounds}
    for race in schedule:
        if race["round"] in done_rounds or date.fromisoformat(race["date"]) - timedelta(days=3) > today:
            continue
        q = load_quali_preview(race, all_sessions)
        if q:
            quali_preview[str(race["round"])] = q
            print(f"Clasificación ronda {race['round']:>2}: {len(q['entries'])} pilotos (OpenF1)")

    payload = {
        "season": SEASON,
        "generated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "schedule": schedule,
        "rounds": rounds,
        "standings": {
            "drivers": load_driver_standings(),
            "constructors": load_constructor_standings(),
        },
        "prices": load_prices(),
        "practice": practice,
        "upgrades": load_upgrades(),
        "track_preview": track_preview,
        "quali_preview": quali_preview,
        "practice_stats": practice_stats(rounds, practice),
    }

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(
        "window.F1_DATA = " + json.dumps(payload, ensure_ascii=False, indent=1) + ";\n",
        encoding="utf-8",
    )
    print(f"Listo: {len(rounds)} rondas con resultados -> {OUT}")


if __name__ == "__main__":
    try:
        main()
    except OpenF1Unavailable as err:
        # No se escribe data/data.js: se conservan los datos anteriores.
        print(f"OpenF1 no está disponible ahora: {err}")
        print("No se modificó data/data.js. Vuelve a correr fetch_data.py cuando termine la sesión en vivo.")
        sys.exit(1)
