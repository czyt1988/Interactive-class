# 课程契约 v1

> 这份文档定义一门课从源文件到可播放课程包的全部约定。
> 课程任务主要依赖这份文档、独立模板包 [`course-template/`](../course-template/README.md) 和 HyperFrames 技能；视觉、配色、场景版式与文案规范以 [DESIGN.md](../DESIGN.md) 为准；[架构设计](architecture.md)用于理解运行时边界，不要求课程作者记住平台内部实现。

## 1. 一个课程包是什么

一门课 = 一个目录 `courses/<slug>/`，包含：

- 一份编辑清单 `course.json`；
- 一个 HyperFrames 工程 `composition/`；
- 可选封面 `cover.webp`；
- 一份课程脚本 `STORYBOARD.md`（不进入构建产物）。

构建后得到一个可以独立部署的静态目录 `dist/courses/<slug>/`。它不依赖 FastAPI、不依赖 API、不引用 CDN；同源进度同步是可选增强。学习进度是站点侧的增强；课程包在没有数据库、没有登录态时仍然完整可用。

约定：

- **一门课一个 composition。**
- **一屏一个 scene。**
- **屏幕顺序和时间由根 composition 决定，编辑信息由 `course.json` 决定。**
- **课程任务只修改 `courses/<slug>/`。** 需要改平台、运行时或站点时，另开平台任务。

## 2. 目录结构

```text
courses/<slug>/
├─ course.json                     # 必须
├─ STORYBOARD.md                   # 必须，但不进入产物
├─ cover.webp                      # 可选，1600×900
└─ composition/                    # 必须，HyperFrames 工程根
   ├─ index.html                   # 根 composition
   ├─ hyperframes.json
   ├─ package.json
   ├─ compositions/
   │  ├─ 01-hook.html
   │  ├─ 02-tokens.html
   │  └─ ...
   └─ assets/
      ├─ course.css
      ├─ fonts/
      │  └─ NotoSansSC-VF.woff2
      ├─ images/
      ├─ audio/
      └─ vendor/
         ├─ gsap.min.js
         └─ LICENSES/
```

`course-template/` 是同一份目录结构的独立模板包：它不在 `courses/` 下参与构建，而是交给课程作者或外部 AI 当作工作目录，生成完成后整个文件夹按 7.7 导入。模板包的作者文档（`AGENTS.md`、`COURSE-CONTRACT.md`、`STYLE.md`）与本契约保持一致；冲突时以本契约为准。

命名规则：

- `slug` 必须匹配 `^[a-z0-9]+(?:-[a-z0-9]+)*$`，并且等于目录名。
- 屏幕 `id` 必须匹配 `^[a-z][a-z0-9-]*$`，1–32 个字符，全课唯一。
- scene host 的 id 固定为 `s-<screen-id>`；scene 文件的 `data-composition-id` 和时间轴 key 也必须等于 `s-<screen-id>`。
- scene 文件名建议 `NN-<screen-id>.html`，序号只用于阅读，不参与排序。

## 3. `course.json`

### 3.1 示例

```json
{
  "schemaVersion": 1,
  "slug": "what-is-a-token",
  "title": "AI 眼中的文字",
  "subtitle": "从 token 开始，理解大模型如何阅读",
  "summary": "一句话被切成 token 之后，模型才真正开始工作。这节课用一屏一屏的动画，把 tokenization 讲清楚。",
  "description": "从字符、词和 token 的区别开始，逐步看到一次分词如何发生，以及为什么上下文长度按 token 计算。",
  "level": "beginner",
  "tags": ["LLM", "token", "基础"],
  "language": "zh-CN",
  "status": "published",
  "featured": true,
  "order": 10,
  "accent": "#E4572E",
  "cover": "cover.webp",
  "outcomes": [
    "说清 token 与字符、词的区别",
    "看懂一次分词的过程",
    "理解上下文长度为什么按 token 计算"
  ],
  "prerequisites": ["不需要编程基础"],
  "takeaways": [
    "模型读到的不是字，是 token",
    "token 是模型处理文本的最小单位",
    "上下文长度限制的是 token 数量"
  ],
  "audio": false,
  "interactive": false,
  "playback": "screens",
  "composition": {
    "entry": "composition/index.html",
    "width": 1920,
    "height": 1080,
    "fps": 30
  },
  "screens": [
    {
      "id": "hook",
      "kicker": "01 / 开场",
      "title": "模型看到的不是字",
      "summary": "你输入的一句话，在模型眼里是一串数字。",
      "transcript": "你敲下的是一句话，模型收到的却是一串 token。这一屏先让你看到这个落差。",
      "autoAdvance": false
    },
    {
      "id": "split",
      "kicker": "02 / 切分",
      "title": "先切成 token",
      "summary": "分词器决定从哪里下刀。",
      "transcript": "分词器把文本切成 token。有的 token 是一个词，有的只是词的一部分，甚至是一个空格。"
    }
  ],
  "site": {
    "homeUrl": "/",
    "backLabel": "返回课程库"
  },
  "credits": {
    "author": "AI Learning",
    "updatedAt": "2026-11-07",
    "sources": []
  }
}
```

### 3.2 顶层字段

| 字段 | 必须 | 类型 | 规则 |
| --- | --- | --- | --- |
| `schemaVersion` | 是 | int | 固定 `1`；不识别就报错，不猜测 |
| `slug` | 是 | string | 同上；必须等于目录名 |
| `title` | 是 | string | 2–40 字符；课程页 `h1` |
| `subtitle` | 否 | string | ≤ 60 字符；封面副标题 |
| `summary` | 是 | string | 40–160 字符；课程卡片和 meta description |
| `description` | 否 | string | 长描述，纯文本；用于课程页和 SEO |
| `level` | 是 | enum | `beginner` / `intermediate` / `advanced` |
| `tags` | 否 | string[] | ≤ 5 个，每个 ≤ 12 字符；用于课程库过滤 |
| `language` | 否 | string | 默认 `zh-CN` |
| `status` | 是 | enum | `draft` / `published` / `archived`；生产只构建 `published` |
| `featured` | 否 | bool | 默认 `false`；首页精选 |
| `order` | 否 | number | 默认 `100`；越小越靠前 |
| `accent` | 否 | string | 十六进制颜色，如 `#E4572E`；课程外壳强调色 |
| `cover` | 否 | string | 相对路径，建议 `cover.webp`，1600×900，≤ 300KB |
| `outcomes` | 否 | string[] | 2–4 条；封面“学完能” |
| `prerequisites` | 否 | string[] | ≤ 3 条；封面 |
| `takeaways` | 否 | string[] | 2–4 条；完成页回顾 |
| `audio` | 否 | bool | 默认 `false`；为 `true` 时课程外壳显示声音控制 |
| `interactive` | 否 | bool | 默认 `false`；v1 不使用，保留给未来的练习屏 |
| `composition` | 是 | object | 见 3.3 |
| `screens` | 是 | array | 至少 1 项；见 3.4 |
| `watermark` | 否 | object | 可选课程水印；见 3.7 |
| `site` | 否 | object | 见 3.5 |
| `credits` | 否 | object | 见 3.6 |

