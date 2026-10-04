from __future__ import annotations

from typing import Any

from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from app.db.connectors import DialectAdapter

SchemaInfo = dict[str, Any]  # {"tables": {"schema.table": {"columns": [...], "pk": [...], "fks": [...]}}}


def inspect_schema(engine: Engine, adapter: DialectAdapter, max_tables: int = 200) -> SchemaInfo:
    insp = inspect(engine)
    tables: dict[str, Any] = {}
    for schema in insp.get_schema_names():
        if schema.lower() in adapter.system_schemas or schema.startswith("pg_"):
            continue
        names = [(n, "table") for n in insp.get_table_names(schema=schema)]
        names += [(n, "view") for n in insp.get_view_names(schema=schema)]
        for name, kind in names:
            if len(tables) >= max_tables:
                break
            cols = [{"name": c["name"], "type": str(c["type"]), "nullable": c.get("nullable", True)}
                    for c in insp.get_columns(name, schema=schema)]
            pk = insp.get_pk_constraint(name, schema=schema).get("constrained_columns", [])
            fks = [{"cols": f["constrained_columns"], "ref": f"{f.get('referred_schema') or schema}.{f['referred_table']}",
                    "ref_cols": f["referred_columns"]} for f in insp.get_foreign_keys(name, schema=schema)]
            tables[f"{schema}.{name}"] = {"kind": kind, "columns": cols, "pk": pk, "fks": fks}
    return {"tables": tables}


def schema_to_prompt(info: SchemaInfo) -> str:
    lines = []
    for qname, t in info["tables"].items():
        cols = ", ".join(f"{c['name']} {c['type']}" for c in t["columns"])
        lines.append(f"- {qname} ({t['kind']}): {cols}")
        if t["pk"]:
            lines.append(f"    PK: {', '.join(t['pk'])}")
        for fk in t["fks"]:
            lines.append(f"    FK: {', '.join(fk['cols'])} -> {fk['ref']}({', '.join(fk['ref_cols'])})")
    return "\n".join(lines)


def allowed_tables(info: SchemaInfo) -> set[str]:
    out: set[str] = set()
    for qname in info["tables"]:
        out.add(qname.lower())
        out.add(qname.split(".", 1)[1].lower())
    return out
