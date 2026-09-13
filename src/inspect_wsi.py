"""Print the small set of WSI properties needed before any analysis."""

from __future__ import annotations

import argparse
from pathlib import Path

from pathomics.wsi_reader import open_wsi


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect an OpenSlide-compatible TIFF or SVS WSI.")
    parser.add_argument("wsi_path", type=Path)
    parser.add_argument("--mpp", type=float, default=None, help="Override only when scanner MPP is known.")
    args = parser.parse_args()

    with open_wsi(args.wsi_path, mpp_override=args.mpp) as slide:
        print(f"File: {slide.path.name}")
        print(f"Reader: {slide.reader_name}")
        print(f"Format: {slide.format}")
        print(f"Level-0 dimensions (px): {slide.dimensions[0]} × {slide.dimensions[1]}")
        print(f"Pyramid levels: {slide.level_count}")
        print(f"MPP (µm/px): {slide.mpp}")
        print(f"Objective power: {slide.objective_power}")
        print(f"Bounds (level-0 px): {slide.bounds}")
        print("Levels:")
        for level, (dimensions, downsample) in enumerate(zip(slide.level_dimensions, slide.level_downsamples)):
            print(f"  {level}: {dimensions[0]} × {dimensions[1]} px (downsample {downsample:.2f}×)")


if __name__ == "__main__":
    main()
