# 偉人相談AI

好きな偉人を選び、その人物の人生・思想・実績・失敗・人間関係・時代背景に基づいて人生相談ができるサービス。
単なる人格模倣ではなく、「その人物が残した知識・経験・思想から、この相談にどう答えるか」を推論する。

## 現在の状態

- `DESIGN.md` — アーキテクチャ・技術スタック・RAG設計・信頼性ポリシー・偉人追加フロー
- `schemas/` — JSON Schema（1ファイル = spec の1セクション）
- `characters/_template/` — 新規偉人のひな形
- `characters/steve_jobs/` — サンプル（構造の実例）
- `kb/` — **RAGパイプライン実装済み**（Indexer → Chunker → Embedding → Vector Store → 検索 → 人格適用 → 回答生成）
- `api/` — **FastAPI 実装済み**（`GET /characters`, `GET /characters/{slug}`, `POST /consult`, `POST /consult/stream` SSE）
- `web/` — **スマホファースト SPA 実装済み**（ビルド不要・PWA 構造・一覧 / 詳細 / チャット）

## RAGパイプライン（`kb/`）

```
python -m kb.cli validate <slug>            # スキーマ + 参照整合チェック
python -m kb.cli build    <slug>            # JSON → characters/<slug>/knowledge/chunks.jsonl
python -m kb.cli embed    <slug>            # chunks.jsonl → Embedding → Vector Store
python -m kb.cli reindex                    # characters/index.json 再生成
python -m kb.cli retrieve <slug> "<query>"  # 取得 Knowledge をデバッグ表示（出典・スコア・採否理由）
python -m kb.cli ask      <slug> "<question>" [--show-knowledge] [--show-prompt]
python -m kb.cli stats    <slug>
```
`<slug>` の代わりに `--all` で全偉人。`retrieve` / `ask` は `--k`, `--themes a,b`, `--people x`,
`--reliability primary,secondary_reliable`, `--type quote,failure` でフィルタ可能。

### プロバイダ切替（`config.yaml` / 環境変数）

| 層 | 既定（オフライン） | 切替先 |
|---|---|---|
| Embedding | `fake`（feature hashing 256次元） | `openai` / `voyage`（+ SDK と API キー） |
| Vector Store | `memory`（numpy コサイン、`.vectorstore/`） | `chroma`（`pip install chromadb`） |
| LLM | `fake`（プロンプトと採用 Knowledge を可視化） | **`ollama`（ローカル LLM・無料・APIキー不要）** / `anthropic` / `openai` |

環境変数 `KB_EMBEDDINGS_PROVIDER` / `KB_VECTORSTORE_BACKEND` / `KB_LLM_PROVIDER` / `KB_OLLAMA_MODEL` / `KB_OLLAMA_BASE_URL` / `KB_ANSWER_STYLE` で一時上書き。
抽象化は `kb/embeddings/base.py` `kb/vectorstore/base.py` `kb/llm/base.py`。実装差し替えで他は不変。

**ローカル LLM（Ollama）で実際の回答文を生成する手順は [OLLAMA_SETUP.md](OLLAMA_SETUP.md) を参照。**
`llm.answer_style`（**`dialogue` 既定** / `advisor` / `embody`）で応答スタイルを切替:
`dialogue`＝偉人本人として短く対話（一人称「私」、過去は過去形、共感→経験1つ→助言1つ→質問で締める、120〜180字）／
`advisor`＝第三者アドバイザーが思想を参照して助言（300〜500字）／`embody`＝一人称の長文。
人物ごとの口調は `profile.json > speaking_style`（`first_person` / `sentence_length` / `dialogue_style` / `persona_tone`、いずれも任意）で調整可。

### 信頼性の扱い（回答生成）

- `reliability` でスコア減衰（`retrieval.reliability_weights`）。`drop_reliability` で完全除外も可。
- 名言は `attribution_status` で減衰（`misattributed` / `apocryphal` は大幅減）＋ プロンプトで「本人の言葉として引用しない」ルールを明示。
- エピソードは `authenticity` で減衰。
- `rag_include: false` のエントリは embed 時に登録せず、検索でも除外。
- 取得結果は `source_file` / `entry_pointer`（例 `/quotes/3`）/ `source_ids` を保持し追跡可能。

## Web アプリ（`api/` + `web/`）

