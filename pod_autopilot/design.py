"""Prompt → print-ready PNG.

STATUS: STUB. The real text-to-image provider call is NOT implemented (see
HANDOFF.md Prompt 2). What exists:
  - `generate_design(prompt, out_path, cfg)` — the stable signature the pipeline
    and mock mode depend on. Do not change it when implementing the real provider.
  - a MOCK path that writes a deterministic transparent-background PNG locally so
    the pipeline runs fully offline.
  - `validate_png()` — the print-readiness gate the real impl must satisfy:
    alpha channel present + long edge >= LONG_EDGE_MIN px (~300 DPI full-front).

Definition of done (from CLAUDE.md): real provider call, transparent-background
PNG, >=4500px long edge, validated, retry/backoff + timeout.

Independently runnable:
    python -m pod_autopilot.design --prompt "whimsical mushroom" --out out.png
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from . import config

LONG_EDGE_MIN = 4500  # px; ~300 DPI across a 15" full-front print


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


def _real_provider(prompt: str, out_path: Path, cfg: config.Config) -> Design:
    """NOT IMPLEMENTED. See HANDOFF.md Prompt 2.

    Implement here: call cfg.image_provider's text-to-image API with cfg.image_api_key,
    (retry/backoff + timeout), ensure a transparent background (remove bg if the
    provider doesn't return alpha), upscale/validate to >= LONG_EDGE_MIN, then return
    validate_png(out_path). Keep this behind generate_design() so callers are unaffected.
    """
    raise NotImplementedError(
        "design.py real provider is a stub — implement _real_provider (HANDOFF.md Prompt 2), "
        "or run with MOCK=1 for offline development."
    )


def generate_design(
    prompt: str,
    out_path: str | Path,
    cfg: config.Config | None = None,
) -> Design:
    """Produce a print-ready transparent PNG for `prompt` at `out_path`.

    STABLE SIGNATURE — do not change. MOCK mode yields a deterministic local PNG;
    otherwise delegates to the (currently stubbed) real provider.
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
