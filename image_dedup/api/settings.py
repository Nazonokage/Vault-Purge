import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="IMAGE_DEDUP_", env_file=".env", extra="ignore")
    database: Path = Path(".image_dedup/cache.sqlite3")
    dry_run: bool = True
    dest_folder: str = "_duplicates_backup"
    show_recommendation: bool = True
    workers: int = Field(default=min(4, os.cpu_count() or 1), ge=1, le=61)
    phash_threshold: int = Field(default=10, ge=0, le=20)
    blur_threshold: float = Field(default=100.0, ge=0)
    thumb_size: int = Field(default=320, ge=64, le=1024)
