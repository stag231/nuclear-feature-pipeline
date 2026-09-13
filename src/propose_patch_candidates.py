"""List well-inside-tissue technical candidate centres from a QC mask.

Candidates are selected only by distance from the usable-region boundary.
They are not tumour classifications and must be checked by a pathologist.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import distance_transform_edt, minimum_filter


def propose_candidates(
    mask: np.ndarray,
    *,
    size: int,
    target_mpp: float,
    count: int,
    downsample: float,
    mask_mpp: tuple[float, float],
) -> list[dict[str, float | int]]:
    """Rank centres by tissue margin, retaining complete square footprints.

    A distance-transform threshold alone only fits an inscribed circle, not
    the patch corners. The minimum filter checks a conservative pixel-rounded
    square, treating everything beyond the mask image as unusable.
    """
    if mask.ndim != 2 or 0 in mask.shape:
        raise ValueError("The mask must be a non-empty two-dimensional array")
    if not isinstance(size, int) or size <= 0 or not isinstance(count, int) or count <= 0:
        raise ValueError("--size and --count must be positive integers")
    if any(not math.isfinite(value) or value <= 0 for value in (target_mpp, downsample, *mask_mpp)):
        raise ValueError("Target MPP, mask MPP, and downsample must be finite and positive")
    mask_mpp_x, mask_mpp_y = mask_mpp
    if not np.isclose(mask_mpp_x, mask_mpp_y):
        raise ValueError("Technical candidates require square mask pixels")
    mask = mask.astype(bool)
    half_width_mask_px = size * target_mpp / (2 * mask_mpp_x)
    if not math.isfinite(half_width_mask_px):
        raise ValueError("The requested patch footprint is too large")
    radius = int(math.ceil(half_width_mask_px))
    if 2 * radius + 1 > min(mask.shape):
        return []
    complete_square = minimum_filter(
        mask, size=2 * radius + 1, mode="constant", cval=0
    ).astype(bool)
    # Explicit outside zeros are essential for all-tissue masks and borders.
    working = distance_transform_edt(np.pad(mask, 1, constant_values=False))[1:-1, 1:-1]
    working[~complete_square] = 0
    yy, xx = np.ogrid[: mask.shape[0], : mask.shape[1]]
    candidates: list[dict[str, float | int]] = []
    for rank in range(1, count + 1):
        y, x = np.unravel_index(np.argmax(working), working.shape)
        margin = float(working[y, x])
        if margin <= 0:
            break
        candidates.append(
            {
                "rank": rank,
                "mask_center_x_px": int(x),
                "mask_center_y_px": int(y),
                "level0_center_x_px": int(round(x * downsample)),
                "level0_center_y_px": int(round(y * downsample)),
                "tissue_margin_mask_px": round(margin, 2),
                "patch_size_px": size,
                "target_mpp_um_per_px": target_mpp,
            }
        )
        working[(xx - x) ** 2 + (yy - y) ** 2 <= (half_width_mask_px * 2) ** 2] = 0
    return candidates


def main() -> None:
    parser = argparse.ArgumentParser(description="Propose technical ROI candidates from a coordinate-aware tissue mask.")
    parser.add_argument("mask_npz", type=Path)
    parser.add_argument("--proxy-image", type=Path, required=True)
    parser.add_argument("--mask-metadata", type=Path, required=True)
    parser.add_argument("--size", type=int, default=512)
    parser.add_argument("--target-mpp", type=float, default=0.25)
    parser.add_argument("--count", type=int, default=9)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()
    if args.size <= 0 or not math.isfinite(args.target_mpp) or args.target_mpp <= 0 or args.count <= 0:
        raise ValueError("--size and --count must be positive; --target-mpp must be finite and positive")

    mask_path = args.mask_npz.expanduser().resolve()
    proxy_path = args.proxy_image.expanduser().resolve()
    metadata_path = args.mask_metadata.expanduser().resolve()
    for path, description in ((mask_path, "mask"), (proxy_path, "proxy image"), (metadata_path, "mask metadata")):
        if not path.is_file():
            raise FileNotFoundError(f"{description} not found: {path}")
    output_dir = (args.output_dir or mask_path.parent).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    with np.load(mask_path, allow_pickle=False) as mask_archive:
        mask = mask_archive["mask"].astype(bool)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    downsample = float(metadata["mask_downsample_from_level0"])
    mask_mpp_x, mask_mpp_y = (float(value) for value in metadata["mask_mpp_um_per_px"])
    if mask.ndim != 2 or list(mask.shape[::-1]) != metadata["mask_dimensions_px"]:
        raise ValueError("Mask dimensions do not match the supplied mask metadata")
    candidates = propose_candidates(
        mask,
        size=args.size,
        target_mpp=args.target_mpp,
        count=args.count,
        downsample=downsample,
        mask_mpp=(mask_mpp_x, mask_mpp_y),
    )
    half_width_mask_px = args.size * args.target_mpp / (2 * mask_mpp_x)

    fields = [
        "rank",
        "mask_center_x_px",
        "mask_center_y_px",
        "level0_center_x_px",
        "level0_center_y_px",
        "tissue_margin_mask_px",
        "patch_size_px",
        "target_mpp_um_per_px",
    ]
    csv_path = output_dir / "technical_patch_candidates.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(candidates)

    image = Image.open(proxy_path).convert("RGB")
    if image.size != (mask.shape[1], mask.shape[0]):
        image = image.resize((mask.shape[1], mask.shape[0]), Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(image)
    for candidate in candidates:
        x = int(candidate["mask_center_x_px"])
        y = int(candidate["mask_center_y_px"])
        radius = int(round(half_width_mask_px))
        draw.rectangle((x - radius, y - radius, x + radius, y + radius), outline="red", width=4)
        draw.text((x + radius + 6, y - radius), str(candidate["rank"]), fill="red", stroke_width=1)
    overlay_path = output_dir / "technical_patch_candidates_overlay.png"
    image.save(overlay_path)
    print(f"Candidates: {len(candidates)}")
    print(f"CSV: {csv_path}")
    print(f"Overlay: {overlay_path}")
    if candidates:
        first = candidates[0]
        print(
            "First technical candidate (not a tumour label): "
            f"--center-x {first['level0_center_x_px']} --center-y {first['level0_center_y_px']}"
        )
    else:
        print("No full-tissue candidate fit the requested patch field of view.")


if __name__ == "__main__":
    main()
