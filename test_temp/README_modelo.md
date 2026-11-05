# Modelo normalizado de PostgreSQL

`load_dataset.py` importa los tres JSON y genera el modelo acordado. La notebook
`Analisis_DataSet.py` utiliza este importador. La importación SQLite de la raíz es
un flujo separado.

## Tablas

Se mantienen los nombres en plural y `snake_case` del importador:

| Entidad | Tabla | Contenido |
|---|---|---|
| Vehículo | `vehiculos` | ID, tipo y capacidad. |
| Nodo | `nodos` | ID vial y coordenadas, si se conocen. |
| Segmento | `segmentos` | ID y par dirigido de nodos, único. |
| Observación de segmento | `observaciones_segmento` | ID de origen, segmento, vehículo, fecha UTC, franja original y segundos observados. |
| Hoja de ruta | `hojas` | Identificador original, vehículo, vigencia y documento original. |
| Recorrido | `recorridos` | Hoja, variante, geometría y referencia OSRM del recorrido completo. |
| Segmentos del recorrido | `recorrido_segmentos` | Recorrido, orden, segmento y estimación original del tramo. |
| Parada | `paradas` | Ubicación y localidad. |
| Paradas del recorrido | `recorrido_paradas` | Recorrido, orden, parada y hora de referencia original. |

Las relaciones tienen claves foráneas. La clave de las dos tablas ordenadas es
`(recorrido_id, orden)`: un mismo tramo o lugar puede repetirse en distintas posiciones.
Los tiempos estimados del tramo quedan en la relación con el recorrido, no en la
identidad del segmento.

`hojas` conserva también atributos de vehículo presentes en cada documento como
instantánea de origen; el dataset obtiene las características de `vehiculos`.
Por ahora, para un vehículo se conserva el primer valor de características encontrado.

### Conservación de los originales

- `segmentos_importados`, `observaciones_importadas` y `paradas_importadas`
  conservan los campos de origen antes de normalizarlos, incluso registros que
  no cumplen los requisitos para entrenar.
- Las observaciones normalizadas exigen vehículo, fecha válida, ambos nodos y
  un tiempo finito positivo. Su `idobservacion` referencia el registro importado.
- Los segmentos con ambos nodos se identifican por ese par dirigido, que es la
  granularidad disponible en las observaciones. No se infieren conexiones adicionales.
- Si un nodo aparece solo en observaciones, se conserva su ID con coordenadas
  nulas. No se inventa una ubicación.
- Se conservan `gps`, `pasajeros` y `waypoints`, además del documento de cada hoja.

### Paradas

`hora_referencia` es texto de origen, por ejemplo `05:25` o una cadena vacía.
No se convierte a UTC: no tiene fecha ni zona horaria y todavía no se confirmó
si es un horario programado, de llegada o de salida.

Como las paradas no traen identidad propia, se conserva una entidad por registro
importado, trazable por su ID. **No se deduplican por proximidad**. Identificar
lugares compartidos entre hojas queda pendiente de una regla validada.

Si una variante tiene paradas o waypoints pero carece de geometría OSRM, se crea
el recorrido con cero segmentos y duración OSRM nula; así no se pierden sus paradas.
El orden se conserva tal como viene. Órdenes repetidos dentro de una variante
producen un error de integridad; no se reordenan ni se descartan silenciosamente.

## Dataset y CSV

`dataset_entrenamiento` contiene una fila por observación válida y tiene
`idobservacion` como clave primaria. Incluye:

- IDs de observación, segmento y vehículo.
- Características del vehículo y coordenadas de ambos nodos.
- Fecha UTC original y `dia`, `hora_local`, `dia_semana` derivados en
  `America/Argentina/Buenos_Aires` (`dia_semana`: lunes = 1, domingo = 7).
- Franja original y `tiemporeal` sin modificaciones.
- Contexto de recorrido cuando existe una única candidatura.
- `recorridos_candidatos` y `estado_asociacion`.

Una candidatura exige mismo vehículo, fecha dentro de la vigencia de la hoja
(ambos extremos incluidos) y segmento dirigido presente en la variante.
Las repeticiones del segmento en un mismo recorrido no multiplican las candidaturas.

