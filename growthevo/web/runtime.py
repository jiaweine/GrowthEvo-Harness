from __future__ import annotations

from dataclasses import dataclass
import os
from urllib.parse import urlparse


_VALID_MODES = {"demo", "api", "production"}


def _csv(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(item.strip().rstrip("/") for item in value.split(",") if item.strip())


def _configured(*names: str) -> bool:
    return any(bool(os.getenv(name, "").strip()) for name in names)


def _safe_host(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return urlparse(value).hostname
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class RuntimeSettings:
    """Public-safe runtime configuration.

    Presence of credentials/configuration is deliberately distinct from an
    active adapter. This prevents a production process from claiming durable
    persistence merely because ``DATABASE_URL`` exists while product state is
    still served by the reference in-memory implementation.
    """

    mode: str
    environment: str
    cors_origins: tuple[str, ...]
    database_configured: bool
    object_store_configured: bool
    llm_configured: bool
    channel_configured: bool
    database_host: str | None
    persistence_backend: str

    @classmethod
    def from_env(cls) -> "RuntimeSettings":
        raw_mode = os.getenv("GROWTHEVO_MODE", "demo").strip().lower() or "demo"
        mode = raw_mode if raw_mode in _VALID_MODES else "demo"
        environment = os.getenv("GROWTHEVO_ENV", "local").strip().lower() or "local"
        database_url = os.getenv("GROWTHEVO_DATABASE_URL") or os.getenv("DATABASE_URL")
        cors_origins = _csv(os.getenv("GROWTHEVO_CORS_ORIGINS"))
        # No durable persistence adapter is wired into product_data/decisioning
        # yet. Keep this explicit rather than inferring activation from a URL.
        persistence_backend = "reference-memory"
        return cls(
            mode=mode,
            environment=environment,
            cors_origins=cors_origins,
            database_configured=bool(database_url),
            object_store_configured=_configured(
                "GROWTHEVO_OBJECT_STORE_URL",
                "S3_ENDPOINT_URL",
                "AWS_S3_BUCKET",
            ),
            llm_configured=_configured(
                "OPENAI_API_KEY",
                "ANTHROPIC_API_KEY",
                "GEMINI_API_KEY",
            ),
            channel_configured=_configured(
                "GROWTHEVO_CHANNEL_WEBHOOK_URL",
                "META_ACCESS_TOKEN",
                "GOOGLE_ADS_DEVELOPER_TOKEN",
            ),
            database_host=_safe_host(database_url),
            persistence_backend=persistence_backend,
        )

    @property
    def synthetic_data(self) -> bool:
        return self.mode == "demo"

    @property
    def production(self) -> bool:
        return self.mode == "production"

    @property
    def persistence_active(self) -> bool:
        # Future durable adapters should make activation an explicit runtime
        # capability after successful initialization/migration checks. The
        # current branch intentionally has no such adapter yet.
        return self.persistence_backend not in {"reference-memory", "none"}

    @property
    def ready(self) -> bool:
        # Demo/reference API mode is credential-free. Production fails closed
        # until an actual durable adapter is active, not merely configured.
        return not self.production or self.persistence_active

    def connector_states(self) -> list[dict[str, str]]:
        if self.persistence_active:
            persistence_state = "connected"
        elif self.database_configured:
            persistence_state = "configured_not_active"
        elif self.synthetic_data:
            persistence_state = "demo"
        else:
            persistence_state = "unconfigured"
        return [
            {
                "id": "persistence",
                "label": "Durable PostgreSQL",
                "state": persistence_state,
            },
            {
                "id": "object_store",
                "label": "Object Storage",
                "state": "configured_not_active" if self.object_store_configured else "unconfigured",
            },
            {
                "id": "llm",
                "label": "LLM Provider",
                "state": "configured_not_active" if self.llm_configured else "unconfigured",
            },
            {
                "id": "channels",
                "label": "Execution Channels",
                "state": "configured_not_active" if self.channel_configured else "unconfigured",
            },
        ]

    def public_payload(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "environment": self.environment,
            "data_mode": "synthetic" if self.synthetic_data else "reference-contract",
            "ready": self.ready,
            "side_effects_enabled": False,
            "execution_mode": "reference-only",
            "persistence": {
                "configured": self.database_configured,
                "active": self.persistence_active,
                "backend": self.persistence_backend,
                "host": self.database_host,
            },
            "connectors": self.connector_states(),
        }
