# ローカル LLM（Ollama）で回答生成する

Claude / OpenAI などの有料 API を使わず、PC 上の Ollama（無料・ローカル）で
偉人の RAG 知識をもとに実際の相談回答文を生成するための手順。

```
iPhone (Expo Go) → FastAPI → RAG Retriever → 関連チャンク
                 → Consultant / system prompt → OllamaLLMProvider → ローカル LLM → 回答
```

`llm.provider` を `fake` ↔ `ollama` ↔ `anthropic` ↔ `openai` で切り替えるだけ。
既存の `FakeLLMProvider` はそのまま残っている（通信テスト用）。

スマホは `POST /consult/stream`（SSE）で生成トークンを逐次受信し、ChatGPT のように
文字が少しずつ表示される。`POST /consult`（非ストリーミング）も残っている。

---

## 速度について（重要 / GPU なしの場合）

CPU 推論では待ち時間の主因は **prompt_eval（プロンプト処理）** で、モデルが大きいほど遅い。
本実装で入れた対策:

| 対策 | 効果 |
|---|---|
| ストリーミング（`/consult/stream`）| 全文完成を待たず、生成中の文字がすぐ出る |
| プロンプト圧縮（9,300字 → 約2,800字、chunk 10→5件、各chunk 180字上限）| prompt_eval を短縮 |
| system プロンプトを「不変部分→\<knowledge\>」の順に配置 | Ollama のプレフィックスキャッシュが効く |
| `warmup_on_start` + `warmup_characters` | 起動時にモデルロード＋その偉人の不変プレフィックスをキャッシュ化 → 最初の相談の prompt_eval が「可変部分だけ」に |
| `keep_alive: 30m` | 応答後もメモリ常駐。2回目以降ロード不要 |
| `no_think_prefill`（assistant プレフィル）| qwen3:4b/1.7b の「思考の垂れ流し」を止める最終手段（後述） |
| `think: false` ＋ `/no_think` | 思考出力を抑制（回答トークンを無駄にしない） |
| `num_predict: 340` | 回答を約300〜450字に制限し生成時間を抑える |
| 末尾ゴミ除去 | 弱いモデルが本文の後に付ける「（499字）」「※注記」「英語の独り言」を自動で切り落とす |

### qwen3 の「思考の垂れ流し」対策（Ollama 0.33 系）

Ollama **0.33.3（現時点の最新安定版）でも**、qwen3:4b / qwen3:1.7b は `think:false` を渡しても
英語の思考メモを回答本文に垂れ流す（qwen3:8b は比較的まとも）。これは Ollama のチャットテンプレートの
既知の挙動。対策として **assistant ロールを短い定型句で prefill** し、モデルを「回答の続き」から
書き始めさせて思考フェーズをスキップさせている（`config.yaml` の `llm.ollama.no_think_prefill`）。
回答は必ずこの語（既定「ご相談ありがとうございます。」）で始まる。qwen3:8b では不要なので `""` にしてよい。

### モデル別の目安（この PC：CPU のみ、プロンプト約1,900トークン）

| | first token（初回/コールド）| first token（プレフィックス温済み）| 生成速度 | 品質 |
|---|---|---|---|---|
| **qwen3:4b（既定）** | 約 30〜55s | 約 6〜10s | 約 7 tok/s（約50s で500字）| 良好・RAG忠実・自然 |
| qwen3:8b | 約 90〜125s | 約 8〜15s | 約 4 tok/s | 最良だが遅すぎる |
| qwen3:1.7b | 約 25〜35s | 約 3〜7s | 約 14 tok/s | **不採用**：`</think>` 混入・回答重複が出る |

いずれの場合も、`no_think_prefill` の定型句は **0.1〜1.5 秒で表示**されるので、体感的な「無反応時間」は短い。

速度は CLI で計測できる:
```powershell
python -m kb.cli benchmark steve_jobs "大学を辞めて起業するか迷っています" --runs 3
python -m kb.cli benchmark steve_jobs "大学を辞めて起業するか迷っています" --model qwen3:8b --runs 3
```

---

## Windows でのセットアップ

### 1. Ollama をインストール
<https://ollama.com/download> から Windows 版を入れる。インストール後、
タスクトレイに Ollama が常駐し `http://localhost:11434` で API が待ち受ける。
（手動起動は PowerShell で `ollama serve`）

### 2. モデルを取得（PowerShell）
```powershell
ollama pull qwen3:8b
```
- **推奨: `qwen3:8b`**（日本語の相談回答に十分な品質、8B）
- PC が重い場合: `ollama pull qwen3:4b`
- さらに軽量: `ollama pull qwen3:1.7b`
- モデル名は設定で変更できる（特定モデルに依存しない実装）。

### 3. 取得済みモデルの確認
```powershell
ollama list
```

### 4. 単体テスト（Ollama だけで動くか）
```powershell
ollama run qwen3:8b
>>> こんにちは。日本語で自己紹介してください。
```
日本語で返ってくれば OK（`/bye` で終了）。

