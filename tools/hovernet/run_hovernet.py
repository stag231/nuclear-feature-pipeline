"""Run pretrained HoVer-Net on one physically calibrated ROI patch.

The input is a 512 x 512 PNG at 0.25 um/px.  HoVer-Net internally requires
256 x 256 input tiles, therefore the PNG is processed as a small virtual WSI
(``patch_mode=False``) rather than as one fixed-size model input.  TIAToolbox
tiles and stitches it, then stores nuclei as an AnnotationStore SQLite DB.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODEL_NAME = "hovernet_fast-pannuke"


def choose_device(requested: str) -> str:
    """Choose a PyTorch device without silently changing an explicit request."""
    import torch

    if requested != "auto":
        if requested == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDA was requested but is not available.")
        if requested == "mps" and not torch.backends.mps.is_available():
            raise RuntimeError("Apple MPS was requested but is not available.")
        return requested
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def iter_paths(value: Any) -> Iterable[Path]:
    """Flatten the nested path values returned by TIAToolbox WSI mode."""
    if isinstance(value, (str, Path)):
        yield Path(value)
    elif isinstance(value, dict):
        for item in value.values():
            yield from iter_paths(item)
    elif isinstance(value, Iterable):
        for item in value:
            yield from iter_paths(item)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run HoVer-Net on one PNG patch and save nuclei in a SQLite .db file."
    )
    parser.add_argument("patch", type=Path, help="PNG patch (e.g. 512 px at 0.25 um/px)")
    parser.add_argument("--mpp", type=float, required=True, help="Patch resolution in um/px")
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="New output directory; it must not already exist.",
    )
    parser.add_argument(
        "--weights-dir",
        type=Path,
        default=PROJECT_ROOT / "models" / "hovernet",
        help="Persistent cache for the public pretrained weights.",
    )
    parser.add_argument("--device", choices=("auto", "mps", "cpu", "cuda"), default="auto")
    parser.add_argument("--batch-size", type=int, default=1)
    args = parser.parse_args()

    patch = args.patch.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    weights_dir = args.weights_dir.expanduser().resolve()
    if not patch.is_file():
        raise FileNotFoundError(f"Patch not found: {patch}")
    if patch.suffix.lower() not in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
        raise ValueError("The patch must be an image file (PNG, JPEG, or TIFF).")
    if not math.isfinite(args.mpp) or not math.isclose(args.mpp, 0.25, rel_tol=0, abs_tol=1e-9):
        raise ValueError("This release requires --mpp 0.25 for the pretrained model's input/output coordinate scale.")
    if args.batch_size < 1:
        raise ValueError("--batch-size must be at least 1.")
    if output_dir.exists():
        raise FileExistsError(
            f"Output directory already exists: {output_dir}. "
            "Choose a new directory; this script never overwrites previous inference."
        )
    patch_metadata = patch.with_suffix(".json")
    if patch_metadata.is_file():
        recorded_mpp = json.loads(patch_metadata.read_text(encoding="utf-8")).get("output_mpp_um_per_px")
        if recorded_mpp is not None and not math.isclose(float(recorded_mpp), args.mpp, rel_tol=0, abs_tol=1e-9):
            raise ValueError("--mpp disagrees with the patch extraction metadata. Do not relabel a patch's physical scale.")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    weights_dir.mkdir(parents=True, exist_ok=True)

    import tiatoolbox
    from tiatoolbox.models.architecture import fetch_pretrained_weights
    from tiatoolbox.models.engine.multi_task_segmentor import MultiTaskSegmentor

    device = choose_device(args.device)
    print(f"Input patch: {patch}")
    print(f"Patch MPP: {args.mpp:g} um/px")
    print(f"Device: {device}")
    print(f"Model: {MODEL_NAME}")
    weights = fetch_pretrained_weights(MODEL_NAME, save_path=weights_dir)
    engine = MultiTaskSegmentor(
        model=MODEL_NAME,
        weights=weights,
        batch_size=args.batch_size,
        num_workers=0,
        device=device,
        verbose=True,
    )
    result = engine.run(
        images=[patch],
        patch_mode=False,
        save_dir=output_dir,
        overwrite=False,
        output_type="annotationstore",
        auto_get_mask=False,
        input_resolutions=[{"units": "mpp", "resolution": args.mpp}],
        wsireader_kwargs={"mpp": (args.mpp, args.mpp)},
    )
    db_paths = sorted(path.resolve() for path in iter_paths(result) if path.suffix == ".db")
    if len(db_paths) != 1 or not db_paths[0].is_file():
        raise RuntimeError(
            "HoVer-Net did not yield exactly one AnnotationStore .db file. "
            f"Returned values: {result!r}"
        )
    metadata = {
        "input_patch": str(patch),
        "input_mpp_um_per_px": args.mpp,
        "model": MODEL_NAME,
        "device": device,
        "weights": str(weights),
        "annotation_store_db": str(db_paths[0]),
        "tiatoolbox_version": getattr(tiatoolbox, "__version__", "unknown"),
        "weights_licensing": "Pretrained weights have separate terms. See THIRD_PARTY_NOTICES.md; no weights are redistributed here.",
        "note": (
            "PanNuke cell types are not bladder-cancer-specific labels. "
            "Use all-nuclei morphology as the primary analysis."
        ),
    }
    metadata_path = output_dir / "hovernet_run.json"
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Nuclei AnnotationStore: {db_paths[0]}")
    print(f"Run metadata: {metadata_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