未知字段一律报错。宁可让作者删掉拼错的字段，也不要让一个 `autoAdvence` 静默失效。

### 3.3 `composition`

| 字段 | 必须 | 类型 | 规则 |
| --- | --- | --- | --- |
| `entry` | 否 | string | 默认 `composition/index.html`；必须是 `composition/` 下的 HTML 文件 |
| `width` | 是 | int | v1 固定 `1920` |
| `height` | 是 | int | v1 固定 `1080` |
| `fps` | 否 | int | 默认 `30`；v1 固定 `30` |

### 3.4 `screens[]`

| 字段 | 必须 | 类型 | 规则 |
| --- | --- | --- | --- |
| `id` | 是 | string | 见 2 的命名规则；必须与 composition host 的 `data-screen-id` 一致 |
| `kicker` | 否 | string | 例如 `01 / 开场`；显示在屏幕上方 |
| `title` | 是 | string | ≤ 40 字符；当前屏标题 |
| `summary` | 是 | string | ≤ 120 字符；控制条和大纲里的一句话 |
| `transcript` | 否 | string | 纯文本；有 `audio: true` 时每屏必须有 |
| `autoAdvance` | 否 | bool | 默认 `false`；为 `true` 时到点自动进下一屏 |
| `poster` | 否 | string | 可选，当前屏的静态帧；用于加载/降级 |
| `keywords` | 否 | string[] | ≤ 5 个；用于搜索，不影响播放 |

**不要**在源清单里写 `start`、`duration`、`index`。这些由构建从 composition 解析后写进产物。手写时间一定会和 composition 漂移。

`screens` 数组的顺序只用于阅读。实际播放顺序以根 composition 中 host 的 `data-start` 为准；构建会按时间重排。数组顺序和 composition 顺序不一致不会报错，但会让作者困惑，建议保持一致。

### 3.5 `site`

| 字段 | 必须 | 类型 | 规则 |
| --- | --- | --- | --- |
| `homeUrl` | 否 | string \| null | 默认 `/`；`null` 表示课程独立分发，不显示“返回课程库” |
| `backLabel` | 否 | string | 默认 `返回课程库` |

如果课程要单独部署到别的域名，把 `homeUrl` 设为站点绝对地址，或者设为 `null`。

### 3.6 `credits`

| 字段 | 必须 | 类型 | 规则 |
| --- | --- | --- | --- |
| `author` | 否 | string | 作者/团队 |
| `updatedAt` | 否 | string | `YYYY-MM-DD` |
| `sources` | 否 | string[] | 参考资料链接或说明；只用于展示，不会被运行时请求 |

### 3.7 `watermark`

可选。水印是课程内容的一部分：构建时渲染进课程页，独立部署的课程包也保留，不依赖站点、数据库或 API。两种水印可以同时使用。

```json
{
  "watermark": {
    "enabled": true,
    "corners": [
      {
        "position": "top-left",
        "text": "作者：张三",
        "fontSize": 30,
        "color": "#16140f",
        "opacity": 0.6
      },
      {
        "position": "bottom-right",
        "text": "示例公司",
        "fontSize": 24,
        "color": "#b8452b",
        "opacity": 0.5
      }
    ],
    "repeating": {
      "text": "内部资料，请勿外传",
      "fontSize": 28,
      "color": "#16140f",
      "opacity": 0.12,
      "gapX": 320,
      "gapY": 200,
      "rotate": -24
    }
  }
}
```

| 字段 | 必须 | 类型 | 规则 |
| --- | --- | --- | --- |
| `enabled` | 否 | bool | 默认 `true`；为 `false` 时保留配置但不渲染 |
| `corners` | 否 | object[] | 最多 4 条，每个角最多一条；见下 |
| `repeating` | 否 | object \| null | 满屏平铺水印；`null` 或省略表示关闭 |

`corners[]`：

| 字段 | 必须 | 类型 | 规则 |
| --- | --- | --- | --- |
| `position` | 是 | enum | `top-left` / `top-right` / `bottom-left` / `bottom-right`，全课唯一 |
| `text` | 是 | string | 1–80 字符；纯文本，构建时转义 |
| `fontSize` | 否 | int | 默认 `30`；10–96，单位是 1920×1080 画布的设计像素 |
| `color` | 否 | string | 默认 `#16140f`；必须是 `#RRGGBB` |
| `opacity` | 否 | number | 默认 `0.6`；0–1 |

`repeating`：

| 字段 | 必须 | 类型 | 规则 |
| --- | --- | --- | --- |
| `text` | 是 | string | 1–48 字符；纯文本，构建时转义 |
| `fontSize` | 否 | int | 默认 `28`；10–96，设计像素 |
| `color` | 否 | string | 默认 `#16140f`；`#RRGGBB` |
| `opacity` | 否 | number | 默认 `0.12`；0–1 |
| `gapX` | 否 | int | 默认 `320`；120–960，平铺网格的横向步长（相邻水印的格宽），设计像素 |
| `gapY` | 否 | int | 默认 `200`；80–600，纵向步长（格高），设计像素 |
| `rotate` | 否 | int | 默认 `-24`；-90 到 90，每块水印的倾斜角 |

渲染约定：

- 角标水印贴在画布四角，满屏平铺水印按 16:9 网格从上到下、从左到右重复。
- `gapX` / `gapY` 是网格的步长（相邻水印的格宽与格高），不是文字与文字之间的净空隙；文字比步长更长时相邻水印会叠在一起。
- 字号的“设计像素”按 1920×1080 画布计算；课程外壳按画布实际尺寸等比缩放，所以 1440p 屏幕和全屏下的观感一致。
- 水印只覆盖播放画布，不遮控制条，`pointer-events: none`，不拦截播放器点击；纯 CSS，无动画、无网络请求。
- 视觉水印层对辅助技术隐藏；角标文字会另外以不可见文本提供一次，平铺的防截屏文字不重复朗读。
- 水印文字的字体与课程外壳共用；字体子集不包含的生僻字会回退到系统字体，不影响可读性。
- 后台 `/admin/courses/<slug>/watermark` 可以可视化编辑并保存到源 `course.json`，保存后自动重新构建。手工改 `course.json` 后仍需运行构建。

