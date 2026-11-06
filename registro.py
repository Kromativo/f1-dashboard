"""Historial de predicciones (trazabilidad). Guarda en data/historial.db y exporta data/historial.js.

Uso:
  python3 registro.py            # solo vuelve a exportar historial.js desde la base
Para registrar una ronda nueva, agrega su lista en RONDAS y corre el script.
"""
import json, sqlite3, pathlib

BASE = pathlib.Path(__file__).parent / "data"
DB = BASE / "historial.db"

# Cada fila: (pregunta, tema, titulo, respuesta, resultado real, acierto 1/0/None, puntos o None, nota)
# acierto None = sin respuesta o sin verificar. Puntos None = la pregunta no muestra puntaje.
RONDAS = {
    18: {
        "gp": "Gran Premio de EE. UU.",
        "chip": None,
        "modelo": {"rho_quali": 0.94, "top3_quali": 2, "top10_quali": 9},
        "preguntas": [
            (1, "carrera", "Podio", "1º ANT, 2º VER, 3º LEC", "1º ANT, 2º LEC, 3º VER", 0.5, None,
             "Acierto parcial: ANT exacto; VER y LEC en el podio pero con posiciones cambiadas."),
            (2, "quali", "Pole", "LEC", "ANT", 0, None, "LEC salió 4º."),
            (3, "quali", "Leclerc vs Hamilton en quali", "LEC", "LEC (4º) por delante de HAM (5º)", 1, 10, ""),
            (4, "quali", "Máximo de Alpine en quali", "Q3", "Q2 (GAS 11º, COL 14º)", 0, 0, "Valía 15 pts con Q2."),
            (5, "carrera", "Vuelta rápida", "ANT", "LEC (1:37.976)", 0, None, "Tomado de la mejor vuelta de carrera en Jolpica."),
            (6, "carrera", "Parada en pits más rápida", "(sin respuesta)", "sin datos de paradas", None, None, "No se eligió equipo."),
            (7, "carrera", "Quién termina por delante", "LAW", "LAW 9º, GAS 10º, ALO 16º, SAI 18º", 1, 10, "LAW terminó por delante de los otros tres."),
            (8, "carrera", "Haas + Cadillac clasificados", "3", "2 (OCO, PER)", 0, 0, "BEA y BOT se retiraron; si BOT contó como clasificado el total sería 3."),
            (9, "carrera", "Dónde termina Norris", "4º-10º", "5º", 1, 10, ""),
            (10, "carrera", "Nuevo campeón este fin de semana", "NO", "NO (RUS 8º, ANT ganó pero no alcanzó)", 1, 10, ""),
        ],
    },
}

def main():
    con = sqlite3.connect(DB)
    con.executescript("""
    CREATE TABLE IF NOT EXISTS rondas(ronda INTEGER PRIMARY KEY, gp TEXT, chip INTEGER, rho_quali REAL, top3_quali INTEGER, top10_quali INTEGER);
    CREATE TABLE IF NOT EXISTS predicciones(ronda INTEGER, pregunta INTEGER, tema TEXT, titulo TEXT, respuesta TEXT,
        real TEXT, acierto REAL, puntos INTEGER, nota TEXT, PRIMARY KEY(ronda, pregunta));
    """)
    for r, d in RONDAS.items():
        m = d["modelo"]
        con.execute("INSERT OR REPLACE INTO rondas VALUES(?,?,?,?,?,?)", (r, d["gp"], d["chip"], m["rho_quali"], m["top3_quali"], m["top10_quali"]))
        for q in d["preguntas"]:
            con.execute("INSERT OR REPLACE INTO predicciones VALUES(?,?,?,?,?,?,?,?,?)", (r, *q))
    con.commit()
    con.row_factory = sqlite3.Row
    out = []
    for ro in con.execute("SELECT * FROM rondas ORDER BY ronda"):
        qs = [dict(x) for x in con.execute("SELECT * FROM predicciones WHERE ronda=? ORDER BY pregunta", (ro["ronda"],))]
        out.append({**dict(ro), "preguntas": qs})
    (BASE / "historial.js").write_text("const HISTORIAL = " + json.dumps(out, ensure_ascii=False, indent=1) + ";\n", encoding="utf-8")
    print(f"Historial: {len(out)} ronda(s) -> {DB.name}, historial.js")

if __name__ == "__main__":
    main()
