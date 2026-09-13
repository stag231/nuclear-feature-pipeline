"""Run HistoQC on a proxy TIFF with the correct proxy magnification.

The generic QC proxy TIFF does not retain a scanner objective-power property.
This wrapper reads the known magnification from ``proxy_metadata.json`` and
writes a matching HistoQC configuration before launching the first-pass QC.
"""

from __future__ import annotations

import argparse
import configparser
import json
from pathlib import Path

from histoqc.__main__ import main as histoqc_main
from histoqc.config import read_config_template


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a first-pass HistoQC analysis on one QC proxy TIFF.")
    parser.add_argument("proxy_tiff", type=Path)
    parser.add_argument("--proxy-metadata", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()

    proxy_tiff = args.proxy_tiff.expanduser().resolve()
    metadata_path = args.proxy_metadata.expanduser().resolve()
    if not proxy_tiff.is_file() or not metadata_path.is_file():
        raise FileNotFoundError("Both the proxy TIFF and proxy_metadata.json must exist.")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    base_mag = float(metadata["suggested_histoqc_base_magnification"])
    if base_mag <= 0:
        raise ValueError("The suggested HistoQC base magnification must be positive.")

    output_dir = (args.output_dir or proxy_tiff.parent / "histoqc_first_pass").expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    config_path = output_dir / "histoqc_proxy_first_pass.ini"
    config = configparser.ConfigParser()
    config.read_string(read_config_template("first"))
    config["BaseImage.BaseImage"]["base_mag"] = f"{base_mag:g}x"
    config["BaseImage.BaseImage"]["confirm_base_mag"] = "False"
    with config_path.open("w", encoding="utf-8") as handle:
        config.write(handle)

    print(f"Proxy base magnification: {base_mag:g}x")
    print(f"HistoQC config: {config_path}")
    print(f"HistoQC output: {output_dir}")
    return histoqc_main(["-c", str(config_path), "-n", "1", "-o", str(output_dir), str(proxy_tiff)])


if __name__ == "__main__":
    raise SystemExit(main())
