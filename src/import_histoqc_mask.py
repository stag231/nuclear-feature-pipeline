"""Make HistoQC's usable-region mask explicit in level-0 WSI coordinates."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image


def mask_coordinate_mapping(
    mask_size: tuple[int, int],
    proxy_size: tuple[int, int],
    metadata: dict,
) -> tuple[float, float, tuple[float, float]]:
    """Validate proxy/mask sizes and return their level-0 coordinate scale."""
    claimed_proxy_size = metadata["proxy_dimensions_px"]
    for size in (mask_size, proxy_size, claimed_proxy_size):
        if len(size) != 2 or any(not isinstance(value, int) or value <= 0 for value in size):
            raise ValueError("Mask and proxy dimensions must contain two positive integers")
    if tuple(claimed_proxy_size) != tuple(proxy_size):
        raise ValueError("The proxy image dimensions do not match proxy_metadata.json")
    scale_x = proxy_size[0] / mask_size[0]
    scale_y = proxy_size[1] / mask_size[1]
    if not np.isclose(scale_x, scale_y, rtol=1e-3):
        raise ValueError("HistoQC mask has different x and y scaling relative to the proxy")
    downsample = float(metadata["proxy_downsample_from_level0"])
    source_mpp = tuple(float(value) for value in metadata["source_mpp_um_per_px"])
    if len(source_mpp) != 2 or any(
        not math.isfinite(value) or value <= 0 for value in (downsample, *source_mpp)
    ):
        raise ValueError("Source MPP and proxy downsample must be finite and positive")
    level0_downsample = downsample * scale_x
    if not math.isfinite(level0_downsample):
        raise ValueError("The combined mask downsample must be finite")
    return scale_x, level0_downsample, source_mpp


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert a HistoQC *_mask_use.png into a coordinate-aware NPZ mask.")
    parser.add_argument("histoqc_mask", type=Path)
    parser.add_argument("--proxy-metadata", type=Path, required=True)
    parser.add_argument("--proxy-image", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()

    mask_path = args.histoqc_mask.expanduser().resolve()
    metadata_path = args.proxy_metadata.expanduser().resolve()
    proxy_path = args.proxy_image.expanduser().resolve()
    for path, description in ((mask_path, "HistoQC mask"), (metadata_path, "proxy metadata"), (proxy_path, "proxy image")):
        if not path.is_file():
            raise FileNotFoundError(f"{description} not found: {path}")
    output_dir = (args.output_dir or mask_path.parents[2]).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    mask_image = Image.open(mask_path).convert("L")
    proxy_image = Image.open(proxy_path).convert("RGB")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    mask_width, mask_height = mask_image.size
    scale_x, level0_downsample, (source_mpp_x, source_mpp_y) = mask_coordinate_mapping(
        mask_image.size, proxy_image.size, metadata
    )
    mask = np.asarray(mask_image) > 0
    report = {
        "source_slide": metadata["source_slide"],
        "mask_type": "histoqc_first_pass_usable_region",
        "mask_source_file": mask_path.name,
        "mask_dimensions_px": [mask_width, mask_height],
        "mask_downsample_from_proxy": scale_x,
        "mask_downsample_from_level0": level0_downsample,
        "mask_mpp_um_per_px": [source_mpp_x * level0_downsample, source_mpp_y * level0_downsample],
        "level0_coordinate_mapping": "level0_px = mask_px * mask_downsample_from_level0",
        "usable_fraction_of_mask_image": float(mask.mean()),
        "important_limit": "This first-pass HistoQC mask excludes technical artefacts but does not label tumour.",
    }
    np.savez_compressed(output_dir / "histoqc_usable_mask.npz", mask=mask)
    (output_dir / "histoqc_usable_mask_metadata.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if proxy_image.size != mask_image.size:
        proxy_image = proxy_image.resize(mask_image.size, Image.Resampling.LANCZOS)
    overlay = np.asarray(proxy_image).astype(np.float32)
    overlay[mask] = 0.55 * overlay[mask] + 0.45 * np.array([0, 210, 70])
    overlay_path = output_dir / "histoqc_usable_mask_overlay.png"
    Image.fromarray(overlay.astype(np.uint8)).save(overlay_path)
    print(f"Usable fraction: {report['usable_fraction_of_mask_image']:.2%}")
    print(f"Mask NPZ: {output_dir / 'histoqc_usable_mask.npz'}")
    print(f"Mask metadata: {output_dir / 'histoqc_usable_mask_metadata.json'}")
    print(f"Overlay: {overlay_path}")


if __name__ == "__main__":
    main()
