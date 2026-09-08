# RELEASE_STATUS — 偉人相談AI リリース状況

最終更新: 2026-09-08 / 担当: リードエンジニア兼リリース担当

目標: **iPhone TestFlight → App Store 公開**（最短経路・MVP優先）

---

## 1. LLM（回答生成）

| 項目 | 状態 |
|---|---|
| プロバイダ | **Cloudflare Workers AI**（OpenAI 互換 API）接続済み |
| 採用モデル | **`@cf/meta/llama-3.3-70b-instruct-fp8-fast`**（確定） |
| first token | 約 **1.4 秒**（実 uvicorn + `/consult/stream` 実測） |
| total | 約 **2.9 秒**（171字の回答、retrieval 5 chunks 含む） |
| コスト | 約 60 neurons/相談 ≈ **$0.0007**。`max_tokens: 320` で上限管理 |
| dialogue 品質 | 一人称「私」・過去形・80〜180字・質問で締め・RAG忠実・捏造なし を実測で確認 |
| 認証情報 | `CLOUDFLARE_ACCOUNT_ID` / `CLOUDFLARE_API_TOKEN`（**バックエンドの環境変数のみ**。Git・アプリには入れない） |
| ローカル開発 | `provider: ollama` のまま維持。本番のみ `KB_LLM_PROVIDER=cloudflare` で切替 |
| FakeLLM | 本番で使用しない。到達不可時は 503 を返す（Fake へフォールバックしない） |

比較で却下: qwen3-30b-a3b（thinking 垂れ流し）、gemma-4-26b（空応答）。次点: mistral-small-3.1-24b。

---

## 2. 本番バックエンド（Railway）

| 項目 | 状態 |
|---|---|
| デプロイ先 | **Railway**（FastAPI を常駐プロセスで実行） |
| 準備ファイル | `Procfile` / `railway.json` / `.python-version`(3.13) / `requirements.txt`（API依存を統合済み） |
| 起動コマンド | `uvicorn api.main:app --host 0.0.0.0 --port $PORT` |
| ヘルスチェック | `GET /health` → `{"status":"ok","provider":"cloudflare"}`（LLM を動かさない・秘密情報を返さない） |
| RAG データ | `.vectorstore/`（fake embedding・決定論的・約1MB・3人分）を**リポジトリに同梱**。さらに起動時に未生成の偉人を自動 build/embed する保険（`_ensure_rag_index`） |
| MemoryVectorStore の揮発性 | 問題なし。消えても起動時に再構築可能。外部DBは不要 |
| Windows依存 | なし（`pathlib` のみ、OS 固有パス・処理なし）。Linux で動作確認済み |
| デプロイ実行 | **未実施**（Railway ログイン / project 作成 / Variables 入力はユーザー操作） |

### Railway に設定する環境変数（Variables）

| 変数 | 値 | 必須 | 備考 |
|---|---|---|---|
| `KB_LLM_PROVIDER` | `cloudflare` | ✅ | これがないとローカル既定(ollama)になる |
| `CLOUDFLARE_ACCOUNT_ID` | （32桁） | ✅ | 秘密。Git に入れない |
| `CLOUDFLARE_API_TOKEN` | （トークン） | ✅ | 秘密。Workers AI 権限のみ |
| `KB_ENV` | `production` | 推奨 | CORS 警告・本番挙動の切替に使用 |
| `KB_CORS_ORIGINS` | `none` | 推奨 | Web を公開しないならブラウザからの利用を拒否。ネイティブアプリは影響なし |
| `KB_RATELIMIT_PER_MIN` | `20` | 任意 | 1 IP あたり毎分の上限（既定 20） |
| `KB_ADMIN_TOKEN` | （任意の文字列） | 任意 | `POST /admin/reload` を保護したい場合 |
| `PORT` | （Railway が自動注入） | — | 手動設定不要 |

`.env` は**本番では使わない**（`.env` は git 管理外・ローカル開発専用）。Railway は Variables に入れる。

---

## 3. モバイルアプリ（Expo）

