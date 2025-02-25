from os.path import dirname, join
from dotenv import load_dotenv
import os
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
import bdi_api

# Cargar el archivo .env
load_dotenv()

PROJECT_DIR = dirname(dirname(bdi_api.__file__))



class Settings(BaseSettings):
    source_url: str = Field(
        default="https://samples.adsbexchange.com/readsb-hist",
        description="Base URL to the website used to download the data.",
    )
    local_dir: str = Field(
        default=join(PROJECT_DIR, "data"),
        description="For any other value set env variable 'BDI_LOCAL_DIR'",
    )
    s3_bucket: str = Field(
        default=os.getenv("S3_BUCKET", "bdi-aircraft-marioalbz"),  # Usar valor de .env si existe
        description="Call the api like  S3_BUCKET=yourbucket poetry run uvicorn... ",
    )

    s3_key_id: str = Field(
        default=os.getenv("AWS_ACCESS_KEY_ID", "supersecretkey_id"),  # Valor por defecto para testing
        description="Call the api like  AWS_ACCESS_KEY_ID=yourkey poetry run uvicorn... ",
    )
    s3_access_key: str = Field(
        default=os.getenv("AWS_SECRET_ACCESS_KEY", "superaccesskey"),  # Valor por defecto para testing
        description="Call the api like  AWS_SECRET_ACCESS_KEY=yourkey poetry run uvicorn... ",
    )
    s3_session_token: str = Field(
        default=os.getenv("AWS_SESSION_TOKEN", "supersessiontoken"),  # Valor por defecto para testing
        description="Call the api like  AWS_SESSION_TOKEN=yours ",
    )
    s3_region: str = Field(
        default=os.getenv("AWS_REGION", "us-east-1"),  # Valor por defecto para testing
        description="Call the api like  AWS_REGION=yourregion poetry run uvicorn... ",
    )

    telemetry: bool = False
    telemetry_dsn: str = "http://project2_secret_token@uptrace:14317/2"

    model_config = SettingsConfigDict(env_prefix="bdi_")

    @property
    def raw_dir(self) -> str:
        """Store inside all the raw jsons"""
        return join(self.local_dir, "raw")

    @property
    def prepared_dir(self) -> str:
        return join(self.local_dir, "prepared")
