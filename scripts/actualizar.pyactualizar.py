"""
Actualiza los datos de Mazar desde CELEC, reentrena el modelo y escribe data.json
para la app de riesgo de apagones de Ecuanomía.

Uso:
    python scripts/actualizar.py              # descarga días faltantes + reconstruye data.json
    python scripts/actualizar.py --sin-descarga   # solo reconstruye data.json
"""
import argparse, json, os, time
from datetime import date, timedelta
import numpy as np, pandas as pd

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV = os.path.join(RAIZ, "data", "celec_mazar.csv")
EPIS = os.path.join(RAIZ, "data", "apagones.csv")
SALIDA = os.path.join(RAIZ, "data.json")

# ---------------------------------------------------------------- descarga
URL = "https://generacioncsr.celec.gob.ec:8443/ords/csr/sardomcsr/pointValues"
MRIDS = {"cota_mazar": 30031, "caudal_mazar": 30538, "caudal_coca_codo": 100037}


def descargar(hasta):
    import requests, urllib3
    urllib3.disable_warnings()
    s = requests.Session()

    def lecturas(mrid, dia):
        sig = dia + timedelta(days=1)
        params = {"mrid": mrid, "fechaInicio": f"{dia}T06:00:00.000Z",
                  "fechaFin": f"{sig}T05:00:00.000Z", "fecha": dia.strftime("%d/%m/%Y 01:00:00")}
        for intento in range(3):
            try:
                r = s.get(URL, params=params, verify=False, timeout=30)
                r.raise_for_status()
                return [i["valueedit"] for i in r.json().get("items", []) if i.get("valueedit") is not None]
            except Exception:
                time.sleep(3 * (intento + 1))
        return []

    df = pd.read_csv(CSV)
    d = date.fromisoformat(df["fecha"].max()) + timedelta(days=1)
    nuevas = []
    while d <= hasta:
        fila = {"fecha": str(d)}
        for col, mrid in MRIDS.items():
            v = lecturas(mrid, d)
            if col.startswith("cota"):
                fila[col] = round(v[0], 2) if v else None
            else:
                fila[col] = round(sum(v) / len(v), 2) if v else None
                fila[col + "_n"] = len(v)
            time.sleep(0.3)
        # solo se guarda un día completo; si CELEC aún no publica, se reintenta mañana
        if fila["cota_mazar"] is None or fila["caudal_mazar"] is None or fila["caudal_mazar_n"] < 20:
            print("Día incompleto, se detiene en", d)
            break
        nuevas.append(fila)
        print(fila)
        d += timedelta(days=1)
    if nuevas:
        pd.concat([df, pd.DataFrame(nuevas)]).to_csv(CSV, index=False)
    return len(nuevas)


# ---------------------------------------------------------------- modelo
def construir():
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import make_pipeline
    from sklearn.neighbors import NearestNeighbors

    r = pd.read_csv(CSV, parse_dates=["fecha"]).set_index("fecha").sort_index()
    r = r[~r.index.duplicated(keep="last")][["cota_mazar", "caudal_mazar"]].dropna()
    doy = lambda idx: np.minimum(idx.dayofyear, 365)

    # etiquetas: apagón ese día o en los 30 siguientes
    r["apagon"] = 0
    for _, e in pd.read_csv(EPIS).iterrows():
        r.loc[e.inicio:e.fin, "apagon"] = 1
    r["y"] = (r.apagon[::-1].rolling("30D", min_periods=1).max()[::-1] > 0).astype(int)
    r["q7"] = r.caudal_mazar.rolling(7, min_periods=1).mean()
    r["lq"] = np.log(r.q7)

    # climatología: mediana diaria y caudal esperado de los próximos 30 días
    q = r.caudal_mazar
    med = q.groupby(doy(q.index)).median().reindex(range(1, 366)).interpolate().bfill().ffill().values
    ext = np.concatenate([med, med])
    exp30 = np.array([ext[i + 1:i + 31].mean() for i in range(365)])
    r["lqe"] = np.log(exp30[doy(r.index) - 1])

    # percentiles por fecha (ventana de ±15 días) para los escenarios de lluvia
    dq = pd.DataFrame({"q": q.values, "d": doy(q.index)})
    clim = {}
    for p in [10, 50, 90]:
        arr = []
        for d in range(1, 366):
            w = ((dq.d - d + 182) % 365 - 182).abs() <= 15
            arr.append(round(float(np.percentile(dq.q[w], p)), 2))
        clim[str(p)] = arr

    # regresión logística: cota + ln(caudal 7d) + ln(caudal esperado 30d)
    F = ["cota_mazar", "lq", "lqe"]
    b = r.iloc[7:]
    m = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000)).fit(b[F], b.y)
    sc, lr = m[0], m[1]
    w = lr.coef_[0] / sc.scale_
    a = lr.intercept_[0] - (lr.coef_[0] * sc.mean_ / sc.scale_).sum()

    # dinámica de la cota: cm por día por cada m³/s de diferencia y turbinado reciente
    r["dc"] = r.cota_mazar.diff() * 100
    d = r[(r.cota_mazar.shift() < 2150)].dropna(subset=["dc"])
    d = d[d.caudal_mazar < 150]
    k = float(np.polyfit(d.caudal_mazar, d.dc, 1)[0])
    rec = d[d.index > d.index.max() - pd.Timedelta(days=30)]
    qout = float((rec.caudal_mazar - rec.dc / k).mean())

    # máscara de zonas con datos
    F2 = ["cota_mazar", "lq"]
    sc2 = StandardScaler().fit(b[F2])
    nn = NearestNeighbors(n_neighbors=5).fit(sc2.transform(b[F2]))
    NC = NQ = 230
    cs = np.linspace(2104, 2160, NC); lqs = np.linspace(np.log(5), np.log(400), NQ)
    C, L = np.meshgrid(cs, lqs, indexing="ij")
    G = pd.DataFrame({"cota_mazar": C.ravel(), "lq": L.ravel()})
    mask = nn.kneighbors(sc2.transform(G))[0].mean(1) <= 0.35

    hist = r.iloc[-70:]
    data = {
        "asof": str(r.index[-1].date()),
        "hist": [{"d": str(i.date()), "c": round(x.cota_mazar, 2), "q": round(x.caudal_mazar, 2), "q7": round(x.q7, 2)}
                 for i, x in hist.iterrows()],
        "model": {"a": float(a), "bc": float(w[0]), "bq": float(w[1]), "be": float(w[2])},
        "clim": clim, "exp30": [round(float(v), 2) for v in exp30],
        "k": round(k, 3), "qout": round(qout, 1),
        "grid": {"c0": 2104, "c1": 2160, "nc": NC, "lq0": float(np.log(5)), "lq1": float(np.log(400)), "nq": NQ,
                 "mask": "".join("1" if v else "0" for v in mask)},
        "ep": [{"c": round(x.cota_mazar, 2), "q7": round(x.q7, 2)} for _, x in r[r.apagon == 1].iterrows()],
    }
    with open(SALIDA, "w") as f:
        json.dump(data, f, separators=(",", ":"))
    p_hoy = 1 / (1 + np.exp(-(a + w @ b[F].iloc[-1].values)))
    print(f"data.json al {data['asof']}: cota {hist.cota_mazar.iloc[-1]:.2f}, "
          f"caudal 7d {hist.q7.iloc[-1]:.1f}, probabilidad {p_hoy:.0%}, turbinado {qout:.0f} m³/s")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sin-descarga", action="store_true")
    a = ap.parse_args()
    if not a.sin_descarga:
        n = descargar(date.today() - timedelta(days=1))
        print("Días nuevos:", n)
    construir()
