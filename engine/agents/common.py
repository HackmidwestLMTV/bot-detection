"""Explicit model configuration; credentials are never included in reports."""

import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]


class ConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class ModelSettings:
    provider: str
    model_id: str
    base_url: str = ""
    api_key: str = field(default="", repr=False)
    region: str = "us-east-1"
    min_interval_s: float = 3


def load_settings(environ=None, *, provider=None):
    if environ is None:
        load_dotenv(ROOT / ".env", override=False)
        environ = os.environ
    flag = environ.get("USE_BEDROCK", "0").strip().lower()
    if flag not in ("0", "1", "true", "false"):
        raise ConfigurationError("USE_BEDROCK must be 0 or 1")
    selected = provider or ("bedrock" if flag in ("1", "true") else "akamai")
    if selected not in ("akamai", "bedrock"):
        raise ConfigurationError("provider must be akamai or bedrock")
    try:
        interval = float(environ.get("MODEL_MIN_INTERVAL_S", "3"))
        if not math.isfinite(interval) or not 1 <= interval <= 30:
            raise ValueError()
    except (ValueError, TypeError) as exc:
        raise ConfigurationError("MODEL_MIN_INTERVAL_S must be between 1 and 30") from exc
    if selected == "bedrock":
        model_id = environ.get("BEDROCK_MODEL_ID", "").strip()
        if not model_id:
            raise ConfigurationError("missing BEDROCK_MODEL_ID; configure an available model for your AWS account")
        return ModelSettings(provider=selected, model_id=model_id,
                             region=environ.get("AWS_REGION", "us-east-1"), min_interval_s=interval)
    required = ("AKAMAI_BASE_URL", "AKAMAI_API_KEY", "MODEL_ID")
    missing = [key for key in required if not environ.get(key, "").strip()]
    if missing:
        raise ConfigurationError("missing " + ", ".join(missing) + "; configure the ignored repository-root .env")
    base_url = environ["AKAMAI_BASE_URL"].strip()
    try:
        url = urlsplit(base_url)
        valid = url.scheme == "https" and bool(url.hostname) and not (url.username or url.password or url.query or url.fragment)
    except ValueError:
        valid = False
    if not valid:
        raise ConfigurationError("AKAMAI_BASE_URL must be an HTTPS endpoint without embedded credentials or query parameters")
    return ModelSettings(provider=selected, model_id=environ["MODEL_ID"].strip(), base_url=base_url,
                         api_key=environ["AKAMAI_API_KEY"].strip(), min_interval_s=interval)


def make_model(settings=None, *, client=None, request_timeout=30.0):
    settings = settings or load_settings()
    if settings.provider == "bedrock":
        if client is not None:
            raise ValueError("custom client is only supported for the OpenAI-compatible provider")
        from botocore.config import Config
        from strands.models import BedrockModel

        return BedrockModel(model_id=settings.model_id, region_name=settings.region,
                            max_tokens=1500, streaming=False,
                            boto_client_config=Config(connect_timeout=10, read_timeout=request_timeout,
                                                      retries={"total_max_attempts": 1, "mode": "standard"}))
    from engine.agents.providers import AkamaiModel

    kwargs = {"client": client} if client is not None else {"client_args": {
        "base_url": settings.base_url, "api_key": settings.api_key, "timeout": request_timeout, "max_retries": 0,
    }}
    return AkamaiModel(**kwargs, model_id=settings.model_id, stream=False, params={"max_tokens": 1500})