| 項目 | 状態 |
|---|---|
| API URL | `EXPO_PUBLIC_API_BASE_URL` で切替。`mobile/src/config/api.ts` から参照 |
| development | `mobile/.env` の `EXPO_PUBLIC_API_BASE_URL`（LAN IP）。git 管理外 |
| production | `eas.json` の `production.env.EXPO_PUBLIC_API_BASE_URL`（Railway の HTTPS URL）※ eas.json は次フェーズで作成 |
| ハードコード撤廃 | `http://192.168.3.30:8000` は `__DEV__` 時のフォールバックのみ。本番ビルドには含まれない |
| 秘密情報 | アプリ内・Expo 環境変数には API URL のみ。キー類は一切なし |
| タイムアウト | 60 秒（Cloudflare は数秒で返るため） |
| ストリーミング | XHR ベース SSE 受信（既存）。変更なし |

---

## 4. セキュリティ（App Store 最低限）

| 対策 | 状態 |
|---|---|
| 相談文の最大文字数 | ✅ 2000字（`clean_user_message`） |
| 空文字拒否 | ✅ 422 |
| LLM max_tokens | ✅ 320（`config.yaml: llm.cloudflare.max_tokens`） |
| タイムアウト | ✅ サーバ 60s（Cloudflare）/ アプリ 60s |
| レート制限 | ✅ 1 IP 毎分 20（`api/ratelimit.py`・固定ウィンドウ・インメモリ）。429 + `Retry-After` |
| 異常連打 | ✅ 上記レート制限で吸収。X-Forwarded-For の先頭 IP で判定 |
| stack trace 秘匿 | ✅ 未処理例外は `500 {"detail":"内部エラーが発生しました"}` のみ |
| secrets をログに出さない | ✅ トークンはログ出力なし（provider 名のみ） |
| 認証・ログイン | v1 では実装しない（不要） |

---

## 5. 動作確認（ローカルの実 uvicorn 経由）

```
GET  /health          → {"status":"ok","provider":"cloudflare"}
GET  /characters      → 3名（einstein / fukuzawa / jobs）
POST /consult/stream  {"character":"steve_jobs","message":"受験で失敗した"}
  → provider=cloudflare  model=@cf/meta/llama-3.3-70b-instruct-fp8-fast
  → first_token 1353ms / total 2931ms / 171字 / sources 5
  → 「それは悔しかったですね。私も、思い通りにいかない失敗を何度も経験しました。
     Apple から追われたことも…すべて私の人生を形作る経験でした。でも、一度の失敗で
     自分の価値まで決まるわけではありません。いま一番つらいのは、結果そのものですか？
     それとも周りの目ですか？」
```

一人称・過去形・短さ・質問締め・RAG忠実 すべて OK。既存テスト `python -m tests.test_api` 8/8 パス。

---

## 6. TestFlight までの残作業

| # | 作業 | 誰 |
|---|---|---|
| 1 | GitHub リポジトリ作成（バックエンドのみ。`mobile/` は `.gitignore` 済み） | ユーザー（承認）+ 実装側（`git init`〜push 手順提示） |
| 2 | Railway で project 作成 → GitHub 連携 → Variables 入力（上表） | **ユーザー** |
| 3 | 初回デプロイ確認（`/health`・`/characters`・`/consult/stream`） | 実装側（URL をもらって検証） |
| 4 | `mobile/app.json` に `ios.bundleIdentifier` / `buildNumber` / EAS `projectId` / 権限整理 | 実装側 |
| 5 | `eas.json`（development / preview / production）作成、`production.env` に Railway URL | 実装側 |
| 6 | About 画面（AI が史料から人物像を再現している旨の開示）+ Settings 画面 | 実装側 |
| 7 | `eas-cli` 導入・EAS ログイン・`eas build --profile production --platform ios` | **ユーザー**（Apple Developer / EAS ログイン） |
| 8 | App Store Connect でアプリ作成・TestFlight 配信 | **ユーザー** |
| 9 | App Store 申請メタデータ（`APP_STORE_CHECKLIST.md` 参照） | 実装側が下書き → ユーザー入力 |

---

## 7. 既知の未対応・注意点

- 偉人は 3 名。公開は 5〜10 名が望ましい（公開を遅らせない範囲で追加）。
- `api/routes/consult.py` の timings ログキーが `ollama_first_token_ms` 等 Ollama 名のまま（値は Cloudflare でも正しい。ラベルのみ）。→ `TODO_RELEASE_LATER.md`
- `web/` SPA が `/` にマウントされたまま（本番でも配信される）。害はないが不要なら外す。→ `TODO_RELEASE_LATER.md`
- Railway hobby プランは 1 レプリカ想定。レート制限・warmup はレプリカ内で完結。
