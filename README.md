# Riesgo de apagones — Mazar

Simulador de Ecuanomía: mapa de riesgo del sistema hidroeléctrico según la cota y el caudal del embalse de Mazar, con escenarios de lluvia, demanda e importación desde Colombia.

## Estructura

| Archivo | Qué es |
|---|---|
| `index.html` | La app. Lee `data.json` al cargar. |
| `data.json` | Datos recientes, coeficientes del modelo, climatología y supuestos. Se genera solo. |
| `data/celec_mazar.csv` | Serie diaria de cota y caudal desde 2022 (CELEC SUR). |
| `data/apagones.csv` | Episodios de apagones usados como etiquetas. Edítalo para corregir fechas. |
| `scripts/actualizar.py` | Descarga los días faltantes de CELEC, reentrena el modelo y escribe `data.json`. |
| `.github/workflows/diario.yml` | Corre el script todos los días a las 08:00 de Ecuador. |
| `CNAME` | Dominio propio para GitHub Pages. |
| `embed_ghost.html` | Código para pegar en una tarjeta HTML de Ghost. |

## Puesta en marcha

1. Crea un repositorio público en GitHub y sube todos estos archivos.
2. **Settings → Actions → General → Workflow permissions:** elige *Read and write permissions*.
3. **Settings → Pages:** *Source: Deploy from a branch*, rama `main`, carpeta `/ (root)`.
4. En el DNS de ecuanomia.com crea un registro `CNAME`: `apagones` → `TU-USUARIO.github.io`.
5. En **Settings → Pages → Custom domain** escribe `apagones.ecuanomia.com` y, cuando se valide, activa *Enforce HTTPS*.
6. **Actions → Actualizar datos de Mazar → Run workflow** para la primera actualización.
7. En Ghost, crea una página con una tarjeta HTML y pega el contenido de `embed_ghost.html`.

## Uso local

```bash
pip install -r requirements.txt
python scripts/actualizar.py                 # descarga + reconstruye
python scripts/actualizar.py --sin-descarga  # solo reconstruye
python -m http.server                        # abre http://localhost:8000
```

## Notas

- Si CELEC todavía no publica el día completo, el script se detiene y lo reintenta al día siguiente.
- Los supuestos de los escenarios (10 MW por m³/s turbinado, demanda de 4.400 MW, 450 MW de importación) están en `index.html`, función `simulate`.
