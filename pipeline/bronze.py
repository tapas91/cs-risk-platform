"""Bronze loader: landed Parquet files -> append-only DuckDB tables, each file loaded exactly once.

LANDING_URI is a local folder in this project; an s3:// URI works unchanged (httpfs + S3_* env vars).

Bronze keeps what landed, as landed, plus where and when it came from:
    _tenant_id, _synced_month   from the object path (tenant=/synced_month= partitions)
    _source_file                full path of the file the row came from
    _batch_id, _ingested_at     which load put it here, and when
Nothing is updated, deduplicated or deleted here. Silver does that, so it can always be rebuilt.

Schema drift policy: a new column is added; a column whose type changes is widened to the common
supertype DuckDB picks (e.g. DATE + VARCHAR -> VARCHAR). Every change is logged to ops.schema_changes."""
import os
import re
import uuid
from collections import defaultdict
from contextlib import contextmanager
from typing import Dict, List

import duckdb

WAREHOUSE = os.environ.get("WAREHOUSE_PATH", "warehouse/warehouse.duckdb")
LANDING = os.environ.get("LANDING_URI", "landing").rstrip("/")
PATH_RE = re.compile(r"tenant=(?P<tenant>[^/]+)/(?P<source>[^/]+)/(?P<table>[^/]+)/synced_month=(?P<month>[^/]+)/[^/]+\.parquet$")
SOURCES = ["salesforce", "zendesk", "stripe", "product", "gmail"]


@contextmanager
def connect(read_only: bool = False):
    con = duckdb.connect(WAREHOUSE, read_only=read_only, config={"TimeZone": "UTC"})
    try:
        if LANDING.startswith("s3://"):
            con.execute("LOAD httpfs")
            con.execute(f"""
                CREATE OR REPLACE TEMP SECRET landing (
                    TYPE s3, KEY_ID '{os.environ["S3_ACCESS_KEY"]}', SECRET '{os.environ["S3_SECRET_KEY"]}',
                    ENDPOINT '{os.environ.get("S3_ENDPOINT", "s3.amazonaws.com")}', REGION '{os.environ.get("S3_REGION", "us-east-1")}')""")
        yield con
    finally:
        con.close()


def bootstrap(con) -> None:
    con.execute("CREATE SCHEMA IF NOT EXISTS bronze")
    con.execute("CREATE SCHEMA IF NOT EXISTS ops")
    con.execute("""
        CREATE TABLE IF NOT EXISTS bronze._ingested_files (
            file VARCHAR PRIMARY KEY, tenant_id VARCHAR, source VARCHAR, table_name VARCHAR,
            synced_month VARCHAR, row_count BIGINT, batch_id VARCHAR, ingested_at TIMESTAMPTZ)""")
    con.execute("""
        CREATE TABLE IF NOT EXISTS ops.schema_changes (
            batch_id VARCHAR, table_name VARCHAR, column_name VARCHAR, change VARCHAR,
            old_type VARCHAR, new_type VARCHAR, changed_at TIMESTAMPTZ)""")


def discover(con) -> Dict[str, Dict[str, List[str]]]:
    """New files in the landing zone, grouped {source: {table: [files]}}."""
    listed = [r[0] for r in con.execute(f"SELECT file FROM glob('{LANDING}/**/*.parquet')").fetchall()]
    seen = {r[0] for r in con.execute("SELECT file FROM bronze._ingested_files").fetchall()}
    out: Dict[str, Dict[str, List[str]]] = defaultdict(lambda: defaultdict(list))
    for f in listed:
        m = PATH_RE.search(f)
        if m and f not in seen:
            out[m["source"]][m["table"]].append(f)
    return out


def _supertype(con, a: str, b: str) -> str:
    return con.execute(f"SELECT typeof(x) FROM (SELECT NULL::{a} AS x UNION ALL SELECT NULL::{b} AS x) LIMIT 1").fetchone()[0]


def _columns(con, schema: str, table: str) -> Dict[str, str]:
    return dict(con.execute(
        "SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = ? AND table_name = ? ORDER BY ordinal_position",
        [schema, table]).fetchall())


def load_table(con, source: str, table: str, files: List[str]) -> int:
    name = f"{source}__{table}"
    batch = uuid.uuid4().hex[:12]
    file_list = "[" + ", ".join(f"'{f}'" for f in files) + "]"
    con.execute("BEGIN")
    try:
        con.execute(f"""
            CREATE OR REPLACE TEMP TABLE _batch AS
            SELECT * EXCLUDE (tenant, synced_month, filename),
                   tenant AS _tenant_id, synced_month AS _synced_month, filename AS _source_file,
                   '{batch}' AS _batch_id, now() AS _ingested_at
            FROM read_parquet({file_list}, union_by_name = true, filename = true,
                              hive_partitioning = true, hive_types_autocast = false)""")
        incoming = dict(con.execute("SELECT column_name, column_type FROM (DESCRIBE _batch)").fetchall())
        existing = _columns(con, "bronze", name)
        if not existing:
            con.execute(f"CREATE TABLE bronze.{name} AS SELECT * FROM _batch")
        else:
            for col, typ in incoming.items():
                if col not in existing:
                    con.execute(f'ALTER TABLE bronze.{name} ADD COLUMN "{col}" {typ}')
                    con.execute("INSERT INTO ops.schema_changes VALUES (?, ?, ?, 'added', NULL, ?, now())", [batch, name, col, typ])
                elif typ != existing[col] and typ != '"NULL"':
                    wide = _supertype(con, existing[col], typ)
                    if wide != existing[col]:
                        con.execute(f'ALTER TABLE bronze.{name} ALTER COLUMN "{col}" TYPE {wide}')
                        con.execute("INSERT INTO ops.schema_changes VALUES (?, ?, ?, 'widened', ?, ?, now())",
                                    [batch, name, col, existing[col], wide])
            con.execute(f"INSERT INTO bronze.{name} BY NAME SELECT * FROM _batch")
        con.execute(f"""
            INSERT INTO bronze._ingested_files
            SELECT _source_file, any_value(_tenant_id), '{source}', '{table}', any_value(_synced_month), count(*), '{batch}', now()
            FROM _batch GROUP BY _source_file""")
        n = con.execute("SELECT count(*) FROM _batch").fetchone()[0]
        con.execute("DROP TABLE _batch")
        con.execute("COMMIT")
        return n
    except Exception:
        con.execute("ROLLBACK")
        raise


def load_source(source: str) -> Dict[str, int]:
    """Load every new file for one source. Returns rows loaded per table."""
    with connect() as con:
        bootstrap(con)
        pending = discover(con).get(source, {})
        return {table: load_table(con, source, table, files) for table, files in sorted(pending.items())}


def pending_files() -> int:
    with connect() as con:
        bootstrap(con)
        return sum(len(fs) for tables in discover(con).values() for fs in tables.values())
