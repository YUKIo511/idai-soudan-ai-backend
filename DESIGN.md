# 偉人相談AI — データ構造・アーキテクチャ設計

## 0. この設計のゴール

- 偉人1人を「表面プロフィール」ではなく **網羅的な人物知識ベース (Knowledge Base / KB)** として表現する。
- すべての情報に **出典と信頼性ラベル** を付け、AIが不確実な情報を事実として断定しないようにする。
- **偉人の追加が容易**（ディレクトリを1つ足してJSONを埋め、ビルドを回すだけ）。
- 100〜1000人規模でも破綻しない。構造化データ（人間が編集する正）と RAG インデックス（機械が生成する派生物）を分離する。

---

## 1. 全体像

```
構造化データ (characters/<slug>/*.json)   ← 人間が編集する Source of Truth
        │  build_kb（チャンク化）
        ▼
チャンク (characters/<slug>/knowledge/chunks.jsonl)  ← 機械生成・Git管理可
        │  embed（プロバイダ抽象）
        ▼
ベクトルDB (Chroma / Qdrant / pgvector)   ← 機械生成・再構築可能
        │  retrieve（character固定 + フィルタ + 信頼性重み）
        ▼
回答生成 (LLM 抽象: Claude / OpenAI)  ← 人格・話し方・信頼性ルールを注入
```

- 構造化データだけが「正」。チャンクとベクトルDBはいつでも作り直せる。
- Git にコミットするのは `*.json` と `manifest.json`。`knowledge/` と `.chroma/` は生成物（コミット任意）。

---

## 2. ディレクトリ構造

```
偉人相談AI/
  DESIGN.md
  README.md
  config.yaml                     # プロバイダ・モデル・DB接続の切替
  schemas/                        # JSON Schema (Draft 2020-12)
    common.schema.json            # 共通定義（信頼性・出典・日付・多言語・entryMeta）
    manifest.schema.json
    profile.schema.json
    timeline.schema.json
    achievements.schema.json
    failures.schema.json
    quotes.schema.json
    statements.schema.json
    philosophy.schema.json
    personality.schema.json
    relationships.schema.json
    episodes.schema.json
    works.schema.json
    historical_context.schema.json
    criticisms.schema.json
    sources.schema.json
  characters/
    index.json                    # 生成物: 全 manifest の集約（一覧API用）
    _template/                    # 新規偉人のひな形（コピーして使う）
      manifest.json
      profile.json
      ...（全ファイル空スケルトン）
    steve_jobs/
      manifest.json
      profile.json
      sources.json                # 出典マスター（他ファイルは source_id で参照）
      timeline.json
      achievements.json
      failures.json
      quotes.json
      statements.json
      philosophy.json
      personality.json
      relationships.json
      episodes.json
      works.json
      historical_context.json
      criticisms.json
      knowledge/                  # 生成物
        chunks.jsonl
        supplement/               # 任意: 長文の生資料（手紙全文・スピーチ全文など .md）
  kb/                             # パイプライン実装（後段）
    validate.py  build.py  embed.py  retrieve.py  answer.py
    llm/  embeddings/  vectorstore/   # それぞれ base.py で抽象化
  api/                            # FastAPI（後段）
```

**1ファイル = spec の1セクション** に対応させ、追加時に「どこに何を書くか」が自明になるようにする。

