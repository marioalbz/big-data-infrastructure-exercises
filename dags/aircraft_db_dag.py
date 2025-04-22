import os
import json
import gzip
from io import BytesIO
from datetime import datetime, timedelta
from contextlib import contextmanager

import boto3
import requests
from airflow import DAG
from airflow.operators.python import PythonOperator
from psycopg2 import pool

S3_BUCKET = os.getenv("S3_BUCKET", "bdi-aircraft-marioalbz")
PG_HOST = os.getenv("DB_HOST", "localhost")
PG_PORT = int(os.getenv("DB_PORT", "5433"))
PG_DBNAME = os.getenv("DB_NAME", "bdi_db")
PG_USER = os.getenv("DB_USERNAME", "postgres")
PG_PASSWORD = os.getenv("DB_PASSWORD", "postgres")

def get_connection_pool():
    return pool.ThreadedConnectionPool(
        minconn=1,
        maxconn=10,
        dbname=PG_DBNAME,
        user=PG_USER,
        password=PG_PASSWORD,
        host=PG_HOST,
        port=PG_PORT,
    )

@contextmanager
def get_db_conn():
    pool_conn = get_connection_pool()
    conn = pool_conn.getconn()
    try:
        yield conn
    finally:
        pool_conn.putconn(conn)

def ensure_registry_table():
    with get_db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS aircraft_registry (
                    icao TEXT PRIMARY KEY,
                    reg TEXT,
                    icatype TEXT,
                    year TEXT,
                    manufacturer TEXT,
                    model TEXT,
                    ownop TEXT,
                    faa_pia BOOLEAN,
                    faa_ladd BOOLEAN,
                    short_type TEXT,
                    mil BOOLEAN
                );
                """
            )
            conn.commit()

def download_and_process_registry(**context):
    url = "http://downloads.adsbexchange.com/downloads/basic-ac-db.json.gz"
    execution_date = context["ds"]
    date_str = execution_date.replace("-", "")
    s3_raw_key = f"raw/registry/day={date_str}/basic-ac-db.json.gz"
    s3_prepared_key = f"prepared/registry/day={date_str}/aircraft_registry.json"

    s3 = boto3.client("s3")

    try:
        s3.head_object(Bucket=S3_BUCKET, Key=s3_prepared_key)
        print(f"[SKIP] Already exists: s3://{S3_BUCKET}/{s3_prepared_key}")
        return
    except s3.exceptions.ClientError:
        pass

    response = requests.get(url, stream=True)
    response.raise_for_status()
    raw_bytes = response.content

    s3.upload_fileobj(BytesIO(raw_bytes), S3_BUCKET, s3_raw_key)

    decompressed_data = gzip.decompress(raw_bytes).decode("utf-8")
    lines = decompressed_data.strip().split("\n")
    data = [json.loads(line) for line in lines]

    s3.put_object(
        Bucket=S3_BUCKET,
        Key=s3_prepared_key,
        Body=json.dumps(data, indent=2),
    )

    ensure_registry_table()

    with get_db_conn() as conn:
        with conn.cursor() as cur:
            for row in data:
                cur.execute(
                    """
                    INSERT INTO aircraft_registry (
                        icao, reg, icatype, year, manufacturer,
                        model, ownop, faa_pia, faa_ladd, short_type, mil
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (icao) DO UPDATE SET
                        reg = EXCLUDED.reg,
                        icatype = EXCLUDED.icatype,
                        year = EXCLUDED.year,
                        manufacturer = EXCLUDED.manufacturer,
                        model = EXCLUDED.model,
                        ownop = EXCLUDED.ownop,
                        faa_pia = EXCLUDED.faa_pia,
                        faa_ladd = EXCLUDED.faa_ladd,
                        short_type = EXCLUDED.short_type,
                        mil = EXCLUDED.mil;
                    """,
                    (
                        row.get("icao"),
                        row.get("reg"),
                        row.get("icatype"),
                        row.get("year"),
                        row.get("manufacturer"),
                        row.get("model"),
                        row.get("ownop"),
                        row.get("faa_pia"),
                        row.get("faa_ladd"),
                        row.get("short_type"),
                        row.get("mil"),
                    ),
                )
            conn.commit()

default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=2),
}

with DAG(
    dag_id="aircraft_db_dag",
    default_args=default_args,
    schedule_interval="@daily",
    start_date=datetime(2023, 11, 1),
    catchup=True,
    max_active_runs=1,
    tags=["adsb", "aircraft", "registry", "etl"],
) as dag:
    process_registry = PythonOperator(
        task_id="download_aircraft_db",
        python_callable=download_and_process_registry,
    )
