"""Prompt → print-ready PNG.

Real provider: Recraft (https://external.api.recraft.ai/v1/images/generations).
Recraft's transparent-background vector-illustration style is a good fit for POD.

Because Recraft's max output dimension is 4096px but print needs >= LONG_EDGE_MIN
(4500px), we generate a transparent square and LANCZOS-upscale it locally to the
threshold. Vector-style art upscales cleanly, so this is lossless enough for print.
(Recraft also exposes /v1/images/crispUpscale — noted as an optional enhancement.)

What exists:
  - `generate_design(prompt, out_path, cfg)` — STABLE signature the pipeline and
    mock mode depend on. Do not change it.
  - MOCK path: deterministic transparent PNG, fully offline.
  - `_real_provider`: Recraft call with timeout + retry/backoff, alpha enforced,
    upscaled and validated.
  - `validate_png()` — print-readiness gate: alpha channel + long edge >= LONG_EDGE_MIN.

Independently runnable:
    python -m pod_autopilot.design --prompt "whimsical mushroom" --out out.png
"""

from __future__ import annotations

import hashlib
import io
import time
from dataclasses import dataclass
from pathlib import Path

from . import config

LONG_EDGE_MIN = 4500  # px; ~300 DPI across a 15" full-front print

RECRAFT_URL = "https://external.api.recraft.ai/v1/images/generations"
_HTTP_TIMEOUT = (10, 120)   # (connect, read) seconds — generation can be slow
_MAX_RETRIES = 4
_BACKOFF_BASE = 1.5         # seconds; exponential


class DesignError(RuntimeError):
    """Raised when a design can't be produced or fails validation."""


@dataclass(frozen=True)
class Design:
    prompt: str
    path: Path
    width: int
    height: int
    has_alpha: bool

    @property
    def long_edge(self) -> int:
        return max(self.width, self.height)


def validate_png(path: str | Path) -> Design:
    """Open a PNG and assert print-readiness: alpha channel + long edge threshold.

    Raises DesignError if the file is missing a channel or is too small. The real
    provider implementation must produce output that passes this.
    """
    from PIL import Image  # lazy import

    path = Path(path)
    if not path.exists():
        raise DesignError(f"design file not found: {path}")

    with Image.open(path) as img:
        img.load()
        width, height = img.size
        has_alpha = img.mode in ("RGBA", "LA") or "transparency" in img.info

    if not has_alpha:
        raise DesignError(f"design has no alpha channel (mode check failed): {path}")
    long_edge = max(width, height)
    if long_edge < LONG_EDGE_MIN:
        raise DesignError(
            f"design long edge {long_edge}px < required {LONG_EDGE_MIN}px: {path}"
        )
    return Design(prompt="", path=path, width=width, height=height, has_alpha=has_alpha)


def _mock_png(prompt: str, out_path: Path, size: int = LONG_EDGE_MIN) -> Design:
    """Deterministic solid-color transparent PNG derived from the prompt hash.

    Fully offline. Produces a valid, validatable print-ready file so the whole
    pipeline can run without any image provider.
    """
    from PIL import Image, ImageDraw  # lazy import

    digest = hashlib.sha256(prompt.encode("utf-8")).digest()
    color = (digest[0], digest[1], digest[2], 255)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))  # transparent canvas
    draw = ImageDraw.Draw(img)
    # A centered filled circle so there's real opaque + transparent area.
    margin = size // 8
    draw.ellipse([margin, margin, size - margin, size - margin], fill=color)
    img.save(out_path, format="PNG")

    return Design(prompt=prompt, path=out_path, width=size, height=size, has_alpha=True)


def _transparent_prompt(prompt: str) -> str:
    """Nudge Recraft toward an alpha background (V3+ honors this in the prompt)."""
    low = prompt.lower()
    if "transparent background" in low or "transparent bg" in low:
        return prompt
    return f"{prompt.rstrip('. ')}, on a transparent background, no background"


def _recraft_request(prompt: str, cfg: config.Config) -> bytes:
    """Call Recraft, retry on 429/5xx with backoff, return raw PNG bytes.

    Two hops: POST for a generation, then GET the returned image URL. Both share
    the timeout + retry policy. Raises DesignError on unrecoverable failure.
    """
    import requests  # lazy import

    if not cfg.image_api_key:
        raise DesignError("IMAGE_API_KEY is empty — cannot call Recraft (or use MOCK=1)")

    headers = {"Authorization": f"Bearer {cfg.image_api_key}"}
    payload = {
        "prompt": _transparent_prompt(prompt),
        "model": cfg.recraft_model,
        "style": cfg.recraft_style,
        "size": cfg.recraft_size,
        "response_format": "url",
    }

    data = _post_with_retry(requests, RECRAFT_URL, headers, payload)
    try:
        image_url = data["data"][0]["url"]
    except (KeyError, IndexError, TypeError) as exc:
        raise DesignError(f"unexpected Recraft response shape: {data!r}") from exc

    return _get_bytes_with_retry(requests, image_url, headers)


