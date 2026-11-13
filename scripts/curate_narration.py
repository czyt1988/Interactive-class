"""Parse the director script and curate `courses/ai-first-sees/narration/scenes.json`.

Source of truth: ``courses-outline/ai-first-sees/outline.md`` (the 29-shot long
version; S28 safety was dropped, so the course ships 28 scenes).
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
OUTLINE = ROOT / "courses-outline" / "ai-first-sees" / "outline.md"
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
    "S16": ("china-agents", "crowd", "第四幕 · 群雄", "国内 Agent：紧跟，也有自己的做法", ["Trae", "Qwen Code", "ZCode", "Kimi Code", "DSH"]),
    "S17": ("stateless-notebook", "use", "第五幕 · 用", "只认笔记本的专家", ["无状态", "笔记本", "上下文"]),
    "S18": ("long-session", "use", "第五幕 · 用", "长会话不是免费的记忆", ["token", "重放", "成本"]),
    "S19": ("compact", "use", "第五幕 · 用", "写满的笔记本", ["上下文窗口", "压缩", "compaction"]),
    "S20": ("agents-md", "use", "第五幕 · 用", "给 AI 一个项目记忆", ["AGENTS.md", "项目记忆", "全局记忆"]),
    "S21": ("agents-md-content", "use", "第五幕 · 用", "目录的记忆：AGENTS.md 写什么", ["AGENTS.md", "项目概述", "目录结构", "员工守则"]),
    "S22": ("prompt-assembly", "use", "第五幕 · 用", "你只问一句，模型读的是一大本", ["系统提示", "技能列表", "MCP", "上下文"]),
    "S23": ("skills", "use", "第五幕 · 用", "技能不是越多越好", ["Skill", "superpowers", "grill-me", "huashu design"]),
    "S24": ("model-choice", "use", "第五幕 · 用", "先选对模型", ["多模态", "非多模态", "生图", "生视频"]),
    "S25": ("slash-commands", "use", "第五幕 · 用", "斜杠后面的三个命令", ["/init", "/goal", "/plan"]),
    "S26": ("task-scope", "use", "第五幕 · 用", "把 0 到 100 切成三段", ["任务粒度", "分段", "复盘"]),
    "S27": ("secrets", "use", "第五幕 · 用", "有些东西，不能交给 Agent", ["API key", "密码", "脱敏", "最小权限"]),
    "S29": ("closing", "epilogue", "收尾", "第三次跃迁", ["看", "说", "做", "用"]),
}

# The outline dropped S28 (safety) after folding its message into S27 (secrets).
# The closing shot keeps its outline heading (S29) but ships as the 28th screen.
CODE_REMAP = {"S29": "S28"}

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

# The migrated outline (`courses-outline/ai-first-sees/outline.md`) was rebuilt from
# an older copy of the director script: its S15-S17 narration predates fixes that
# already shipped in the course (Qoder, the WorkBuddy consolidation, Kimi Code
# dates, the "100 万 vs 21 万 token" context window). Keep the shipped narration
# for those three scenes so we do not silently regress them; everything else,
# including the new S21-S27, comes from the outline.
NARRATION_OVERRIDES: dict[str, str] = {
    "S15": "先看国外。2023 年 3 月，Cursor 上线，一开始它只是更好用的 AI IDE，核心是补全；到 2024 年 11 月，它有了 Agent 模式，开始自己改多个文件、跑命令。2025 年 2 月，Anthropic 放出 Claude Code 的研究预览，5 月正式发布，它从终端起步，把「在终端里干活」做成了完整体验。同一年 5 月，OpenAI 发布 Codex，它最早是云端任务，但也有开源的 CLI 和 IDE 插件。还有 OpenCode，开源、跨模型，适合想自己掌控工具链的人。这四款不是四种互斥的形态：它们从不同入口起家，后来都在往对方的入口长。谁最强？这个问题每个月都可能换答案。",
    "S16": "国内也不缺 Agent。2025 年 3 月，字节的 Trae 发布国内版，走 IDE 路线；7 月，阿里的 Qwen Code 跟着 Qwen3-Coder 一起开源；8 月，阿里又发布 Qoder，一个独立的 Agentic IDE；智谱的 ZCode 走长任务路线；2026 年 3 月，腾讯把 CodeBuddy 和办公能力，一起收进 WorkBuddy 一个主入口；5 月，月之暗面的 Kimi Code 开源；8 月，DeepSeek 发布 DeepSeek Harness。这些我大多用过一段时间；我的体验是：国内团队在模型和 Agent 上都跟得很紧，而且今年开始把入口收成一个。DeepSeek Harness 在 2026 年 8 月发布 v0.1，9 月底出桌面端，11 月初日活 154 万。它比较特别的地方不在模型，而在架构：基于 Cordis 插件运行时，模型、工具、Skill、会话、沙箱、Agent Loop，全都是插件。连「循环」本身都可以被替换。这意味着，你可以让 Harness 改变自己的功能，这是一种比较新的软件设计思路。软件的界面想要怎样，是由你说了算，而不是官方给你设计好你就继续这样用，你完全可以让它自己改成你想要的样子。它是一套可以自己生长的 Harness。群雄看完了，接下来最实际的问题：这些 Agent 到底该怎么用？",
    "S17": "先问一个你肯定遇到过的问题：你换一个模型，对话还能接着聊；网断了重连，记录还在；第二天打开，它还记得昨天聊到哪。可大模型的 API，默认是「不记得你」的。那这些记忆，到底存在哪？\n\n你可以把大模型想成一个黑屋里的专家。屋子很小，只有一张桌子、一盏灯、一个窗口。专家非常聪明，但他不认人，只认笔记本。门外排着成千上万的人，每人手里一本笔记本。\n\n每一本笔记本，就是一次会话。第一页是 Harness 写的系统提示词：你是谁、能做什么、不能做什么。后面是你们聊过的每一句话，中间还夹着工具返回的结果。专家每次拿到本子，都从第一页开始读，一直读到最后一页，然后在下一页写下答案，合上，递出去。下一个本子进来，他又是从头开始。\n\n现在你就能解释那三件事了。换模型，就是把同一本笔记本，递给另一个专家；断网，就是笔记本一直在你手里，重新递进去就行；那为什么长对话越来越贵？因为每问一次，专家都要把整本从头读一遍。而且，每个专家一次能读完、记住的厚度是有限的，这就是上下文窗口，有的模型能读 100 万 token，有的只有 21 万。本子太厚，前面的内容就得压缩、丢掉。所以真正的记忆不在模型里，在 Harness 帮你整理的这本笔记本里。",
}

COURSE_META = {
    "slug": "ai-first-sees",
    "title": "从会聊天到会干活：AI Agent 入门",
    "subtitle": "看 → 说 → 做 → 用：AI 的三次跃迁，和我们的用法",
    "summary": "二十八个镜头，把 AI 十年能力跃迁讲成一条线：从 AlphaGo 学会看，到 ChatGPT 学会说，再到 Agent 与 Harness 学会做，最后讲清普通人怎么安全、省钱、省心地把它用好。",
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
        "说出 Harness 的四件套，并会写 AGENTS.md、选模型、用斜杠命令控制任务范围",
    ],
    "prerequisites": ["用过 ChatGPT 之类的对话产品", "不需要编程或数学基础"],
    "takeaways": [
        "AI 第一次学会看，第二次学会说，第三次学会做",
        "Harness 是工程：工具是手，Skill 是说明书，MCP 是接口，循环是心跳",
        "一任务，一会话；写满了就压缩，但压缩会丢细节",
        "一个目录一份 AGENTS.md；技能少而精；有些东西不能交给 Agent",
    ],
    "updatedAt": "2026-11-13",
    "sources": [
        "Google：AlphaGo 官方博客",
        "Nature 2016：Mastering the game of Go",
        "NeurIPS 2012：AlexNet",
        "OpenAI：GPT-1、GPT-2、GPT-3、InstructGPT、ChatGPT 官方博客/论文",
        "Anthropic：MCP 官方发布",
        "AGENTS.md：agents.md 官方站点",
        "Microsoft Learn：Harness 运行时说明",
        "GitHub：obra/superpowers、alchaincyf/huashu-design 仓库与 API 星标数据（2026-11-12）",
        "DeepSeek Harness 官方产品页",
        "DeepSeek、千问、智谱官方模型发布说明（DeepSeek-V4.1 / Qwen3.8 / GLM-5.3）",
        "字节 Seedance、快手可灵、OpenAI Sora、Google Veo 官方页面",
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
        narration = NARRATION_OVERRIDES.get(code, narration)
        code = CODE_REMAP.get(code, code)
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
    PARSED.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")

    scenes = build_scenes(parsed)
    payload = {"course": COURSE_META, "scenes": scenes}
    TARGET.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")

    chars = sum(len(scene["narration"]) for scene in scenes)
    estimated = chars / 3.9
    print(f"{len(scenes)} scenes -> {TARGET}")
    print(f"narration chars: {chars} (~{estimated / 60:.1f} min at the current voice)")
    for scene in scenes:
        print(f"  {scene['code']} {scene['id']:>20s} {len(scene['narration']):5d} chars  {scene['title']}")


if __name__ == "__main__":
    main()
