"""Pruebas de integración; cada caso crea y elimina su propio esquema PostgreSQL.

ETA_TEST_DB_URI='dbname=postgres ...' python -m unittest discover -s test_temp -p 'test_load_dataset.py'
"""

import csv
import json
import os
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import make_dsn

from load_dataset import importar_dataset_postgres


@unittest.skipUnless(os.environ.get("ETA_TEST_DB_URI"), "Requiere ETA_TEST_DB_URI")
class ImportacionNormalizadaTest(unittest.TestCase):
    def setUp(self):
        self.esquema = "eta_test_" + uuid4().hex
        self.admin = psycopg2.connect(os.environ["ETA_TEST_DB_URI"])
        self.admin.autocommit = True
        with self.admin.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.esquema)))
        self.dsn = make_dsn(
            os.environ["ETA_TEST_DB_URI"], options=f"-c search_path={self.esquema}"
        )
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def tearDown(self):
        with self.admin.cursor() as cur:
            cur.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.esquema)))
        self.admin.close()

    def importar(self, archivos, lote=2):
        return importar_dataset_postgres(
            archivos, self.dsn, lote=lote, log=lambda _: None,
            csv_salida=Path(self.tmp.name) / "salida.csv",
        )

    def consultar(self, sentencia):
        with psycopg2.connect(self.dsn) as con:
            with con.cursor() as cur:
                cur.execute(sentencia)
                return cur.fetchall()

    def test_datos_reducidos_y_reimportacion(self):
        origen = Path(__file__).parent / "data_redux"
        archivos = {
            "hojas": origen / "hojaDeRuta_reducido.json",
            "gps": origen / "rastreoSatelital_reducido.json",
            "observaciones": origen / "observacionesSegmentosViales_reducido.json",
        }
        resultado = self.importar(archivos)
        conteos = {f["tabla"]: f["filas"] for f in resultado["tablas"]}
        self.assertEqual(conteos["dataset_entrenamiento"], 2)
        self.assertEqual(conteos["observaciones_segmento"], 2)
        self.assertGreater(conteos["recorrido_segmentos"], 0)
        self.assertGreater(conteos["recorrido_paradas"], 0)
        self.assertEqual(conteos["paradas_importadas"], conteos["recorrido_paradas"])
        self.assertEqual(
            self.consultar("SELECT hora_referencia FROM recorrido_paradas ORDER BY idparada LIMIT 1"),
            [("05:25",)],
        )
        self.assertEqual(self.consultar("SELECT count(*) FROM segmentos_detalle"),
                         [(conteos["recorrido_segmentos"],)])
        with Path(resultado["csv"]).open(encoding="utf-8", newline="") as archivo:
            filas = list(csv.DictReader(archivo))
        self.assertEqual(len(filas), 2)
        self.assertEqual(len({f["idobservacion"] for f in filas}), 2)
        with self.assertRaisesRegex(ValueError, "esquema.*contiene"):
            self.importar(archivos)
        self.assertEqual(self.consultar("SELECT count(*) FROM dataset_entrenamiento"), [(2,)])

    def test_identidad_orden_ambiguedad_y_hora_local(self):
        def hoja(identificador, vehiculo, segmentos, paradas=None, geometria=True):
            doc = {
                "_id": identificador,
                "vehiculo": {"id": vehiculo, "tipoVehiculo": "Minibus", "cantidadPlazas": 19},
                "fechaDesde": {"$date": "2026-06-01T00:00:00Z"},
                "fechaHasta": {"$date": "2026-06-03T00:00:00Z"},
                "paradasIda": paradas or [],
            }
            if geometria:
                doc["geometriaOSRM"] = {"ida": {
                    "analitica_segmentos": [
                        {"origen": a, "destino": b, "tiempo_estimado": 10}
                        for a, b in segmentos
                    ],
                    "puntos": [[-38, -68], [-38.1, -68.1], [-38, -68], [-38.1, -68.1]],
                    "duracion_osrm_original": 30,
                }}
            return doc

        def observacion(vehiculo, origen, destino, tiempo=12):
            return {
                "flotaID": vehiculo, "nodo_origen": origen, "nodo_destino": destino,
                "fecha": {"$date": "2026-06-02T01:00:00Z"},
                "franja_horaria": "Lunes_22_23", "tiempo_real": tiempo,
            }

        parada = {"orden": 0, "hora": "05:25", "localidad": "Neuquén",
                  "coordenadas": {"latitud": -38, "longitud": -68}}
        documentos = {
            "hojas": [
                hoja("h1", "v1", [(1, 2), (2, 1), (1, 2)], [parada]),
                hoja("h2", "v2", [(1, 2)]),
                hoja("h3", "v2", [(1, 2)]),
                hoja("h4", "v3", [], [parada], geometria=False),
            ],
            "gps": [],
            "observaciones": [
                observacion("v1", 1, 2),
                observacion("v2", 1, 2),
                observacion("solo_observado", 80, 90),
                observacion("v1", 1, 2, tiempo=-1),
                observacion(None, 1, 2),
            ],
        }
        archivos = {}
        for nombre, docs in documentos.items():
            ruta = Path(self.tmp.name) / f"{nombre}.json"
            ruta.write_text(json.dumps(docs), encoding="utf-8")
            archivos[nombre] = ruta
        self.importar(archivos)

        self.assertEqual(self.consultar("SELECT count(*) FROM segmentos"), [(3,)])
        secuencia = self.consultar("""
            SELECT orden, origen, destino FROM segmentos_detalle
            JOIN recorridos USING (recorrido_id) JOIN hojas USING (hoja_n)
            WHERE hoja_id = 'h1' ORDER BY orden
        """)
        self.assertEqual(secuencia, [(0, "1", "2"), (1, "2", "1"), (2, "1", "2")])
        self.assertEqual(self.consultar("SELECT count(*) FROM observaciones_importadas"), [(5,)])
        self.assertEqual(self.consultar("SELECT count(*) FROM observaciones_segmento"), [(3,)])
        asociaciones = self.consultar("""
            SELECT idvehiculo, recorridos_candidatos, estado_asociacion,
                   ref_recorrido IS NOT NULL, dia::text, hora_local::text, dia_semana
            FROM dataset_entrenamiento ORDER BY idvehiculo
        """)
        self.assertEqual(asociaciones, [
            ("solo_observado", 0, "sin_coincidencia", False, "2026-06-01", "22:00:00", 1),
            ("v1", 1, "unico_no_validado", True, "2026-06-01", "22:00:00", 1),
            ("v2", 2, "ambiguo", False, "2026-06-01", "22:00:00", 1),
        ])
        self.assertEqual(self.consultar("SELECT latitud, longitud FROM nodos WHERE idnodo = '80'"),
                         [(None, None)])
        self.assertEqual(self.consultar("""
            SELECT rp.hora_referencia, r.n_segmentos, r.duracion_osrm_original
            FROM recorrido_paradas rp JOIN recorridos r USING (recorrido_id)
            JOIN hojas USING (hoja_n) WHERE hoja_id = 'h4'
        """), [("05:25", 0, None)])


if __name__ == "__main__":
    unittest.main()
