"""Extract one WSI ROI at a specified physical scale for downstream inference."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image

from pathomics.wsi_reader import open_wsi


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract one physically calibrated square patch from an OpenSlide WSI.")
    parser.add_argument("wsi_path", type=Path)
    parser.add_argument("--center-x", type=int, required=True, help="Patch centre x in level-0 pixels.")
    parser.add_argument("--center-y", type=int, required=True, help="Patch centre y in level-0 pixels.")
    parser.add_argument("--size", type=int, default=512)
    parser.add_argument("--target-mpp", type=float, default=0.25)
    parser.add_argument("--mpp", type=float, default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    source = args.wsi_path.expanduser().resolve()
    output = args.output or Path("outputs/patches") / f"{source.stem}_x{args.center_x}_y{args.center_y}_{args.target_mpp:g}mpp.png"
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with open_wsi(source, mpp_override=args.mpp) as slide:
        patch = slide.read_patch_at_mpp(
            center_level0=(args.center_x, args.center_y),
            output_size_px=args.size,
            target_mpp=args.target_mpp,
        )
        metadata = {
            "source_slide": source.name,
            "source_format": slide.format,
            "source_reader": slide.reader_name,
            "source_mpp_um_per_px": list(slide.mpp),
            "source_mpp_source": "override" if args.mpp is not None else "embedded_metadata",
            "center_level0_px": [args.center_x, args.center_y],
            "output_dimensions_px": [args.size, args.size],
            "output_mpp_um_per_px": args.target_mpp,
            "field_of_view_um": [args.size * args.target_mpp, args.size * args.target_mpp],
            "source_bounds_level0_px": list(patch.source_bounds_level0),
            "source_size_px_before_resampling": list(patch.source_size_px),
            "note": "Resampling aligns visual scale with the downstream model; it does not add spatial detail.",
        }
    Image.fromarray(patch.rgb).save(output)
    metadata_path = output.with_suffix(".json")
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Patch: {output}")
    print(f"Metadata: {metadata_path}")
    print(f"Field of view: {metadata['field_of_view_um'][0]:.1f} × {metadata['field_of_view_um'][1]:.1f} µm")
    print(f"Source before resampling: {patch.source_size_px[0]} × {patch.source_size_px[1]} px")


if __name__ == "__main__":
    main()
