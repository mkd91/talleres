"""
Genera data/ovt/*.json: talleres de España sacados de Overture Maps (tema «places»).

Uso (necesita Python 3.9+ y duckdb):
    python -m pip install duckdb
    python tools/build_overture.py 2026-10-21.0

El número de versión está en https://docs.overturemaps.org/release/latest/
Overture publica una versión al mes; volver a ejecutar el script actualiza los datos.

Salida:
    data/ovt/index.json      {release, tile, cats, tiles: {"<i>_<j>": n}}
    data/ovt/<i>_<j>.json    [[id, nombre, lat, lon, teléfonos, dirección, web, categoría], ...]
donde i = floor(lat / TILE), j = floor(lon / TILE).

Licencia de los datos: Overture Maps Foundation, CDLA Permissive 2.0 (hay que citarla).
"""
import json
import math
import os
import shutil
import sys
import time

import duckdb

TILE = 0.25  # grados (~28 x 22 km en España)
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "ovt")

# taxonomy.primary de Overture -> etiqueta en español. Solo talleres y servicios de reparación
# (sin lavaderos, ITV, grúas, gestorías ni concesionarios).
CATS = {
    "automotive_repair": "Taller mecánico",
    "automotive_service": "Servicio del automóvil",
    "auto_body_shop": "Chapa y pintura",
    "motorcycle_repair": "Taller de motos",
    "tire_dealer_and_repair": "Neumáticos",
    "tire_shop": "Neumáticos",
    "auto_glass_service": "Lunas",
    "windshield_installation_and_repair": "Lunas",
    "truck_repair": "Camiones",
    "trailer_repair": "Remolques",
    "auto_electrical_repair": "Electricidad del automóvil",
    "brake_service_and_repair": "Frenos",
    "engine_repair_service": "Motor",
    "transmission_repair": "Cajas de cambio",
    "exhaust_and_muffler_repair": "Escapes",
    "oil_change_station": "Cambio de aceite",
    "wheel_and_rim_repair": "Llantas",
    "auto_restoration_service": "Restauración",
    "auto_upholstery": "Tapicería",
    "auto_customization": "Personalización",
    "motorsport_vehicle_repair": "Competición",
    "car_window_tinting": "Tintado de lunas",
    "car_stereo_installation": "Audio del coche",
}


def main(release):
    src = f"s3://overturemaps-us-west-2/release/{release}/theme=places/type=place/*"
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs; SET s3_region='us-west-2';")
    labels = sorted(set(CATS.values()))
    tax_list = ",".join("'" + t + "'" for t in CATS)
    t0 = time.time()
    rows = con.execute(f"""
        SELECT id,
               names."primary" AS name,
               taxonomy."primary" AS tax,
               (bbox.ymin + bbox.ymax) / 2 AS lat,
               (bbox.xmin + bbox.xmax) / 2 AS lon,
               phones,
               websites,
               addresses[1].freeform AS street,
               addresses[1].postcode AS postcode,
               addresses[1].locality AS locality
        FROM read_parquet('{src}', hive_partitioning=1)
        WHERE bbox.xmin BETWEEN -18.5 AND 4.6 AND bbox.ymin BETWEEN 27.5 AND 44.0
          AND addresses[1].country = 'ES'
          AND taxonomy."primary" IN ({tax_list})
          AND coalesce(operating_status, 'open') <> 'permanently_closed'
          AND names."primary" IS NOT NULL
    """).fetchall()
    print(f"{len(rows)} talleres ({time.time() - t0:.0f}s)")

    tiles = {}
    for (pid, name, tax, lat, lon, phones, websites, street, postcode, locality) in rows:
        tel = []
        for p in phones or []:
            p = (p or "").strip()
            if p and p not in tel:
                tel.append(p)
        city = " ".join(x for x in (postcode, locality) if x)
        addr = ", ".join(x for x in ((street or "").strip(), city) if x)
        web = (websites or [None])[0] or ""
        rec = [pid[:16], name.strip(), round(lat, 5), round(lon, 5), ";".join(tel), addr, web,
               labels.index(CATS[tax])]
        key = f"{math.floor(lat / TILE)}_{math.floor(lon / TILE)}"
        tiles.setdefault(key, []).append(rec)

    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT)
    total = 0
    for key, recs in tiles.items():
        recs.sort(key=lambda r: (r[2], r[3]))
        with open(os.path.join(OUT, key + ".json"), "w", encoding="utf-8") as f:
            json.dump(recs, f, ensure_ascii=False, separators=(",", ":"))
        total += os.path.getsize(os.path.join(OUT, key + ".json"))
    index = {"release": release, "tile": TILE, "cats": labels,
             "tiles": {k: len(v) for k, v in sorted(tiles.items())}}
    with open(os.path.join(OUT, "index.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{len(tiles)} ficheros, {total / 1e6:.1f} MB en {os.path.normpath(OUT)}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Uso: python tools/build_overture.py <versión, p. ej. 2026-10-21.0>")
    main(sys.argv[1])