## 4. composition 约定

### 4.1 工程根

`composition/` 是一个标准 HyperFrames 项目根：

- `index.html` 是根 composition；
- `compositions/` 放每屏的 scene 文件；
- `assets/` 放字体、图片、音频、GSAP；
- `hyperframes.json` 和 `package.json` 用于本地创作，不进入构建产物的必要文件清单；
- 在 `composition/` 目录里运行 `npx hyperframes@0.9.19 preview` / `check` / `snapshot`。

`package.json` 的脚本必须固定版本：

```json
{
  "name": "course-<slug>",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "npx --yes hyperframes@0.9.19 preview",
    "check": "npx --yes hyperframes@0.9.19 check",
    "snapshot": "npx --yes hyperframes@0.9.19 snapshot"
  }
}
```

不要用 `latest`。课程包和 HyperFrames 版本必须可复现。

### 4.2 根 `index.html`

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=1920, height=1080" />
    <script src="assets/vendor/gsap.min.js"></script>
    <link rel="stylesheet" href="assets/course.css" />
  </head>
  <body>
    <div
      id="root"
      data-composition-id="main"
      data-start="0"
      data-duration="28"
      data-width="1920"
      data-height="1080"
    >
      <div
        id="s-hook"
        data-screen-id="hook"
        data-composition-id="s-hook"
        data-composition-src="compositions/01-hook.html"
        data-start="0"
        data-duration="12"
        data-track-index="0"
        data-track-kind="graphics"
        data-width="1920"
        data-height="1080"
      ></div>

      <div
        id="s-split"
        data-screen-id="split"
        data-composition-id="s-split"
        data-composition-src="compositions/02-split.html"
        data-start="12"
        data-duration="16"
        data-track-index="1"
        data-track-kind="graphics"
        data-width="1920"
        data-height="1080"
      ></div>
    </div>

    <script>
      window.__timelines["main"] = gsap.timeline({ paused: true });
    </script>
  </body>
</html>
```

规则：

- 根时间轴必须注册，可以是空时间轴；**不要把 scene 的时间轴 `add()` 到根时间轴**，runtime 会自己驱动 scene。
- 总时长以根 `data-duration` 为准。如果某个 player/runtime 版本从根时间轴推导时长而不是读 `data-duration`，先在 Phase 3a 契约测试里确认，再决定是否加一个 0.01s 的空 tween；不要改变 scene 的时间。
- 根 `data-duration` 是整门课的总时长，必须覆盖最后一屏的结束时间。
- 根 `data-width` / `data-height` 与课程清单一致。
- host 按 `data-start` 升序书写；不要用 `data-start="hook + 0.5"` 这类表达式，构建只接受数字。
- 每个 host 必须有唯一的 `data-track-index`；`data-track-kind="graphics"`。
- 不要在根 composition 里写导航按钮、进度条或站点 UI；这些属于课程外壳。

### 4.3 host 属性

| 属性 | 必须 | 说明 |
| --- | --- | --- |
| `id` | 是 | `s-<screen-id>` |
| `data-screen-id` | 是 | 课程清单里的屏幕 id |
| `data-composition-id` | 是 | 与 `id` 相同，并与 scene 文件里的值、时间轴 key 一致 |
| `data-composition-src` | 是 | 指向 `compositions/` 下的 scene 文件 |
| `data-start` | 是 | 数字秒，绝对时间 |
| `data-duration` | 是 | 数字秒，这一屏的教学节拍长度 |
| `data-track-index` | 是 | 唯一整数 |
| `data-track-kind` | 否 | 建议 `graphics` |
| `data-width` / `data-height` | 是 | `1920` / `1080` |

如果某个 HyperFrames 版本对 `data-screen-id` 报未知属性，构建解析器可以退化为从 `id` 的 `s-` 前缀推导屏幕 id；但不要改用 class、注释或文件名来承载 id。优先保留 `data-screen-id`。

### 4.4 scene 文件

```html
<template>
  <style>
    @font-face {
      font-family: "Noto Sans SC";
      src: url("assets/fonts/NotoSansSC-VF.woff2") format("woff2");
      font-weight: 100 900;
      font-display: swap;
    }

    #root {
      position: absolute;
      inset: 0;
      background: #0b0b0c;
      color: #f6f2e9;
      font-family: "Noto Sans SC", sans-serif;
    }

    #s-hook-title {
      position: absolute;
      left: 192px;
      top: 300px;
      width: 1536px;
      font-size: 132px;
      line-height: 1.1;
      font-weight: 700;
      letter-spacing: -0.02em;
    }
  </style>

  <div id="root" data-composition-id="s-hook" data-width="1920" data-height="1080">
    <h1 id="s-hook-title" class="clip" data-start="0.3" data-duration="11">
      模型看到的不是字
    </h1>
  </div>

  <script>
    const tl = gsap.timeline({ paused: true });

    tl.fromTo(
      "#s-hook-title",
      { opacity: 0, y: 40 },
      { opacity: 1, y: 0, duration: 0.6, ease: "power3.out" },
      0.3,
    );

    window.__timelines["s-hook"] = tl;
  </script>
</template>
```

规则：

- 所有样式、标记、脚本都在 `<template>` 内；scene 文件不是完整 HTML 页面。
- scene 根必须写成 `#root`，用 `position: absolute; inset: 0`，不要写死像素宽高。
- scene 里所有元素 id 加 `s-<screen-id>-` 前缀，避免和别的 scene 冲突。
- 时间轴必须是 `paused: true`，并注册到 `window.__timelines["s-<screen-id>"]`。
- 用 `fromTo`，不要用 `from`。scene 会被反复 seek，`from` 的起始状态会漂移。
- 时间轴在构建完成后注册；异步构建时，注册必须是最后一步。
- 不要在 scene 里 `play()`、`pause()` 或 seek 媒体；runtime 负责时钟。

### 4.5 时间规则