### 5. `config.yaml` を Ollama に切り替え
`C:\偉人相談AI\config.yaml` の `llm:` を編集：
```yaml
llm:
  provider: ollama              # fake → ollama
  answer_style: dialogue        # dialogue=本人と短く対話（既定） / advisor=第三者助言 / embody=一人称の長文
  ollama:
    model: qwen3:8b             # dialogue は 8b が安定。速度優先なら qwen3:4b（口調が荒くなる）
    base_url: http://localhost:11434
    no_think_prefill: "なるほど。"  # 返信の共感の入りを固定＋qwen3 の思考メモ混入を防ぐ
    keep_alive: 30m
    num_ctx: 4096
    num_predict: 260            # dialogue は短いので少なめ
    stop: ["（※", "(※", "（注", "\n[", "\n- ", "\n* ", "</think>", "字）", "字以内", "\n\n\n", "\n---"]
    request_timeout: 600
    warmup_on_start: true
    warmup_characters: ["steve_jobs"]
```

環境変数でも上書きできる（config.yaml より優先）：
```powershell
$env:KB_LLM_PROVIDER   = "ollama"
$env:KB_OLLAMA_MODEL    = "qwen3:8b"
$env:KB_OLLAMA_BASE_URL = "http://localhost:11434"
$env:KB_ANSWER_STYLE    = "dialogue"   # dialogue / advisor / embody
```

### 応答スタイル（answer_style）

| 値 | 話し方 | 長さ | 用途 |
|---|---|---|---|
| **`dialogue`（既定）** | 偉人本人として一人称「私」。過去の出来事は過去形。共感→自分の経験を1つ→短い助言→相手への質問、で締める | 約120〜180字 | スマホの短い対話 |
| `advisor` | 第三者アドバイザーが「{名前}は…という経験をしています」と参照して助言 | 約300〜500字 | じっくり読む相談 |
| `embody` | 本人として一人称で、より長め | 制限ゆるめ | 長文の語り |

人物ごとの口調は `characters/<slug>/profile.json` の `speaking_style` に任意で:
```json
"speaking_style": {
  "first_person": "私",
  "sentence_length": "short",      // very_short | short | medium
  "dialogue_style": "interactive", // interactive | direct | socratic
  "persona_tone": "blunt_passionate"
}
```
（再ビルド不要。次のリクエストから反映される）

### 6. FastAPI を起動
```powershell
cd C:\偉人相談AI
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
```
確認：ブラウザで `http://localhost:8000/healthz` → `{"status":"ok","llm":"ollama",...}`

### 7. Expo を起動
```powershell
cd C:\偉人相談AI\mobile
npx expo start
```
iPhone の Expo Go で開き、steve_jobs を選んで相談する。
スマホ側の API 仕様（`POST /consult`）は変わらない。中身が Fake → Ollama に替わるだけ。

---

## 軽量モデルへの変更

`config.yaml` の `llm.ollama.model` を書き換えて FastAPI を再起動するだけ：

| 用途 | model |
|---|---|
| 標準（推奨） | `qwen3:8b` |
| PC が重い | `qwen3:4b` |
| かなり軽量 | `qwen3:1.7b` |

対応する `ollama pull <model>` を先に実行しておくこと。

---

## 動作確認（steve_jobs）

質問：**「大学を辞めて起業するか迷っています。失敗するのが怖いです。」**

期待される流れ：
1. Retriever が関連チャンクを検索（failures / philosophy / personality / quotes などが上位に入る）
2. Consultant が persona + knowledge + 信頼性ルール入りの system prompt を組み立てる
3. `OllamaLLMProvider.chat()` が `POST http://localhost:11434/api/chat` を呼ぶ
4. ローカル LLM が 300〜700 字程度の自然な日本語で回答（毎回内容が変わる／固定文ではない）
5. `POST /consult` が回答を返す
6. Expo のチャット画面に AI メッセージとして表示される

CLI でも確認できる：
```powershell
python -m kb.cli ask steve_jobs "大学を辞めて起業するか迷っています。失敗するのが怖いです。"
```

---

## エラー時の確認ポイント

| 症状 | 原因と対処 |
|---|---|
| チャットに「Ollama に接続できません…」 | Ollama が起動していない。タスクトレイの Ollama を確認、または `ollama serve`。接続先違いなら `KB_OLLAMA_BASE_URL` / `config.yaml` の `base_url` を確認 |
| 「モデル 'qwen3:8b' が見つかりません。`ollama pull qwen3:8b` を実行してください」 | モデル未取得。`ollama pull qwen3:8b` → `ollama list` で確認 |
| 「Ollama の応答がタイムアウトしました」 | 初回のモデルロードが遅い。先に `ollama run qwen3:8b` でロード、`keep_alive: 30m` を設定、または軽いモデルへ。`request_timeout` を増やす |
| 回答が `【FAKE LLM 出力 …】` のまま | まだ `provider: fake`。`config.yaml` を `ollama` にして **FastAPI を再起動**（設定はプロセス起動時に読む） |
| スマホがサーバーに繋がらない | PC と iPhone が同じ Wi-Fi か、`uvicorn` を `--host 0.0.0.0` で起動しているか、`mobile/src/config/api.ts` の `API_BASE_URL` が PC の LAN IP か |
| 回答が途中で切れる | `max_tokens`（config.yaml の `llm.max_tokens`）を増やす。Ollama では `num_predict` に対応 |
| 回答に `<think>…</think>` が混じる | 通常は自動除去される。残る場合は `config.yaml` の `llm.ollama.think: false` を有効化（新しめの Ollama 必要） |
| FastAPI 起動時に `ModuleNotFoundError: httpx` | `pip install -r requirements.txt`（httpx は FastAPI 同梱のことが多いが未導入なら） |

---

## FakeLLM に戻す

`config.yaml` を `provider: fake` に戻して FastAPI を再起動するだけ。
通信経路のテストや、Ollama を止めているときはこちら。
