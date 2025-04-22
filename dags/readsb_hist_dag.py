import os
import json
import gzip
from io import BytesIO
from datetime import datetime, timedelta
from contextlib import contextmanager

import boto3
import requests
from bs4 import BeautifulSoup
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

def ensure_tables_exist(cursor):
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS traces (
        id SERIAL PRIMARY KEY,
        icao TEXT NOT NULL,
        registration TEXT NULL,
        type TEXT NULL,
        lat DOUBLE PRECISION NULL,
        lon DOUBLE PRECISION NULL,
        timestamp TEXT NULL,
        max_alt_baro NUMERIC NULL,
        max_ground_speed NUMERIC NULL,
        had_emergency BOOLEAN DEFAULT FALSE
    );
    CREATE INDEX IF NOT EXISTS idx_traces_icao ON traces (icao);
    """)

def download_files(**context):
    execution_date = context["ds"]
    date_obj = datetime.strptime(execution_date, "%Y-%m-%d")
    if date_obj.day != 1:
        print(f"[SKIP] {execution_date} is not the 1st of the month.")
        return

    base_url = f"https://samples.adsbexchange.com/readsb-hist/{date_obj.strftime('%Y/%m/%d')}/"
    s3 = boto3.client("s3")
    s3_prefix = f"raw/day={date_obj.strftime('%Y%m%d')}/"

    response = requests.get(base_url)
    if response.status_code != 200:
        print(f"[ERROR] Failed to access index page: {base_url}")
        return

    soup = BeautifulSoup(response.content, "html.parser")
    links = [a["href"] for a in soup.find_all("a") if a["href"].endswith(".json.gz")]
    print(f"[FOUND] {len(links)} files in index.")

    for idx, filename in enumerate(links[:100]):
        s3_key = s3_prefix + filename
        try:
            s3.head_object(Bucket=S3_BUCKET, Key=s3_key)
            print(f"[SKIP] Already exists in S3: {s3_key}")
            continue
        except s3.exceptions.ClientError:
            pass

        url = base_url + filename
        res = requests.get(url)
        if res.status_code == 200:
            s3.upload_fileobj(BytesIO(res.content), S3_BUCKET, s3_key)
            print(f"[S3] Uploaded to s3://{S3_BUCKET}/{s3_key}")
        else:
            print(f"[WARN] Failed to fetch file: {url}")

def prepare_files(**context):
    execution_date = context["ds"]
    date_obj = datetime.strptime(execution_date, "%Y-%m-%d")
    if date_obj.day != 1:
        print(f"[SKIP] {execution_date} is not the 1st of the month.")
        return

    s3 = boto3.client("s3")
    raw_prefix = f"raw/day={date_obj.strftime('%Y%m%d')}/"
    paginator = s3.get_paginator("list_objects_v2")
    pages = paginator.paginate(Bucket=S3_BUCKET, Prefix=raw_prefix)

    conn = get_connection_pool().getconn()
    cur = conn.cursor()
    ensure_tables_exist(cur)

    inserted_rows = 0
    for page in pages:
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if not key.endswith(".json.gz"):
                continue
            print(f"[PROCESS] Reading {key}")

            raw_data = s3.get_object(Bucket=S3_BUCKET, Key=key)["Body"].read()
            try:
                with gzip.GzipFile(fileobj=BytesIO(raw_data)) as gz:
                    decompressed_data = gz.read().decode("utf-8")
                data = json.loads(decompressed_data)
            except Exception as e:
                print(f"[ERROR] Failed to parse {key}: {e}")
                continue

            for entry in data.get("aircraft", []):
                icao = entry.get("hex")
                try:
                    cur.execute(
                        """
                        INSERT INTO traces
                        (icao, lat, lon, timestamp, max_alt_baro, max_ground_speed, had_emergency, registration, type)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s);
                        """,
                        (
                            icao,
                            entry.get("lat", 0.0) if isinstance(entry.get("lat"), (int, float)) else 0.0,
                            entry.get("lon", 0.0) if isinstance(entry.get("lon"), (int, float)) else 0.0,
                            entry.get("seen_pos", ""),
                            entry.get("alt_baro", 0.0) if isinstance(entry.get("alt_baro"), (float,)) else 0.0,
                            entry.get("gs", 0.0) if isinstance(entry.get("gs"), (float,)) else 0.0,
                            entry.get("alert") == 1,
                            entry.get("r", None),
                            entry.get("t", None)
                        )
                    )
                    inserted_rows += 1
                except Exception as e:
                    print(f"[WARN] Skipping entry for {icao}: {e}")

    conn.commit()
    print(f"[DB] Total rows inserted: {inserted_rows}")
    cur.close()
    conn.close()

default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=3),
}

with DAG(
    dag_id="readsb_hist_dag",
    default_args=default_args,
    description="ETL for ADS-B readsb-hist: download raw → prepare → store & insert",
    schedule_interval="@monthly",
    start_date=datetime(2023, 11, 1),
    end_date=datetime(2024, 11, 1),
    catchup=True,
    max_active_runs=1,
    tags=["readsb", "etl", "aviation"],
) as dag:

    download_task = PythonOperator(
        task_id="download_readsb_hist",
        python_callable=download_files,
    )

    prepare_task = PythonOperator(
        task_id="prepare_and_upload_readsb_hist",
        python_callable=prepare_files,
    )

    download_task >> prepare_task