| ファイル | spec対応 | 役割 |
|---|---|---|
| `profile.json` | §1 | 基本プロフィール、話し方 (`speaking_style`)、常時投入用 `summary` |
| `timeline.json` | §2 | 人生年表。1出来事 = 年/年齢/場所/背景/原因/結果/本人の行動/発言/歴史的意味 |
| `achievements.json` | §3 | 成し遂げたこと。何を/なぜ/どうやって/難しさ/結果/影響 |
| `failures.json` | §4 | 失敗・挫折・判断ミス・対立。`disputed` で見解の割れを明示 |
| `quotes.json` | §5 | 名言。`attribution_status` で本人発言の確実性を必須管理 |
| `statements.json` | §6 | インタビュー/スピーチ/手紙/日記など思想理解の一次資料 |
| `philosophy.json` | §7 | 思想を `domain`（仕事/お金/失敗/死生観…）ごとに。根拠発言へリンク |
| `personality.json` | §8 | 人格。証拠付き `traits` ＋ 断定しないための `caveats` |
| `relationships.json` | §9 | 人間関係。誰と/どんな関係で/いつ/何があったか |
| `episodes.json` | §10 | 有名エピソード。行動/発言/そこから分かる価値観/史実性 |
| `works.json` | §11 | 作品。制作年/内容/背景/目的/影響/評価 |
| `historical_context.json` | §12 | 時代背景。`contrast_with_today` で現代基準の解釈を防ぐ |
| `criticisms.json` | §13 | 当時/現代の評価・批判・論争・倫理的問題 |
| `sources.json` | 情報の信頼性 | 出典マスター。全ファイルが `source_id` で参照 |
| `manifest.json` | 将来目標 | 一覧表示用メタ、ビルド状態、完成度 |

---

## 3. 共通スキーマ要素（`common.schema.json`）

### 3.1 `reliability`（情報単位の信頼性）

| 値 | 意味 | 回答生成での扱い |
|---|---|---|
| `primary` | 一次資料（本人の著作・発言記録・自筆・公式記録） | 断定可 |
| `secondary_reliable` | 信頼できる二次資料（学術伝記・査読論文・主要報道） | 断定可（出典明示が望ましい） |
| `common_knowledge` | 複数の二次資料で一致する周知の事実 | 概ね断定可 |
| `uncertain` | 出典が不確か | 「〜と言われる」等の留保必須 |
| `legend` | 伝説・逸話（史実性が低い／後世の創作の可能性） | 「逸話として伝わる」と明示、事実として使わない |

### 3.2 `sourceRef`（各情報が参照する出典）

```jsonc
{ "source_id": "isaacson_2011", "locator": "chap. 12, p.230",
  "quote": "…原文抜粋…", "url": "https://…", "accessed": "2026-09", "note": "…" }
```

### 3.3 `partialDate`

`YYYY` / `YYYY-MM` / `YYYY-MM-DD`。紀元前は先頭 `-`（ISO 8601 拡張）。不確かなら同階層に `"approx": true`。

### 3.4 `localizedText`

`{ ja, en, original, original_lang }`。名言・作品名・人名で使用。原語原文を必ず保持できる。

### 3.5 `entryMeta`（配列エントリ共通メタ／各スキーマで `allOf` 合成）

```jsonc
{
  "id": "…",                  // ファイル内一意。チャンクIDの素。安定させる（消さない）
  "reliability": "…",         // 必須
  "confidence": 0.0-1.0,      // 任意
  "approx": false,
  "disputed": false,          // 史料間で見解が割れている
  "sources": [ sourceRef, … ],
  "tags": [ … ],
  "themes": [ "仕事", "失敗", "リーダーシップ", "お金", "家族", "死生観", … ],
  "people": [ "steve_wozniak", "John Sculley", … ],   // relationships.json の id か表示名
  "rag_include": true,        // false で Embedding 対象外（内部メモ等）
  "notes": "…"
}
```

`themes` / `people` はRAG検索時のメタデータフィルタに使う。語彙は緩く運用し、`kb/vocab.yaml`（後段）で正規化。

---

## 4. RAG 設計

### 4.1 チャンク化（`build`）

各構造化エントリ → 1つ以上のチャンク。テンプレートで自然文に整形する。

