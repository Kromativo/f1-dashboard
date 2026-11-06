# F1 Dashboard 2026 (uso personal)

Tablero local con datos públicos de Jolpica-F1 y precios capturados a mano de la interfaz de F1 Fantasy.

## Cómo correrlo

```bash
cd "/Users/richarddm/Library/CloudStorage/GoogleDrive-richarddiazdigital@gmail.com/Mi unidad/Projects/Own/F1-Dashboard"
python3 fetch_data.py
```

Después abre `index.html` con doble clic. Necesitas internet para cargar Chart.js.

Cada vez que haya carrera nueva, vuelve a correr `fetch_data.py`.

## Precios (`prices/2026.csv`)

Una fila por ronda y por cada piloto o constructor, con el precio que muestra Fantasy esa semana.

| columna | ejemplo | notas |
|---|---|---|
| round | 17 | número de ronda |
| tipo | piloto / constructor | |
| codigo | ANT / mercedes | piloto: código de 3 letras. Constructor: `constructorId` de Jolpica |
| precio_musd | 27.1 | en millones de dólares |
| delta_musd | 0.1 | cambio respecto a la ronda anterior (negativo si bajó) |

Constructores: `mercedes`, `ferrari`, `red_bull`, `mclaren`, `alpine`, `aston_martin`, `williams`, `haas`, `rb`, `audi`, `cadillac`. Los IDs se confirman en `data/data.js` después de correr el script.

El presupuesto de tus equipos (cost cap) no va en este archivo: es tu liga, no el precio de los pilotos.

## Limitaciones

- Los "puntos" del tablero son puntos de campeonato de carrera y sprint, no puntos de Fantasy. Fantasy usa otras reglas (posiciones ganadas, clasificación, penalizaciones, chips).
- La carga de precios es manual. Si falta una ronda, la gráfica de precio se queda corta.

## Historial de predicciones

`registro.py` guarda las respuestas y los resultados reales en `data/historial.db` (SQLite) y exporta `data/historial.js`, que el tablero muestra en "Historial de predicciones". Para registrar un fin de semana nuevo, agrega su bloque en `RONDAS` y corre `python3 registro.py`.

## En la nube

- Código y datos: https://github.com/Kromativo/f1-dashboard (público).
- Sitio: Vercel, proyecto importado desde ese repositorio (sin build; es estático, `vercel.json` ya está).
- Actualización automática: `deploy/actualizar-datos.yml` debe estar en `.github/workflows/` del repositorio. Corre `fetch_data.py` y `registro.py` cada 6 horas y sube los cambios; Vercel redespliega solo.
- La contraseña de entrada es un filtro en el navegador, no seguridad real: los archivos de `data/` siguen siendo públicos.
- Lo manual sigue igual: `prices/2026.csv`, `upgrades/2026.csv` y las preguntas de `registro.py`.
