from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal

class Settings(BaseSettings):
    app_name: str = "THO NHANH API"
    debug: bool = True
    cors_origins: list[str] = []
    database_url: str
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440
    auth_cookie_name: str = "access_token"
    auth_cookie_secure: bool = False
    auth_cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    auth_cookie_domain: str | None = None

    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()