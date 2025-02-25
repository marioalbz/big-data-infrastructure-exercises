from concurrent.futures import ThreadPoolExecutor
import logging
import os
import shutil
from typing import Annotated
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
import pandas as pd
from tqdm import tqdm
import json

from fastapi import APIRouter, status
from fastapi.params import Query

import boto3
from botocore.exceptions import NoCredentialsError, PartialCredentialsError

from bdi_api.settings import Settings

settings = Settings()

# Creamos el cliente para AWS S3
s3_client = boto3.client(
    's3',
    aws_access_key_id=settings.s3_key_id,
    aws_secret_access_key=settings.s3_access_key,
    aws_session_token=settings.s3_session_token,
    region_name=settings.s3_region
)

s4 = APIRouter(
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Not found"},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"description": "Something is wrong with the request"},
    },
    prefix="/api/s4",
    tags=["s4"],
)


@s4.post("/aircraft/download")
def download_data(
    file_limit: Annotated[
        int,
        Query(
            ..., description="""
    Limits the number of files to download.
    You must always start from the first the page returns and
    go in ascending order in order to correctly obtain the results.
    I'll test with increasing number of files starting from 100.""",
        ),
    ] = 100,
) -> str:
    """Downloads aircraft data and uploads it to AWS S3."""
    base_url = settings.source_url + "/2023/11/01/"
    s3_bucket = settings.s3_bucket
    s3_prefix_path = "raw/day=20231101/"
    
    download_dir = os.path.join(settings.raw_dir, "day=20231101")

    if os.path.exists(download_dir):
        shutil.rmtree(download_dir)
    os.makedirs(download_dir, exist_ok=True)

    try:
        response = requests.get(base_url)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        files = [a["href"] for a in soup.find_all("a") if a["href"].endswith(".json.gz")][:file_limit]

        def fetch_file(file_name):
            file_url = urljoin(base_url, file_name)
            file_path = os.path.join(download_dir, file_name[:-3])
            response = requests.get(file_url, stream=True)
            if response.status_code == 200:
                with open(file_path, "wb") as f:
                    f.write(response.content)

        with ThreadPoolExecutor(max_workers=5) as executor:
            list(tqdm(executor.map(fetch_file, files), total=len(files), desc="Downloading files"))

    except requests.RequestException as e:
        logging.error(f"Error accessing URL: {str(e)}")
        return f"Error accessing URL: {str(e)}"
    
    # Upload raw data to S3
    all_files = []
    for root, _, files in os.walk(download_dir):
        for file in files:
            local_file_path = os.path.join(root, file)
            relative_path = os.path.relpath(local_file_path, download_dir)
            s3_object_name = os.path.join(s3_prefix_path, relative_path).replace("\\", "/")
            all_files.append((local_file_path, s3_object_name))

    for local_file_path, s3_object_name in tqdm(all_files, desc="Uploading files", unit="file"):
        try:
            s3_client.upload_file(local_file_path, s3_bucket, s3_object_name)
        except Exception as e:
            return f"Failed to upload {local_file_path}: {e}"
        
    return "OK"


@s4.post("/aircraft/prepare")
def prepare_data() -> str:
    """Processes aircraft data and uploads prepared files to AWS S3."""
    s3_bucket = settings.s3_bucket
    s3_prefix_path = "raw/day=20231101/"
    prepared_s3_prefix_path = "prepared/day=20231101/"
    local_dir = os.path.join(settings.prepared_dir, "day=20231101/")

    try:
        response = s3_client.list_objects_v2(Bucket=s3_bucket, Prefix=s3_prefix_path)
        
        if 'Contents' not in response:
            print(f"No files found in S3 prefix: {s3_prefix_path}")
            return "No raw data found."
        
        all_files = [obj['Key'] for obj in response['Contents'] if obj['Key'] != s3_prefix_path]
        for s3_file in tqdm(all_files, desc="Downloading files", unit="file"):
            local_file_path = os.path.join(local_dir, os.path.relpath(s3_file, s3_prefix_path))
            os.makedirs(os.path.dirname(local_file_path), exist_ok=True)
            try:
                s3_client.download_file(s3_bucket, s3_file, local_file_path)
            except Exception as e:
                return f"Failed to download {s3_file}: {e}"
    
    except Exception as e:
        return f"Error accessing the S3 bucket: {e}"
    
    prepared_folder = os.path.join(settings.prepared_dir, "day=20231101")

    if not os.path.exists(prepared_folder) or not os.listdir(prepared_folder):
        logging.error(f"No raw data found in {prepared_folder}")
        return "No raw data found."

    for file in os.listdir(prepared_folder):
        if file.endswith(".json"):
            file_path = os.path.join(prepared_folder, file)
            try:
                with open(file_path) as f:
                    file_data = json.load(f)
                
                aircraft_data = [
                    {"icao": aircraft.get("hex"), "registration": aircraft.get("r"), "type": aircraft.get("t"), "latitude": aircraft.get("lat"), "longitude": aircraft.get("lon"), "alt_baro": aircraft.get("alt_baro", None), "gs": aircraft.get("gs", None), "emergency": aircraft.get("emergency", False), "timestamp": file_data.get("now")}
                    for aircraft in file_data.get("aircraft", [])
                    if aircraft.get("hex") and aircraft.get("lat") and aircraft.get("lon")
                ]

                if not aircraft_data:
                    logging.warning(f"No aircraft data found in {file}")
                    continue

                df = pd.DataFrame(aircraft_data)
                df.dropna(subset=["icao", "latitude", "longitude", "timestamp"], inplace=True)

                output_csv = os.path.join(prepared_folder, f"{os.path.splitext(file)[0]}.csv")
                df.to_csv(output_csv, index=False)

                s3_client.upload_file(output_csv, s3_bucket, os.path.join(prepared_s3_prefix_path, os.path.basename(output_csv)))
            except Exception as e:
                return f"Failed to process file {file}: {e}"
    return "OK"
