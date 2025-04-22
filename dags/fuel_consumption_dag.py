import os
from datetime import datetime
from airflow import DAG
from airflow.operators.python import PythonOperator
import requests
import boto3

S3_BUCKET = os.getenv("S3_BUCKET", "bdi-aircraft-marioalbz")
URL = "https://raw.githubusercontent.com/martsec/flight_co2_analysis/main/data/aircraft_type_fuel_consumption_rates.json"

def download_fuel_consumption_rates(**kwargs):
    s3_client = boto3.client("s3")
    response = requests.get(URL)
    if response.status_code == 200:
        s3_key = "bronze/fuel-consumption/aircraft_type_fuel_consumption_rates.json"
        s3_client.put_object(Bucket=S3_BUCKET, Key=s3_key, Body=response.content)
        print(f"Downloaded fuel consumption rates to S3: {s3_key}")
    else:
        raise Exception(f"Failed to download fuel consumption rates: {response.status_code}")

with DAG(
    "fuel_consumption_dag",
    start_date=datetime(2023, 11, 1),
    schedule_interval="@monthly",
    catchup=False,
) as dag:
    download_task = PythonOperator(
        task_id="download_fuel_consumption_rates",
        python_callable=download_fuel_consumption_rates,
    )

    download_task