- host 的 `data-start` 和 `data-duration` 都是数字秒。
- 屏幕按 `start` 升序，区间不能重叠。允许有空隙，但空隙不会出现在任何一屏里，通常意味着时间没排好，构建会给警告。
- 根 `data-duration` 必须 ≥ 最后一屏的 `start + duration`；建议正好等于。
- 一屏的 `duration` 是**教学节拍**：入场 + 讲解 + 结尾停留。不是“动画文件长度”，也不是“文字读完的时间”。
- 建议单屏 10–30 秒，最长不超过 45 秒；一门课 6–10 屏，总时长 2–5 分钟。
- **长视频课程例外**（4.11）：一屏对应大纲里的一个 S，时长由旁白音频决定，可以到 30 屏 / 35 分钟；必须在 `course.json` 设 `audio: true`、`playback: "continuous"`，并让屏幕上每一句旁白都有对应字幕。旁白课程只做浅色纸面，播放器必须提供暂停、字幕开关和配音开关。
- 屏幕要在结束前落到稳定状态。不要在 `duration` 的最后一刻还在运动；播放器会停在那一帧。
- scene 的时间轴可以比 host 的 `duration` 短，短的部分会保持最后一帧。这正是“讲完之后停一下”的实现方式。

### 4.6 资源和字体

- 所有路径相对，使用 `assets/...`，不要以前导 `/` 开头。
- scene 文件里引用素材也写 `assets/...`，由 HyperFrames 按工程根解析；不要写 `../assets/...`。
- 不允许外部**资源加载**：`script[src]`、会加载资源的 `link[href]`、`img/source/video/audio[src]`、`poster`、CSS `url()`、`@import` 都不能指向课程包外部。普通 `<a href>` 外链可以用于引用/致谢，但要加 `rel="noopener noreferrer"`，且不能自动加载。
- GSAP 必须放在 `assets/vendor/gsap.min.js`，在根 `index.html` 里本地引用。
- 字体必须本地：`@font-face` 的 `src` 指向 `assets/fonts/...`。不能用 Google Fonts 或系统字体作为唯一方案。
- 课程外壳的字体是可选的：构建时如果 `composition/assets/fonts/` 里有 `.woff2`，课程页会自动注入一份 `@font-face`，让封面、控制条、讲义和动画用同一套字体；优先用 `NotoSansSC-VF.woff2`，没有时才取目录里任意一个，都没有就回退到系统字体，构建不报错。
- 中文正文使用自托管的 Noto Sans SC 子集；拉丁标签/数字可以用一套几何无衬线；等宽标签用 `ui-monospace` 或本地字体。
- 图片 WebP/AVIF；音频 AAC/MP3/Opus；视频只在必要屏幕使用，且必须本地、压缩、带 `muted` 或 `data-has-audio="true"`。
- 第三方库（Three.js、Lottie、anime.js 等）放在 `assets/vendor/`，带 LICENSE，并在 `STORYBOARD.md` 里记录版本。

预算：

| 项目 | 上限 |
| --- | --- |
| 封面 | 300KB |
| 单张图片 | 500KB |
| 单屏素材 | 3MB |
| 整门课（不含视频） | 15MB |
| 字体子集 | 2MB |
| 单文件 HTML | 200KB |

超预算时先优化素材，不是先放宽预算。

### 4.7 排版规则

字号、配色、安全区和场景版式的完整规范以 [DESIGN.md](../DESIGN.md) 第 8 节为准。本节只列课程契约级别的底线：

- 画布 1920×1080，30fps。
- 动作安全区 90%（左右上下至少 96px）；关键文字在标题安全区 80%（至少 192px 边距）。
- 默认短课一律亮色纸面，禁止深色场景；配色只用 `design/tokens.css` 的纸色/墨色/课程强调色。长视频课程按 4.11 使用四幕主题。
- 正文对比度至少 4.5:1；大号文字至少 3:1。
- 字号按 DESIGN.md 8.2 的阶梯取；关键文字不小于 32px，正文 40–56px。
- 中文每行 18-28 字；行高 1.5-1.7；不要用两端对齐制造大空隙。
- 标点用中文全角；中英文之间留一个半角空格；数字和单位之间按语境留空格。
- 一屏最多两个文字层级。标题、正文、标签不要同时出现三种以上字号。
- 文字不要压到画面边缘；不要用装饰线穿过正文。

### 4.8 动画规则

- 一屏一个中心论题，一个主要的运动焦点。其他元素可以为它服务，但不能抢。
- 动画要展示关系、过程、因果或变化；如果删掉动画论证仍然完整，这个动画大概率是装饰。
- 入场 0.3–0.6 秒，使用 `power2.out` / `power3.out` 一类的缓动；不要弹跳、旋转、闪烁堆叠。
- 每次揭示后至少停留 1 秒再进入下一个动作；让学习者有时间读。
- 不使用无限循环；需要循环时用有限次数。
- 不使用 `Date.now()`、`setInterval()`、未播种的 `Math.random()`；所有可见状态必须是 timeline 时间的函数。
- 不 tween `display`、`visibility`、`autoAlpha` 到 `.clip` 元素；要淡出就动画子元素或 opacity。
- 不要同时用 CSS transform 和 GSAP 动画同一个元素的 transform；用 GSAP 的 `x`/`y`/`scale`。
- 动画结束前落到稳定帧；最后一帧就是学习者停留、阅读的帧。

### 4.9 音频

- 默认无音频。需要语音/音效时，在 `course.json` 设 `audio: true`。
- 每屏有语音就必须有 `transcript`；这是无障碍要求，不是可选项。
- 音频文件本地化，和课程一起分发；不要从外部 URL 加载。
- 不要让音频在页面加载时自动播放；课程外壳用“开始学习”这个用户手势解锁。
- 音乐/音效音量要低于语音；语音要清晰；不要用背景音乐压过讲解。
- 音频的总大小计入课程预算。
- 长视频课程（4.11）的旁白文件建议用 OGG/Opus 或 AAC，30 分钟控制在 6MB 以内；每个场景一个文件，命名 `s<NN>-<screen-id>.ogg`。

### 4.10 禁止项

- 外部网络请求、CDN 字体/脚本/图片。
- `fetch`、XHR、WebSocket、动态数据。
- `Date.now()`、`setInterval()`、未播种的 `Math.random()` 作为动画时钟。
- 在 composition 里放站点导航、课程进度、返回按钮。
- 一屏讲两个中心概念。
- 关键信息只存在于动画里，暂停后读不到。
- 正文小于 32px，或对比度不足。
- 直接编辑 `dist/` 里的任何文件。
- 在 scene 里直接 `play()` / `pause()` / seek 媒体。

### 4.11 长视频课程（旁白驱动）

`courses/ai-first-sees` 是这类课程的样板：22 个 S、约 18.6 分钟、一条旁白一条时间轴。

