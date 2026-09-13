# 非公開から公開へ切り替える前に

このリポジトリは、非公開で準備して所有者の判断で公開する運用です。
公開日時の予約や自動切り替えは行いません。

## 公開前の確認

- [ ] 自作コードの権利・所属施設の公開許可を確認した。
- [ ] 自作コードの利用ライセンスを選ぶか、未付与で公開するかを判断した。
- [ ] `THIRD_PARTY_NOTICES.md` とモデル重みの別条件を確認した。
- [ ] 患者ID、WSI、パッチ、病理画像、実測CSV、発表PPTX、臨床解析ファイルを含めていない。
- [ ] APIキー、トークン、パスワード、個人環境のパス、`.env`を含めていない。
- [ ] 現在のファイルだけでなく、すべてのブランチ・タグ・コミット履歴も確認した。
- [ ] GitHub Actionsのログ・成果物、Issues等にも非公開情報がないことを確認した。
- [ ] 新しい環境でREADMEの手順を確認し、未検証環境や限界を明示した。
- [ ] 入力画像の取得MPPと、モデル用に補間したMPPを区別して説明した。
- [ ] 公開するURLと講演スライドのURL/QRコードが一致している。

ローカルで追跡対象を確認する補助コマンド：

```bash
git status --short
git ls-files
python3 scripts/check_release.py
git log --all --oneline
```

チェッカーは代表的なファイル・文字列パターンを検出する補助です。
匿名化の判定や秘密情報の完全な検出はできません。
通常の追加時は`.gitignore`が保護しますが、`git add -f`やWebアップロードは回避できるため、
送信するファイルそのものを確認してください。

## 公開する当日の操作

所有者がGitHubの対象リポジトリを開き、`Settings`内の`Danger Zone`から
`Change repository visibility`を選び、`Public`への変更を確認します。
画面上の警告を読み、対象名が正しいことを確認してから切り替えます。

公開すると他者が閲覧・複製・forkでき、あとで非公開へ戻しても既存コピーは回収できません。
公開直後はログアウトしたブラウザ等からURLとREADMEの表示を確認してください。
非公開のままでは、講演参加者がURLやQRコードを開いても閲覧できません。

## 公式参考資料

- [GitHub: リポジトリの公開範囲変更](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/managing-repository-settings/setting-repository-visibility)
- [GitHub: ライセンスの設定](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository)
- [GitHub: 秘密情報を誤って記録した場合](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)

Publicにすることと、改変・再配布のオープンソースライセンスを付与することは別です。
