"""Parse the director script and curate `courses/ai-first-sees/narration/scenes.json`.

Source of truth: ``大纲/AI-Agent-入门课/02-逐页脚本.md`` (the 22-shot long version).
Every run re-parses the markdown, so editing the script is the only way to change
the course; this file only carries the editorial decisions:

- The narration is copied verbatim (only whitespace / quote-style normalisation);
  the author marked it as reviewed copy, so do not rewrite sentences here.
- Every scene uses the light paper theme. The user explicitly ruled out dark
  scenes after the first cut; the "black room" metaphor in S17/S19 is drawn as a
  warm paper-cut room, not a dark fill.
- Each act keeps its own accent colour, but paper is the only ground.
- Scene ids, short screen titles, thesis one-liners and keywords are set here.

Outputs:
- ``narration/scenes.from-outline.json``: raw parse, kept for diffing the outline.
- ``narration/scenes.json``: curated manifest consumed by scripts/build_narration.py.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTLINE = ROOT / "大纲" / "AI-Agent-入门课" / "02-逐页脚本.md"
NARRATION_DIR = ROOT / "courses" / "ai-first-sees" / "narration"
PARSED = NARRATION_DIR / "scenes.from-outline.json"
TARGET = NARRATION_DIR / "scenes.json"

CJK = r"\u3400-\u9fff"
CJK_LATIN = re.compile(rf"([{CJK}])([A-Za-z0-9])")
LATIN_CJK = re.compile(rf"([A-Za-z0-9])([{CJK}])")
SPACE_BEFORE_PUNCT = re.compile(r"\s+([，。；：！？、）》」』…”])")
SPACE_AFTER_OPEN = re.compile(r"([（《「『])\s+")
MULTISPACE = re.compile(r"[ \t]{2,}")

SECTION_RE = re.compile(r"^## (S\d{2}) · ([a-z0-9-]+) — (.+?)\s*$", re.MULTILINE)
FIELD_RE = re.compile(r"^- \*\*(?P<name>[^*]+)\*\*：\s*(?P<rest>.*)$")
TOP_FIELD_RE = re.compile(r"^- \*\*[^*]+\*\*：")
QUOTE_RE = re.compile(r"^\s*>\s?(?P<text>.*)$")
HEADING_RE = re.compile(r"^#{1,3} ", re.MULTILINE)

# code -> (id, act, act_label, title, keywords)
META: dict[str, tuple[str, str, str, str, list[str]]] = {
    "S01": ("hook", "prologue", "开场", "三个画面", ["2016", "2022", "2026", "跃迁"]),
    "S02": ("roadmap", "prologue", "开场", "四个字", ["看", "说", "做", "用"]),
    "S03": ("alphago", "watch", "第一幕 · 看", "机器第一次赢在「直觉」", ["AlphaGo", "DeepMind", "4:1", "围棋"]),
    "S04": ("cnn", "watch", "第一幕 · 看", "一层一层的滤镜", ["CNN", "AlexNet", "2012", "特征"]),
    "S05": ("gpt1", "speak", "第二幕 · 说", "文字接龙", ["GPT-1", "117M", "下一个词"]),
    "S06": ("scaling-emergence", "speak", "第二幕 · 说", "规模定律与涌现", ["GPT-2", "GPT-3", "scaling law", "涌现"]),
    "S07": ("chatgpt", "speak", "第二幕 · 说", "只动嘴的顾问", ["ChatGPT", "2022-11-30", "聊天框"]),
    "S08": ("l1-l2", "make", "第三幕 · 做", "聊天框，和工作流", ["L1", "L2", "Coze", "工作流"]),
    "S09": ("l3-agent", "make", "第三幕 · 做", "给 AI 套一层循环", ["Cursor", "Agent", "ReAct"]),
    "S10": ("what-is-agent", "make", "第三幕 · 做", "四加一", ["目标", "工具", "循环", "权限"]),
    "S11": ("two-generations", "make", "第三幕 · 做", "两代智能体", ["提示词型", "Harness 型"]),
    "S12": ("harness-anatomy", "make", "第三幕 · 做", "一个完整能力的办公工位", ["工具", "Skill", "MCP", "行动循环"]),
    "S13": ("tools-skills-mcp", "make", "第三幕 · 做", "都是喂给模型的文字", ["工具", "Skill", "MCP", "上下文"]),
    "S14": ("timeline-landscape", "crowd", "第四幕 · 群雄", "从 demo 到日用", ["AutoGPT", "Devin", "Claude Code", "OpenClaw"]),
    "S15": ("foreign-agents", "crowd", "第四幕 · 群雄", "国外 Agent：四条路线", ["Cursor", "Claude Code", "Codex", "OpenCode"]),
    "S16": ("china-agents", "crowd", "第四幕 · 群雄", "国内 Agent：模型在左，Harness 在右", ["Trae", "Qwen Code", "ZCode", "Kimi Code", "DSH"]),
    "S17": ("stateless-notebook", "use", "第五幕 · 用", "只认笔记本的专家", ["无状态", "笔记本", "上下文"]),
    "S18": ("long-session", "use", "第五幕 · 用", "长会话不是免费的记忆", ["token", "重放", "成本"]),
    "S19": ("compact", "use", "第五幕 · 用", "写满的笔记本", ["上下文窗口", "压缩", "compaction"]),
    "S20": ("agents-md", "use", "第五幕 · 用", "给 AI 一个项目记忆", ["AGENTS.md", "项目记忆", "全局记忆"]),
    "S21": ("safety", "use", "第五幕 · 用", "能操作电脑，不等于可以随便操作", ["提示注入", "权限", "审批"]),
    "S22": ("closing", "epilogue", "收尾", "第三次跃迁", ["看", "说", "做", "用"]),
}

ACT_ACCENT = {
    "prologue": "#2FB68A",
    "watch": "#2FB68A",
    "speak": "#E8B23A",
    "make": "#4C7DFF",
    "crowd": "#7B6CFF",
    "use": "#E85B4A",
    "epilogue": "#2FB68A",
}

# Only the theme that is allowed to exist in the course.
THEME = "paper"

THESIS_OVERRIDES = {
    "S02": "记住「看、说、做、用」，就记住了整场。",
}

# Narration-only fixes. The outline text is authoritative; these are punctuation
# normalisations, never rewordings.
NARRATION_FIXES: dict[str, list[tuple[str, str]]] = {
    "S01": [("6 年后", "6 年后")],
}

COURSE_META = {
    "slug": "ai-first-sees",
    "title": "从会聊天到会干活：AI Agent 入门",
    "subtitle": "看 → 说 → 做 → 用：AI 的三次跃迁，和我们的用法",
    "summary": "二十二个镜头，把 AI 十年能力跃迁讲成一条线：从 AlphaGo 学会看，到 ChatGPT 学会说，再到 Agent 与 Harness 学会做，最后讲清普通人怎么安全、省钱地用。",
    "description": "这门课把 2016 到 2026 的 AI 发展压成四个动词：看、说、做、用。上半场解释机器怎么学会看和说，下半场解释它怎么学会做，以及我们怎么用 Harness 把它变成能干活、但不失控、也不烧钱的同事。每个镜头一页，旁白驱动动画，像一条可以随时暂停的视频。",
    "level": "beginner",
    "tags": ["AI Agent", "大模型", "Harness"],
    "language": "zh-CN",
    "status": "published",
    "featured": True,
    "order": 10,
    "accent": "#2FB68A",
    "outcomes": [
        "分清 CNN、AlphaGo 与 LLM、ChatGPT 是两条不同的技术路线",
        "说清 Agent 的三级跳，以及提示词型与 Harness 型的区别",
        "解释「API 默认无状态」、长会话成本和上下文压缩",
        "说出 Harness 的四件套：工具、Skill、MCP、行动循环",
    ],
    "prerequisites": ["用过 ChatGPT 之类的对话产品", "不需要编程或数学基础"],
    "takeaways": [
        "AI 第一次学会看，第二次学会说，第三次学会做",
        "Harness 是工程：工具是手，Skill 是说明书，MCP 是接口，循环是心跳",
        "一任务，一会话；写满了就压缩，但压缩会丢细节",
        "能操作电脑，不等于可以随便操作",
    ],
    "updatedAt": "2026-11-08",
    "sources": [
        "Google：AlphaGo 官方博客",
        "Nature 2016：Mastering the game of Go",
        "NeurIPS 2012：AlexNet",
        "OpenAI：GPT-1、GPT-2、GPT-3、InstructGPT、ChatGPT 官方博客/论文",
        "Anthropic：MCP 官方发布",
        "AGENTS.md：agents.md 官方站点",
        "MIT AI Agent Index：Cursor / Claude Code",
        "国家网络与信息安全信息通报中心等：OpenClaw 安全预警",
    ],
}


def normalise(text: str) -> str:
    text = text.strip()
    text = text.replace("`", "")
    text = text.replace(",", "，").replace(";", "；")
    # One quote style across the whole course: 「」.
    text = re.sub(r"“([^”]*)”", r"「\1」", text)
    text = CJK_LATIN.sub(r"\1 \2", text)
    text = LATIN_CJK.sub(r"\1 \2", text)
    text = SPACE_BEFORE_PUNCT.sub(r"\1", text)
    text = SPACE_AFTER_OPEN.sub(r"\1", text)
    return MULTISPACE.sub(" ", text)


def parse_outline(markdown: str) -> list[dict]:
    """Turn the markdown into one dict per `## Sxx · id — title` section."""
    matches = list(SECTION_RE.finditer(markdown))
    if not matches:
        raise SystemExit("outline: no scene headings found")
    scenes: list[dict] = []
    for index, match in enumerate(matches):
        body_start = match.end()
        body_end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        body = markdown[body_start:body_end]
        fields: dict[str, str] = {}
        narration_lines: list[str] = []
        lines = body.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i]
            field = FIELD_RE.match(line)
            if field:
                name = field.group("name").strip()
                rest = field.group("rest").strip()
                if name == "旁白":
                    # Naration is an indented blockquote list. Collect until the
                    # next top-level field; blank quote lines separate paragraphs.
                    i += 1
                    paragraph: list[str] = []
                    paragraphs: list[str] = []
                    while i < len(lines):
                        quote = QUOTE_RE.match(lines[i])
                        if not quote:
                            if TOP_FIELD_RE.match(lines[i]) or HEADING_RE.match(lines[i]):
                                break
                            i += 1
                            continue
                        text = quote.group("text").strip()
                        if text:
                            paragraph.append(text)
                        elif paragraph:
                            paragraphs.append("".join(paragraph))
                            paragraph = []
                        i += 1
                    if paragraph:
                        paragraphs.append("".join(paragraph))
                    narration_lines = paragraphs
                    continue
                # Normal fields: keep the first line plus any continuation lines
                # that are not another field / heading.
                extra: list[str] = []
                i += 1
                while i < len(lines):
                    nxt = lines[i]
                    if TOP_FIELD_RE.match(nxt) or HEADING_RE.match(nxt) or nxt.strip() == "---":
                        break
                    if nxt.strip().startswith("|") or nxt.strip() == "":
                        i += 1
                        continue
                    extra.append(nxt.strip())
                    i += 1
                fields[name] = normalise(" ".join([rest, *extra])) if extra else rest
                continue
            i += 1

        scenes.append(
            {
                "code": match.group(1),
                "id": match.group(2),
                "heading": match.group(3).strip(),
                "时长": fields.get("时长", ""),
                "一句话论题": fields.get("一句话论题", ""),
                "屏幕文字": fields.get("屏幕文字", ""),
                "画面": fields.get("画面", ""),
                "动画": fields.get("动画", ""),
                "事实/口径": fields.get("事实/口径", ""),
                "素材": fields.get("素材", ""),
                "narration": "\n\n".join(narration_lines),
            }
        )
    return scenes


def build_scenes(parsed: list[dict]) -> list[dict]:
    scenes: list[dict] = []
    seen: set[str] = set()
    for item in parsed:
        code = item["code"]
        if code not in META:
            raise SystemExit(f"curate: {code} is not in META; add it or drop the section")
        scene_id, act, act_label, title, keywords = META[code]
        if scene_id in seen:
            raise SystemExit(f"curate: duplicate id {scene_id}")
        seen.add(scene_id)
        narration = item["narration"]
        if not narration:
            raise SystemExit(f"curate: {code} has no narration")
        for old, new in NARRATION_FIXES.get(code, []):
            narration = narration.replace(old, new)
        narration = normalise(narration)
        thesis = normalise(THESIS_OVERRIDES.get(code, item["一句话论题"]))
        scenes.append(
            {
                "code": code,
                "id": scene_id,
                "act": act,
                "actLabel": act_label,
                "theme": THEME,
                "accent": ACT_ACCENT[act],
                "title": title,
                "thesis": thesis,
                "screenText": item["屏幕文字"],
                "visual": item["画面"],
                "animation": item["动画"],
                "facts": item["事实/口径"],
                "materials": item["素材"],
                "keywords": keywords,
                "narration": narration,
            }
        )
    return scenes


def main() -> None:
    markdown = OUTLINE.read_text(encoding="utf-8")
    parsed = parse_outline(markdown)
    NARRATION_DIR.mkdir(parents=True, exist_ok=True)
    PARSED.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")

    scenes = build_scenes(parsed)
    payload = {"course": COURSE_META, "scenes": scenes}
    TARGET.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    chars = sum(len(scene["narration"]) for scene in scenes)
    estimated = chars / 3.9
    print(f"{len(scenes)} scenes -> {TARGET}")
    print(f"narration chars: {chars} (~{estimated / 60:.1f} min at the current voice)")
    for scene in scenes:
        print(f"  {scene['code']} {scene['id']:>20s} {len(scene['narration']):5d} chars  {scene['title']}")


if __name__ == "__main__":
    main()
