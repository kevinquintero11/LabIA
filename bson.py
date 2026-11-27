from datetime import UTC, datetime


def a_id(val):
    if val is None:
        return None
    if isinstance(val, dict) and "$oid" in val:
        return str(val["$oid"])
    texto = str(val).strip()
    return texto if texto else None


def a_float(val):
    if val is None or isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, dict):
        for clave in ("$numberDouble", "$numberInt", "$numberLong", "$numberDecimal"):
            if clave in val:
                val = val[clave]
                break
        else:
            return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def a_dt(val):
    if val is None:
        return None
    if isinstance(val, datetime):
        return val if val.tzinfo else val.replace(tzinfo=UTC)
    if isinstance(val, dict) and "$date" in val:
        val = val["$date"]
        if isinstance(val, dict) and "$numberLong" in val:
            val = int(val["$numberLong"])
    if isinstance(val, (int, float)):
        ts = val / 1000 if abs(val) > 1e11 else val
        return datetime.fromtimestamp(ts, tz=UTC)
    if isinstance(val, str):
        texto = val[:-1] + "+00:00" if val.endswith("Z") else val
        try:
            dt = datetime.fromisoformat(texto)
            return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
        except ValueError:
            return None
    return None