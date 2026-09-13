# Third-party tools and pretrained weights

This repository contains workflow wrappers and setup instructions. It does not bundle
third-party library distributions, pretrained weights, WSI data, or the presentation deck.
Dependencies are installed separately through the committed environment definitions.
The owner's license for original wrapper code is not yet selected.

| Component | Version / source used | Upstream license reference |
|---|---|---|
| OpenSlide / openslide-python | Python binding 1.4.6; openslide-bin 4.0.1.2 package | [LGPL-2.1-only, official license page](https://openslide.org/license/) |
| HistoQC | Commit `30d2f65acbebb3d6291bcb15d3bceeca61fdfd7d` | [BSD-3-Clause-Clear, pinned LICENSE.txt](https://github.com/choosehappy/HistoQC/blob/30d2f65acbebb3d6291bcb15d3bceeca61fdfd7d/LICENSE.txt) |
| TIAToolbox source | 2.1.3 | [BSD-3-Clause, pinned LICENSE](https://github.com/TissueImageAnalytics/tiatoolbox/blob/v2.1.3/LICENSE) |
| HoVer-Net fast PanNuke weights | Model identifier `hovernet_fast-pannuke` | [TIAToolbox 2.1.3 pretrained-model terms: CC BY-NC-SA 4.0](https://tia-toolbox.readthedocs.io/en/v2.1.3/pretrained.html#pannuke-dataset) |

## Model weights are separate from source code

The model-weight license is not the TIAToolbox source-code license or any future license
chosen for this repository. Check the upstream model/dataset terms before downloading or using
the weights, especially for commercial use or redistribution. The first inference run uses
TIAToolbox's official weight-fetching mechanism and stores a local cache under `models/hovernet/`.
This directory must remain excluded from Git.

The source versions and Python packages are pinned in three `uv.lock` files. The upstream
model identifier is recorded, but a Hugging Face revision/hash for the weights is not pinned
by this wrapper. Therefore package locking alone does not guarantee that all future weight
downloads are byte-identical. Archive the permitted local execution metadata and weight checksum
within the institution when exact research reproducibility is required.

HistoQC's configuration is generated at runtime from its installed template. Do not copy
third-party distributions or generated upstream configurations into a release without checking
the applicable notice and redistribution requirements. Transitive dependencies retain their
own licenses; the table above is not an exhaustive inventory of every installed package.

## Technical sources and citation starting points

- [OpenSlide supported formats](https://openslide.org/formats/)
- [HistoQC official repository](https://github.com/choosehappy/HistoQC)
- [HoVer-Net original implementation and paper references](https://github.com/vqdang/hover_net)
- [TIAToolbox 2.1.3 MultiTaskSegmentor API](https://tia-toolbox.readthedocs.io/en/v2.1.3/_autosummary/tiatoolbox.models.engine.multi_task_segmentor.MultiTaskSegmentor.html)
- [TIAToolbox 2.1.3 pretrained model resolution and type labels](https://tia-toolbox.readthedocs.io/en/v2.1.3/pretrained.html#pannuke-dataset)

When using this workflow in research, cite the tools, models and datasets actually used,
following their upstream citation guidance. This notice is a technical summary, not a substitute
for the applicable licenses or the institution's authorization to release code.
