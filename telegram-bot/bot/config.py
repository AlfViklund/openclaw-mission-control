"""Telegram bot configuration."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class BotSettings(BaseSettings):
    """Configuration for the Telegram bot."""

    telegram_bot_token: str = Field(..., alias="TELEGRAM_BOT_TOKEN")
    allowed_user_ids: str = Field(default="", alias="TELEGRAM_ALLOWED_USER_IDS")
    api_base_url: str = Field(default="http://backend:8000", alias="API_BASE_URL")
    api_token: str = Field(default="", alias="API_TOKEN")

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def allowed_ids(self) -> set[int]:
        if not self.allowed_user_ids.strip():
            return set()
        return {
            int(x.strip())
            for x in self.allowed_user_ids.split(",")
            if x.strip().isdigit()
        }

    @property
    def api_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        return headers


settings = BotSettings()
