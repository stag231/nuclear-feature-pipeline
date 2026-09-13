# 核特徴量抽出：①〜⑥の実行手順

この手順は、手元の OpenSlide 対応 WSI から **512 × 512 px のパッチを1枚**切り出し、HoVer-Net による核セグメンテーションと形態特徴量の CSV 出力までを体験するためのものです。WSI 全体の解析、腫瘍領域の自動同定、症例単位の予後予測は行いません。研究・教育用であり、診断用に検証されたシステムではありません。

```text
① WSI の情報確認
      ↓
② 低解像度の QC 用画像 → HistoQC
      ↓
③ 組織／背景マスクと、品質上使用可能な領域の確認
      ↓
④ 技術的候補を目視確認 → パッチ1枚を抽出
      ↓
⑤ HoVer-Net → 核の輪郭と推定型ラベル
      ↓
⑥ 核ごとの形態特徴量 → CSV と重ね合わせ画像
```

## 準備：VS Code と3つの Python 環境

Git、uv、VS Code を用意します。uv のインストール方法は [uv 公式ガイド](https://docs.astral.sh/uv/getting-started/installation/)を参照してください。初回の環境作成・モデル重み取得にはネット接続が必要です。リポジトリが非公開の間はアクセス権のある GitHub アカウントでの認証も必要です。

作業場所のターミナルで取得し、そのフォルダを VS Code の「ファイル → フォルダーを開く」で開きます。

```bash
git clone https://github.com/stag231/nuclear-feature-pipeline.git
cd nuclear-feature-pipeline
uv --version
uv sync --frozen
uv sync --frozen --project tools/histoqc
uv sync --frozen --project tools/hovernet
```

環境は分かれています。ルートと HistoQC は Python 3.10、HoVer-Net は Python 3.11 です。`uv` はそれぞれの `pyproject.toml` と `uv.lock` を参照します。別の仮想環境を手動で有効にしている場合は、先にその環境を終了してください。`uv run` を使うため、この手順では `source .venv/bin/activate` は不要です。

```bash
uv run --frozen python -c 'import sys; print(sys.executable)'
uv run --frozen --project tools/histoqc python -c 'import sys; print(sys.executable)'
uv run --frozen --project tools/hovernet python -c 'import sys; print(sys.executable)'
```

以降のコマンドは **Bash または zsh の同じターミナルで、リポジトリ直下から**順番に実行します。`tools/` に `cd` する必要はありません。途中でエラーになった場合は、次の工程へ進まず原因を確認します。PowerShell 用の構文ではありません。

匿名化済みで利用権限のある WSI を `WSI/INPUT.tif` として手元に置いてください。画像は GitHub に追加しません。SVS の場合は以下の `WSI_PATH` だけを対応するファイル名に変更します。拡張子が TIFF でも OpenSlide で読めるとは限りません。この公開版は BIF の直接読み込み・変換を実装していません。

```bash
mkdir -p WSI
WSI_PATH="WSI/INPUT.tif"
RUN_DIR="outputs/demo_01"
QC_DIR="$RUN_DIR/qc"
PATCH_PATH="$RUN_DIR/patches/INPUT_selected_512px_0.25mpp.png"
HOVERNET_DIR="$RUN_DIR/hovernet"
PATCH_MPP="0.25"
```

WSI のコピーは自分で行ってください。再実行するときは `RUN_DIR` を新しい名前にします。特に HoVer-Net の出力フォルダは既存だと実行を停止します。

### MPP と対物倍率を混同しない

- **元 WSI の MPP**：元画像の1ピクセルが何 µm に相当するか。
- **対物倍率（objective power）**：スキャナの撮影条件。MPP だけから 20×／40× を決めません。
- **パッチ MPP**：モデルに渡す画像をどの物理的尺度で作るか。この手順では `0.25 µm/px` です。

まず埋め込みメタデータを利用します。次の変数は通常は空のままです。メタデータが欠落している場合に限り、スキャナの設定記録・施設の担当者などで確認した値を設定してください。推測値を入れないでください。

```bash
VERIFIED_SOURCE_MPP=""
VERIFIED_OBJECTIVE_POWER=""
MPP_ARGS=()
OBJECTIVE_ARGS=()
if [ -n "$VERIFIED_SOURCE_MPP" ]; then
  MPP_ARGS=(--mpp "$VERIFIED_SOURCE_MPP")
fi
if [ -n "$VERIFIED_OBJECTIVE_POWER" ]; then
  OBJECTIVE_ARGS=(--objective-power "$VERIFIED_OBJECTIVE_POWER")
fi
```

`--mpp` は元画像の尺度を明示的に上書きする指定です。この指定は x・y とも同じ MPP とします。異方的な画素など、値の意味が不明な場合は進めないでください。

## ① WSI を開く：画像の条件を確認する

```bash
uv run --frozen python src/inspect_wsi.py "$WSI_PATH" "${MPP_ARGS[@]}"
```

表示される画像サイズ、ピラミッド階層、MPP、対物倍率を確認します。この処理は画像を変更しません。MPP が読めなければエラーになります。確認済みの尺度を上の変数へ設定し、配列設定も再実行してからやり直します。`Objective power: None` は対物倍率の情報がないという意味であり、20× と扱ってよいという意味ではありません。

発表用の一言：**「まず病理画像を開き、サイズと物理的な解像度を確認します。」**

## ② 品質管理：QC 用 proxy と HistoQC

巨大な WSI 全体を扱いやすい低解像度画像（proxy）へ書き出します。元 WSI はそのまま残します。自動選択するピラミッド階層は画像によって異なります。

自動選択では長辺8,000 px以下の概観階層が必要です。該当階層がない巨大な単層TIFFは停止します。メモリ量を確認せずに全解像度を読み込まず、ピラミッド画像の準備などを検討してください。

```bash
uv run --frozen python src/create_qc_proxy.py \
  "$WSI_PATH" \
  "${MPP_ARGS[@]}" \
  "${OBJECTIVE_ARGS[@]}" \
  --output-dir "$QC_DIR"
```

対物倍率が埋め込まれていなければ、確認済みの `VERIFIED_OBJECTIVE_POWER` を設定するまで停止します。HistoQC に使う proxy の基準倍率は、元の対物倍率を縮小率で割って計算します。QC を元画像の20倍・40倍の全解像度で実施するという意味ではありません。

`level3` や `level4` を決め打ちせず、実際のメタデータから proxy を取得します。

```bash
PROXY=$(uv run --frozen python -c '
import json, sys
from pathlib import Path
p = Path(sys.argv[1])
m = json.loads(p.read_text(encoding="utf-8"))
expected = "{}_level{}_proxy.tif".format(Path(m["source_slide"]).stem, m["proxy_level"])
matches = [q for q in p.parent.glob("*_level*_proxy.tif") if q.name == expected]
if len(matches) != 1:
    raise SystemExit("Expected exactly one proxy matching proxy_metadata.json")
print(matches[0])
' "$QC_DIR/proxy_metadata.json")
```

続いて HistoQC の first-pass 設定を使います。

```bash
uv run --frozen --project tools/histoqc python tools/histoqc/run_proxy_qc.py \
  "$PROXY" \
  --proxy-metadata "$QC_DIR/proxy_metadata.json" \
  --output-dir "$QC_DIR/histoqc_first_pass"
```

確認画像は proxy TIFF と同名の `.png` です。HistoQC の出力・マスクも目視確認します。これは低解像度 proxy 上の first-pass QC であり、あらゆるぼけ・折れ・染色不良を保証して除去するものではありません。

発表用の一言：**「低解像度の概観画像を作り、解析に不向きな領域を品質管理で調べます。腫瘍判定ではありません。」**

## ③ 組織マスク：背景と使用可能領域を区別する

色調を使い、染まった組織と背景を分ける初期マスクを作成します。

```bash
uv run --frozen python src/create_tissue_mask.py \
  "$PROXY" \
  --proxy-metadata "$QC_DIR/proxy_metadata.json" \
  --output-dir "$QC_DIR"
```

次に HistoQC が生成した `*_mask_use.png` を取得し、元 WSI の座標に対応付けます。候補が0個または複数なら自動で選ばず停止します。

```bash
HISTOQC_MASK=$(uv run --frozen python -c '
import sys
from pathlib import Path
root, proxy = Path(sys.argv[1]), Path(sys.argv[2])
matches = [p for p in root.rglob("*_mask_use.png") if p.name == proxy.name + "_mask_use.png"]
if len(matches) != 1:
    raise SystemExit("Expected exactly one HistoQC usable mask for this proxy")
print(matches[0])
' "$QC_DIR/histoqc_first_pass" "$PROXY")

uv run --frozen python src/import_histoqc_mask.py \
  "$HISTOQC_MASK" \
  --proxy-metadata "$QC_DIR/proxy_metadata.json" \
  --proxy-image "$PROXY" \
  --output-dir "$QC_DIR"
```

| 確認する画像 | 意味 |
|---|---|
| `initial_tissue_mask_overlay.png` | 色調による、初期の組織／背景の区別 |
| `histoqc_usable_mask_overlay.png` | HistoQC first-pass による、技術的に使用可能な領域 |

どちらも `$QC_DIR` 内にあります。このコードでは、初期マスクと HistoQC マスクを自動で AND 結合してはいません。④は HistoQC の usable mask を使います。**どちらの緑色領域も腫瘍 ROI を示すものではありません。**

発表用の一言：**「背景を除き、品質管理で使用可能とされた領域を座標付きのマスクとして保存します。」**

## ④ パッチ抽出：候補を確認して1枚を選ぶ

```bash
uv run --frozen python src/propose_patch_candidates.py \
  "$QC_DIR/histoqc_usable_mask.npz" \
  --proxy-image "$PROXY" \
  --mask-metadata "$QC_DIR/histoqc_usable_mask_metadata.json" \
  --size 512 \
  --target-mpp "$PATCH_MPP" \
  --count 9 \
  --output-dir "$QC_DIR/candidates"
```

`$QC_DIR/candidates/technical_patch_candidates_overlay.png` と同フォルダの `technical_patch_candidates.csv` を VS Code で開き、元 WSI も適切なビューアで確認します。候補は使用可能マスクの境界からの距離で選びます。順位は腫瘍らしさ・悪性度・代表性の順位ではありません。矩形パッチ全体の品質や腫瘍成分は別途確認してください。

確認後、使用する候補の `rank` を入力します。候補がない場合や適切な組織でない場合は、別の画像／選択方針を検討し、無理に続行しません。

配布版では正方形パッチの四隅までマスク内に収まる条件と画像境界のチェックを追加しています。以前の講演デモと同じ画像でも、候補の順位・座標が変わる場合があります。

```bash
printf '目視確認して選んだ候補の rank を入力: '
read -r CANDIDATE_RANK

CENTER_X=$(uv run --frozen python -c '
import csv, sys
with open(sys.argv[1], newline="", encoding="utf-8") as f:
    rows = [r for r in csv.DictReader(f) if int(r["rank"]) == int(sys.argv[2])]
if len(rows) != 1:
    raise SystemExit("Select one existing candidate rank")
print(rows[0]["level0_center_x_px"])
' "$QC_DIR/candidates/technical_patch_candidates.csv" "$CANDIDATE_RANK")

CENTER_Y=$(uv run --frozen python -c '
import csv, sys
with open(sys.argv[1], newline="", encoding="utf-8") as f:
    rows = [r for r in csv.DictReader(f) if int(r["rank"]) == int(sys.argv[2])]
if len(rows) != 1:
    raise SystemExit("Select one existing candidate rank")
print(rows[0]["level0_center_y_px"])
' "$QC_DIR/candidates/technical_patch_candidates.csv" "$CANDIDATE_RANK")

uv run --frozen python src/extract_patch.py \
  "$WSI_PATH" \
  "${MPP_ARGS[@]}" \
  --center-x "$CENTER_X" \
  --center-y "$CENTER_Y" \
  --size 512 \
  --target-mpp "$PATCH_MPP" \
  --output "$PATCH_PATH"
```

`$PATCH_PATH` を開き、背景・大きなアーチファクト・パッチ境界を確認します。同名の `.json` には元画像の MPP、中心座標、切り出し範囲、リサンプリング前のサイズなどが保存されます。

512 px × 0.25 µm/px の視野は128 µm四方です。ただしリサンプリングしても元画像にない微細構造は増えません。`0.25 µm/px` の出力を作ったことを「40倍で撮影した」と言い換えないでください。

発表用の一言：**「技術的な候補を目で確認し、物理的な尺度を指定して1枚の画像に切り出します。」**

## ⑤ 核セグメンテーション：学習済み HoVer-Net を使う

```bash
uv run --frozen --project tools/hovernet python tools/hovernet/run_hovernet.py \
  "$PATCH_PATH" \
  --mpp "$PATCH_MPP" \
  --device auto \
  --batch-size 1 \
  --output-dir "$HOVERNET_DIR"
```

`hovernet_fast-pannuke` の学習済み重みを使い、新たなモデル学習はしません。このリリースではモデルの入出力尺度に合わせ、`--mpp 0.25` のみを受け付けます。別の尺度の画像に `0.25` と指定しても画像が正しくなるわけではありません。同名のパッチ `.json` が存在する場合は、その尺度との一致も確認します。

初回はモデル重みが `models/hovernet/` に取得されます。重みには独立した利用条件があります。[第三者ソフトウェア・モデルの注意事項](../THIRD_PARTY_NOTICES.md)を確認し、重みをこのリポジトリへコミットしないでください。

`--device auto` は使用可能なら CUDA、次に Apple MPS、どちらもなければ CPU を選びます。選択されたデバイスはターミナルに出ます。環境による差があるため、講演前に実機で確認してください。MPS などで問題が出た場合は、新しい出力先に変更して `--device cpu` で試せます。CPU で高速に処理できることを保証するものではありません。

TIAToolbox はこの1枚の画像を内部でさらにタイルに分けて処理し、輪郭をつなぎ合わせます。そのため「512 px の画像1枚＝ニューラルネットワークの入力1回」とは限りません。

結果は AnnotationStore の `.db`（SQLite）と `hovernet_run.json` です。`.db` のファイル名を推測せず、実際の記録から取得します。

```bash
NUCLEI_DB=$(uv run --frozen python -c '
import json, sys
from pathlib import Path
m = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
p = Path(m["annotation_store_db"])
if not p.is_file():
    raise SystemExit("Recorded AnnotationStore does not exist")
print(p)
' "$HOVERNET_DIR/hovernet_run.json")
```

発表用の一言：**「学習済み AI が個々の核の輪郭を推定します。膀胱癌での正解が保証された分類ではありません。」**

## ⑥ 特徴量の計算：核ごとの数値を CSV にする

```bash
uv run --frozen --project tools/hovernet python tools/hovernet/extract_nuclear_features.py \
  "$NUCLEI_DB" \
  --patch "$PATCH_PATH" \
  --mpp "$PATCH_MPP" \
  --output-dir "$HOVERNET_DIR/features"
```

**ここで指定する MPP は元 WSI ではなく、HoVer-Net に渡したパッチの MPP です。** 以下が `$HOVERNET_DIR/features` に保存されます。

| ファイル | 内容 |
|---|---|
| `nuclear_features.csv` | 1行＝1核。面積、長径、短径、方向、円形度、solidity、品質確認フラグなど |
| `nuclear_feature_summary.csv` | このパッチの核をまとめた1行の記述統計。症例全体の特徴量ではない |
| `nucleus_type_counts.csv` | モデルが推定した型ラベルごとの核数 |
| `nuclei_overlay.png` | パッチに核輪郭を重ねた確認画像。⑤の結果を⑥で可視化したもの |
| `feature_metadata.json` | 尺度、入力、特徴量定義、色などの記録 |

このコマンドの既定では、パッチ境界に接する核もフラグ付きで残します。境界核を除外する方針を選んだ場合は、次のように別の出力先へ作成します。`--exclude-edge` は CSV・サマリー・型別核数・重ね合わせ画像のすべてに適用されます。集約結果を見てから都合よく選び直さず、研究では採用方針を事前に決めてください。

```bash
uv run --frozen --project tools/hovernet python tools/hovernet/extract_nuclear_features.py \
  "$NUCLEI_DB" \
  --patch "$PATCH_PATH" \
  --mpp "$PATCH_MPP" \
  --exclude-edge \
  --output-dir "$HOVERNET_DIR/features_exclude_edge"
```

列の正確な意味と集約時の注意は [FEATURES.md](FEATURES.md) に記載しています。色はモデルの推定型に対応します。赤だから確実に癌細胞、青だから確実に炎症細胞と扱うことはできません。

発表用の一言：**「核の輪郭から面積や形を計算し、解像度を使って物理単位へ変換します。」**

## デモの次に必要なこと

研究へ発展させる場合は、目的に合った腫瘍 ROI の確認、複数領域の抽出、核輪郭の精度検証、境界核・不適切な核の扱い、症例単位の集約方法を事前に決めます。複数パッチには同じ核の重複や選択偏りも生じます。HistoQC を通った1パッチを、その患者の腫瘍全体の代表として扱わないでください。

WSI・パッチ・核輪郭・CSV・実行 JSON は研究データとして扱います。出力の一部にはローカルの絶対パスが記録されるため、匿名化済み画像でもそのまま公開してよいとは限りません。公開前に内容と利用許諾を別途確認してください。
