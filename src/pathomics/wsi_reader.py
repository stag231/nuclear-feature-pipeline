"""OpenSlide-only reader and physically calibrated patch helper.

This rebuilt project begins with OpenSlide-compatible TIFF/SVS inputs.  It
deliberately does not guess a physical scale: an embedded MPP or an explicit
``--mpp`` override is required before any patch is extracted.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path

import numpy as np
import openslide
from PIL import Image


MPP_KEYS = ("openslide.mpp-x", "aperio.MPP")
OBJECTIVE_POWER_KEYS = ("openslide.objective-power", "aperio.AppMag")
SUPPORTED_SUFFIXES = {".svs", ".tif", ".tiff"}


def _first_float(properties: dict[str, str], keys: tuple[str, ...]) -> float | None:
    """Return the first readable positive numeric metadata value."""

    for key in keys:
        value = properties.get(key)
        if value is None:
            continue
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(parsed) and parsed > 0:
            return parsed
    return None


@dataclass(frozen=True)
class PatchAtMPP:
    """A resampled RGB patch and the source footprint that produced it."""

    rgb: np.ndarray
    source_bounds_level0: tuple[int, int, int, int]
    source_size_px: tuple[int, int]


class OpenSlideWSI:
    """A thin context-managed wrapper around :class:`openslide.OpenSlide`."""

    def __init__(
        self,
        path: Path,
        slide: openslide.OpenSlide,
        mpp: tuple[float, float],
        objective_power: float | None,
    ) -> None:
        self.path = path
        self._slide = slide
        self.mpp = mpp
        self.objective_power = objective_power

    @property
    def reader_name(self) -> str:
        return "OpenSlide"

    @property
    def format(self) -> str:
        return str(self._slide.properties.get("openslide.vendor", "unknown"))

    @property
    def dimensions(self) -> tuple[int, int]:
        return tuple(int(value) for value in self._slide.dimensions)

    @property
    def level_count(self) -> int:
        return int(self._slide.level_count)

    @property
    def level_dimensions(self) -> list[tuple[int, int]]:
        return [tuple(int(value) for value in dimensions) for dimensions in self._slide.level_dimensions]

    @property
    def level_downsamples(self) -> list[float]:
        return [float(value) for value in self._slide.level_downsamples]

    @property
    def bounds(self) -> tuple[int, int, int, int]:
        properties = self._slide.properties
        width, height = self.dimensions
        return (
            int(float(properties.get("openslide.bounds-x", 0))),
            int(float(properties.get("openslide.bounds-y", 0))),
            int(float(properties.get("openslide.bounds-width", width))),
            int(float(properties.get("openslide.bounds-height", height))),
        )

    def read_level_rgb(self, level: int) -> np.ndarray:
        """Read one complete pyramid level as an RGB array."""

        if not 0 <= level < self.level_count:
            raise ValueError(f"level must be between 0 and {self.level_count - 1}")
        width, height = self.level_dimensions[level]
        image = self._slide.read_region((0, 0), level, (width, height))
        return np.asarray(_white_background_rgb(image))

    def read_patch_at_mpp(
        self,
        *,
        center_level0: tuple[int, int],
        output_size_px: int,
        target_mpp: float,
    ) -> PatchAtMPP:
        """Read one level-0 footprint and resample it to a stated output MPP."""

        if not isinstance(output_size_px, int) or output_size_px <= 0:
            raise ValueError("output_size_px must be a positive integer")
        if not math.isfinite(target_mpp) or target_mpp <= 0:
            raise ValueError("target_mpp must be finite and positive")
        if any(not math.isfinite(value) or value <= 0 for value in self.mpp):
            raise ValueError("Source MPP values must be finite and positive")
        source_width = max(1, int(round(output_size_px * target_mpp / self.mpp[0])))
        source_height = max(1, int(round(output_size_px * target_mpp / self.mpp[1])))
        center_x, center_y = center_level0
        x0 = int(round(center_x - source_width / 2))
        y0 = int(round(center_y - source_height / 2))
        width, height = self.dimensions
        if x0 < 0 or y0 < 0 or x0 + source_width > width or y0 + source_height > height:
            raise ValueError(
                "The requested patch footprint extends outside the WSI. "
                "Choose a centre with the full patch inside the level-0 image."
            )
        image = _white_background_rgb(
            self._slide.read_region((x0, y0), 0, (source_width, source_height))
        )
        resized = image.resize((output_size_px, output_size_px), Image.Resampling.LANCZOS)
        return PatchAtMPP(
            rgb=np.asarray(resized),
            source_bounds_level0=(x0, y0, x0 + source_width, y0 + source_height),
            source_size_px=(source_width, source_height),
        )

    def close(self) -> None:
        self._slide.close()

    def __enter__(self) -> "OpenSlideWSI":
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()


def _white_background_rgb(image: Image.Image) -> Image.Image:
    """Composite transparent OpenSlide pixels on white instead of black."""
    rgba = image.convert("RGBA")
    background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    return Image.alpha_composite(background, rgba).convert("RGB")


def open_wsi(path: Path, *, mpp_override: float | None = None) -> OpenSlideWSI:
    """Open an OpenSlide-compatible TIFF/SVS and determine its physical scale."""

    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"WSI file not found: {resolved}")
    if resolved.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError("This rebuilt project accepts .svs, .tif, and .tiff OpenSlide inputs only.")
    try:
        slide = openslide.OpenSlide(str(resolved))
    except openslide.OpenSlideError as error:
        raise RuntimeError(f"OpenSlide could not open {resolved.name}: {error}") from error

    properties = dict(slide.properties)
    mpp_x = _first_float(properties, MPP_KEYS)
    mpp_y = _first_float(properties, ("openslide.mpp-y", "aperio.MPP"))
    if mpp_override is not None:
        if not math.isfinite(mpp_override) or mpp_override <= 0:
            slide.close()
            raise ValueError("--mpp must be finite and positive")
        mpp_x = mpp_y = float(mpp_override)
    if mpp_x is None or mpp_y is None:
        slide.close()
        raise ValueError(
            "This WSI has no readable MPP metadata. Confirm the scanner value and rerun with --mpp <um_per_px>."
        )
    objective_power = _first_float(properties, OBJECTIVE_POWER_KEYS)
    return OpenSlideWSI(resolved, slide, (mpp_x, mpp_y), objective_power)
