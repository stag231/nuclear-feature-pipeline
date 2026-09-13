"""Synthetic feature tests; no patient images, pretrained weights, or network."""

from __future__ import annotations

import csv
import importlib.util
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd
from PIL import Image
from shapely.geometry import Polygon, box
from tiatoolbox.annotation.storage import Annotation, SQLiteStore

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/hovernet/extract_nuclear_features.py"
spec = importlib.util.spec_from_file_location("nuclear_features", SCRIPT)
features = importlib.util.module_from_spec(spec)
spec.loader.exec_module(features)


class FeatureTests(unittest.TestCase):
    def test_ellipse_axes_and_axial_angle(self):
        theta = np.linspace(0, 2 * np.pi, 100, endpoint=False)
        points = np.column_stack((30 + 12 * np.cos(theta), 30 + 6 * np.sin(theta)))
        long_axis, short_axis, angle = features.ellipse_features(points, 0.25)
        self.assertAlmostEqual(long_axis, 6.0, places=4)
        self.assertAlmostEqual(short_axis, 3.0, places=4)
        self.assertLess(min(abs(angle), abs(angle - 180)), 1e-3)

    def test_degenerate_ellipse_is_nan(self):
        self.assertTrue(all(math.isnan(v) for v in features.ellipse_features(np.zeros((3, 2)), 0.25)))

    def test_summary_finite_values_and_sample_sd(self):
        summary = features.summarize(pd.Series([1.0, 3.0, np.nan, np.inf]))
        self.assertEqual(summary["mean"], 2.0)
        self.assertEqual(summary["median"], 2.0)
        self.assertAlmostEqual(summary["sd"], math.sqrt(2))
        self.assertEqual(summary["iqr"], 1.0)

    def test_edge_flag(self):
        self.assertTrue(features.touches_patch_edge(np.array([[0, 3], [2, 5], [2, 2]]), 64, 64))
        self.assertFalse(features.touches_patch_edge(np.array([[5, 3], [7, 5], [7, 2]]), 64, 64))

    def test_annotationstore_to_csv(self):
        with tempfile.TemporaryDirectory(prefix="nuclei-synthetic-") as temporary:
            directory = Path(temporary)
            patch = directory / "synthetic.png"
            Image.new("RGB", (64, 64), "white").save(patch)
            db = directory / "synthetic.db"
            store = SQLiteStore(db)
            store.append(Annotation(box(10, 10, 20, 20), properties={"type": "Synthetic"}), key="synthetic-inside")
            store.append(Annotation(box(0, 30, 10, 40), properties={"type": "Synthetic"}), key="synthetic-edge")
            store.append(Annotation(Polygon([(40, 40), (50, 50), (40, 50), (50, 40)]), properties={"type": "Synthetic"}), key="synthetic-invalid")
            store.commit()
            store.close()
            # TIAToolbox's destructor closes again; release while the temp DB still exists.
            del store
            for exclude_edge, expected in ((False, 2), (True, 1)):
                output = directory / ("exclude" if exclude_edge else "retain")
                command = [sys.executable, str(SCRIPT), str(db), "--patch", str(patch), "--mpp", "0.25", "--output-dir", str(output)]
                if exclude_edge:
                    command.append("--exclude-edge")
                result = subprocess.run(command, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                with (output / "nuclear_features.csv").open(newline="") as handle:
                    rows = list(csv.DictReader(handle))
                self.assertEqual(len(rows), expected)
                self.assertAlmostEqual(float(rows[0]["area_um2"]), 6.25)
                self.assertAlmostEqual(float(rows[0]["solidity"]), 1.0)
                self.assertAlmostEqual(float(rows[0]["circularity"]), math.pi / 4)
                self.assertTrue((output / "nuclei_overlay.png").is_file())
                with (output / "nuclear_feature_summary.csv").open(newline="") as handle:
                    summary = next(csv.DictReader(handle))
                self.assertEqual(int(summary["n_skipped_invalid_geometry"]), 1)
                self.assertEqual(int(summary["n_excluded_edge"]), int(exclude_edge))


if __name__ == "__main__":
    unittest.main()
