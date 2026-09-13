"""Convert a HoVer-Net AnnotationStore into per-nucleus morphology features.

The input ``.db`` is the SQLite AnnotationStore produced by ``run_hovernet.py``.
Geometry is measured from each nucleus contour, then calibrated with the patch
MPP.  The output is a per-nucleus CSV plus a one-row summary; it is not yet a
patient-level feature table.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pandas as pd
from PIL import Image, ImageDraw
from tiatoolbox.annotation.storage import SQLiteStore


TYPE_COLORS: dict[str, tuple[int, int, int]] = {
    "Neoplastic": (230, 76, 60),
    "Inflammatory": (48, 105, 210),
    "Connective": (65, 168, 90),
    "Dead": (245, 166, 35),
    "Non-Neoplastic Epithelial": (152, 78, 163),
    "Background": (120, 120, 120),
}
DEFAULT_COLOR = (230, 170, 0)


def largest_polygon(geometry: Any) -> Any | None:
    """Return a usable Polygon, choosing the largest part if needed."""
    if geometry is None or geometry.is_empty:
        return None
    if geometry.geom_type == "Polygon":
        return geometry
    if geometry.geom_type == "MultiPolygon":
        return max(geometry.geoms, key=lambda item: item.area, default=None)
    return None


def contour_points(geometry: Any) -> np.ndarray | None:
    polygon = largest_polygon(geometry)
    if polygon is None:
        return None
    points = np.asarray(polygon.exterior.coords[:-1], dtype=np.float64)
    if len(points) < 3:
        return None
    return points


def ellipse_features(points_px: np.ndarray, mpp: float) -> tuple[float, float, float]:
    """Return long axis, short axis (um), and axial long-axis angle (degrees)."""
    if len(points_px) < 5:
        return math.nan, math.nan, math.nan
    try:
        (_, _), (axis_a_px, axis_b_px), angle_deg = cv2.fitEllipse(
            points_px.astype(np.float32).reshape(-1, 1, 2)
        )
    except cv2.error:
        return math.nan, math.nan, math.nan
    if axis_a_px <= 0 or axis_b_px <= 0:
        return math.nan, math.nan, math.nan
    if axis_a_px >= axis_b_px:
        long_axis_px, short_axis_px, long_axis_angle = axis_a_px, axis_b_px, angle_deg
    else:
        long_axis_px, short_axis_px, long_axis_angle = axis_b_px, axis_a_px, angle_deg + 90.0
    return long_axis_px * mpp, short_axis_px * mpp, long_axis_angle % 180.0


def summarize(series: pd.Series) -> dict[str, float]:
    values = series.dropna().to_numpy(dtype=float)
    values = values[np.isfinite(values)]
    if len(values) == 0:
        return {key: math.nan for key in ("mean", "sd", "median", "q05", "q25", "q75", "q95", "iqr")}
    q05, q25, q75, q95 = np.quantile(values, [0.05, 0.25, 0.75, 0.95])
    return {
        "mean": float(np.mean(values)),
        "sd": float(np.std(values, ddof=1)) if len(values) > 1 else math.nan,
        "median": float(np.median(values)),
        "q05": float(q05),
        "q25": float(q25),
        "q75": float(q75),
        "q95": float(q95),
        "iqr": float(q75 - q25),
    }


def make_overlay(patch: Path, rows: list[dict[str, Any]], output: Path) -> None:
    image = Image.open(patch).convert("RGB")
    canvas = image.copy()
    draw = ImageDraw.Draw(canvas)
    for row in rows:
        points = row.get("_contour_points_px")
        if points is None:
            continue
        color = TYPE_COLORS.get(str(row["nucleus_type"]), DEFAULT_COLOR)
        draw.line([tuple(point) for point in points] + [tuple(points[0])], fill=color, width=2)
    canvas.save(output)


def touches_patch_edge(points_px: np.ndarray, width_px: int, height_px: int) -> bool:
    """Flag contours that may be truncated by the image boundary."""
    x_values, y_values = points_px[:, 0], points_px[:, 1]
    return bool(
        (x_values.min() <= 0)
        or (y_values.min() <= 0)
        or (x_values.max() >= width_px - 1)
        or (y_values.max() >= height_px - 1)
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract calibrated nuclear morphology features from a HoVer-Net .db file."
    )
    parser.add_argument("annotation_store", type=Path, help="HoVer-Net AnnotationStore SQLite .db")
    parser.add_argument("--patch", type=Path, required=True, help="The image patch used for HoVer-Net")
    parser.add_argument("--mpp", type=float, required=True, help="Patch resolution in um/px")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--exclude-edge", action="store_true", help="Exclude boundary-touching nuclei from both the per-nucleus CSV and summary (default: retain and flag).")
    args = parser.parse_args()

    db_path = args.annotation_store.expanduser().resolve()
    patch_path = args.patch.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    if not db_path.is_file():
        raise FileNotFoundError(f"AnnotationStore not found: {db_path}")
    if not patch_path.is_file():
        raise FileNotFoundError(f"Patch not found: {patch_path}")
    if not math.isfinite(args.mpp) or args.mpp <= 0:
        raise ValueError("--mpp must be finite and positive.")
    run_metadata_path = db_path.parent / "hovernet_run.json"
    if run_metadata_path.is_file():
        run_metadata = json.loads(run_metadata_path.read_text(encoding="utf-8"))
        recorded_mpp = float(run_metadata["input_mpp_um_per_px"])
        if not math.isclose(recorded_mpp, args.mpp, rel_tol=0, abs_tol=1e-9):
            raise ValueError("--mpp disagrees with HoVer-Net run metadata.")
    output_dir.mkdir(parents=True, exist_ok=True)
    with Image.open(patch_path) as patch_image:
        patch_width_px, patch_height_px = patch_image.size

    store = SQLiteStore.open(db_path)
    rows: list[dict[str, Any]] = []
    skipped = 0
    excluded_edge = 0
    try:
        for nucleus_id, annotation in store.items():
            polygon = largest_polygon(annotation.geometry)
            points_px = contour_points(annotation.geometry)
            if polygon is None or points_px is None or not polygon.is_valid or not np.isfinite(points_px).all():
                skipped += 1
                continue
            area_px2 = float(polygon.area)
            perimeter_px = float(polygon.length)
            hull_area_px2 = float(polygon.convex_hull.area)
            if not all(math.isfinite(v) and v > 0 for v in (area_px2, perimeter_px, hull_area_px2)):
                skipped += 1
                continue
            touches_edge = touches_patch_edge(points_px, patch_width_px, patch_height_px)
            if args.exclude_edge and touches_edge:
                excluded_edge += 1
                continue
            long_axis_um, short_axis_um, orientation_deg = ellipse_features(points_px, args.mpp)
            properties = annotation.properties or {}
            centroid = properties.get("centroid", polygon.centroid.coords[0])
            nucleus_type = str(properties.get("type", "Unclassified"))
            rows.append(
                {
                    "nucleus_id": str(nucleus_id),
                    "nucleus_type": nucleus_type,
                    "probability": properties.get("prob", math.nan),
                    "geometry_type": polygon.geom_type,
                    "geometry_is_valid": bool(polygon.is_valid),
                    "touches_patch_edge": touches_edge,
                    "centroid_x_um": float(centroid[0]) * args.mpp,
                    "centroid_y_um": float(centroid[1]) * args.mpp,
                    "area_um2": area_px2 * args.mpp * args.mpp,
                    "perimeter_um": perimeter_px * args.mpp,
                    "long_axis_um": long_axis_um,
                    "short_axis_um": short_axis_um,
                    "orientation_deg": orientation_deg,
                    "ellipse_fit_status": "ok" if math.isfinite(orientation_deg) else "not_available",
                    "circularity": 4.0 * math.pi * area_px2 / (perimeter_px * perimeter_px),
                    "solidity": area_px2 / hull_area_px2,
                    "mpp_um_per_px": args.mpp,
                    "source_db": str(db_path),
                    "source_patch": str(patch_path),
                    "_contour_points_px": points_px,
                }
            )
    finally:
        close = getattr(store, "close", None)
        if callable(close):
            close()

    if not rows:
        raise RuntimeError("No valid nucleus contours were found in the AnnotationStore.")
    overlay_path = output_dir / "nuclei_overlay.png"
    make_overlay(patch_path, rows, overlay_path)
    frame = pd.DataFrame(rows).drop(columns=["_contour_points_px"])
    features_path = output_dir / "nuclear_features.csv"
    frame.to_csv(features_path, index=False)

    summary: dict[str, Any] = {
        "annotation_store": str(db_path),
        "patch": str(patch_path),
        "mpp_um_per_px": args.mpp,
        "n_nuclei": int(len(frame)),
        "n_skipped_invalid_geometry": int(skipped),
        "n_excluded_edge": int(excluded_edge),
        "edge_policy": "exclude" if args.exclude_edge else "retain_and_flag",
    }
    for feature in ("area_um2", "long_axis_um", "short_axis_um", "circularity", "solidity"):
        for statistic, value in summarize(frame[feature]).items():
            summary[f"{feature}_{statistic}"] = value
    summary_path = output_dir / "nuclear_feature_summary.csv"
    pd.DataFrame([summary]).to_csv(summary_path, index=False)
    type_counts_path = output_dir / "nucleus_type_counts.csv"
    frame.groupby("nucleus_type", dropna=False).size().rename("n_nuclei").reset_index().to_csv(
        type_counts_path, index=False
    )
    metadata = {
        "annotation_store": str(db_path),
        "patch": str(patch_path),
        "mpp_um_per_px": args.mpp,
        "n_nuclei": len(frame),
        "n_skipped_invalid_geometry": skipped,
        "n_excluded_edge": excluded_edge,
        "edge_policy": "exclude" if args.exclude_edge else "retain_and_flag",
        "feature_definitions": {
            "area_um2": "Nuclear contour area × MPP².",
            "long_axis_um": "Major axis of an OpenCV ellipse fitted to the nuclear contour × MPP.",
            "short_axis_um": "Minor axis of an OpenCV ellipse fitted to the nuclear contour × MPP.",
            "orientation_deg": "Long-axis axial orientation in [0, 180) degrees; undefined ellipse fits are blank (NaN).",
            "circularity": "4π × area / perimeter².",
            "solidity": "Contour area / convex-hull area.",
        },
        "type_label_note": (
            "HoVer-Net PanNuke type labels are not validated bladder-cancer-specific cell labels; "
            "use all-nuclei morphology as the primary analysis."
        ),
        "overlay_colors_rgb": TYPE_COLORS,
    }
    metadata_path = output_dir / "feature_metadata.json"
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Nuclei: {len(frame)}")
    print(f"Per-nucleus CSV: {features_path}")
    print(f"Summary CSV: {summary_path}")
    print(f"Overlay: {overlay_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