约定：

- **一屏 = 大纲里的一个 S。** 不要把 40–100 秒的 S 再拆成 2–4 页；一页内用连续动画讲完。
- **旁白是时钟。** 每屏一条旁白音频；`data-start` / `data-duration` 从音频时长推导，不由作者手写。旁白念完后留 1–2 秒收尾，再进入下一屏。
- **音频放根 composition。** 每屏一个 `<audio id="nar-s-<id>" class="clip" data-start data-duration src="assets/audio/...">`；音频 id 必须存在，文件必须本地。
- **字幕在画布内。** 每屏底部是旁白条（约 180px），字幕按句切开，用 `.clip` 的 `data-start` / `data-duration` 控制；导出的 MP4 自带烧录字幕。
- **文案一致。** `course.json` 的 `screens[].transcript` 必须和旁白文本一致；`screens[].autoAdvance` 在长视频课程里全部为 `true`。
- **连续播放。** `playback: "continuous"` 时，上一屏/下一屏只是 seek；播放器不重新加载，屏幕之间没有转场遮罩。
- **生成工具。** 旁白、时间、根 composition、`course.json` 和字幕由 `scripts/build_narration.py` 生成；作者只写画面和动效，不手改时间。

## 5. 构建如何合并

### 5.1 解析算法

1. 读取 `course.json`，校验为 `CourseSource`。
2. 读取 `composition.entry`，用 `html.parser` 找出所有带 `data-screen-id` 的 host。
3. 读取每个 host 的 `id`、`data-composition-id`、`data-composition-src`、`data-start`、`data-duration`。
4. 按 `data-start` 升序排序；检查重复、重叠、越界。
5. 用 `data-screen-id` 匹配 `course.json` 的屏幕元数据。
6. 检查每个屏幕元数据都有 host，每个 host 都有元数据。
7. 检查每个 `data-composition-src` 文件存在，且文件里的 `data-composition-id` 与 host 一致，并注册了同名时间轴 key。
8. 读取根 `data-duration`，检查覆盖最后一屏。
9. 合并为 `ResolvedScreen`：加上 `index`、`start`、`duration`。
10. 生成 `ResolvedCourse`，写进产物。

### 5.2 构建错误

| 错误码 | 含义 | 修复 |
| --- | --- | --- |
| `manifest_invalid` | JSON 结构/类型/未知字段错误 | 按报错字段修 |
| `slug_mismatch` | slug 和目录名不一致 | 改其中一个 |
| `composition_missing` | 找不到 `composition.entry` | 检查路径/文件 |
| `screen_meta_orphan` | 清单里有屏幕，composition 里没有 host | 补 host，或删元数据 |
| `screen_host_orphan` | composition 里有 host，清单里没有元数据 | 补元数据，或删 host |
| `screen_id_duplicate` | 屏幕 id 重复 | 改成唯一 id |
| `screen_id_invalid` | id 不符合命名规则 | 改成小写字母/数字/连字符 |
| `host_start_invalid` | start 不是有限非负数 | 改成数字秒 |
| `host_duration_invalid` | duration ≤ 0 或非数字 | 改成数字秒 |
| `host_order_invalid` | host 没有按 start 升序 | 重排或修时间 |
| `host_overlap` | 两屏时间重叠 | 调整 start/duration |
| `root_duration_missing` | 根没有 data-duration | 补上 |
| `root_duration_short` | 根时长不足以覆盖最后一屏 | 增大根时长 |
| `scene_missing` | `data-composition-src` 指向的文件不存在 | 补文件/改路径 |
| `scene_id_mismatch` | scene 文件的 `data-composition-id` 与 host 不一致 | 改成一致 |
| `timeline_missing` | scene 没有注册 `window.__timelines[...]` | 补注册 |
| `external_asset` | HTML/CSS 里有外部资源加载 | 下载到本地，改相对路径 |
| `vendor_missing` | GSAP/runtime 文件缺失 | 运行 sync 脚本/补文件 |
| `font_missing` | 字体文件缺失 | 补字体或改 `@font-face` |
| `audio_transcript_missing` | 有音频但某屏没有讲义 | 补 `transcript` |
| `asset_budget_exceeded` | 单文件/总大小超预算 | 压缩/拆分 |
| `shell_field_invalid` | `site`/`credits`/`accent` 等字段非法 | 按字段规则修 |

构建错误必须包含：课程 slug、文件路径、屏幕 id、字段名、期望值。不要只打印“构建失败”。

### 5.3 解析后的清单

```json
{
  "schemaVersion": 1,
  "slug": "what-is-a-token",
  "title": "AI 眼中的文字",
  "composition": {
    "entry": "composition/index.html",
    "width": 1920,
    "height": 1080,
    "fps": 30,
    "duration": 28
  },
  "screens": [
    {
      "id": "hook",
      "index": 0,
      "start": 0,
      "duration": 12,
      "title": "模型看到的不是字",
      "summary": "你输入的一句话，在模型眼里是一串数字。",
      "transcript": "你敲下的是一句话，模型收到的却是一串 token。这一屏先让你看到这个落差。",
      "autoAdvance": false
    },
    {
      "id": "split",
      "index": 1,
      "start": 12,
      "duration": 16,
      "title": "先切成 token",
      "summary": "分词器决定从哪里下刀。"
    }
  ],
  "stats": {
    "screenCount": 2,
    "durationSeconds": 28,
    "estimatedMinutes": 1
  },
  "build": {
    "runtimeVersion": "0.9.19",
    "contentHash": "…"
  }
}
```

**作者不要手写这个文件。** 它由构建生成，放在 `dist/courses/<slug>/course.json`，同时内联进课程页。上面的示例只列关键字段；实际产物会保留 `status`、`featured`、`order`、`level`、`tags`、`outcomes` 等所有编辑字段，供站点和 API 使用。

## 6. 生成的课程页

课程页 `dist/courses/<slug>/index.html` 由 `runtime/shell.html.j2` 渲染，包含：

