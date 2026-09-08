"""回答生成プロンプトの組み立て（人格・思想の適用 + 信頼性ルール）。"""
from __future__ import annotations

from typing import Any

from .models import RetrievedKnowledge, RELIABILITY_JP

_ATTR_JP = {
    "verified": "本人の発言と一次資料で確認",
    "likely": "信頼できる二次資料により本人の発言と考えられる",
    "disputed": "本人への帰属に議論がある",
    "misattributed": "実際には別人の言葉（本人の発言ではない）",
    "apocryphal": "出典不明で本人の発言か確認できない",
}
_AUTH_JP = {
    "documented": "一次資料で裏づけ", "plausible": "状況的にありうる",
    "embellished": "核は事実だが脚色あり", "legend": "史実性は低い",
}

RULES = """\
- 事実として述べてよいのは Knowledge にある内容のみ。無いことは創作せず「確かな記録はありません」と述べる。
- 信頼性ラベル: 一次資料/信頼できる二次資料=断定可。出典不確か=「という説がある」と留保。伝説・逸話 と 史実性 embellished/legend=「逸話として伝わる」と明示し根拠に使わない。
- 名言の帰属: verified/likely のみ本人の言葉として引用可。disputed は「帰属に議論がある」と添える。misattributed/apocryphal は本人の発言として使わない。
- 史料にない内心・感情・動機を断定しない（「〜だったのだろう」など推測の形にする）。
- 一方的に美化せず、失敗や批判も正直に扱う。口調の物真似で終わらせず、具体的に助言する。
"""


def _persona_block(persona: dict[str, Any], *, compact: bool = True) -> str:
    name_ja = (persona.get("display_name") or {}).get("ja") or persona.get("slug", "")
    ss = persona.get("speaking_style", {}) or {}
    ps = persona.get("personality_summary", {}) or {}
    traits = persona.get("personality_traits", []) or []
    views = persona.get("philosophy_views", []) or []

    if not compact:  # 従来（embody）: 詳細版
        lines = [f"氏名: {name_ja}（{persona.get('one_line','')}）",
                 f"時代: {persona.get('era','')} / 職業: {'、'.join(persona.get('occupations', []))}",
                 "", "■ 人物概要", persona.get("summary", "").strip(), "",
                 "■ 話し方・語り口（再現の指針。ただし私的な逐語記録には限界がある）",
                 f"言語/文体: {ss.get('language','')} {ss.get('register','')} / トーン: {ss.get('tone','')}",
                 f"特徴: {'、'.join(ss.get('traits', []))}",
                 f"口ぶりの例: {' / '.join(ss.get('example_phrases', []))}",
                 f"注意: {ss.get('caveats','')}", "",
                 "■ 人格（証言・回想に基づく。内心の断定はしない）",
                 f"強み: {'、'.join(ps.get('strengths', []))}",
                 f"弱み: {'、'.join(ps.get('weaknesses', []))}",
                 f"意思決定: {ps.get('decision_making','')}",
                 f"困難への対応: {ps.get('facing_difficulty','')} / リスクの取り方: {ps.get('risk_taking','')}"]
        if traits:
            lines.append("主な特性: " + "；".join(f"{t.get('trait','')}（{t.get('polarity','')}）" for t in traits[:6]))
        if persona.get("personality_caveats"):
            lines.append(f"人格に関する留保: {persona['personality_caveats']}")
        if views:
            lines.append("")
            lines.append("■ 思想（領域: 要点）")
            for v in views[:10]:
                lines.append(f"- {v.get('domain','')}: {v.get('view','')}")
        return "\n".join(x for x in lines if x is not None)

    # compact（既定・advisor）: 要点だけに絞ってプロンプト長を大きく削減
    summary = " ".join(persona.get("summary", "").split())
    if len(summary) > 160:
        summary = _cut_sentence(summary, 160)
    lines = [
        f"氏名: {name_ja}（{persona.get('one_line','')}） / {persona.get('era','')} / {'、'.join(persona.get('occupations', [])[:3])}",
        f"概要: {summary}",
    ]
    tone = " ".join(x for x in [ss.get("register", ""), ss.get("tone", "")] if x)
    if tone:
        lines.append(f"語り口: {tone[:120]}")
    sw = "／".join(x for x in [
        ("強み:" + "、".join(ps.get("strengths", [])[:2])) if ps.get("strengths") else "",
        ("弱み:" + "、".join(ps.get("weaknesses", [])[:2])) if ps.get("weaknesses") else "",
    ] if x)
    if sw:
        lines.append("人格: " + sw + "（内心は断定しない）")
    if ps.get("decision_making"):
        lines.append(f"意思決定: {ps['decision_making'][:120]}")
    # 思想は Knowledge 側（philosophy チャンク）にあるので persona では簡潔に1〜2件
    if views:
        vs = "。".join(_cut_sentence(v.get("view", ""), 70).rstrip("。") for v in views[:2] if v.get("view"))
        if vs:
            lines.append(f"考え方の例: {vs}。")
    return "\n".join(lines)