```
pip install -r requirements.txt -r api_requirements.txt
python -m kb.cli build steve_jobs && python -m kb.cli embed steve_jobs && python -m kb.cli reindex
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
```
- PC で `http://localhost:8000`、スマホは同じ Wi-Fi で `http://<PCのLAN IP>:8000`。
- フロントは FastAPI が同一オリジンで配信（`web/` を `/` にマウント）。CORS 不要・PWA 可。

### エンドポイント

| メソッド・パス | 内容 |
|---|---|
| `GET /characters` | 偉人一覧（`characters/index.json` を読む。1000人規模でも O(1) ファイル読取） |
| `GET /characters/{slug}` | 人物紹介・生涯・実績・思想・代表的な名言（`verified`/`likely` のみ） |
| `POST /consult` | `{character, message}` → `{answer, knowledge[], disclaimer, …}`。既存 `Consultant.consult()` を実行 |
| `POST /consult/stream` | SSE: `event: knowledge` → `event: delta`（逐次）→ `event: done` |
| `GET /healthz` | プロバイダ構成・偉人数 |
| `POST /admin/reload` | reindex 後にキャッシュ破棄（`KB_ADMIN_TOKEN` で保護、任意） |

### セキュリティ

- LLM API 呼び出しはバックエンドのみ。API キーは環境変数（`ANTHROPIC_API_KEY` 等）。`api/.env.example` 参照。
- フロントは Knowledge Base を一切持たない。`/consult` が返す `knowledge[]` は出典要約のみ。
- ユーザー入力は制御文字除去・長さ制限のうえ、**system prompt ではなく user メッセージ**として渡る（`kb.prompts` のシステム側ルールで帰属・信頼性を強制）。
- 未処理例外はスタックトレースを返さず `500 {"detail": "内部エラー"}`。

### 拡張性・PWA

- 新しい偉人: JSON 追加 → `validate → build → embed → reindex` → プロセス再起動か `POST /admin/reload` で一覧・詳細・RAG・相談すべてに自動反映。
- `web/sw.js`: アプリシェルをキャッシュ、`/characters` は network-first、`/consult` はキャッシュしない。
- `web/manifest.webmanifest`: `display: standalone`。将来のストア展開に耐える構成。

### kb/ への変更（追加のみ・既存関数は不変）

`kb/llm/*` に `stream_chat()`、`kb/answer.py` に `Consultant.consult_stream()` / `prepare()` を追加。
`chat()` / `consult()` を含む既存の検索・チャンク・埋め込みロジックは変更していない。

### テスト

```
python -m tests.test_api      # pytest 不要（TestClient ベース、8ケース）
```

## ディレクトリ

| パス | 内容 |
|---|---|
| `schemas/` | データ構造の定義。`common.schema.json` を全スキーマが参照 |
| `characters/<slug>/` | 偉人1人の知識ベース（`*.json`）。これが Source of Truth |
| `characters/<slug>/knowledge/` | ビルド生成物（チャンク）。コミット任意 |
| `characters/index.json` | 全 manifest の集約（生成物） |
| `kb/` | 検証・チャンク化・Embedding・検索・回答（後段） |

## 偉人の追加

```
cp -r characters/_template characters/<slug>
# sources.json に出典を登録 → 各 *.json を埋める
python -m kb.validate <slug>     # スキーマ検証＋参照整合
python -m kb.build <slug>        # chunks.jsonl 生成
python -m kb.embed <slug>        # Embedding＋ベクトルDB
python -m kb.reindex             # index.json 再生成 → 一覧に自動表示
```

詳細は `DESIGN.md` §6。

## 信頼性の原則

- 事実を書く前に `sources.json` へ出典を登録する。
- すべての情報に `reliability`（primary / secondary_reliable / common_knowledge / uncertain / legend）を付ける。
- 名言は `attribution_status` 必須。`misattributed` / `apocryphal` は保持するが本人の言葉としては使わせない。
- 史料から確認できない内心を事実として書かない。

## スキーマ検証（参考）

```
pipx install check-jsonschema
check-jsonschema --schemafile schemas/profile.schema.json characters/steve_jobs/profile.json
```
`$ref` のクロスファイル解決には `schemas/` をベースディレクトリに解決するローダーが要る（`kb/validate.py` で実装予定）。