- 封面：标题、副标题、目标、先修、章节大纲、时长/级别/屏数、开始按钮；
- 舞台：`<hyperframes-player>`、加载遮罩、转场遮罩；播放态下页面占满视口（`100dvh`、无页面滚动），16:9 画布按可用区域等比最大化，控制条在画布外通栏；有封面时才设置 player 的 `poster`。
- 控制条：退出课程（返回课程库）、上一屏、播放/暂停、下一屏、跳到最后（`End`）、重播、讲义、字幕（有音频时）、配音（有音频时）、全屏、当前屏进度；
- 水印：可选，按 `course.json` 的 `watermark` 渲染角标和满屏平铺水印，只覆盖 16:9 画布，全屏可见；
- 进度：课程总进度按全课时间连续增长；当前屏进度是可拖动的 range，拖动时暂停、松手恢复，拖到末端等同于「跳到最后」；
- 章节信息：当前屏 kicker、标题、摘要；
- 讲义抽屉：当前屏文本；
- 完成页：takeaways、重看、返回课程库；
- 错误页：说明、重试、返回封面。

作者可以定制的字段：

- `title`、`subtitle`、`summary`、`description`
- `outcomes`、`prerequisites`、`takeaways`
- `accent`、`cover`
- `audio`、`interactive`
- `watermark`（角标水印与满屏平铺水印，见 3.7；后台可视化编辑页在 `/admin/courses/<slug>/watermark`）
- `site.homeUrl`、`site.backLabel`
- `screens[].kicker/title/summary/transcript/autoAdvance`

v1 不支持自定义课程页 HTML。每门课的差异通过封面图、强调色、文案和 composition 体现。如果某门课确实需要不同的外壳，先开平台任务，不要复制一份 shell 到课程目录。

课程页在无 JS 时仍然显示封面和大纲；动画需要 JS。`<noscript>` 里要有说明和讲义入口。

进度不是课程包的职责。课程页始终先写 `localStorage`；如果构建时注入了同源 `progressEndpoint` 和 `progressOrigin`，再异步同步到 SQLite；`location.origin` 不匹配时跳过。没有 API、没有 Cookie、独立部署，都退化为本地进度。课程任务不需要改数据库，也不应该把登录/进度逻辑写进 scene。

## 7. 作者工作流

### 7.1 先写 `STORYBOARD.md`

在写任何 HTML 之前，先把课程讲清楚。模板：

```markdown
# <课程名>

## 学习者
谁，已经知道什么，不知道什么。

## 学完能
1.
2.
3.

## 屏幕

| # | id | 一句话论题 | 看见什么 | 动画如何论证 | 屏幕文字 | 讲义 | 时长 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | hook | 模型看到的不是字 | 一句话被切成碎片 | 碎片逐块变成数字 | 一行标题 + 一句结论 | … | 12s |
| 2 | split | 先切成 token | 分词器下刀 | 切分线依次落下 | … | … | 16s |

## 参考
- 来源、页码、链接。事实不确定的地方标出来。
```

要求：

- 每屏只有一个论题；写不出“一句话论题”就拆屏。
- “看见什么”和“动画如何论证”必须具体到动作，不能写“用动画展示”。
- 事实要有来源；不确定的内容不要写进课程。
- 先给用户/评审看 storyboard，再进入实现。storyboard 通过后再做动画，返工成本最低。

### 7.2 脚手架

平台内的新课程用脚手架脚本生成（只复制 `course.json`、`STORYBOARD.md` 和 `composition/`）：

```bash
python scripts/new_course.py <slug> --title "课程标题"
```

它会校验 `slug` 命名、拒绝覆盖已存在目录、把 `composition/package.json` 的 name 改成 `course-<slug>`，并把 `course.json` 的 `status` 重置为 `draft`。生成后改 `course.json` 的 `slug`、`title`、`subtitle`、`summary`、`outcomes`、`accent`。

外部作者拿到的模板包是仓库根目录的 `course-template/`：同一份两屏骨架，加上给作者和 AI 阅读的 `AGENTS.md`、`COURSE-CONTRACT.md`、`STYLE.md`。整个文件夹就是工作目录，生成完成后按 7.7 导入。

### 7.3 做 scene

1. 先做第一屏，在 `composition/` 下跑 `npm run check`。
2. 用 `npm run snapshot` 看 0%、50%、90% 三个时间点。
3. 确认文字可读、构图稳定、动画结束在稳定帧。
4. 需要现成的标题、图表、转场时，先查 HyperFrames registry；复用时把依赖本地化，并按第 4.6 节审计外部资源。
5. 再做下一屏；每加一屏都重新跑一次 composition 的 check/snapshot。
6. 不要等所有屏做完再检查。

### 7.4 接根 composition

1. 按 `STORYBOARD.md` 的顺序，在 `composition/index.html` 里挂 host。
2. 设置 `data-start` / `data-duration`，确保不重叠、根时长覆盖最后一屏。
3. 运行构建；如果报 `screen_meta_orphan` / `screen_host_orphan`，按提示补。
4. 构建解析出的时间必须和 storyboard 一致；不一致就改 storyboard 或 composition，不要手改产物。

### 7.5 构建和验收

```bash
python scripts/build_courses.py --course <slug>
```

只校验、不写产物：`python scripts/build_courses.py --course <slug> --check-only`。

然后在稿件所在目录跑 HyperFrames 自检（只警告不阻塞的项要逐条看过）：

```bash
cd courses/<slug>/composition && npx --yes hyperframes@0.9.19 check
```

构建完之后：

1. 打开站点 `/courses/<slug>/`，走一遍完整流程。
2. 起一个普通静态服务器再走一遍：`python scripts/serve.py dist/courses/<slug> --port 8081`。
   在 Windows 上不要用 `python -m http.server`——注册表可能把 `.js` 映射成 `text/plain`，浏览器会拒绝加载 ES module。
3. 用键盘走一遍。
4. 打开“减少动态效果”，确认不自动播放、讲义可读。
5. 断网/看 Network，确认没有外部请求。
6. 手机横屏看一遍；竖屏看讲义模式。

### 7.6 评审

至少看三遍：

1. 当学习者：能不能跟上？哪里走神？
2. 当审稿人：每屏一个论题？术语第一次出现有解释？事实有来源？
3. 当挑刺的人：暂停在任意一帧可读吗？最后一帧稳定吗？手机横屏能用吗？键盘顺手吗？

### 7.7 导入外部生成的课程

外部作者用 `course-template/` 生成的课程，不要求克隆整个仓库，按文件夹交付即可。导入是构建流水线的前置封装，不改变契约：

```bash
python scripts/import_course.py <课程文件夹>        # 导入一个课程文件夹
python scripts/import_course.py <父文件夹>          # 批量：导入其下所有含 course.json 的目录
python scripts/import_course.py --inbox             # 批量：扫描仓库根 course-inbox/
python scripts/import_course.py courses/<slug>      # 课程已在 courses/：只校验并重新构建
```