| Estado | Significado |
|---|---|
| `sin_coincidencia` | No se encontró recorrido candidato; contexto nulo. |
| `unico_no_validado` | Un candidato; se adjunta su contexto, sin afirmar que se realizó ese viaje. |
| `ambiguo` | Varios candidatos; no se selecciona uno y el contexto queda nulo. |

El CSV se ordena por vehículo y fecha y se exporta, por defecto, a
`data/procesados/dataset_entrenamiento.csv`. Puede cambiarse con `csv_salida`.

**El objetivo inicial es circulación**, incluyendo demoras del tránsito. Todavía
no se comprobó si `tiempo_real` incluye detenciones de ascenso/descenso; no se
descuentan tiempos supuestos. Tampoco se reconstruyen viajes. La duración OSRM
es del recorrido completo y no debe compararse directamente con una observación
individual de segmento. El objetivo y los identificadores de trazabilidad no deben
incorporarse automáticamente como variables de entrada del modelo.

## Primera importación

La configuración compartida de `driverdb.py` apunta al esquema `eta_modelo` mediante
`search_path`. La notebook y los módulos de exploración usan esa misma conexión.
Este esquema debe existir antes de cargar; para prepararlo en otra computadora,
ejecutar una vez en la base configurada:

```sql
CREATE SCHEMA IF NOT EXISTS eta_modelo;
```

El esquema recién creado está vacío: las tablas se crean al ejecutar el importador.
Las tablas de `public` quedan separadas del nuevo modelo.

Este esquema cambia la estructura anterior: `CREATE TABLE IF NOT EXISTS` no alcanza
para migrar sus tablas. **Usar una base o un esquema nuevo y vacío** y apuntar las
conexiones del equipo a ese mismo destino. El importador rechaza una segunda carga
sobre las tablas existentes, sin borrarlas, para evitar duplicaciones o mezclar
estructuras. No ejecuta una migración destructiva de la base anterior.

Dependencias del importador PostgreSQL: `ijson` y `psycopg2` (también puede instalarse
como `psycopg2-binary`). Usar el entorno virtual del proyecto.

Ejemplo desde la raíz, usando la conexión compartida de `driverdb.py`:

```python
from pathlib import Path
from test_temp.load_dataset import importar_dataset_postgres
from test_temp.driverdb import DB_URI

originales = Path("data/originales")
resultado = importar_dataset_postgres(
    archivos={
        "hojas": originales / "hojaDeRuta.json",
        "gps": originales / "rastreoSatelital.json",
        "observaciones": originales / "observacionesSegmentosViales.json",
    },
    db_uri=DB_URI,
    lote=5000,
)
print(resultado)
```

La carga confirma lotes para procesar archivos grandes. Si falla a mitad de camino,
pueden quedar lotes ya confirmados: para reintentarla usar otro destino vacío o
limpiar explícitamente solo el esquema de esa importación. Si falla únicamente la
exportación, la tabla del dataset ya puede estar confirmada y se puede exportar
directamente desde PostgreSQL.

La notebook realiza la primera carga al ejecutar su celda de importación. En una
base ya cargada, ejecutar únicamente las celdas de consulta y exploración; no volver
a ejecutar la celda de importación.

## Compatibilidad de consultas

- `observaciones` es una vista de las observaciones normalizadas, con los nombres
  anteriores (`observacion_n`, `flota_id`, `nodo_origen`, etc.). Solo muestra válidas;
  para auditar descartadas consultar `observaciones_importadas`.
- `segmentos_detalle` une `recorrido_segmentos` con `segmentos` y expone el detalle
  ordenado con `origen` y `destino`. Las consultas exploratorias se adaptaron a ella.
- `dataset_up.py` es el importador anterior; no genera este modelo.

## Verificación

Con PostgreSQL disponible, configurar `ETA_TEST_DB_URI` y ejecutar:

```bash
.venv/bin/python -m unittest discover -s test_temp -p 'test_load_dataset.py' -v
```

Cada prueba crea y elimina exclusivamente su propio esquema aleatorio. Se prueba
la carga real de los JSON reducidos, trazabilidad y CSV, rechazo de reimportación,
segmentos repetidos y dirigidos, candidatos ambiguos, observaciones inválidas,
nodos sin coordenadas, fecha local y paradas sin geometría OSRM.
