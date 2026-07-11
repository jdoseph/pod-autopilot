"""Env/config loader.

Single source of truth for configuration. NEVER hardcode secrets elsewhere —
read them from here. Loads a .env file if present (a tiny parser, so we don't
depend on python-dotenv), then overlays real environment variables.

Independently runnable:  python -m pod_autopilot.config   (prints resolved config,
secrets masked).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from pathlib import Path

# Project root = parent of this package directory.
ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader. Does not override already-set env vars."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(ROOT / ".env")


def _bool(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


def _int(name: str):
    val = os.environ.get(name, "").strip()
    if not val:
        return None
    try:
        return int(val)
    except ValueError:
        return None


@dataclass(frozen=True)
class Config:
    # Anthropic / ideation
    anthropic_api_key: str = ""
    ideation_model: str = "claude-sonnet-5"

    # Printify
    printify_api_token: str = ""
    printify_shop_id: str = ""
    printify_blueprint_id: int | None = None
    printify_print_provider_id: int | None = None

    # Image generation (design.py stub)
    image_provider: str = ""
    image_api_key: str = ""

    # Trend proxy
    trend_source: str = "google"       # "google" | "csv"
    trend_csv_path: str = ""

    # Behaviour
    mock: bool = False
    output_dir: Path = field(default_factory=lambda: ROOT / "output")
    min_margin: float = 0.35
    retail_price: float = 24.99

    _SECRET_FIELDS = ("anthropic_api_key", "printify_api_token", "image_api_key")

    @classmethod
    def load(cls) -> "Config":
        out_dir = os.environ.get("OUTPUT_DIR", "").strip() or "output"
        out_path = Path(out_dir)
        if not out_path.is_absolute():
            out_path = ROOT / out_path
        return cls(
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", "").strip(),
            ideation_model=os.environ.get("IDEATION_MODEL", "").strip() or "claude-sonnet-5",
            printify_api_token=os.environ.get("PRINTIFY_API_TOKEN", "").strip(),
            printify_shop_id=os.environ.get("PRINTIFY_SHOP_ID", "").strip(),
            printify_blueprint_id=_int("PRINTIFY_BLUEPRINT_ID"),
            printify_print_provider_id=_int("PRINTIFY_PRINT_PROVIDER_ID"),
            image_provider=os.environ.get("IMAGE_PROVIDER", "").strip(),
            image_api_key=os.environ.get("IMAGE_API_KEY", "").strip(),
            trend_source=(os.environ.get("TREND_SOURCE", "").strip() or "google").lower(),
            trend_csv_path=os.environ.get("TREND_CSV_PATH", "").strip(),
            mock=_bool("MOCK", False),
            output_dir=out_path,
            min_margin=_float("MIN_MARGIN", 0.35),
            retail_price=_float("RETAIL_PRICE", 24.99),
        )

    def masked(self) -> dict:
        """Config as a dict with secrets masked, for logging/inspection."""
        out = {}
        for f in fields(self):
            val = getattr(self, f.name)
            if f.name in self._SECRET_FIELDS and val:
                val = val[:4] + "…(masked)"
            out[f.name] = str(val)
        return out


def load() -> Config:
    return Config.load()


if __name__ == "__main__":
    import json

    print(json.dumps(load().masked(), indent=2))
