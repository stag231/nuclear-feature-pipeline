"""Create an initial stained-tissue mask from the QC proxy.

This mask is an early background-versus-stained-tissue check.  It is not a
HistoQC artefact mask and it never labels tumour.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image
from skimage.color import rgb2hsv
from skimage.filters import threshold_otsu
from skimage.morphology import binary_closing, disk, remove_small_holes, remove_small_objects


def create_mask(rgb: np.ndarray) -> tuple[np.ndarray, float]:
    hsv = rgb2hsv(rgb)
    saturation = hsv[..., 1]
    value = hsv[..., 2]
    saturation_threshold = max(0.035, min(0.08, float(threshold_otsu(saturation))))
    mask = (saturation >= saturation_threshold) & (value < 0.985)
    min_object_px = max(64, round(mask.size * 0.00002))
    mask = remove_small_objects(mask, min_size=min_object_px)
    mask = binary_closing(mask, footprint=disk(3))
    mask = remove_small_holes(mask, area_threshold=min_object_px)
    return mask, saturation_threshold


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an initial tissue-versus-background mask.")
    parser.add_argument("proxy_image", type=Path)
    parser.add_argument("--proxy-metadata", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()

    proxy_image = args.proxy_image.expanduser().resolve()
    metadata_path = args.proxy_metadata.expanduser().resolve()
    if not proxy_image.is_file() or not metadata_path.is_file():
        raise FileNotFoundError("The QC proxy image and proxy_metadata.json must both exist.")
    output_dir = (args.output_dir or proxy_image.parent).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    rgb = np.asarray(Image.open(proxy_image).convert("RGB"))
    mask, saturation_threshold = create_mask(rgb)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata.update(
        {
            "mask_type": "initial_stain_based_tissue_mask",
            "saturation_threshold": saturation_threshold,
            "tissue_fraction": float(mask.mean()),
            "important_limit": "This mask distinguishes stained tissue from background only. It is not a tumour label.",
        }
    )
    Image.fromarray((mask * 255).astype(np.uint8)).save(output_dir / "initial_tissue_mask.png")
    np.savez_compressed(output_dir / "initial_tissue_mask.npz", mask=mask)
    overlay = rgb.astype(np.float32)
    overlay[mask] = 0.55 * overlay[mask] + 0.45 * np.array([0, 210, 70])
    Image.fromarray(overlay.astype(np.uint8)).save(output_dir / "initial_tissue_mask_overlay.png")
    report_path = output_dir / "initial_tissue_mask_metadata.json"
    report_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Tissue fraction: {metadata['tissue_fraction']:.2%}")
    print(f"Mask: {output_dir / 'initial_tissue_mask.png'}")
    print(f"Overlay: {output_dir / 'initial_tissue_mask_overlay.png'}")
    print(f"Mask metadata: {report_path}")


if __name__ == "__main__":
    main()
