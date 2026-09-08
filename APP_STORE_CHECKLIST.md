# APP_STORE_CHECKLIST — 偉人相談AI 申請チェックリスト

最終更新: 2026-09-08。App Store Connect 提出までの具体作業。**現行の Apple 要件で確認すること**（ルールは変わる）。

チェック: ☐ 未 / ☑ 済 / ▲ ユーザー操作待ち

---

## A. 事前準備（アカウント・ツール）

- ▲ Apple Developer Program 登録（年 $99）
- ▲ App Store Connect にアプリ枠を作成（Bundle ID を登録）
- ▲ EAS アカウント / `eas-cli` ログイン
- ☐ `mobile/app.json`: `ios.bundleIdentifier`（例 `com.<あなた>.idaisoudanai`）、`ios.buildNumber`、`version`
- ☐ `eas.json`: `production` プロファイル + `env.EXPO_PUBLIC_API_BASE_URL`（Railway URL）
- ☐ EAS `projectId`（`eas init` で発行 → `app.json` の `extra.eas.projectId`）

## B. バックエンド（Railway）※ RELEASE_STATUS.md 参照

- ▲ Railway デプロイ・Variables 設定
- ☐ 本番 URL で `/health` `/characters` `/consult/stream` 動作確認
- ☐ 本番 URL を `eas.json` の `production.env` に記入

## C. アプリ本体（MVP 画面）

- ☑ ホーム / 偉人一覧 / 偉人詳細 / チャット
- ☐ About 画面（**AI 開示**: 「本アプリは史料・伝記・発言記録をもとに AI が人物像を再現しています。故人本人の発言ではありません」）
- ☐ Settings 画面（About へのリンク、プライバシーポリシー URL、問い合わせ先）
- ☐ アプリ内のどこかから About に必ず到達できる導線

## D. アイコン・スクリーンショット・スプラッシュ

- ☐ アプリアイコン 1024×1024（透過なし・角丸なし）
- ☐ iPhone 6.9"（1320×2868 など現行必須サイズ）スクリーンショット 3〜10 枚
- ☐ iPhone 6.5" スクリーンショット（必要なら）
- ☐ スプラッシュ（`expo-splash-screen` 設定済み。ロゴ差し替えは任意）
- ☐ アイコンに実在人物の肖像写真を使わない（権利・肖像権）

## E. App Store 掲載情報（メタデータ）

- ☐ アプリ名（30 字以内、例「偉人相談AI」）
- ☐ サブタイトル（30 字以内、例「歴史上の偉人に人生相談」）
- ☐ 説明文（何ができるか / AI である旨 / 史料ベースである旨）
- ☐ キーワード（100 字、カンマ区切り）
- ☐ プロモーション用テキスト（170 字、任意）
- ☐ カテゴリ（第一: ライフスタイル or 教育、第二: 任意）
- ☐ サポート URL（問い合わせ先ページ。GitHub Pages / Notion 可）
- ☐ マーケティング URL（任意）
- ☐ 著作権表記（例「2026 <あなた>」）

## F. 年齢区分（Age Rating）

- ☐ App Store Connect の質問票に回答
- ☐ AI 生成コンテンツを含む旨（Apple の生成 AI 関連の設問に回答）
- ☐ 想定: 12+（生成テキストのため。実際は質問票の結果に従う）

## G. プライバシー

- ☐ **プライバシーポリシー URL**（必須。静的ページで可）。記載内容:
  - 収集するもの: 相談として入力されたテキスト
  - 送信先と目的: 自社バックエンド（Railway）経由で Cloudflare Workers AI に送信し、回答を生成するため
  - 保存: サーバーで相談内容を永続保存しない（ログに一部が残る場合はその旨）
  - 第三者: Cloudflare（推論処理）。広告・トラッキングは行わない
  - 問い合わせ先
- ☐ **App Privacy（プライバシー栄養ラベル）** 入力:
  - Data Types: 「User Content（その他のユーザーコンテンツ）」= 相談テキスト
  - 用途: App Functionality（機能提供）
  - ユーザーに紐づくか: No（アカウントなし・識別子と結びつけない）
  - トラッキング: No
  - それ以外（連絡先・位置・識別子・購入履歴等）: 収集なし
- ☐ 実際に送っていないデータを「収集」と書かない / 送っているテキストを隠さない
- ☐ アカウント作成機能が無いため「アカウント削除導線」要件は**非該当**（申請ノートに明記）

## H. 権限（Info.plist / app.json）

- ☐ 不要な権限を入れない（カメラ・マイク・位置情報・写真・連絡先など**すべて不要**）
- ☐ `app.json` の `ios.infoPlist` に不要な `NS*UsageDescription` を追加しない
- ☐ プッシュ通知は v1 では使わない（capability を付けない）

## I. 輸出コンプライアンス（暗号化）

- ☐ `app.json` に `ios.config.usesNonExemptEncryption: false` を設定
  （通信は HTTPS のみ・独自暗号なし → 標準の適用除外）
- ☐ App Store Connect の輸出コンプライアンス設問で「独自の暗号化なし」を選択

## J. ビルド & TestFlight

- ▲ `eas build --profile production --platform ios`
- ▲ `eas submit -p ios`（または Transporter で .ipa アップロード）
- ☐ TestFlight で実機インストール → 下記 K を実施
- ☐ App Review 情報: 連絡先、審査用メモ（「バックエンドは常時稼働。AI 回答は Cloudflare Workers AI を使用。ログイン不要」）

## K. 実機テスト（TestFlight ビルドで）

質問 4 種:「受験で失敗した」「大学を辞めて起業しようか迷っている」「親に反対されている」「失敗するのが怖い」

- ☐ 各質問で回答が返る / 一人称「私」 / 過去は過去形 / 80〜180字程度 / 質問で終わる / 捏造なし
- ☐ ストリーミング表示される / 停止・再送が効く
- ☐ 送信直後に UI 反応（入力欄クリア・考え中表示）
- ☐ 連打しても二重送信されない
- ☐ 機内モード → 「ネットワークに接続できません」等の分かるエラー（stack trace は出さない）
- ☐ Wi-Fi → 4G/5G 切替でも動く
- ☐ バックエンド停止時 → 「サーバーに接続できません」表示・クラッシュしない
- ☐ キーボード表示でレイアウトが崩れない / SafeArea OK
- ☐ ダーク前提の配色で表示崩れなし

## L. 申請前 最終

- ☐ バージョン/ビルド番号が App Store Connect と一致
- ☐ 本番ビルドが Railway の HTTPS URL を向いている（LAN IP が含まれない）
- ☐ `console.log` に秘密情報が出ていない
- ☐ プライバシーポリシー URL / サポート URL が公開されアクセス可能
- ☐ 「販売」対象国・価格（無料）設定
- ☐ 提出 → 審査