`course-inbox/` 是默认收件箱（不进 Git）。开发环境还提供 `/import` 页面：列出收件箱里的课程文件夹、显示校验状态、点击导入，并显示最近导入记录；生产环境（`ENV=prod`）不开放这个页面。

导入的约定：

1. **输入是课程文件夹本身**：里面有 `course.json`（必须）、`composition/`（必须）、可选 `cover.webp` 和 `STORYBOARD.md`。作者文件夹的名字不重要，最终目录名以 `course.json` 的 `slug` 为准。
2. **slug 不能是占位符或保留名**（`your-course-slug`、`_template`、`template`、`course-template`）；出现时报 `slug_reserved`，需在 `course.json` 里改成课程自己的 slug。
3. **先校验后落盘**：导入先在隐藏的临时目录里完成解析、资产扫描和构建，全部通过后才移动到 `courses/<slug>/` 并原子替换 `dist/courses/<slug>/`；失败不会留下半个课程。
4. **目标已存在**：默认报 `course_exists` 并停止；显式传 `--overwrite`（或页面上的覆盖导入）才替换。
5. **数据库只记来源**：成功后往 `course_imports` 表 upsert 一行（slug、标题、来源路径、来源哈希、内容哈希、屏数、时长、导入时间）。课程内容仍然在文件里，站点目录仍然只读 `dist/`；表没迁移或数据库不可用时导入照常完成，只打印警告。
6. **站点无需重启**：构建完成后目录加载器按 `dist/` 签名失效，下一次请求就能看到新课。
7. **草稿**：`status: "draft"` 的课程在 `--include-drafts` 打开时才会构建；构建被跳过时导入仍成功，但会提示先改成 `published`。

导入失败的错误码沿用 5.2；新增三个：

| 错误码 | 含义 | 修复 |
| --- | --- | --- |
| `slug_reserved` | `course.json` 的 slug 还是占位符或保留名 | 改成课程自己的小写连字符 slug |
| `course_exists` | `courses/<slug>/` 已存在 | 换 slug，或显式 `--overwrite` |
| `import_failed` | 复制、构建或替换过程中失败 | 看错误消息里的路径和原因；工作区已回滚 |

导入不替代人工验收：课程仍然要按第 8 节逐项检查。

### 7.8 配置课程水印

水印是课程的展示配置，不改变播放时间，也不写数据库。两种做法选一种：

1. **后台配置页（推荐）**：打开 `/admin/courses/<slug>/watermark`（需要 `ADMIN_TOKEN`），在 16:9 预览里调四角水印和满屏平铺水印。保存会写回 `courses/<slug>/course.json` 的 `watermark` 字段并重新构建该课程包；构建失败时页面会列出错误。
2. **手工编辑**：直接在 `course.json` 里加 `watermark`（见 3.7），然后运行 `python scripts/build_courses.py --course <slug>`。

注意：

- 水印只写课程源文件，`dist/` 是构建产物。改完不构建不会出现在课程页。
- 生产环境如果只部署了 `dist/` 和 `app/`，没有 `courses/` 源文件，配置页会变成只读；此时在持有课程源的机器上配置，或随课程包一起发布。
- 水印用于署名和降低截图外传的可读性，**不是访问控制**：它不阻止截图、下载或查看源码。需要权限控制时用登录和访问策略。

## 8. 验收清单

### 内容

- [ ] 每屏只有一个中心论题。
- [ ] 每屏的“一句话论题”能写出来。
- [ ] 术语第一次出现时有解释或类比。
- [ ] 事实有来源；没有编造的数据、引文或结论。
- [ ] 课程有开头、推进和回顾，不是知识点的平铺。
- [ ] 讲义和屏幕文字一致，没有互相矛盾。

### 元数据

- [ ] `slug` 等于目录名，符合命名规则。
- [ ] 从模板或外部文件夹导入的课程：slug 已替换占位符，`python scripts/import_course.py --dry-run <文件夹>` 通过。
- [ ] 标题、副标题、summary、outcomes、takeaways 完整。
- [ ] `level`、`tags`、`order`、`featured` 合理。
- [ ] 封面存在时 ≤ 300KB；没有封面时接受排版封面。
- [ ] `accent` 对比度足够，和课程内容气质一致。
- [ ] `audio` 和实际音频一致；有音频的屏都有 transcript。
- [ ] `watermark` 字段合法（颜色 `#RRGGBB`、字号和步长在范围内、每个角最多一条）；不需要水印时省略该字段。

### composition

- [ ] 根 `data-duration` 覆盖最后一屏。
- [ ] 每屏 host 的 id、`data-composition-id`、scene 时间轴 key 一致。
- [ ] 时间升序、不重叠、无意外空隙。
- [ ] 每完成一屏，composition 都通过 `npx hyperframes@0.9.19 check`。
- [ ] 每个 scene 的 0%/50%/90% 快照都看过。
- [ ] 没有外部资源加载、CDN、Google Fonts；引用链接不自动请求。
- [ ] GSAP、字体、runtime 都是本地文件。
- [ ] 没有 `Date.now()`、`setInterval()`、未播种随机数。
- [ ] 最后 0.5 秒是稳定帧。
- [ ] 单屏 10–30 秒，最长 ≤ 45 秒；整门课 2–5 分钟（长视频课程按 4.11 的例外验收）。
- [ ] 长视频课程：每屏有旁白、字幕在画布内、`audio: true`、`playback: "continuous"`、`autoAdvance: true`；`scripts/build_narration.py` 重跑后时间不变。

### 视觉

- [ ] 关键文字在 80% 标题安全区内。
- [ ] 正文字号 ≥ 40px；关键文字 ≥ 32px。
- [ ] 对比度 ≥ 4.5:1（正文）/ 3:1（大字）。
- [ ] 中文断行自然，没有孤字、拥挤或溢出。
- [ ] 一屏不超过两个文字层级。
- [ ] 颜色、字体、圆角、留白和课程整体一致。

### 播放体验

