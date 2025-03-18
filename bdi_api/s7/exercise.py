import io
import gzip
import json
import boto3
from fastapi import APIRouter, HTTPException
from bdi_api.settings import DBCredentials, Settings
import psycopg2
from psycopg2.extras import execute_batch

# Basic setup
settings = Settings()
db_credentials = DBCredentials()
s3_client = boto3.client("s3")
BUCKET_NAME = "bdi-aircraft-marioalbz"
s7 = APIRouter(prefix="/api/s7", tags=["s7"])

# Database connection using context manager
def connect_to_database():
    return psycopg2.connect(
        dbname=db_credentials.database,
        user=db_credentials.username,
        password=db_credentials.password,
        host=db_credentials.host,
        port=db_credentials.port
    )

# Create and validate database tables
def create_database_tables():
    with connect_to_database() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS aircraft (
                    icao VARCHAR PRIMARY KEY,
                    registration VARCHAR,
                    type VARCHAR
                );
                CREATE TABLE IF NOT EXISTS aircraft_positions (
                    icao VARCHAR REFERENCES aircraft(icao),
                    timestamp BIGINT,
                    lat DOUBLE PRECISION,
                    lon DOUBLE PRECISION,
                    altitude_baro DOUBLE PRECISION,
                    ground_speed DOUBLE PRECISION,
                    emergency BOOLEAN,
                    PRIMARY KEY (icao, timestamp)
                );
            """)
            conn.commit()

# Read and process files from S3
def get_all_files_from_s3():
    all_data = []
    response = s3_client.list_objects_v2(Bucket=BUCKET_NAME)
    
    for obj in response.get("Contents", []):
        file_key = obj["Key"]
        data = get_file_from_s3(file_key)
        all_data.extend(data)

    return all_data

def get_file_from_s3(file_key):
    try:
        obj = s3_client.get_object(Bucket=BUCKET_NAME, Key=file_key)
        with gzip.GzipFile(fileobj=io.BytesIO(obj["Body"].read())) as gz:
            data = json.loads(gz.read().decode("utf-8"))
    except gzip.BadGzipFile:
        data = json.loads(obj["Body"].read().decode("utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read {file_key}: {str(e)}")
    
    return data.get("aircraft", data) if isinstance(data, dict) else data

# Insert data into PostgreSQL
def save_to_database(data):
    aircraft_data = []
    position_data = []

    for record in data:
        if not isinstance(record, dict):
            continue

        icao = record.get("icao") or record.get("hex")
        if not icao:
            continue

        # Collect aircraft data
        aircraft_data.append((
            icao,
            record.get("registration", ""),
            record.get("type", "")
        ))

        # Collect position data if available
        if "lat" in record and "lon" in record:
            position_data.append((
                icao,
                record.get("timestamp", 0),
                record["lat"],
                record["lon"],
                float(record.get("altitude_baro", 0)),
                float(record.get("ground_speed", 0)),
                bool(record.get("emergency", False))
            ))

    with connect_to_database() as conn:
        with conn.cursor() as cur:
            if aircraft_data:
                execute_batch(cur, """
                    INSERT INTO aircraft (icao, registration, type)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (icao) DO UPDATE SET
                        registration = EXCLUDED.registration,
                        type = EXCLUDED.type;
                """, aircraft_data)

            if position_data:
                execute_batch(cur, """
                    INSERT INTO aircraft_positions
                    (icao, timestamp, lat, lon, altitude_baro, ground_speed, emergency)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (icao, timestamp) DO NOTHING;
                """, position_data)
                
            conn.commit()

# Endpoint to prepare data from S3
@s7.post("/aircraft/prepare")
def prepare_data():
    create_database_tables()
    data = get_all_files_from_s3()
    if not data:
        raise HTTPException(status_code=404, detail="No aircraft data found in S3")
    save_to_database(data)
    return {"status": "success", "message": "Aircraft data saved successfully"}

# Endpoint to list all aircraft
@s7.get("/aircraft/")
def list_aircraft(num_results: int = 100, page: int = 0):
    with connect_to_database() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT icao, registration, type FROM aircraft ORDER BY icao LIMIT %s OFFSET %s",
                (num_results, page * num_results)
            )
            results = [{"icao": r[0], "registration": r[1], "type": r[2]} for r in cur.fetchall()]
    return results

# Endpoint to get position of specific aircraft
@s7.get("/aircraft/{icao}/positions")
def get_aircraft_position(icao: str, num_results: int = 1000, page: int = 0):
    with connect_to_database() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT timestamp, lat, lon 
                FROM aircraft_positions 
                WHERE icao = %s 
                ORDER BY timestamp 
                LIMIT %s OFFSET %s
                """,
                (icao, num_results, page * num_results)
            )
            results = [{"timestamp": r[0], "lat": r[1], "lon": r[2]} for r in cur.fetchall()]
    return results

# Endpoint to get stats of specific aircraft
@s7.get("/aircraft/{icao}/stats")
def get_aircraft_statistics(icao: str):
    with connect_to_database() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 
                    COALESCE(MAX(altitude_baro), 0),
                    COALESCE(MAX(ground_speed), 0),
                    COALESCE(BOOL_OR(emergency), FALSE)
                FROM aircraft_positions 
                WHERE icao = %s
                """,
                (icao,)
            )
            row = cur.fetchone()
            if row:
                return {
                    "max_altitude_baro": row[0],
                    "max_ground_speed": row[1],
                    "had_emergency": row[2]
                }
            else:
                raise HTTPException(status_code=404, detail=f"No data found for ICAO: {icao}")