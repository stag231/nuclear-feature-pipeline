"""Export a modest-sized TIFF proxy for QC without changing the source WSI."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import tifffile
from PIL import Image

from pathomics.wsi_reader import OpenSlideWSI, open_wsi


def select_qc_level(slide: OpenSlideWSI, maximum_side_px: int = 8000) -> int:
    """Choose the highest-resolution level whose long side is manageable for QC."""

    if not isinstance(maximum_side_px, int) or maximum_side_px <= 0:
        raise ValueError("maximum_side_px must be a positive integer")
    for level, dimensions in enumerate(slide.level_dimensions):
        if max(dimensions) <= maximum_side_px:
            return level
    raise ValueError(
        "No pyramid level is small enough for the automatic QC proxy. "
        "Provide a pyramidal WSI; an explicit --level bypasses this size guard "
        "and should only be used after checking memory requirements."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a QC proxy TIFF from an OpenSlide WSI.")
    parser.add_argument("wsi_path", type=Path)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--level", type=int, default=None)
    parser.add_argument("--mpp", type=float, default=None)
    parser.add_argument(
        "--objective-power",
        type=float,
        default=None,
        help="Required when the WSI does not embed the scanner objective power.",
    )
    args = parser.parse_args()

    source = args.wsi_path.expanduser().resolve()
    output_dir = (args.output_dir or Path("outputs/qc") / source.stem).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    with open_wsi(source, mpp_override=args.mpp) as slide:
        level = args.level if args.level is not None else select_qc_level(slide)
        if not 0 <= level < slide.level_count:
            raise ValueError(f"--level must be between 0 and {slide.level_count - 1}")
        objective_power = args.objective_power if args.objective_power is not None else slide.objective_power
        if objective_power is None:
            raise ValueError(
                "The WSI has no objective-power metadata. Confirm the scanner objective and use --objective-power, e.g. --objective-power 20."
            )
        if not math.isfinite(objective_power) or objective_power <= 0:
            raise ValueError("--objective-power must be finite and positive")
        rgb = slide.read_level_rgb(level)
        downsample = slide.level_downsamples[level]
        if not math.isfinite(downsample) or downsample <= 0:
            raise ValueError("The selected pyramid downsample must be finite and positive")
        metadata = {
            "source_slide": source.name,
            "source_format": slide.format,
            "source_reader": slide.reader_name,
            "source_level0_dimensions_px": list(slide.dimensions),
            "source_mpp_um_per_px": list(slide.mpp),
            "source_mpp_source": "override" if args.mpp is not None else "embedded_metadata",
            "source_objective_power": objective_power,
            "source_objective_power_source": "override" if args.objective_power is not None else "embedded_metadata",
            "proxy_level": level,
            "proxy_dimensions_px": [int(rgb.shape[1]), int(rgb.shape[0])],
            "proxy_downsample_from_level0": downsample,
            "proxy_mpp_um_per_px": [slide.mpp[0] * downsample, slide.mpp[1] * downsample],
            "level0_coordinate_mapping": "level0_px = proxy_px * proxy_downsample_from_level0",
            "suggested_histoqc_base_magnification": objective_power / downsample,
        }

    proxy_path = output_dir / f"{source.stem}_level{level}_proxy.tif"
    preview_path = output_dir / f"{source.stem}_level{level}_proxy.png"
    metadata_path = output_dir / "proxy_metadata.json"
    tifffile.imwrite(
        proxy_path,
        rgb,
        photometric="rgb",
        tile=(256, 256),
        compression="deflate",
        metadata=None,
        description=json.dumps(metadata, ensure_ascii=True),
    )
    Image.fromarray(rgb).save(preview_path)
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Proxy TIFF: {proxy_path}")
    print(f"Preview PNG: {preview_path}")
    print(f"Metadata: {metadata_path}")
    print(f"Suggested HistoQC base magnification: {metadata['suggested_histoqc_base_magnification']:.2f}x")


if __name__ == "__main__":
    main()
