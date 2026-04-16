"""Application configuration."""

from __future__ import annotations

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PPO_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    grid_capacity_mw: float = 20.0
    power_block_mw: float = 16.0

    bess_capacity_mwh: float = 20.0
    bess_power_mw: float = 5.0
    bess_round_trip_efficiency: float = 0.90
    bess_min_soc: float = 0.10
    bess_max_soc: float = 0.95

    forecast_horizon_hours: int = 72
    forecast_refresh_minutes: int = 15

    shed_response_minutes: int = 15
    shed_safety_margin_mw: float = 1.5
    cruise_ais_detection_hours: float = 2.0

    capacity_fee_dkk_mw_month: float = 35_000
    truck_bay_lease_dkk_month: float = 12_000
    bess_land_lease_dkk_year: float = 600_000
    ppo_license_dkk_year: float = 480_000

    database_url: str = "sqlite:///ppo.db"

    api_host: str = "127.0.0.1"
    api_port: int = 8000
    debug: bool = False


settings = Settings()