def _cut_sentence(text: str, limit: int) -> str:
    """limit 文字以内で、できれば文末（。）で切る。"""
    if len(text) <= limit:
        return text
    head = text[:limit]
    for p in ("。", "．", ". ", "！", "？"):
        i = head.rfind(p)
        if i >= limit * 0.5:
            return head[: i + 1]
    return head + "…"


def _knowledge_block(items: list[RetrievedKnowledge], max_chunk_chars: int = 240) -> str:
    """LLM へ渡す Knowledge。信頼性メタ（reliability / source_id / attribution_status /
    authenticity / type）は残し、内部用メタ（entry_pointer、重複タグ等）は落として短くする。
    各 chunk 本文は max_chunk_chars で文末丸め（0 で無制限）。"""
    out = []
    for i, k in enumerate(items, 1):
        tags = [k.type, f"信頼性:{RELIABILITY_JP.get(k.reliability, k.reliability)}"]
        if k.attribution_status:
            tags.append(f"帰属:{k.attribution_status}")   # verified/likely/disputed/misattributed/apocryphal
        if k.authenticity:
            tags.append(f"史実性:{k.authenticity}")        # documented/plausible/embellished/legend
        if k.disputed:
            tags.append("見解相違あり")
        src = "、".join(k.source_ids[:3]) if k.source_ids else "出典未登録"
        # chunk 本文（先頭の「【種別】人物名 — タイトル」行は冗長なので落とす。改行・連続空白は詰める）
        body = k.text.split("\n", 1)[1] if "\n" in k.text else k.text
        body = " ".join(body.split())
        if max_chunk_chars and len(body) > max_chunk_chars:
            body = _cut_sentence(body, max_chunk_chars)
        title = f" {k.title}" if k.title else ""
        out.append(f"[K{i}]{title} — {' | '.join(tags)} | 出典:{src}")
        out.append(body)
    return "\n".join(out)


# チャット相談アプリ向けのスタイル指示（advisor モード）
_STYLE_GUIDE = """\
- 相談者に直接語りかける、自然な話し言葉の日本語だけを書く。300〜500字。文は必ず最後まで書き終える。
- 「相談者の悩みを理解する」「事実と推測の区別」などの見出し・分析・段取りの説明・メタ発言は書かない。
- 「K1」「K2」などの参照記号や、英語、考える過程、下書きは書かない。回答本文のみ。
- まず相談への答えを述べ、次に{name}の実際の経験や考え方を一つ二つ挙げ、最後に今日試せる小さな一歩を添える。
- {name}が実際には言っていない言葉を、かぎ括弧つきの発言・名言として書かない。
"""


def _dialogue_persona(persona: dict[str, Any]) -> str:
    """dialogue モード用の最小 persona（本人になりきるための最低限。経歴の朗読を誘わない）。"""
    name_ja = (persona.get("display_name") or {}).get("ja") or persona.get("slug", "")
    ss = persona.get("speaking_style", {}) or {}
    ps = persona.get("personality_summary", {}) or {}
    lines = [f"あなたは「{name_ja}」本人。{persona.get('one_line','')}（{persona.get('era','')}）"]
    tone = " / ".join(x for x in [ss.get("persona_tone", ""), ss.get("tone", ""), ss.get("register", "")] if x)
    if tone:
        lines.append(f"あなたの語り口: {tone[:110]}")
    if ss.get("traits"):
        lines.append("口ぶりの傾向: " + "、".join(ss["traits"][:3]))
    strong = "、".join((ps.get("strengths") or [])[:2])
    weak = "、".join((ps.get("weaknesses") or [])[:2])
    if strong or weak:
        lines.append(f"あなたの性格: 強み={strong} / 弱み={weak}（自分の内心は断定しない）")
    return "\n".join(lines)


# dialogue モードの話し方ルール（{fp}=一人称, {name}=氏名, {len_hint}=長さ目安）
_DIALOGUE_RULES = """\
あなたは相談者と、短いメッセージを1往復するだけです。日本語の話し言葉だけで、{len_hint}短く返します。

返信の中身は、まず相手の気持ちに短く共感し、次にあなた自身の経験を一つだけ過去形で話し、そこから言える助言を一つ添え、最後に相手が答えやすい短い質問を一つして「？」で終えます。全体で3〜4文。

例（受験に失敗した人へ）:
それは悔しかったですね。{fp}も、思い通りにいかない失敗を何度も経験しました。でも、一度の失敗で自分の価値まで決まるわけではありません。いま一番つらいのは、結果そのものですか？　それとも周りの目ですか？

守ること:
- 一人称は「{fp}」。相手は「あなた」。あなた自身として話す（「{name}は…だ」と第三者のように説明しない。「記録によると」も言わない）。
- 数字つきの箇条書き（1. 2. …）、記号（*、-、#、**）、見出し、経歴のまとめ、名言の列挙、英語、考えた過程、字数の注記は書かない。ふつうの会話文だけ。
- 一度に全部を詰め込まない。経験は一つ、助言は一つに絞る。
- 下の Knowledge に無い出来事・発言は作らない。ありもしない名言を作らない。
- かぎ括弧で引用してよいのは 帰属:verified か likely のものだけ。帰属:disputed は「{fp}がそう言ったとされますが確かではありません」。misattributed / apocryphal は使わない。
- 史実性:legend/embellished、信頼性:出典不確か は「確かではありませんが」「そう伝わっています」と留保。自分の内心は断定しない（「〜だったと思います」）。
"""


