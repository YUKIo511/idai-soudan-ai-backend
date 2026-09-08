"""コマンドラインエントリ:  python -m kb.cli <command> ...

  validate <slug|--all>              スキーマ + 参照整合チェック
  build    <slug|--all>              JSON → knowledge/chunks.jsonl
  embed    <slug|--all> [--keep]     chunks.jsonl → Embedding → Vector Store
  reindex                            characters/index.json 再生成
  retrieve <slug> "<query>" [opts]   #15 デバッグ: 取得 Knowledge を表示
  ask      <slug> "<question>" [opts] フルパイプライン（検索→人格適用→生成）
  stats    <slug|--all>              Vector Store の登録件数
  benchmark <slug> "<q>" [--model M] [--runs N]  速度計測（retrieval/first_token/generation/total）
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from .config import load_settings
from .indexer import Indexer
from .validate import validate_character
from .build import run_build, build_summary
from .embed import run_embed
from .retrieve import Retriever
from .answer import Consultant
from .llm import LLMUnavailableError


def _targets(idx: Indexer, slug: str | None, all_: bool) -> list[str]:
    if all_:
        return idx.list_characters()
    if not slug:
        sys.exit("slug か --all を指定してください")
    return [slug]


def _csv(v: str | None) -> list[str] | None:
    return [x.strip() for x in v.split(",") if x.strip()] if v else None


def cmd_validate(args, settings):
    idx = Indexer(settings.characters_dir)
    rc = 0
    for slug in _targets(idx, args.slug, args.all):
        problems = validate_character(slug, settings)
        if problems:
            rc = 1
            print(f"[NG] {slug}: {len(problems)} 件")
            for p in problems:
                print(f"   {p}")
        else:
            print(f"[OK] {slug}")
    sys.exit(rc)


def cmd_build(args, settings):
    idx = Indexer(settings.characters_dir)
    for slug in _targets(idx, args.slug, args.all):
        chunks = run_build(slug, settings)
        s = build_summary(chunks)
        print(f"[build] {slug}: {s['total']} チャンク  除外(rag_include=false)={s['rag_excluded']}")
        print("        " + "  ".join(f"{t}:{n}" for t, n in sorted(s["by_type"].items())))


def cmd_embed(args, settings):
    idx = Indexer(settings.characters_dir)
    for slug in _targets(idx, args.slug, args.all):
        r = run_embed(slug, settings, reset=not args.keep)
        print(f"[embed] {slug}: {r['embedded']} 件登録  store_count={r['store_count']}")
        print(f"        embedding = {r['embedding']}")
        print(f"        store     = {r['vectorstore']}")
        if r["rag_excluded"]:
            print(f"        除外       = {', '.join(r['rag_excluded'])}")


def cmd_reindex(args, settings):
    idx = Indexer(settings.characters_dir)
    from .build import load_chunks
    chars = []
    for slug in idx.list_characters():
        m = idx.manifest(slug)
        raw = idx.load_raw(slug)
        counts = {}
        from .indexer import ARRAY_FILES
        for fname, (ctype, key) in ARRAY_FILES.items():
            if fname in raw:
                counts[ctype] = len(raw[fname].get(key, []))
        if "personality.json" in raw:
            counts["personality_trait"] = len(raw["personality.json"].get("traits", []))
        if "sources.json" in raw:
            counts["sources"] = len(raw["sources.json"].get("sources", []))
        chars.append({
            **{k: m.get(k) for k in ["slug", "display_name", "one_line", "era", "birth_year",
                                     "death_year", "nationality", "occupations", "tags",
                                     "language_primary", "status"]},
            "counts": counts,
            "kb": m.get("kb", {}),
        })
    out = settings.characters_dir / "index.json"
    out.write_text(json.dumps({"_note": "kb.cli reindex による生成物。手で編集しない。",
                               "characters": chars}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[reindex] {out}  ({len(chars)} 名)")


def cmd_retrieve(args, settings):
    r = Retriever(settings)
    report = r.retrieve(
        args.slug, args.query, k=args.k,
        themes=_csv(args.themes), people=_csv(args.people),
        reliability=_csv(args.reliability), types=_csv(args.type),
        multi_query=(None if args.multi_query is None else args.multi_query),
    )
    if args.json:
        from dataclasses import asdict
        print(json.dumps({
            "query": report.query, "character": report.character, "filters": report.filters,
            "pool_size": report.pool_size,
            "expanded_queries": report.expanded_queries,
            "kept": [asdict(k) for k in report.kept],
            "dropped": [[asdict(k), why] for k, why in report.dropped],
            "below_cutoff": [asdict(k) for k in report.below_cutoff],
        }, ensure_ascii=False, indent=2))
    else:
        print(report.to_text())


def cmd_ask(args, settings):
    c = Consultant(settings)
    print(f"[LLM] provider={c.llm.name} model={c.llm.model or '-'} "
          f"base_url={getattr(c.llm, 'base_url', '-')} answer_style={settings.answer_style}",
          file=sys.stderr)
    try:
        res = c.consult(
            args.slug, args.question, k=args.k,
            themes=_csv(args.themes), people=_csv(args.people),
            reliability=_csv(args.reliability), types=_csv(args.type),
        )
    except LLMUnavailableError as e:
        # Fake へフォールバックせず、明示的にエラー終了
        sys.exit(f"\n[LLM エラー] {e}")
    if args.show_knowledge:
        print(res.report.to_text())
        print()
    if args.show_prompt:
        print("#" * 100)
        print("SYSTEM PROMPT")
        print("#" * 100)
        print(res.system_prompt)
        print("#" * 100)
        print("USER PROMPT")
        print("#" * 100)
        print(res.user_prompt)
        print()
    print("=" * 100)
    print(f"回答（{res.character} / LLM={res.llm_provider}:{res.llm_model} / Knowledge {len(res.report.kept)}件）")
    print("=" * 100)
    print(res.answer)


def cmd_stats(args, settings):
    idx = Indexer(settings.characters_dir)
    from .vectorstore import get_vector_store
    store = get_vector_store(settings)
    for slug in _targets(idx, args.slug, args.all):
        total = store.count(slug)
        by_type = {}
        for t in ["profile", "timeline", "achievement", "failure", "quote", "statement",
                  "philosophy", "personality", "relationship", "episode", "work", "context", "criticism"]:
            n = store.count(slug, {"type": t})
            if n:
                by_type[t] = n
        print(f"[stats] {slug}: {total} 件  " + "  ".join(f"{k}:{v}" for k, v in by_type.items()))


def cmd_benchmark(args, settings):
    """速度計測: retrieval / first_token / generation / total を測る。

    python -m kb.cli benchmark steve_jobs "大学を辞めて起業するか迷っています" [--model qwen3:4b] [--runs 2] [--k 6]
    """
    import time
    from .answer import Consultant
    from .llm import LLMMessage, LLMUnavailableError
    from .llm.ollama_provider import OllamaLLMProvider

    con = Consultant(settings)

    prov = getattr(args, "provider", None)
    if prov == "cloudflare":
        from .llm.cloudflare_provider import CloudflareLLMProvider
        c = settings.cloudflare_options()
        if not settings.cloudflare_account_id or not settings.cloudflare_api_token:
            sys.exit("CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN が未設定です（.env）")
        llm = CloudflareLLMProvider(
            model=args.model or settings.cloudflare_model,
            account_id=settings.cloudflare_account_id,
            api_token=settings.cloudflare_api_token,
            temperature=c.get("temperature"),
            max_tokens=c.get("max_tokens"),
            request_timeout=float(c.get("request_timeout", 60)),
        )
    elif args.model:
        o = settings.ollama_options()
        llm = OllamaLLMProvider(
            model=args.model, base_url=settings.ollama_base_url,
            keep_alive=o.get("keep_alive"), num_ctx=o.get("num_ctx"),
            num_predict=o.get("num_predict"), temperature=o.get("temperature"),
            think=o.get("think"), no_think_prefill=o.get("no_think_prefill", ""),
            stop=o.get("stop"), request_timeout=float(o.get("request_timeout", 600)),
        )
    else:
        llm = con.llm

    print(f"model={llm.model}  provider={llm.name}  answer_style={settings.answer_style}")

    for run in range(1, (args.runs or 2) + 1):
        t0 = time.perf_counter()
        report, system, user, tm = con._retrieve_and_build(args.slug, args.question, k=args.k)
        t1 = time.perf_counter()

        prefill = getattr(llm, "no_think_prefill", "") if getattr(llm, "_use_prefill", lambda: False)() else ""
        first = None       # 最初の「生成」トークン（prefill は除外）
        chars = 0
        stats: dict = {}
        try:
            for i, delta in enumerate(llm.stream_chat(system, [LLMMessage("user", user)], stats=stats)):
                if first is None and not (i == 0 and delta == prefill):
                    first = time.perf_counter()
                chars += len(delta)
        except LLMUnavailableError as e:
            sys.exit(f"\n[LLM エラー] {e}")
        t2 = time.perf_counter()

        load_s = (stats.get("load_duration") or 0) / 1e9
        peval_s = (stats.get("prompt_eval_duration") or 0) / 1e9
        eval_s = (stats.get("eval_duration") or 0) / 1e9
        ecount = stats.get("eval_count") or 0
        toks = ecount / eval_s if eval_s else 0
        ft = f"{first - t1:.2f}s" if first else "-"
        gen_s = (t2 - first) if first else 0.0
        pf_note = f"  (prefill '{prefill}' は即時表示)" if prefill else ""
        print(f"run {run}: retrieval={t1 - t0:.2f}s  first_token={ft}{pf_note}  "
              f"generation={gen_s:.2f}s  total={t2 - t0:.2f}s")
        print(f"        chunks={tm['retrieved_chunk_count']}  prompt_chars={tm['prompt_char_count']}  "
              f"prompt_tokens={stats.get('prompt_eval_count')}  answer_chars={chars}")
        print(f"        [ollama] load={load_s:.2f}s  prompt_eval={peval_s:.2f}s  eval={eval_s:.2f}s  "
              f"eval_count={ecount}  gen_tok/s={toks:.1f}  done_reason={stats.get('done_reason')}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="kb.cli")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_slug(sp, all_=True):
        sp.add_argument("slug", nargs="?")
        if all_:
            sp.add_argument("--all", action="store_true")

    sp = sub.add_parser("validate"); add_slug(sp); sp.set_defaults(func=cmd_validate)
    sp = sub.add_parser("build"); add_slug(sp); sp.set_defaults(func=cmd_build)
    sp = sub.add_parser("embed"); add_slug(sp); sp.add_argument("--keep", action="store_true",
        help="既存の登録を消さずに upsert"); sp.set_defaults(func=cmd_embed)
    sp = sub.add_parser("reindex"); sp.set_defaults(func=cmd_reindex)

    for name in ("retrieve", "ask"):
        sp = sub.add_parser(name)
        sp.add_argument("slug")
        sp.add_argument("query" if name == "retrieve" else "question")
        sp.add_argument("--k", type=int, default=None)
        sp.add_argument("--themes"); sp.add_argument("--people")
        sp.add_argument("--reliability"); sp.add_argument("--type")
        if name == "retrieve":
            sp.add_argument("--multi-query", dest="multi_query", action="store_const", const=True, default=None)
            sp.add_argument("--no-multi-query", dest="multi_query", action="store_const", const=False)
            sp.add_argument("--json", action="store_true")
            sp.set_defaults(func=cmd_retrieve)
        else:
            sp.add_argument("--show-knowledge", action="store_true")
            sp.add_argument("--show-prompt", action="store_true")
            sp.set_defaults(func=cmd_ask)

    sp = sub.add_parser("stats"); add_slug(sp); sp.set_defaults(func=cmd_stats)

    sp = sub.add_parser("benchmark")
    sp.add_argument("slug")
    sp.add_argument("question")
    sp.add_argument("--provider", default=None, choices=["cloudflare"],
                    help="計測するプロバイダを一時上書き（例: cloudflare）")
    sp.add_argument("--model", default=None,
                    help="モデルを一時上書き（Ollama 例: qwen3:4b / Cloudflare 例: @cf/qwen/qwen2.5-7b-instruct）")
    sp.add_argument("--k", type=int, default=None, help="LLM へ渡すチャンク数（既定は config の retrieval.k）")
    sp.add_argument("--runs", type=int, default=2, help="実行回数（keep_alive の効果を見る）")
    sp.set_defaults(func=cmd_benchmark)

    args = p.parse_args(argv)
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    settings = load_settings()
    args.func(args, settings)


if __name__ == "__main__":
    main()
