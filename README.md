# Nuclear feature pipeline

WSIから核の形態特徴量を抽出する、講演・学習用のPythonパイプラインです。
OpenSlide、HistoQC、TIAToolbox経由のHoVer-Netを使用します。

**まずは1枚のパッチで、画像からCSVになる過程を確認します。**
全WSIの自動解析、腫瘍ROIの自動確定、臨床用の診断・予後予測モデルは含みません。
患者データ、病理画像、実測CSV、学習済み重み、発表スライドは収録していません。

## ①〜⑥の対応

| 工程 | スクリプト | 主な出力 |
|---|---|---|
| ① WSIを開く | `src/inspect_wsi.py` | 寸法・階層・MPPの表示 |
| ② 品質管理 | `src/create_qc_proxy.py`、`tools/histoqc/run_proxy_qc.py` | QC proxy、HistoQC結果 |
| ③ 組織マスク | `src/create_tissue_mask.py`、`src/import_histoqc_mask.py` | 初期組織マスク・QC usable mask |
| ④ パッチ抽出 | `src/propose_patch_candidates.py`、`src/extract_patch.py` | 候補座標、512×512パッチとメタデータ |
| ⑤ 核の検出 | `tools/hovernet/run_hovernet.py` | 核輪郭のSQLite `.db` |
| ⑥ 特徴量計算 | `tools/hovernet/extract_nuclear_features.py` | 核ごと・パッチ要約CSV、輪郭画像 |

## 最初に読むもの

- [初学者向け実行手順（日本語）](docs/WORKFLOW_JA.md)：環境構築と①〜⑥の完全なコマンド
- [特徴量の定義と注意点](docs/FEATURES.md)
- [第三者ツール・重みの出典と利用条件](THIRD_PARTY_NOTICES.md)
- [公開直前のチェックリスト](docs/PUBLICATION_CHECKLIST.md)

## 環境構築

元のデモ環境はmacOS / Apple Siliconです。CPU、MPS、CUDAの選択肢がありますが、
各環境での速度や動作を保証するものではありません。まず小さなパッチで確認してください。
Windows/Linuxの新規環境は別途検証が必要です。

1. [VS Code](https://code.visualstudio.com/)と[uv](https://docs.astral.sh/uv/getting-started/installation/)を用意します。
2. このリポジトリを取得し、VS Codeでフォルダを開きます。非公開期間は所有者の許可が必要です。
3. VS Codeの統合ターミナルで、リポジトリ直下から以下を実行します。

```bash
uv sync --locked
uv sync --locked --project tools/histoqc
uv sync --locked --project tools/hovernet
mkdir -p WSI outputs models
```

基本処理とHistoQCはPython 3.10、HoVer-NetはPython 3.11です。
それぞれ独立した`.venv`と`uv.lock`を使います。既存の仮想環境を有効化している場合は、
先に`deactivate`してください。HistoQC取得時はGitも必要です。

自施設で利用権限を確認したOpenSlide対応`.tif` / `.tiff` / `.svs`を、ローカルの`WSI/`に置きます。
`.tif`という拡張子だけではOpenSlide対応やMPPの保持を保証できません。
この配布版はBIF直接読込・BIF変換を含みません。

```bash
uv run --locked python src/inspect_wsi.py WSI/INPUT.tif
```

以降は[実行手順](docs/WORKFLOW_JA.md)に沿って進めます。
HoVer-Netの初回実行では学習済み重みを外部配布元から取得します。
実行前に[重みの利用条件](THIRD_PARTY_NOTICES.md)を確認してください。

## 解釈を誤らないために

- **MPPを確認する**：`0.465 µm/px`の画像を`0.25 µm/px`へ補間しても、撮影時の解像度は増えません。
  対物倍率はMPPから断定せず、スキャナ情報で確認します。
- **QCと腫瘍の判定を区別する**：初期組織マスク、HistoQC usable mask、候補点はいずれも腫瘍ラベルではありません。
  病理医が対象領域と核輪郭の妥当性を確認してください。
- **proxy QCには限界がある**：縮小画像のfirst-pass QCは、すべての高倍率アーチファクトを除外する検証ではありません。
- **本版のHoVer-Netは0.25 MPP入力のみ**：モデルの入出力座標の不一致を避けるため、`--mpp 0.25`を使用します。
- **パッチ要約は症例全体の特徴ではない**：1パッチの核の平均・中央値等は、症例を代表することを保証しません。
  研究ではROI、多パッチ抽出、重複核、境界核、症例内集約の設計と検証が別途必要です。
- **PanNuke型ラベルは予測**：膀胱癌に特化した確定診断ではありません。
- **実行結果は非公開データとして管理**：出力CSVやJSONには入力ファイル名・ローカルパス等を含みます。
  `.gitignore`だけに頼らず、アップロード前の内容を確認してください。

## 検証用コマンド

```bash
uv run --locked python -m unittest discover -s tests -p 'test_core.py' -v
uv run --locked --project tools/hovernet python -m unittest discover -s tests -p 'test_features.py' -v
python3 scripts/check_release.py
```

テストは合成画像・合成輪郭を使用します。モデルの臨床性能を評価するものではありません。
公開前チェックはGitで追跡するファイルを対象とする補助検査であり、機密情報がないことの保証ではありません。

## ライセンス・公開状態

自作コードのライセンスは未決定です。このリポジトリ独自のオープンソースライセンスは付与していません。
第三者ツールやモデルの利用条件は[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)を参照してください。
公開時期・権利処理は所有者が判断します。自動でPublicへ切り替える仕組みはありません。

本コードは教育・研究のための実装例であり、医療機器や臨床用の診断システムではありません。
