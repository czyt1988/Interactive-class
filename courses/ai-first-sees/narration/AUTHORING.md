# 场景作者手册（S01-S28）

这门课 `courses/ai-first-sees` 是对 `courses-outline/ai-first-sees/outline.md`（29 镜头长版；S28 safety 并入 S27，课程落地 28 屏）的落地：**一个 S 编号 = 一个场景 = 一页动态 PPT**。每页时长由旁白音频决定，旁白念完留 1.6 秒收尾后自动进入下一页。整门课约 29.5 分钟。

## 先读这三份

1. 本文件：每页的固定结构、动效硬规则、可用资源。
2. `DESIGN.md` 第 8 节：画布、安全区、字号阶梯、场景规则。
3. 你的分镜：`courses-outline/ai-first-sees/outline.md` 里对应 S 的「画面 / 动画 / 旁白」小节，以及 `narration/scenes.timed.json` 里的分句时间。

## 全局视觉方向（2026-11 改版）

- **只做浅色。整门课只有一种底色：暖纸 #f4efe6。** 不出现深色页面、深色舞台、深色渐变大区块。之前深墨/黑屋的幕全部改成纸面，用强调色区分幕：看=青绿、说=暖黄、做=电光蓝、群雄=蓝紫、用=珊瑚红、开场/收尾=青绿。
- 深色只允许出现在「真实产品截图」这种证据图里，并且必须缩成小卡片（`.media`），不能铺满屏幕、不能当背景。
- 真实素材在 `composition/assets/media/`：`logo/*.png`（23 个真实产品 logo）、`photo/*.webp`（AlphaGo 对局、猫）、`shot/*.webp`（26 张真实产品截图/官方示例）、`gen/*.webp`（4 张生图/生视频官方示例）。路径从根 composition 写：`assets/media/logo/cursor.png`。图片必须写 `alt`、给固定宽高，不加外部链接。
- 视觉母题：纸、叠层、编号、细线、印章、胶带；用粗墨线 SVG / CSS 画出「物件」，不要图库插画，不要 emoji。
- 一屏最多一个强调色；强调色只做重点，不做整屏底色。
- 字号：标题已由页眉统一给；舞台内大论点 72-140px、正文 36-48px、标签 28-32px，关键文字不低于 32px。

## 每页的固定结构（不要破坏）

```html
<template>
  <style> /* 只放本场景的样式；类名前缀 s-<id>- */ </style>
  <div id="root" class="scene-root" data-composition-id="s-<id>" data-width="1920" data-height="1080"
       data-theme="paper" data-act="...">
    <div class="scene-in">
      <header class="scene-head"> S 编号 / 幕 / 标题 / 01 of 22 </header>
      <section id="s-<id>-stage" class="stage"><!-- 你的画面 --></section>
    </div>
    <!-- CAPTIONS:BEGIN --> 自动生成的字幕，不要改 <!-- CAPTIONS:END -->
  </div>
  <script>
    // TIMING:BEGIN ... const N = { duration, cues } ... // TIMING:END
    const tl = gsap.timeline({ paused: true });
    // MOTION:BEGIN ... 你的动效 ... // MOTION:END
    window.__timelines["s-<id>"] = tl;
  </script>
</template>
```

**字幕块（CAPTIONS）和时间块（TIMING）由脚本生成，必须原样保留。** 只改 `<style>`、`.stage` 里的画面和 `// MOTION:BEGIN` 到 `// MOTION:END` 之间的代码。若重写整个文件，交回前跑一次 `python scripts/build_narration.py --no-tts --skip-opus` 让脚本补回这两块。

## 时间：旁白是时钟

- `N.duration` 是本页总时长（秒）；`N.cues[i].t` 是第 i 句字幕在本页内的开始时间；`N.cues[i].text` 是那句话。
- 每个动效钉在 `N.cues[i].t` 上（可加 0.1-0.8 秒偏移），旁白说到哪，画面变到哪；不要按固定间隔自己跑。
- 入口 0.5-0.8s，`power2.out` / `power3.out`；一次只推一个视觉焦点；句与句之间不要超过 3 秒完全静止（让次级元素持续轻微移动）。
- 最后一句话结束前把所有东西落到稳定终态；页尾 1.6 秒不运动。

## 动画硬规则（HyperFrames 契约）

- 只用 GSAP 时间轴驱动 `transform` / `opacity`（必要时 `backgroundColor`）；不要 `display`、`visibility`、`autoAlpha`；不要给会被 GSAP 动的元素写 CSS `transform`。
- 用 `fromTo`，不用 `from`；同一属性被第二条 tween 再动时加 `immediateRender: false`。
- 不用无限循环、`Date.now()`、`setInterval()`、未播种 `Math.random()`、网络请求；循环只跑有限次并停在稳定帧。
- 元素 id 一律 `s-<id>-xxx`；元素写在 HTML 里，不用 JS 生成定时元素。
- **晚出现的元素必须在 CSS 里先 `opacity: 0`**（或脚本顶部 `gsap.set(..., { opacity: 0 })`）：快照和拖动进度条会直接 seek 到中段，`fromTo` 的初始隐藏状态不一定被渲染，元素会提前露出来。已出现的元素再由 `fromTo` 从 0 到 1。
- 所有图片只从 `assets/...` 引用，不写 `/` 开头；不引外部字体/CDN。
- 被 `.clip` 标注的定时元素（只有字幕）不能 tween display/visibility；其余元素用 GSAP 控制即可。

