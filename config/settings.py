from functools import lru_cache

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict, YamlConfigSettingsSource


class DatabaseSettings(BaseModel):
    url: str = Field(default="sqlite+aiosqlite:///./elasticops.db")


class AuthSettings(BaseModel):
    jwt_secret: str | None = None  # None → auto-generated + persisted (see backend.services.secrets)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440


class SecuritySettings(BaseModel):
    encryption_key: str | None = None  # Fernet key; None → auto-generated + persisted
    secrets_file: str = ".elasticops-secrets.json"


class LoggingSettings(BaseModel):
    level: str = "INFO"


class Settings(BaseSettings):
    environment: str = "local"
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)

    model_config = SettingsConfigDict(
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
        yaml_file=["env.yaml", "local.env.yaml"],
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,  # noqa: ARG003
        file_secret_settings: PydanticBaseSettingsSource,  # noqa: ARG003
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (init_settings, env_settings, YamlConfigSettingsSource(settings_cls))


@lru_cache
def get_settings() -> Settings:
    return Settings()
