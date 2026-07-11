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


def _int_list(name: str) -> tuple[int, ...]:
    """Parse a comma-separated list of ints from env, skipping bad entries."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return ()
    out = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except ValueError:
            continue
    return tuple(out)


def _str_list(name: str) -> tuple[str, ...]:
    """Parse a comma-separated list of strings from env (trimmed, non-empty)."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return ()
    return tuple(p.strip() for p in raw.split(",") if p.strip())


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
    printify_variant_ids: tuple[int, ...] = ()   # variants to publish (margin-checked)

    # Image generation (design.py)
    image_provider: str = ""       # "recraft" | "" (empty -> stub raises unless MOCK)
    image_api_key: str = ""
    recraft_model: str = "recraftv3"       # transparent-bg supported on v3+
    recraft_style: str = "vector_illustration"   # clean POD art
    recraft_size: str = "1024x1024"        # generation size (Recraft max dim 4096)

    # Trend proxy
    trend_source: str = "google"       # "google" | "csv"
    trend_csv_path: str = ""

    # Screening / USPTO (disabled unless a search URL is provided; see screening.py)
    uspto_search_url: str = ""
    uspto_api_key: str = ""

    # Behaviour
    mock: bool = False
    output_dir: Path = field(default_factory=lambda: ROOT / "output")
    min_margin: float = 0.35
    retail_price: float = 24.99

    # Scheduled runner
    seeds: tuple[str, ...] = ()          # niches to process each scheduled run
    per_run_cap: int = 3                 # max designs per seed per run
    auto_publish: bool = False           # scheduled runs must opt in explicitly

    _SECRET_FIELDS = ("anthropic_api_key", "printify_api_token", "image_api_key", "uspto_api_key")

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
            printify_variant_ids=_int_list("PRINTIFY_VARIANT_IDS"),
            image_provider=os.environ.get("IMAGE_PROVIDER", "").strip().lower(),
            image_api_key=os.environ.get("IMAGE_API_KEY", "").strip(),
            recraft_model=os.environ.get("RECRAFT_MODEL", "").strip() or "recraftv3",
            recraft_style=os.environ.get("RECRAFT_STYLE", "").strip() or "vector_illustration",
            recraft_size=os.environ.get("RECRAFT_SIZE", "").strip() or "1024x1024",
            trend_source=(os.environ.get("TREND_SOURCE", "").strip() or "google").lower(),
            trend_csv_path=os.environ.get("TREND_CSV_PATH", "").strip(),
            uspto_search_url=os.environ.get("USPTO_SEARCH_URL", "").strip(),
            uspto_api_key=os.environ.get("USPTO_API_KEY", "").strip(),
            mock=_bool("MOCK", False),
            output_dir=out_path,
            min_margin=_float("MIN_MARGIN", 0.35),
            retail_price=_float("RETAIL_PRICE", 24.99),
            seeds=_str_list("SEEDS"),
            per_run_cap=_int("PER_RUN_CAP") or 3,
            auto_publish=_bool("AUTO_PUBLISH", False),
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