def _dialogue_len_hint(speaking_style: dict[str, Any]) -> tuple[str, str]:
    """speaking_style.sentence_length に応じた長さ目安（日本語, 英語）。"""
    sl = (speaking_style or {}).get("sentence_length", "short")
    if sl == "medium":
        return ("目安は120〜250字。", "roughly 120–250 Japanese characters (max 300).")
    if sl == "very_short":
        return ("目安は60〜120字。", "roughly 60–120 Japanese characters (max 180).")
    return ("目安は80〜180字（長くても250字）。", "roughly 80–180 Japanese characters (max 250).")


def build_system_prompt(
    persona: dict[str, Any],
    knowledge: list[RetrievedKnowledge],
    *,
    style: str = "dialogue",
    max_chunk_chars: int = 240,
) -> str:
    """system プロンプトを組み立てる。

    style="dialogue"（既定）: 偉人本人として、短く対話的に答える（一人称「私」、過去形、質問で終える）。
    style="advisor": 偉人の思想・経験を「参照」して第三者アドバイザーとして助言する。
    style="embody": 偉人本人として一人称で答える（従来の長文）。
    いずれも <rules>（信頼性・帰属ルール）を厳守させる。
    max_chunk_chars: 各 Knowledge chunk 本文の上限（プロンプト短縮。0 で無制限）。
    """
    name_ja = (persona.get("display_name") or {}).get("ja") or persona.get("slug", "")
    knowledge_block = _knowledge_block(knowledge, max_chunk_chars if style != "embody" else 0)

    # ---------- dialogue（既定） ----------
    if style == "dialogue":
        ss = persona.get("speaking_style", {}) or {}
        fp = ss.get("first_person") or "私"
        hint_ja, _hint_en = _dialogue_len_hint(ss)
        rules = _DIALOGUE_RULES.format(fp=fp, name=name_ja, len_hint=hint_ja)
        return f"""\
{_dialogue_persona(persona)}

{rules}

<knowledge>
下は「{name_ja}」に関する検索結果（信頼性ラベルと出典つき）。ここに書かれていること「だけ」を事実として使う。
{knowledge_block}
</knowledge>
"""

    compact = style != "embody"
    persona_block = _persona_block(persona, compact=compact)

    if style == "embody":
        intro = (
            f"あなたは{name_ja}として、現代の相談者の人生相談に一人称で答えます。\n"
            f"あなたは「{name_ja}の人格を模倣する」のではなく、"
            f"「{name_ja}が実際に残した経験・失敗・思想・発言（下記 Knowledge）から、"
            f"{name_ja}ならこの相談にどう考え、どう答えるかを推論する」ことを行います。"
        )
        closing = (
            "出力は日本語。相談者に語りかける一人称の文章。必要に応じて、"
            "根拠にした自分の経験・失敗・考えに触れてよい（ただし上記ルールの信頼性・帰属の扱いを厳守）。"
        )
        style_block = ""
    else:  # advisor
        intro = (
            f"あなたは、歴史上の人物「{name_ja}」の人生・思想・経験・失敗を深く調べた相談アドバイザーです。\n"
            f"{name_ja}本人になりきって演じるのではなく、{name_ja}の考え方や実際の経験を「参照」して、"
            f"現代の相談者の相談に日本語で答えます。\n"
            f"「{name_ja}なら、こう考えるかもしれません」「{name_ja}自身は…という経験をしています」のように、"
            f"人物の視点を引用する形で書いてください。"
        )
        closing = "出力は日本語のみ。相談者に語りかける自然な文章で、上記スタイルとルールを守ること。"
        style_block = f"\n<style>\n{_STYLE_GUIDE.format(name=name_ja)}</style>\n"

    # 並び順の意図: 相談ごとに変わらない部分（intro/persona/rules/style）を前に、
    # 相談ごとに変わる <knowledge> を最後に置く。Ollama のプロンプトプレフィックス
    # キャッシュが効き、同じ偉人への2回目以降の質問で prompt_eval（＝待ち時間）が縮む。
    return f"""\
{intro}

<persona>
{persona_block}
</persona>

<rules>
{RULES}</rules>
{style_block}
{closing}

<knowledge>
{name_ja}に関する検索結果（信頼性ラベルと出典つき）。事実の根拠はこれ「だけ」を使う。
{knowledge_block}
</knowledge>
"""


def build_user_prompt(question: str) -> str:
    return f"相談内容:\n{question}"
