import json
import os
from typing import Annotated
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup
from fastapi import APIRouter, status
from fastapi.params import Query
from tqdm import tqdm

from bdi_api.settings import Settings

settings = Settings()

s1 = APIRouter(
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Not found"},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"description": "Something is wrong with the request"},
    },
    prefix="/api/s1",
    tags=["s1"],
)


@s1.post("/aircraft/download")
def download_data(
    file_limit: Annotated[
        int,
        Query(
            ...,
            description="""
    Limits the number of files to download.
    You must always start from the first the page returns and
    go in ascending order in order to correctly obtain the results.
    I'll test with increasing number of files starting from 100.""",
        ),
    ] = 100,
) -> str:
    """Downloads the `file_limit` files AS IS inside the folder data/20231101

    data: https://samples.adsbexchange.com/readsb-hist/2023/11/01/
    documentation: https://www.adsbexchange.com/version-2-api-wip/
        See "Trace File Fields" section

    Think about the way you organize the information inside the folder
    and the level of preprocessing you might need.

    To manipulate the data use any library you feel comfortable with.
    Just make sure to configure it in the `pyproject.toml` file
    so it can be installed using `poetry update`.


    TIP: always clean the download folder before writing again to avoid having old files.
    """
    download_dir = os.path.join(settings.raw_dir, "day=20231101")
    base_url = settings.source_url + "/2023/11/01/"

    os.makedirs(download_dir, exist_ok=True)
    for old_file in os.listdir(download_dir):
        os.remove(os.path.join(download_dir, old_file))

    try:
        response = requests.get(base_url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        files_to_download = [
            link["href"] for link in soup.find_all("a") if link["href"].endswith(".json.gz")
        ][:file_limit]

        files_downloaded = 0
        for file_name in tqdm(files_to_download, desc="Downloading Files"):
            full_url = urljoin(base_url, file_name)
            file_response = requests.get(full_url, stream=True)

            if file_response.status_code == 200:
                output_file = os.path.join(download_dir, file_name[:-3])  # Remove `.gz`
                with open(output_file, "wb") as f:
                    f.write(file_response.content)
                files_downloaded += 1
            else:
                print(f"Failed to download: {file_name}")

        return f"Successfully downloaded {files_downloaded} files to {download_dir}"

    except requests.RequestException as e:
        return f"Error downloading files: {str(e)}"
    except Exception as e:
        return f"Unexpected error: {str(e)}"


@s1.post("/aircraft/prepare")
def prepare_data() -> str:
    """Prepare the data in the way you think it's better for the analysis.

    * data: https://samples.adsbexchange.com/readsb-hist/2023/11/01/
    * documentation: https://www.adsbexchange.com/version-2-api-wip/
        See "Trace File Fields" section

    Think about the way you organize the information inside the folder
    and the level of preprocessing you might need.

    To manipulate the data use any library you feel comfortable with.
    Just make sure to configure it in the `pyproject.toml` file
    so it can be installed using `poetry update`.

    TIP: always clean the prepared folder before writing again to avoid having old files.

    Keep in mind that we are downloading a lot of small files, and some libraries might not work well with this!
    """

    raw_dir = os.path.join(settings.raw_dir, "day=20231101")
    prepared_dir = os.path.join(settings.prepared_dir, "day=20231101")
    os.makedirs(prepared_dir, exist_ok=True)

    for old_file in os.listdir(prepared_dir):
        os.remove(os.path.join(prepared_dir, old_file))

    try:
        data_frames = []

        for raw_file in os.listdir(raw_dir):
            if raw_file.endswith(".json"):
                with open(os.path.join(raw_dir, raw_file)) as f:
                    json_data = json.load(f)
                    if "aircraft" in json_data:
                        df = pd.DataFrame(json_data["aircraft"])
                        df["timestamp"] = json_data["now"]
                        data_frames.append(df)

        combined_data = pd.concat(data_frames, ignore_index=True)
        combined_data = combined_data.rename(columns={
            "hex": "icao",
            "r": "registration",
            "t": "aircraft_type",
            "alt_baro": "altitude_baro",
            "gs": "ground_speed",
            "emergency": "emergency_status",
        })
        combined_data = combined_data.dropna(subset=["icao", "registration", "aircraft_type"])
        emergency_list = ["general", "lifeguard", "minfuel", "nordo", "unlawful", "downed", "reserved"]
        combined_data["emergency_status"] = combined_data["emergency_status"].apply(lambda x: x in emergency_list)

        combined_data.to_csv(os.path.join(prepared_dir, "processed_data.csv"), index=False)
        return f"Data preparation complete. File saved at {prepared_dir}"

    except Exception as error:
        return f"Error during data preparation: {str(error)}"


@s1.get("/aircraft/")
def list_aircraft(num_results: int = 100, page: int = 0) -> list[dict]:
    """List all the available aircraft, its registration and type ordered by
    icao asc
    """
    data_file = os.path.join(settings.prepared_dir, "day=20231101", "processed_data.csv")

    if not os.path.exists(data_file):
        return []

    df = pd.read_csv(data_file)
    df = df[["icao", "registration", "aircraft_type"]].drop_duplicates().sort_values(by="icao")
    df = df.rename(columns={"aircraft_type": "type"})  # Added this line to fix the test

    start_idx, end_idx = page * num_results, (page + 1) * num_results
    return df.iloc[start_idx:end_idx].to_dict(orient="records")


@s1.get("/aircraft/{icao}/positions")
def get_aircraft_position(icao: str, num_results: int = 1000, page: int = 0) -> list[dict]:
    """Returns all the known positions of an aircraft ordered by time (asc)
    If an aircraft is not found, return an empty list.
    """
    data_file = os.path.join(settings.prepared_dir, "day=20231101", "processed_data.csv")

    if not os.path.exists(data_file):
        return []

    df = pd.read_csv(data_file)
    df = df[df["icao"] == icao].sort_values(by="timestamp")

    start_idx, end_idx = page * num_results, (page + 1) * num_results
    return df.iloc[start_idx:end_idx][["timestamp", "lat", "lon"]].to_dict(orient="records")


@s1.get("/aircraft/{icao}/stats")
def get_aircraft_statistics(icao: str) -> dict:
    """Returns different statistics about the aircraft

    * max_altitude_baro
    * max_ground_speed
    * had_emergency
    """

    data_file = os.path.join(settings.prepared_dir, "day=20231101", "processed_data.csv")

    if not os.path.exists(data_file):
        return {}

    df = pd.read_csv(data_file)
    df = df[df["icao"] == icao]

    if df.empty:
        return {}

    def convert_altitude(altitude):
        if altitude == 'ground':
            return 0.0
        return float(altitude)

    return {
        "max_altitude_baro": float(df["altitude_baro"].apply(convert_altitude).max()),
        "max_ground_speed": float(df["ground_speed"].max()),
        "had_emergency": bool(df["emergency_status"].any()),
    }