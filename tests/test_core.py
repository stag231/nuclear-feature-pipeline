"""Synthetic, no-patient-data checks for scale and ROI safety.

Run from the repository root: uv run python -m unittest discover -s tests -v
These tests never read a WSI or download model weights.
"""

from __future__ import annotations

import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np
from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import create_qc_proxy
from import_histoqc_mask import mask_coordinate_mapping
from pathomics.wsi_reader import OpenSlideWSI, _first_float, open_wsi
from propose_patch_candidates import propose_candidates


class FakeSlide:
    """Minimal in-memory stand-in for OpenSlide, not an actual slide file."""

    dimensions = (100, 80)
    level_dimensions = [(100, 80), (50, 40)]
    level_downsamples = [1.0, 2.0]
    level_count = 2
    properties = {"openslide.mpp-x": "0.5", "openslide.mpp-y": "0.5"}

    def __init__(self):
        self.read_calls = []
        self.closed = False

    def read_region(self, origin, level, size):
        self.read_calls.append((origin, level, size))
        return Image.new("RGBA", size, (0, 0, 0, 0))

    def close(self):
        self.closed = True


class ReaderSafetyTests(unittest.TestCase):
    def setUp(self):
        self.source = FakeSlide()
        self.reader = OpenSlideWSI(Path("synthetic.tif"), self.source, (0.5, 0.5), 20.0)

    def test_embedded_scale_ignores_nan_and_infinity(self):
        for invalid in ("nan", "inf", "-inf", "0", "-1", "n/a"):
            with self.subTest(value=invalid):
                value = _first_float({"primary": invalid, "backup": "0.5"}, ("primary", "backup"))
                self.assertEqual(value, 0.5)

    def test_patch_has_expected_source_footprint(self):
        patch = self.reader.read_patch_at_mpp(center_level0=(50, 40), output_size_px=40, target_mpp=0.25)
        self.assertEqual(patch.source_size_px, (20, 20))
        self.assertEqual(patch.source_bounds_level0, (40, 30, 60, 50))
        self.assertEqual(patch.rgb.shape, (40, 40, 3))

    def test_outside_patch_fails_before_read(self):
        for centre in ((0, 0), (99, 79), (-10, 40), (110, 40)):
            with self.subTest(centre=centre), self.assertRaisesRegex(ValueError, "outside the WSI"):
                self.reader.read_patch_at_mpp(center_level0=centre, output_size_px=40, target_mpp=0.25)
        self.assertEqual(self.source.read_calls, [])

    def test_patch_mpp_must_be_finite_and_positive(self):
        for mpp in (float("nan"), float("inf"), float("-inf"), 0, -0.25):
            with self.subTest(mpp=mpp), self.assertRaises(ValueError):
                self.reader.read_patch_at_mpp(center_level0=(50, 40), output_size_px=40, target_mpp=mpp)
        self.assertEqual(self.source.read_calls, [])

    def test_source_mpp_must_be_finite(self):
        self.reader.mpp = (float("inf"), 0.5)
        with self.assertRaises(ValueError):
            self.reader.read_patch_at_mpp(center_level0=(50, 40), output_size_px=40, target_mpp=0.25)
        self.assertEqual(self.source.read_calls, [])

    def test_invalid_override_closes_reader(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "synthetic.tif"
            path.touch()  # Only the mocked reader sees this empty file.
            for invalid in (float("nan"), float("inf"), 0, -1):
                source = FakeSlide()
                with self.subTest(value=invalid), mock.patch("pathomics.wsi_reader.openslide.OpenSlide", return_value=source):
                    with self.assertRaises(ValueError):
                        open_wsi(path, mpp_override=invalid)
                    self.assertTrue(source.closed)

    def test_transparency_composited_on_white(self):
        self.assertTrue(np.all(self.reader.read_level_rgb(1) == 255))
        patch = self.reader.read_patch_at_mpp(center_level0=(50, 40), output_size_px=40, target_mpp=0.25)
        self.assertTrue(np.all(patch.rgb == 255))


class ProxySafetyTests(unittest.TestCase):
    def test_level_selection_retains_most_detail_below_limit(self):
        source = FakeSlide()
        self.assertEqual(create_qc_proxy.select_qc_level(source, 60), 1)
        self.assertEqual(create_qc_proxy.select_qc_level(source, 100), 0)

    def test_no_small_level_fails_without_reading(self):
        source = FakeSlide()
        with self.assertRaisesRegex(ValueError, "No pyramid level"):
            create_qc_proxy.select_qc_level(source, 20)
        self.assertEqual(source.read_calls, [])

    def test_invalid_maximum_side(self):
        for limit in (0, -1, 1.5):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                create_qc_proxy.select_qc_level(FakeSlide(), limit)

    def test_explicit_zero_objective_is_not_silently_replaced(self):
        source = FakeSlide()
        reader = OpenSlideWSI(Path("synthetic.tif"), source, (0.5, 0.5), 20.0)
        with tempfile.TemporaryDirectory() as temporary:
            argv = ["create_qc_proxy.py", "synthetic.tif", "--objective-power", "0", "--output-dir", temporary]
            with mock.patch.object(sys, "argv", argv), mock.patch.object(create_qc_proxy, "open_wsi", return_value=reader):
                with self.assertRaisesRegex(ValueError, "finite and positive"):
                    create_qc_proxy.main()
        self.assertEqual(source.read_calls, [])


class CandidateSafetyTests(unittest.TestCase):
    def candidates(self, mask, **changes):
        args = dict(size=4, target_mpp=1.0, count=9, downsample=8.0, mask_mpp=(1.0, 1.0))
        args.update(changes)
        return propose_candidates(mask, **args)

    def test_all_tissue_image_treats_border_as_unusable(self):
        mask = np.ones((21, 21), dtype=bool)
        rows = self.candidates(mask)
        self.assertEqual((rows[0]["mask_center_x_px"], rows[0]["mask_center_y_px"]), (10, 10))
        for row in rows:
            x, y = row["mask_center_x_px"], row["mask_center_y_px"]
            self.assertTrue(2 <= x <= 18 and 2 <= y <= 18)
            self.assertEqual(row["level0_center_x_px"], x * 8)

    def test_square_corners_cannot_include_hole(self):
        mask = np.ones((11, 11), dtype=bool)
        mask[1, 1] = False
        rows = self.candidates(mask, size=8)
        self.assertTrue(rows)
        for row in rows:
            x, y = row["mask_center_x_px"], row["mask_center_y_px"]
            self.assertNotEqual((x, y), (5, 5))  # Old circle check could admit this square.
            self.assertTrue(mask[y - 4 : y + 5, x - 4 : x + 5].all())

    def test_empty_tissue_or_oversized_patch_yields_no_candidates(self):
        self.assertEqual(self.candidates(np.zeros((21, 21), dtype=bool)), [])
        self.assertEqual(self.candidates(np.ones((3, 3), dtype=bool)), [])

    def test_invalid_mask_or_scale_rejected(self):
        for mask in (np.ones((4, 4, 3)), np.ones((0, 4))):
            with self.subTest(shape=mask.shape), self.assertRaises(ValueError):
                self.candidates(mask)
        for changes in (
            {"target_mpp": float("nan")}, {"downsample": float("inf")},
            {"mask_mpp": (0.0, 0.0)}, {"mask_mpp": (1.0, 2.0)}, {"count": 0},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.candidates(np.ones((21, 21)), **changes)


class MaskMappingTests(unittest.TestCase):
    def setUp(self):
        self.metadata = {
            "proxy_dimensions_px": [200, 100],
            "proxy_downsample_from_level0": 16.0,
            "source_mpp_um_per_px": [0.5, 0.5],
        }

    def test_mapping_composes_proxy_and_mask_scales(self):
        scale, downsample, mpp = mask_coordinate_mapping((100, 50), (200, 100), self.metadata)
        self.assertEqual((scale, downsample, mpp), (2.0, 32.0, (0.5, 0.5)))

    def test_mismatched_proxy_dimensions_rejected(self):
        with self.assertRaisesRegex(ValueError, "do not match"):
            mask_coordinate_mapping((100, 50), (400, 200), self.metadata)

    def test_anisotropic_mask_resize_rejected(self):
        with self.assertRaisesRegex(ValueError, "different x and y"):
            mask_coordinate_mapping((100, 40), (200, 100), self.metadata)

    def test_nonfinite_scale_rejected(self):
        for key, value in (
            ("proxy_downsample_from_level0", float("nan")),
            ("proxy_downsample_from_level0", 0),
            ("source_mpp_um_per_px", [float("inf"), 0.5]),
            ("source_mpp_um_per_px", [-0.5, -0.5]),
        ):
            metadata = copy.deepcopy(self.metadata)
            metadata[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                mask_coordinate_mapping((100, 50), (200, 100), metadata)

    def test_zero_dimension_rejected(self):
        with self.assertRaises(ValueError):
            mask_coordinate_mapping((0, 50), (200, 100), self.metadata)


if __name__ == "__main__":
    unittest.main()