def _post_with_retry(requests, url: str, headers: dict, payload: dict) -> dict:
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=_HTTP_TIMEOUT)
        except requests.RequestException as exc:  # network error — retry
            last_exc = exc
            _sleep_backoff(attempt)
            continue
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 429 or resp.status_code >= 500:
            _sleep_backoff(attempt, retry_after=resp.headers.get("Retry-After"))
            last_exc = DesignError(f"Recraft {resp.status_code}: {resp.text[:500]}")
            continue
        # 4xx other than 429 won't fix itself — fail fast with the body.
        raise DesignError(f"Recraft {resp.status_code}: {resp.text[:500]}")
    raise DesignError(f"Recraft generation failed after {_MAX_RETRIES} attempts: {last_exc}")


def _get_bytes_with_retry(requests, url: str, headers: dict) -> bytes:
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            resp = requests.get(url, headers=headers, timeout=_HTTP_TIMEOUT)
        except requests.RequestException as exc:
            last_exc = exc
            _sleep_backoff(attempt)
            continue
        if resp.status_code == 200:
            return resp.content
        if resp.status_code == 429 or resp.status_code >= 500:
            _sleep_backoff(attempt, retry_after=resp.headers.get("Retry-After"))
            last_exc = DesignError(f"image download {resp.status_code}")
            continue
        raise DesignError(f"image download {resp.status_code}: {url}")
    raise DesignError(f"image download failed after {_MAX_RETRIES} attempts: {last_exc}")


def _sleep_backoff(attempt: int, retry_after: str | None = None) -> None:
    if retry_after:
        try:
            time.sleep(min(float(retry_after), 60.0))
            return
        except (TypeError, ValueError):
            pass
    time.sleep(_BACKOFF_BASE ** attempt)


def _finalize_png(raw: bytes, out_path: Path, prompt: str) -> Design:
    """Ensure alpha + upscale to >= LONG_EDGE_MIN, save, and return a Design.

    Pure image processing (no network) so it's unit-testable with a fixture.
    """
    from PIL import Image  # lazy import

    img = Image.open(io.BytesIO(raw))
    img.load()
    if img.mode != "RGBA":
        # PNG without alpha (or palette-with-transparency) -> promote to RGBA so
        # downstream validation and printing have a real alpha channel.
        img = img.convert("RGBA")

    long_edge = max(img.size)
    if long_edge < LONG_EDGE_MIN:
        scale = LONG_EDGE_MIN / long_edge
        new_size = (round(img.width * scale), round(img.height * scale))
        img = img.resize(new_size, Image.LANCZOS)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, format="PNG")
    return Design(prompt=prompt, path=out_path, width=img.width, height=img.height, has_alpha=True)


def _real_provider(prompt: str, out_path: Path, cfg: config.Config) -> Design:
    """Generate a print-ready transparent PNG via the configured provider."""
    if cfg.image_provider != "recraft":
        raise DesignError(
            f"unsupported IMAGE_PROVIDER={cfg.image_provider!r}; only 'recraft' is "
            "implemented (or set MOCK=1 for offline development)."
        )
    raw = _recraft_request(prompt, cfg)
    return _finalize_png(raw, out_path, prompt)


def generate_design(
    prompt: str,
    out_path: str | Path,
    cfg: config.Config | None = None,
) -> Design:
    """Produce a print-ready transparent PNG for `prompt` at `out_path`.

    STABLE SIGNATURE — do not change. MOCK mode yields a deterministic local PNG;
    otherwise delegates to the real provider (Recraft).
    """
    cfg = cfg or config.load()
    out_path = Path(out_path)
    if cfg.mock:
        design = _mock_png(prompt, out_path)
    else:
        design = _real_provider(prompt, out_path, cfg)
    # Always validate before handing back, mock or real.
    validate_png(design.path)
    return design


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Generate a print-ready PNG for a prompt.")
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    d = generate_design(args.prompt, args.out)
    print(f"wrote {d.path} ({d.width}x{d.height}, alpha={d.has_alpha})")