- [ ] 封面 → 第一屏正常。
- [ ] 播放页占满视口、无页面滚动，控制条通栏；16:9 画布按可用区域等比放大。
- [ ] 当前屏进度可以拖动；拖动时暂停，松手后若原本在播放则继续；拖到末端等同于跳到最后。
- [ ] 「跳到最后」和 `End` 停在当前屏的稳定末帧并标记本屏讲完。
- [ ] 总进度条按全课时间连续增长。
- [ ] 配置了水印时：四角水印和满屏平铺水印只出现在 16:9 画布内，不遮控制条；进入全屏仍可见；点击播放器、拖动进度、按钮操作都不受水印影响。
- [ ] 水印文字过长时在画布内换行或被裁掉，不会撑破舞台；颜色和透明度可读但不盖住正文。
- [ ] 下一屏/上一屏正常，能回到第一屏。
- [ ] 暂停/继续/重播正常。
- [ ] 讲义能打开、关闭，内容正确。
- [ ] 全屏正常，退出后焦点回到触发按钮。
- [ ] 键盘 ←/→/Space/End/C/M/T/F/Esc 正常。
- [ ] 深链 `#s=<id>` 打开后停在该屏，等用户播放。
- [ ] `prefers-reduced-motion` 下不自动播放。
- [ ] 本地进度能“继续上次”。
- [ ] 错误状态有说明和重试，不是空白。

### 独立部署

- [ ] 在 `dist/courses/<slug>/` 用普通静态服务器打开，所有屏正常。
- [ ] Network 面板没有外部请求；没有 `/api/*` 依赖。
- [ ] 不依赖 FastAPI、数据库、cookie 或登录态也能播放。
- [ ] 服务端进度不可用时，本地进度仍然能“继续上次”。
- [ ] `site.homeUrl` 为 `null` 时，返回链接隐藏。
- [ ] 课程页在子路径下部署（如 `/some/path/`）仍然正常；必要时把 `site.homeUrl` 设为站点绝对地址或 `null`。

### 性能

- [ ] 封面首屏 ≤ 2.5MB（gzip）。
- [ ] 首屏动画素材 ≤ 3MB。
- [ ] 整门课 ≤ 15MB（不含视频）。
- [ ] 桌面首帧 ≤ 2.5s（常见宽带）。
- [ ] 没有 console error / 404。

## 9. 常见错误

| 现象 | 原因 | 修复 |
| --- | --- | --- |
| 课程页一直黑屏/加载 | runtime 从 CDN 加载失败，或 `runtime-src` 没设 | 设置本地 `runtime-src` |
| 某屏不显示/渲染等待很久 | host id 和 scene 的 `data-composition-id`/时间轴 key 不一致 | 三处改成同一个 `s-<id>` |
| 最后一屏被截断 | 根 `data-duration` 太短 | 增大到覆盖最后一屏 |
| 切屏后停在错误的帧 | `data-start` 写错/重叠 | 检查时间范围 |
| 动画回看时状态漂移 | 用了 `from` 而不是 `fromTo` | 改成 `fromTo` |
| 课程包在子路径下 404 | 用了前导 `/` 的绝对路径 | 改成 `assets/...` 相对路径 |
| 字体在别人机器上变了 | 用了系统字体/Google Fonts | 本地 `@font-face` + 字体文件 |
| 手机上字太小 | 正文 < 40px 或关键文字 < 32px | 放大字号，减少每屏文字 |
| 动画结束在运动中间 | 没留结尾稳定帧 | 提前结束动画，留 0.5s |
| 构建报 `screen_meta_orphan` | 清单有屏幕但 composition 没 host | 补 host/删元数据 |
| 构建报 `external_asset` | 引用了 CDN 或外链 | 下载到 `assets/` |
| 编辑了 `dist/` 后下次构建被覆盖 | 改错了地方 | 改 `courses/<slug>/` 源文件 |
| 有音频但没有字幕/讲义 | 忘了 `transcript` | 补讲义 |
| 切屏按钮点不动 | 播放器 `interactive` + 事件冲突 | 纯动画不要设 `interactive`，外壳处理点击 |

## 10. 版本与升级

- 契约版本是 `schemaVersion: 1`。
- 独立模板包 `course-template/` 与本契约同版本；改字段、目录或时间规则时，同一任务内同步更新模板包里的 `COURSE-CONTRACT.md`、`course.json` 和 `STORYBOARD.md`。
- 新增可选字段不升 major；删除/改语义升 major，并提供迁移说明。
- HyperFrames/player/runtime 版本在 `runtime/VERSION.json` 里固定。
- 升级 HyperFrames 后，所有课程要重新构建，并通过播放器契约测试和至少两门课的逐屏快照。
- 不要单独升级某一门课的 player；运行时是共享的，版本要一致。

## 11. FAQ

**可以放视频吗？**
可以，但必须本地、压缩、带 `muted` 或 `data-has-audio="true"`，并计入预算。视频不能替代文字和讲义。

**可以用 Three.js / Lottie / anime.js 吗？**
可以。把库放到 `assets/vendor/`，带 LICENSE，按 HyperFrames 的 runtime 规则初始化（暂停、可 seek、注册到对应的全局数组/时间轴），并在 storyboard 里记录版本。不要从 CDN 加载。

**一屏可以互动吗？**
v1 不做。`interactive` 字段保留，但课程外壳和播放器的交互模式还没有验收。练习、分支、测验属于后续平台能力。

**课程任务要处理登录/数据库吗？**
不。课程包不依赖登录和数据库；课程外壳先写本地进度，站点同源时再同步。课程任务只写 `courses/<slug>/`，不要加数据库迁移或登录逻辑。

**可以自定义课程页吗？**
v1 不可以。用封面、强调色、文案和 composition 做差异。需要新外壳时开平台任务，不要复制 shell。

**一门课可以拆成多个 composition 吗？**
v1 不建议。超过 15 屏、50MB 或需要不同画布尺寸时，拆成系列课程，每门课仍是独立包。

**能把别人做好的课程直接放进项目吗？**
可以。课程文件夹通过 `python scripts/import_course.py`（或开发环境的 `/import` 页面）导入：校验、复制到 `courses/<slug>/`、构建到 `dist/`，并在 SQLite 的 `course_imports` 表记一条来源。也可以手动复制到 `courses/<slug>/` 后跑 `python scripts/build_courses.py --course <slug>`。两种方式都要通过本契约；数据库只记来源，不存课程内容。

**可以离线看吗？**
可以离线播放（所有资源本地），但需要通过 HTTP 静态服务器打开，不能双击 `file://`。player 需要同源 iframe 和 runtime 注入。

**可以导出 MP4 吗？**
可以从同一份 composition 导出，作为附属产物。但课程包不依赖 MP4，也不把 MP4 作为主要分发格式。

**课程应该多长？**
6–10 屏，2–5 分钟。单屏 10–30 秒。超过 45 秒的屏通常需要拆。

**必须写 `STORYBOARD.md` 吗？**
必须。它是课程评审和后续修改的依据，不进入构建产物。没有 storyboard 的课程不允许进入实现。
