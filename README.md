# Proyecto ETA — predicción de tiempos de viaje

Proyecto académico para estimar la duración de un viaje al salir y actualizar los minutos restantes durante el recorrido. La referencia de comparación es **OSRM**. Con las estimaciones se calculará una hora estimada de llegada (**ETA**) y se demostrará una regla de aviso de demora.

**Estado documentado:** importación local y exploración inicial con **marimo + SQLite**, utilizando `eta_importacion.py` (`VERSION = 1`). La reconstrucción definitiva de viajes, el panel de entrenamiento, los modelos y los avisos son etapas posteriores; no se generan automáticamente al importar los JSON.

**Modalidad del equipo:** cada integrante tiene el código compartido, una copia local de los mismos tres JSON y su propia base SQLite. Los datos grandes no se suben al repositorio.

> Esta guía usa `eta.py` como nombre de la notebook. Si en el repositorio tiene otro nombre, reemplazarlo en los comandos. Abrir la notebook existente del equipo, no crear una nueva vacía.

## Contenido

[Inicio](#1-puesta-en-marcha) · [Dependencias](#2-dependencias-y-versiones) · [Marimo](#3-cómo-trabajar-con-marimo) · [Datos](#4-datos-y-rutas) · [Importación](#5-primera-ejecución-e-importación) · [Base SQLite](#6-qué-contiene-la-base-sqlite) · [Consultas](#7-consultar-y-entender-los-resultados) · [Trabajo diario](#8-volver-a-trabajar-y-reimportar) · [Equipo](#9-trabajo-en-equipo) · [Problemas](#10-problemas-frecuentes) · [Siguientes etapas](#11-siguientes-etapas-del-proyecto)

## 1. Puesta en marcha

### Requisitos previos

Se propone utilizar **Python 3.11 o posterior**, acordando la misma versión menor entre integrantes. El módulo de importación requiere al menos Python 3.10; la compatibilidad de las bibliotecas instaladas también debe respetarse.

Se necesita un navegador, permiso de escritura en la carpeta del proyecto y espacio para los JSON —aproximadamente **9 GB en total**, según la entrega—, la base SQLite, sus índices y archivos temporales. No se fija un mínimo de RAM ni una duración de importación: dependen del equipo y de la estructura de los documentos. La lectura incremental evita cargar el archivo completo, pero cada documento y los lotes en curso sí ocupan memoria.

Para esta etapa **no hacen falta GPU, MongoDB, MySQL, un servidor OSRM, una cuenta de Colab ni una cuenta en marimo online**. La notebook ejecuta Python localmente. SQLite no requiere un servidor separado.[^sqlite]

### Estructura de carpetas

Clonar o descargar el repositorio compartido y organizarlo así:

```text
proyecto_eta/
├── README.md
├── eta.py                         # Notebook de marimo del equipo
├── eta_importacion.py              # Funciones de importación y consulta
├── requirements.txt                # Dependencias mínimas
├── .gitignore
├── .venv/                          # Se crea en cada computadora; no se comparte
├── datos/
│   ├── originales/                 # Copia local de los tres archivos entregados
│   │   ├── hojaDeRuta.json
│   │   ├── rastreoSatelital.json
│   │   └── observacionesSegmentosViales.json
│   └── procesados/
│       └── eta_datos_v1.sqlite     # Se genera al completar la importación
└── resultados/                     # Opcional: reportes y resultados posteriores
```

`requirements-lock.txt`, cuando el equipo lo genere, también se guarda en la raíz. No viene implícito con Python ni se crea al abrir marimo.

### Windows — PowerShell

Abrir una terminal **en la raíz del proyecto**, donde están `eta.py` y `eta_importacion.py`:

```powershell
py -3 --version
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\marimo.exe edit eta.py
```

Si el equipo acordó una versión concreta, seleccionarla al crear el entorno; por ejemplo, `py -3.12 -m venv .venv` requiere tener Python 3.12 instalado. Si `py` no está disponible pero `python` apunta a la instalación correcta, usar `python -m venv .venv`.

### Linux o macOS

También desde la raíz del proyecto:

```bash
python3 --version
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
.venv/bin/marimo edit eta.py
```

Seleccionar un ejecutable específico, como `python3.12`, cuando corresponda a la versión acordada. Si la distribución no incluye el soporte para `venv`, instalarlo mediante su gestor de paquetes antes de continuar.

**No es necesario activar el entorno:** los comandos anteriores usan directamente sus ejecutables. Esto también evita tener que modificar la política de ejecución de PowerShell. Cada integrante crea su propia `.venv`; no se copia la de otra computadora.[^venv]

Al ejecutar `marimo edit`, se abre el editor en el navegador. Si no se abre automáticamente, copiar la dirección que muestra la terminal, incluido el token cuando corresponda. Mantener esa terminal abierta mientras se trabaja.[^marimo]

## 2. Dependencias y versiones

### Dependencias actuales

El archivo `requirements.txt` mínimo contiene:

```text
marimo
ijson
```

| Componente | Función en esta etapa |
|---|---|
| `marimo` | Editor de la notebook, ejecución de celdas, tablas y botón de importación. |
| `ijson` | Lectura incremental de los arrays JSON. |
| `sqlite3` | Creación y consulta de SQLite; pertenece a la biblioteca estándar de Python. |
| `pathlib`, `json`, `shutil`, `itertools`, etc. | Rutas, configuración y utilidades; también forman parte de Python. |

No ejecutar `pip install sqlite3`, `pip install pathlib` ni instalar `eta_importacion`: este último es el archivo local del repositorio. `ijson` se importa cuando se leen los originales; las funciones de consulta a una base ya creada no lo necesitan.[^importador][^ijson]

`pandas`, `numpy`, `pyarrow`, `matplotlib`, `scikit-learn` y `xgboost` pueden incorporarse para exploración o modelado posterior. **No son necesarias para las celdas actuales que muestran listas de diccionarios con `mo.ui.table`.** Instalar bibliotecas no agrega por sí solo entrenamiento a la notebook.

### Fijar las versiones que ya funcionan

El archivo mínimo identifica dependencias, pero **sin versiones fijadas no garantiza instalaciones idénticas en distintas fechas**. Antes de distribuir un entorno de referencia, una persona debe registrar las versiones de su entorno funcional.

Windows:

```powershell
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m pip freeze | Set-Content -Encoding utf8 requirements-lock.txt
```

Linux/macOS:

```bash
.venv/bin/python --version
.venv/bin/python -m pip freeze > requirements-lock.txt
```

Revisar ese archivo antes de subirlo: no debe incluir rutas privadas ni paquetes ajenos al proyecto. `pip freeze` registra lo instalado; no demuestra que el entorno sea portable ni que las pruebas hayan pasado. Registrar también versión de Python y sistema operativo.[^pip]

Cuando el equipo haya validado el archivo, los demás reemplazan el comando de instalación por `python -m pip install -r requirements-lock.txt`, usando el ejecutable de su `.venv`. No sobrescribir el archivo compartido desde cada computadora ni actualizar paquetes sin coordinarlo.

## 3. Cómo trabajar con marimo

### Notebook, editor y código

Marimo guarda la notebook como un archivo Python (`eta.py`), no como un `.ipynb`. El navegador es la interfaz; Python y los archivos están en la computadora que ejecutó marimo. El `.py` contiene el código y los textos, no una copia de los JSON ni todas las salidas de la sesión.[^marimo][^jupyter]

Para desarrollar se utiliza **`marimo edit eta.py`**. El modo `marimo run` presenta la notebook como aplicación sin editor: no es el modo de trabajo de este proyecto.

### Celdas y dependencias

Una celda puede definir variables, funciones, texto o una consulta. Marimo determina las dependencias a partir de las variables definidas y utilizadas. En ejecución automática, actualizar una celda puede volver a ejecutar sus dependientes; el orden visual no es lo que determina el orden de cálculo.[^reactividad]

Ejemplo conceptual:

```text
Rutas de archivos
       ↓
Importación o reutilización de SQLite
       ↓
Consultas → tablas y exploración
```

**Un nombre global debe definirse en una sola celda.** No repetir `import marimo as mo`, `from pathlib import Path` o `BASE_ETA = ...` en diferentes celdas. Cambiar la definición original o usar nombres distintos. Las variables que empiezan con `_`, como `_ruta`, son locales a su celda en marimo. Además, modificar internamente un objeto en otra celda no dispara necesariamente la reactividad: es preferible producir un nuevo resultado.[^reactividad]

Los ejemplos de este README explican las celdas existentes; **no deben pegarse todos nuevamente** si sus variables ya están definidas. Tampoco hay que pegar los decoradores `@app.cell` en el editor de una celda: marimo administra la estructura del archivo.

### Configuración para este dataset

Cada integrante debe revisar los ajustes del editor:

| Ajuste | Configuración de trabajo propuesta |
|---|---|
| `On startup` | Desactivar la ejecución automática al abrir. |
| `On cell change` | Usar `lazy`. |
| `On module change` | Usar `lazy` si se habilita la recarga de módulos. |

En modo `lazy`, las celdas afectadas quedan pendientes en lugar de ejecutarse inmediatamente. Al ejecutar una celda, marimo también puede actualizar sus dependencias pendientes. No interpretar este modo como una prohibición absoluta de ejecutar código costoso.[^runtime]

Ejecutar una celda con su botón de ejecución o los atajos del editor. El panel de variables ayuda a inspeccionar resultados, y el grafo de dependencias explica por qué una celda necesita otra. Para registrar resultados visibles puede exportarse la vista a HTML desde el menú; revisar su contenido antes de compartirlo.[^editor]

No usar `%pip`, `!pip`, `%cd` o `drive.mount` de Colab en estas celdas. En este proyecto, las instalaciones se hacen desde la terminal usando el Python del entorno.[^jupyter]

## 4. Datos y rutas

### Qué contiene cada JSON

| Archivo | Información principal | Papel en el proyecto |
|---|---|---|
| `hojaDeRuta.json` | Vehículo, ventana de fechas, geometrías OSRM, segmentos y posibles paradas. | Describe el plan y la referencia de duración. |
| `rastreoSatelital.json` | Vehículo, fecha, coordenadas, velocidad y evento. | Permite estudiar el avance registrado. |
| `observacionesSegmentosViales.json` | Vehículo, fecha, nodos del tramo y `tiempo_real`. | Aporta los tiempos observados para construir la etiqueta. |

Según la consigna, son **arrays JSON** `[{...}, {...}]` con documentos estilo `mongoexport`. No tienen que estar organizados como una fila física por documento. Las envolturas `$date` y `$oid` se procesan al importar.[^consigna]

Los tres archivos deben proceder de la misma versión de la entrega. Cada integrante obtiene su copia mediante el canal privado acordado; `git clone` no descarga los datos. No modificar los originales durante la importación.

### Rutas configuradas en la notebook

La celda inicial contiene esta configuración:

```python
from pathlib import Path

PROYECTO = Path.cwd()
ORIGINALES = PROYECTO / "datos" / "originales"
PROCESADOS = PROYECTO / "datos" / "procesados"
PROCESADOS.mkdir(parents=True, exist_ok=True)
```

`Path.cwd()` representa el directorio de trabajo. Por eso se inicia marimo desde la raíz del proyecto. No cambiar silenciosamente de carpeta a mitad de la notebook. Si los archivos están en otro disco, ajustar `ORIGINALES` en su celda original y evitar subir una ruta personal como configuración común.

La asociación de nombres y el destino son:

```python
ARCHIVOS_ETA = {
    "hojas": ORIGINALES / "hojaDeRuta.json",
    "gps": ORIGINALES / "rastreoSatelital.json",
    "observaciones": ORIGINALES / "observacionesSegmentosViales.json",
}
BASE_ETA = PROCESADOS / "eta_datos_v1.sqlite"
```

Las claves `hojas`, `gps` y `observaciones` son las que espera el importador. Comprobar los nombres completos de los archivos, incluidas mayúsculas, extensión y posibles sufijos de descarga.

## 5. Primera ejecución e importación

Recorrer las celdas de la notebook hasta obtener lo siguiente:

| Bloque | Resultado esperado |
|---|---|
| Rutas y vista previa | Se encuentran los archivos y se muestran pocos documentos, no el dataset completo. |
| Funciones auxiliares | Se importan `importar_dataset`, `consultar_base` y `ejemplo_geometria`. |
| Tamaños y espacio libre | Se conocen las rutas de entrada y salida y el espacio disponible. |
| Botón de importación | Aparece **Importar los tres JSON a SQLite**. |
| Importación | Se crea o reutiliza la base y se muestra el resumen. |
| Exploración | Se muestran hojas, incidencias, una geometría y recorridos candidatos. |

La operación central es:

```python
resumen_importacion_eta = importar_dataset(
    archivos=ARCHIVOS_ETA,
    destino=BASE_ETA,
    lote=5_000,
)
BASE_ETA_LISTA = Path(resumen_importacion_eta["base"])
```

El botón y `mo.stop` controlan el inicio cuando no existe la base. Si en modo `lazy` queda una celda pendiente, ejecutar la celda de importación según lo indique el editor. No lanzar una segunda importación mientras la primera sigue activa.[^jupyter]

### Qué hace realmente el importador

Lee un documento a la vez con `ijson`, extrae los campos previstos, guarda las mediciones en lotes y crea índices. `lote=5_000` es el tamaño del lote de GPS y observaciones, **no un límite del total de registros**. Las hojas se procesan individualmente y se confirman periódicamente.[^importador]

Durante la ejecución se verán mensajes de lectura y creación de índices. La etapa de índices también puede demorar aunque hayan terminado los mensajes de lectura. No hay un tiempo fijo prometido.

El programa crea un archivo temporal `*.parcial.sqlite` y un bloqueo `eta_datos_v1.sqlite.lock`. El archivo final se publica cuando la importación concluye. Ante un error que permite ejecutar la limpieza se eliminan esos temporales; un cierre forzado puede dejarlos. No se modifican los JSON ni se sobrescribe una base existente incompatible.[^importador]

La lectura incremental reduce la necesidad de cargar datos simultáneamente, pero una hoja muy grande todavía debe entrar como documento en memoria. Además, `hojas.documento_json` conserva su contenido serializado y los índices ocupan disco: el tamaño final no se deduce directamente de los 9 GB originales.

### Resumen e incidencias

`resumen_importacion_eta` contiene `base`, `firma`, `tablas`, `incidencias`, `segundos_importacion`, `reutilizada` y `notas`. También se guarda dentro de SQLite, en `control`. **Esta versión no crea automáticamente un archivo externo `resumen_importacion.json`.**

Los conteos representan filas importadas, no viajes utilizables para entrenar. Las incidencias son contadores, no una depuración completa: por ejemplo, `gps_velocidad_cero_conservados` informa que se conservaron mediciones con velocidad cero, no que deban eliminarse.

## 6. Qué contiene la base SQLite

Los tres JSON no se convierten necesariamente en tres tablas. `hojaDeRuta.json` contiene información anidada de hojas, recorridos y segmentos; se separa en tres tablas para evitar repetir los datos de una hoja por cada segmento y facilitar las consultas.

| Origen | Tablas generadas |
|---|---|
| `hojaDeRuta.json` | `hojas`, `recorridos`, `segmentos` |
| `rastreoSatelital.json` | `gps` |
| `observacionesSegmentosViales.json` | `observaciones` |
| Metadatos de la importación | `control` |

La relación principal es `hojas` → `recorridos` → `segmentos`. Las mediciones de `gps` y `observaciones` se relacionan posteriormente mediante vehículo, fecha y, para las observaciones, los nodos del segmento.

El esquema efectivo de `eta_importacion.py` es:[^importador]

| Tabla | Columnas principales | Significado |
|---|---|---|
| `hojas` | `hoja_n`, `hoja_id`, `flota_id`, `tipo_vehiculo`, fechas UTC, `ventana_positiva`, `estado`, `documento_json` | Una fila por documento de hoja. |
| `recorridos` | `recorrido_id`, `hoja_n`, `variante`, `ruta_json`, `n_segmentos`, `duracion_osrm_original`, `distancia_osrm` | Geometrías detectadas dentro de cada hoja. |
| `segmentos` | `recorrido_id`, `orden`, `origen`, `destino` | Nodos y posición del segmento en la lista. |
| `gps` | `gps_n`, `flota_id`, `fecha_utc`, `longitud`, `latitud`, `velocidad`, `evento`, `campos_minimos_ok` | Mediciones GPS normalizadas. |
| `observaciones` | `observacion_n`, `flota_id`, `fecha_utc`, nodos, `franja_horaria`, `tiempo_real_seg`, `campos_minimos_ok` | Mediciones de duración por tramo, conservadas en segundos. |
| `control` | `clave`, `valor` | Metadatos y resultado de la importación. |

**Detalles que conviene conocer:**

- `hoja_n`, `gps_n` y `observacion_n` son posiciones en sus arrays originales, comenzando en 1. No son identificadores universales entre exportaciones reorganizadas. `segmentos.orden` comienza en 0.
- `recorridos.ruta_json` es una lista de claves o índices para localizar la geometría dentro de `hojas.documento_json`. **No contiene las coordenadas del recorrido.** Los detalles y tiempos estimados de los segmentos siguen en ese documento; no existe una columna de duración por segmento en la tabla `segmentos` de esta versión.
- `n_segmentos` cuenta elementos de la lista original; puede diferir del número de filas insertadas si había elementos que no eran documentos. No certifica cobertura observada.

### Fechas, unidades y controles

Las fechas reconocidas se normalizan a UTC en formato fijo. Las fechas sin zona horaria no se asumen UTC: quedan sin valor normalizado. La conversión a hora local para futuros atributos debe definirse por separado.

`tiempo_real_seg` conserva los segundos de la consigna. Para consultar minutos puede calcularse `tiempo_real_seg / 60.0`. Los tiempos y distancias OSRM mantienen sus unidades de origen hasta verificar la exportación. Los nodos se guardan como texto para conservar sus identificadores.[^importador][^consigna]

| Indicador | Qué comprueba | Qué no garantiza |
|---|---|---|
| `ventana_positiva` | Fechas interpretables y final posterior al inicio. | Que esas fechas sean salida y llegada reales. |
| `gps.campos_minimos_ok` | Vehículo, fecha y coordenadas en rangos básicos. | Calidad del recorrido o validez de la velocidad; esta última se revisa por separado. |
| `observaciones.campos_minimos_ok` | Vehículo, fecha, nodos y tiempo positivo. | Que la observación pertenezca a una pasada concreta. |

No hay eliminación general de duplicados ni identificación automática de viajes en esta etapa. Una hoja, una geometría, un punto GPS y una observación de tramo representan cosas diferentes.

## 7. Consultar y entender los resultados

Estas funciones se importan desde `eta_importacion.py`; no requieren pandas:

```python
from eta_importacion import (
    importar_dataset,
    consultar_base,
    ejemplo_geometria,
)
```

### Consultar pocas filas

Ejemplo para una celda, después de disponer de `BASE_ETA_LISTA`:

```python
muestra_observaciones_readme = consultar_base(
    BASE_ETA_LISTA,
    """
    SELECT flota_id, fecha_utc, nodo_origen, nodo_destino,
           tiempo_real_seg, tiempo_real_seg / 60.0 AS tiempo_real_min
    FROM observaciones
    WHERE campos_minimos_ok = 1
    ORDER BY observacion_n
    LIMIT 10
    """,
)
mo.ui.table(muestra_observaciones_readme, selection=None)
```

`consultar_base(base, sql, parametros=(), max_filas=1000)` devuelve una lista de diccionarios y abre la base en modo de solo lectura. Si obtiene más de `max_filas`, genera un error: usar `LIMIT`, filtros o agregaciones. Este límite protege el tamaño de la salida; no garantiza que una consulta costosa ejecute poco trabajo.

Para incorporar valores externos al SQL, utilizar `?` y `parametros`, no concatenar texto. Una consulta de rangos debe mantener el mismo formato temporal normalizado que las columnas.

### Inspeccionar geometrías

```python
geometria_revision_readme = ejemplo_geometria(BASE_ETA_LISTA)
print(json.dumps(geometria_revision_readme, indent=2, ensure_ascii=False))
```

Muestra una vista acotada con la variante, los campos OSRM y los dos primeros segmentos. Acepta también `recorrido_id=...` para elegir uno. Algunas listas internas se abrevian: la vista previa no es una exportación completa.

### Interpretar candidatos

La consulta de candidatos de la notebook relaciona vehículo, ventana temporal y nodos del recorrido. Estas son las claves indicadas en la consigna, que advierte que un mismo tramo puede pertenecer a varias hojas.[^consigna]

**Un candidato no es todavía un viaje reconstruido.** La existencia de un GPS y una observación compatible no demuestra cobertura completa, secuencia correcta ni ausencia de pasadas repetidas. No sumar sus tiempos directamente para entrenar.

## 8. Volver a trabajar y reimportar

### Aperturas posteriores

Abrir la terminal en la raíz y ejecutar solamente el comando de marimo del entorno:

```powershell
# Windows
.\.venv\Scripts\marimo.exe edit eta.py
```

```bash
# Linux/macOS
.venv/bin/marimo edit eta.py
```

No recrear `.venv` ni reinstalar paquetes cada vez. Ejecutar las celdas pendientes: el importador recupera la base completa cuando coincide su firma y muestra `Base completa encontrada: no se vuelven a leer los JSON.`

La firma compara **`VERSION`, rutas absolutas, tamaños y fechas de modificación**. No compara SHA-256 ni todo el código fuente. Por eso:

- Los originales deben seguir accesibles al llamar a `importar_dataset`, incluso para reutilizar la base.
- Mover un archivo o copiar la base de otro integrante puede causar una firma diferente aunque los datos sean iguales.
- Una modificación del código no se detecta automáticamente si no cambia `VERSION`. Los cambios de transformación deben versionarse y documentarse.

Las funciones de consulta sí pueden leer una base completa directamente sin volver a comprobar los originales. Esto no cambia la política del grupo de conservarlos para reproducir el procesamiento.

### Cambios e interrupciones

Si cambia el dataset o el importador, conservar la base anterior y elegir otro destino, por ejemplo `eta_datos_v2.sqlite`, modificando **la definición existente** de `BASE_ETA`. Asegurar espacio para ambas bases.

La versión actual **no reanuda importaciones interrumpidas**. Si hubo un cierre forzado, primero verificar que no sigue activo ningún proceso importador. Solo entonces revisar y retirar el bloqueo huérfano y los temporales de esa ejecución. Nunca quitar un `.lock` para permitir dos escritores simultáneos.

Guardar los cambios de la notebook y esperar a que termine la importación antes de cerrar marimo. Para finalizar la sesión, detenerlo en la terminal con `Ctrl+C`. La base completa permanece en disco; las variables en memoria se reconstruyen al ejecutar nuevamente las celdas.