```jsonc
// chunks.jsonl の1行
{
  "id": "steve_jobs/quotes/stay_hungry",
  "character": "steve_jobs",
  "type": "quote",                       // profile|timeline|achievement|failure|quote|statement|philosophy|personality|relationship|episode|work|context|criticism
  "title": "Stay hungry, stay foolish",
  "text": "スティーブ・ジョブズは2005年6月、スタンフォード大学卒業式のスピーチを『Stay hungry, stay foolish（ハングリーであれ、愚か者であれ）』で締めくくった。これは彼が若い頃に愛読した Whole Earth Catalog 最終号の裏表紙の言葉を引用したもの。…",
  "metadata": {
    "reliability": "primary",
    "attribution_status": "verified",     // quote 型のみ
    "confidence": 1.0,
    "date": "2005-06-12",
    "themes": ["生き方", "挑戦", "教育"],
    "people": [],
    "source_ids": ["stanford_2005"],
    "rag_include": true
  }
}
```

### 4.2 検索（`retrieve`）

1. `character` で厳密フィルタ（他人の知識が混ざらない）。
2. クエリを多面展開：人生経験・思想・実績・名言・エピソード・人間関係・時代背景 の観点別にクエリを作り、type ごとに top-k 取得（spec の回答フロー3〜8に対応）。
3. スコアを `reliability` で重み付け（`primary` > `secondary_reliable` > … > `legend`）。`legend` は下限で残す（「逸話」として提示できるように）。
4. `profile.summary` / `personality` サマリ / `philosophy` の該当 domain は常時 or 優先投入。

### 4.3 回答生成（`answer`）

システムプロンプトに注入するもの：

- **人格・話し方**: `profile.speaking_style` ＋ `personality`（証拠付き）＋ 関連 `philosophy`。
- **取得コンテキスト**: 各チャンクに `【信頼性: 一次資料】【出典: isaacson_2011】` を付けて列挙。
- **ルール**（固定文言）:
  - 一次資料／信頼できる二次資料に基づく内容のみ断定してよい。
  - `uncertain` は「確かではないが」、`legend` は「逸話として伝わる」と留保する。
  - `attribution_status` が `verified` / `likely` 以外の名言を、本人の言葉として引用しない。
  - 史料から確認できない内心・感情を事実として述べない。
  - 知らないことは「その点について確かな記録を私は持たない」と述べる。
- **推論の姿勢**: 単なる口調模倣ではなく、「この人物が残した経験・思想・判断基準から、この相談にどう答えるか」を推論する。

---

## 5. 技術スタック提案

要件（Python中心・研究用途、100〜1000人規模、偉人追加の容易さ最優先、LLM両対応）に対する推奨。

| レイヤ | 推奨 | 理由 / 代替 |
|---|---|---|
| 言語 | **Python 3.11+** | 要件。型ヒント・`match` を活用 |
| パッケージ管理 | **uv** | 高速・lockfile・仮想環境一体。代替: Poetry |
| データ検証 | **Pydantic v2** をモデルの正とし、**JSON Schema を自動生成** | 二重管理回避。当面は本リポジトリの手書き JSON Schema を仕様書兼バリデータとして使い、実装時に Pydantic へ移植 |
| スキーマ検証CLI | `check-jsonschema` もしくは `jsonschema`＋`referencing` | `kb/validate.py` から呼ぶ。CI 必須化 |
| Embedding | **抽象化層 `embeddings/base.py`** ＋ 実装3種:<br>OpenAI `text-embedding-3-large` / Voyage `voyage-3`（Anthropic系）/ ローカル `intfloat/multilingual-e5-large` | 多言語（日本語＋原語）対応。`config.yaml` で切替。次元とモデル名を chunks とベクトルDBに記録し、モデル変更時は再構築 |
| ベクトルDB | 初期 **Chroma**（ローカル永続・メタデータフィルタ）→ スケール時 **Qdrant** or **pgvector** | `vectorstore/base.py` で `upsert / query(filter)` を抽象化し移行可能に。1000人・数十万チャンクは Qdrant/pgvector 想定 |
| LLM | **抽象化層 `llm/base.py`** ＋ Claude (`claude-sonnet-5`) / OpenAI (`gpt-*`) | 要件：両対応・切替可能。インタフェースは `chat(messages, system, tools?) -> Message`。ストリーミング対応 |
| オーケストレーション | **自前の薄いパイプライン**（LangChain/LlamaIndex を使わない） | spec が求める多段検索・信頼性重み・人格注入を明示制御したい。デバッグ容易 |
| API | **FastAPI**（後段） | `/characters`、`/characters/{slug}`、`/consult`（SSEストリーム） |
| フロント | **Next.js**（後段） | 偉人選択 → チャット |
| 設定 | `config.yaml` ＋ 環境変数（APIキー） | プロバイダ・モデル・DB・top-k・信頼性重みを一元化 |

