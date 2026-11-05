import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor
from psycopg2.extensions import make_dsn
from typing import Any, Sequence

# Datos de conexión hardcodeados
DB_URI = "postgresql://admin:pase@localhost:5432/db_dataset"

# Todas las consultas del modelo usan el esquema nuevo, separado de public.
DB_SCHEMA = "eta_modelo"
DB_URI = make_dsn(DB_URI, options=f"-c search_path={DB_SCHEMA}")

_conexion = None

def conectarse():
    #Establece la conexión a la base de datos PostgreSQL utilizando la URI configurada.
    global _conexion
    if _conexion is None or _conexion.closed:
        _conexion = psycopg2.connect(DB_URI)
    return _conexion


def desconectarse():
    #Cierra la conexión activa a la base de datos si existe.
    global _conexion
    if _conexion and not _conexion.closed:
        _conexion.close()
        _conexion = None


def realizarSelect(consulta: str | sql.Composed, valores: Sequence[Any] | None = None) -> list[dict[str, Any]]:
    """
    Ejecuta una consulta SELECT sobre la base de datos y retorna el resultado como lista de diccionarios.

    :param consulta: Sentencia SQL (cadena o consulta compuesta de psycopg2.sql).
    :param valores: Parámetros para la consulta parametrizada (opcional).
    :return: Lista de diccionarios con los registros devueltos por la consulta.
    """
    global _conexion
    if _conexion is None or _conexion.closed:
        conectarse()

    cursor = _conexion.cursor(cursor_factory=RealDictCursor)

    if valores:
        cursor.execute(consulta, valores)
    else:
        cursor.execute(consulta)

    resultados = [dict(row) for row in cursor.fetchall()]
    cursor.close()
    return resultados
