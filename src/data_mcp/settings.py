from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://lms:lms_dev@localhost:5432/lms_db"
    db_pool_min: int = 2
    db_pool_max: int = 10

    model_config = {"env_prefix": "LMS_"}


settings = Settings()