## 可用共享样式（`assets/course.css`）

布局：`.scene-in .scene-head .scene-kicker .scene-code .scene-act .scene-title .scene-no .stage`

排版：`.mono .label .dim .faint .accent .ink .big .huge .num .small .body`

容器：`.row .row-top .col .grid-2 .grid-3 .panel .card .chip .chip--solid .tag .kbd .rule .dot .node .bar .track .arrow .strike .muted .strong .center`

物件：`.board .stone .stone--b .stone--w .code .code-line* .term .term-bar .avatar-dot .lamp-glow .media .media__label .photo .photo__label .logo .logo-chip .stamp .silhouette .dash .note`

代码/终端 mock 现在是浅色纸面终端（`.code` / `.term` 已经是浅色），不要自己再写深色终端。

## 验收：快照

每写完一个场景，在 `courses/ai-first-sees/composition` 下：

```powershell
$env:Path = "C:\src\ai-learning\tools\ffmpeg\bin;" + $env:Path
cd C:\src\ai-learning\courses\ai-first-sees\composition
npx --yes hyperframes@0.9.19 snapshot --composition s-<id> --frames 5 --out .snaps-<id>
```

读 `.snaps-<id>/contact-sheet.jpg`：首帧、中段、尾帧都要能看懂；文字不跑出舞台、不压旁白条；背景是纸色；最后一帧稳定。可用 `--at 12.5,24` 看具体秒数。不要跑整门课的 `check`（并行会很慢），Lead 统一跑。

## 分镜清单

| # | S | id | 文件 | 时长 | 标题 | 分句数 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | S01 | hook | `compositions/01-hook.html` | 28.3s | 三个画面 | 7 |
| 2 | S02 | roadmap | `compositions/02-roadmap.html` | 25.2s | 四个字 | 5 |
| 3 | S03 | alphago | `compositions/03-alphago.html` | 26.7s | 机器第一次赢在「直觉」 | 6 |
| 4 | S04 | cnn | `compositions/04-cnn.html` | 53.7s | 一层一层的滤镜 | 11 |
| 5 | S05 | gpt1 | `compositions/05-gpt1.html` | 25.9s | 文字接龙 | 7 |
| 6 | S06 | scaling-emergence | `compositions/06-scaling-emergence.html` | 120.3s | 规模定律与涌现 | 28 |
| 7 | S07 | chatgpt | `compositions/07-chatgpt.html` | 37.1s | 只动嘴的顾问 | 8 |
| 8 | S08 | l1-l2 | `compositions/08-l1-l2.html` | 35.5s | 聊天框，和工作流 | 9 |
| 9 | S09 | l3-agent | `compositions/09-l3-agent.html` | 46.1s | 给 AI 套一层循环 | 11 |
| 10 | S10 | what-is-agent | `compositions/10-what-is-agent.html` | 23.1s | 四加一 | 6 |
| 11 | S11 | two-generations | `compositions/11-two-generations.html` | 39.4s | 两代智能体 | 8 |
| 12 | S12 | harness-anatomy | `compositions/12-harness-anatomy.html` | 75.2s | 一个完整能力的办公工位 | 17 |
| 13 | S13 | tools-skills-mcp | `compositions/13-tools-skills-mcp.html` | 60.0s | 都是喂给模型的文字 | 15 |
| 14 | S14 | timeline-landscape | `compositions/14-timeline-landscape.html` | 30.9s | 从 demo 到日用 | 6 |
| 15 | S15 | foreign-agents | `compositions/15-foreign-agents.html` | 52.4s | 国外 Agent：四条路线 | 13 |
| 16 | S16 | china-agents | `compositions/16-china-agents.html` | 91.3s | 国内 Agent：紧跟，也有自己的做法 | 23 |
| 17 | S17 | stateless-notebook | `compositions/17-stateless-notebook.html` | 98.2s | 只认笔记本的专家 | 23 |
| 18 | S18 | long-session | `compositions/18-long-session.html` | 56.9s | 长会话不是免费的记忆 | 12 |
| 19 | S19 | compact | `compositions/19-compact.html` | 68.5s | 写满的笔记本 | 17 |
| 20 | S20 | agents-md | `compositions/20-agents-md.html` | 66.7s | 给 AI 一个项目记忆 | 17 |
| 21 | S21 | agents-md-content | `compositions/21-agents-md-content.html` | 131.8s | 目录的记忆：AGENTS.md 写什么 | 29 |
| 22 | S22 | prompt-assembly | `compositions/22-prompt-assembly.html` | 117.5s | 你只问一句，模型读的是一大本 | 27 |
| 23 | S23 | skills | `compositions/23-skills.html` | 102.1s | 技能不是越多越好 | 24 |
| 24 | S24 | model-choice | `compositions/24-model-choice.html` | 114.6s | 先选对模型 | 24 |
| 25 | S25 | slash-commands | `compositions/25-slash-commands.html` | 64.3s | 斜杠后面的三个命令 | 16 |
| 26 | S26 | task-scope | `compositions/26-task-scope.html` | 73.8s | 把 0 到 100 切成三段 | 17 |
| 27 | S27 | secrets | `compositions/27-secrets.html` | 82.3s | 有些东西，不能交给 Agent | 17 |
| 28 | S28 | closing | `compositions/28-closing.html` | 45.8s | 第三次跃迁 | 10 |