`config.yaml` の例:

```yaml
llm:
  provider: anthropic          # anthropic | openai
  model: claude-sonnet-5
embeddings:
  provider: openai             # openai | voyage | local
  model: text-embedding-3-large
  dim: 3072
vectorstore:
  backend: chroma              # chroma | qdrant | pgvector
  path: .chroma
retrieval:
  per_type_k: 4
  reliability_weights: { primary: 1.0, secondary_reliable: 0.85, common_knowledge: 0.7, uncertain: 0.45, legend: 0.25 }
```

---

## 6. 偉人の追加フロー

```
1. cp -r characters/_template characters/<slug>
2. sources.json に出典を登録（先に出典、次に事実）
3. 各 *.json を埋める（部分的でも可。manifest.status = draft/in_progress）
4. python -m kb.validate <slug>        # JSON Schema 検証＋参照整合（source_id / *_id / quote_ids）
5. python -m kb.build <slug>           # chunks.jsonl 生成
6. python -m kb.embed <slug>           # Embedding 生成＋ベクトルDB upsert
7. python -m kb.reindex                # characters/index.json 再生成
→ 一覧APIは index.json を読むので自動表示
```

`kb.build --all` / `kb.embed --all` で全体再構築。`slug` は `^[a-z0-9_]+$`。

### 完成度の扱い

`manifest.json` に `status`（draft→in_progress→reviewed→published）と各ファイルの件数を持つ。`published` 未満はUIで「情報が限定的」表示、回答時も「記録が乏しい」と断りやすくする。

---

## 7. スケール方針（100 → 1000人）

- **偉人単位で完全分離**：ディレクトリ・チャンク・ベクトルDB名前空間（collection or `character` フィルタ）を分ける。追加は他偉人に影響しない。
- **ベクトルDB**：Chroma（〜100人程度の開発）→ Qdrant（本番、collection 1つ＋`character` payload フィルタ、または偉人ごと collection）。
- **Embedding コスト**：チャンクにハッシュを持たせ、変更分のみ再 embed（`kb.embed` は差分更新）。
- **CI**：PR で `kb.validate --all`。出典なし `primary`、`quote` の `attribution_status` 欠落、壊れた `*_id` 参照は落とす。
- **語彙管理**：`themes` / `relation_type` / `domain` は enum もしくは `kb/vocab.yaml` で管理し、フィルタが効くようにする。
- **多言語**：原語原文は必ず保持。Embedding は多言語モデルで日本語クエリ↔原語資料を橋渡し。

---

## 8. 信頼性ポリシー（最重要）

1. **出典を先に**：`sources.json` に無い `source_id` は参照不可（validate で落とす）。
2. **`primary` には `sources` 必須**。
3. **名言は `attribution_status` 必須**：`verified` / `likely` / `disputed` / `misattributed` / `apocryphal`。後2者は保持するが「本人の言葉」としては使わせない（回答ルールで制御、UIでは「誤って帰属されがちな言葉」として表示可）。
4. **内心・感情**は `personality` の証拠付き `traits` に限る。要約フィールドには全体 `caveats` を必ず書く。
5. **見解の割れ**は `disputed: true` ＋ 複数 `sources`＋`notes` に対立点。
6. 回答生成は信頼性ラベルをそのままプロンプトへ渡し、留保表現をモデルに強制する。
