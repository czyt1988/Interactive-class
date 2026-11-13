# 课程契约（作者版）

> 这是 AI Learning 平台课程契约的作者版摘要：只保留外部作者和外部 AI 生成课程时需要的规则。
> 完整契约以平台仓库 `docs/course-contract.md` 为准；本文与它冲突时以平台为准。
> 字段、长度和枚举以平台代码 `app/catalog/models.py` 为准；本文列的是作者最常踩到的部分。

## 1. 一个课程包是什么

一门课 = 一个文件夹，里面有：

- `course.json`：编辑清单，课程的全部元数据和每屏文案；
- `composition/`：一个 HyperFrames 工程，画面和动画；
- `STORYBOARD.md`：课程脚本，不进入构建产物；
- `cover.webp`（可选）：课程封面。

约定：

- **一门课一个 composition。**
- **一屏一个 scene。**
- **屏幕顺序和时间由根 composition 决定，编辑信息由 `course.json` 决定。**
- 课程包是自包含静态包：构建产物不依赖 API、数据库、登录态，不引用 CDN，断网也能完整播放。

## 2. 目录结构

```text
<课程文件夹>/
├─ course.json                     # 必须
├─ STORYBOARD.md                   # 必须（不进产物）
├─ cover.webp                      # 可选，1600×900，≤ 300KB
└─ composition/                    # 必须，HyperFrames 工程根
   ├─ index.html                   # 根 composition
   ├─ package.json                 # 可选，本地创作脚本（固定版本）
   ├─ compositions/
   │  ├─ 01-hello.html
   │  ├─ 02-world.html
   │  └─ ...
   └─ assets/
      ├─ course.css
      ├─ fonts/NotoSansSC-VF.woff2  # 本地字体
      ├─ images/                    # 本地图片
      ├─ audio/                     # 本地音频（可选）
      └─ vendor/gsap.min.js         # 本地 GSAP
```

说明：

- **不要求 `hyperframes.json`**：平台现有课程都没有它，构建也会跳过它。`package.json` 只用于本地 `npm run check` / `snapshot` / `preview`，不进入构建产物。
- 构建产物只包含 `course.json`、`composition/` 的可分发文件和平台运行时；`STORYBOARD.md`、`package.json`、`node_modules/`、`renders/`、`.hyperframes/`、`*.mp4`、`*.map` 不会被打包。
- 交付时整个文件夹一起交，不要只交 `composition/`。

## 3. 命名规则

| 对象 | 规则 |
| --- | --- |
| `slug` | `^[a-z0-9]+(?:-[a-z0-9]+)*$`，例如 `what-is-a-token`。平台导入时它会成为 `courses/<slug>/` 的目录名，因此不能是保留名：`your-course-slug`、`_template`、`template`、`course-template` |
| 屏幕 `id` | `^[a-z][a-z0-9-]*$`，1–32 字符，全课唯一，例如 `hello`、`two-paradigms` |
| scene 文件名 | 建议 `NN-<screen-id>.html`，序号只用于阅读，不参与排序 |
| host 元素 id | 固定 `s-<screen-id>` |
| scene 的 `data-composition-id` | 固定 `s-<screen-id>`，与 host 的 `id` 一致 |
| scene 的时间轴 key | 固定 `s-<screen-id>`，即 `window.__timelines["s-<screen-id>"]` |

改 `id` 要同时改四处：`course.json` 的 `screens[].id`、根 composition 的 host、scene 文件名、scene 内的 `data-composition-id` 与时间轴 key。

## 4. `course.json`

### 4.1 示例

就是本文件夹里的 `course.json`：字段完整、值全部是合法占位符。把它们逐项换成课程自己的内容。

### 4.2 顶层字段

| 字段 | 必须 | 类型 | 规则 |
| --- | --- | --- | --- |
| `schemaVersion` | 是 | int | 固定 `1` |
| `slug` | 是 | string | 见第 3 节；不能是占位符 |
| `title` | 是 | string | 2–40 字符；课程页 `h1` |
| `subtitle` | 否 | string | 1–60 字符；封面副标题 |
| `summary` | 是 | string | 40–160 字符；课程卡片和搜索摘要 |
| `description` | 否 | string | 长描述，纯文本；课程页和 SEO |
| `level` | 是 | enum | `beginner` / `intermediate` / `advanced` |
| `tags` | 否 | string[] | 最多 5 个，每个最多 12 字符 |
| `language` | 否 | string | 默认 `zh-CN` |
| `status` | 是 | enum | `draft` / `published` / `archived`；平台默认只构建 `published` |
| `featured` | 否 | bool | 默认 `false` |
| `order` | 否 | number | 默认 `100`；越小越靠前 |
| `accent` | 否 | string | `#RRGGBB`，课程身份强调色 |
| `cover` | 否 | string | 课程目录内的相对路径；不能以 `/` 开头、不能含 `..` |
| `outcomes` | 否 | string[] | 留空，或 2–4 条；封面「学完能」 |
| `prerequisites` | 否 | string[] | 最多 3 条 |
| `takeaways` | 否 | string[] | 留空，或 2–4 条；完成页回顾 |
| `audio` | 否 | bool | 默认 `false`；为 `true` 时每屏必须有 `transcript` |
| `interactive` | 否 | bool | 默认 `false`；v1 不使用 |
| `playback` | 否 | enum | `screens`（默认）/ `continuous` |
| `composition` | 否 | object | 建议显式填写；省略时用 4.3 的默认值 |
| `screens` | 是 | array | 至少 1 项，`id` 唯一 |
| `site` | 否 | object | 见 4.5 |
| `credits` | 否 | object | 见 4.6 |

**未知字段一律报错。** 拼错的 `autoAdvence` 不会静默失效，会变成 `manifest_invalid`。

**不要在源清单里写 `start`、`duration`、`index`。** 它们由构建从 composition 解析后写进产物；手写一定会和 composition 漂移。

### 4.3 `composition`

| 字段 | 必须 | 类型 | 规则 |
| --- | --- | --- | --- |
| `entry` | 否 | string | 默认 `composition/index.html`；必须以 `composition/` 开头、以 `.html` 结尾，不能以 `/` 开头、不能含 `..` |
| `width` | 否 | int | 固定 `1920` |
| `height` | 否 | int | 固定 `1080` |
| `fps` | 否 | int | 固定 `30` |

### 4.4 `screens[]`

| 字段 | 必须 | 类型 | 规则 |
| --- | --- | --- | --- |
| `id` | 是 | string | 见第 3 节；必须和根 composition 的 `data-screen-id` 一致 |
| `kicker` | 否 | string | 例如 `01 / 开场`，显示在屏幕上方 |
| `title` | 是 | string | 1–40 字符 |
| `summary` | 是 | string | 1–120 字符；控制条和大纲里的那一句 |
| `transcript` | 否 | string | 讲义纯文本；`audio: true` 时每屏必须有 |
| `autoAdvance` | 否 | bool | 默认 `false`；为 `true` 时到点自动进下一屏 |
| `poster` | 否 | string | 可选，当前屏静态帧，用于加载/降级 |
| `keywords` | 否 | string[] | 最多 5 个；只影响搜索 |

`screens` 数组顺序只用于阅读；播放顺序以根 composition 的 `data-start` 为准。两者保持一致，避免自己看晕。

### 4.5 `site`

| 字段 | 必须 | 类型 | 规则 |
| --- | --- | --- | --- |
| `homeUrl` | 否 | string \| null | 默认 `/`；必须是绝对 `http(s)` 地址、以 `/` 开头的站内路径，或 `null`（独立分发时隐藏返回入口） |
| `backLabel` | 否 | string | 默认 `返回课程库` |

平台会在课程页顶部渲染一条吸顶页眉，里面是「← `backLabel`」的真实链接，目标为 `homeUrl`。页眉只在封面可见，开始播放后隐藏，退出改由控制条第一个控件「退出课程」承担；完成页和错误页也各有自己的返回按钮。`homeUrl` 为 `null` 时整条页眉不渲染，这些返回入口也都不显示，适合完全独立分发的课程。

### 4.6 `credits`

| 字段 | 必须 | 类型 | 规则 |
| --- | --- | --- | --- |
| `author` | 否 | string | 作者/团队 |
| `updatedAt` | 否 | string | `YYYY-MM-DD`，必须是合法日期 |
| `sources` | 否 | string[] | 参考资料链接或说明；只用于展示，运行时不会请求 |

### 4.7 课程水印（不是课程字段）

课程水印是平台部署方的配置，不存在 `course.json` 里：平台后台 `/admin/courses/<slug>/watermark` 把它保存在站点数据库（不进 Git、不随课程源文件分发），构建时再把水印层写进构建产物的 composition 内层，独立部署也保留，网页播放和后台导出的视频都带同一层。外部作者不需要、也不应该写 `watermark` 字段，写了会被平台当作未知字段拒绝。

需要水印时交给需求方在平台后台配置（角标四角最多各一条 + 满屏平铺一层）。水印只覆盖播放画布，不遮控制条、不拦截点击，进入全屏仍可见，导出的视频也带；它是署名和降低截图外传可读性的展示配置，不是访问控制。

## 5. composition 根工程

### 5.1 工程根与 `package.json`

`composition/` 是标准 HyperFrames 工程根。在 `composition/` 目录里运行：

```bash
npm run check       # npx --yes hyperframes@0.9.19 check
npm run snapshot    # 导出 0% / 50% / 90% 快照
npm run dev         # npx --yes hyperframes@0.9.19 preview
```

`package.json` 的脚本必须固定版本，不要用 `latest`：

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

模板里已经固定成 `hyperframes@0.9.19`；生成新课程时把 `name` 改成 `course-<slug>`，版本不要动。

### 5.2 根 `index.html`

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
      data-duration="26"
      data-width="1920"
      data-height="1080"
    >
      <div
        id="s-hello"
        data-screen-id="hello"
        data-composition-id="s-hello"
        data-composition-src="compositions/01-hello.html"
        data-start="0"
        data-duration="12"
        data-track-index="0"
        data-track-kind="graphics"
        data-width="1920"
        data-height="1080"
      ></div>
      <!-- 其余屏按 data-start 升序继续挂 -->
    </div>
    <script>
      window.__timelines = window.__timelines || {};
      window.__timelines["main"] = gsap.timeline({ paused: true });
    </script>
  </body>
</html>
```

根 composition 规则：

- 根元素必须是 `<div id="root">`（双引号），带数字的 `data-duration`；`data-width` / `data-height` 必须和 `course.json` 一致（1920 / 1080）。
- 根时间轴必须注册，可以是空时间轴。**不要把 scene 的时间轴 `add()` 进根时间轴**，运行时自己驱动 scene。
- 根 `data-duration` 是整门课总时长，必须 ≥ 最后一屏的 `start + duration`，建议正好相等。
- host 按 `data-start` 升序书写，`data-start` 只写数字，不要写表达式。
- 不要在根 composition 里写导航、进度条、返回按钮，这些属于平台播放器外壳。

### 5.3 host 属性

| 属性 | 必须 | 说明 |
| --- | --- | --- |
| `id` | 是 | `s-<screen-id>` |
| `data-screen-id` | 是 | `course.json` 里的屏幕 id |
| `data-composition-id` | 是 | 与 `id` 相同 |
| `data-composition-src` | 是 | 指向 `compositions/` 下的 scene 文件 |
| `data-start` | 是 | 数字秒，绝对时间 |
| `data-duration` | 是 | 数字秒，这一屏的教学节拍 |
| `data-track-index` | 是 | 全课唯一整数，从 0 开始 |
| `data-track-kind` | 否 | 建议 `graphics` |
| `data-width` / `data-height` | 是 | `1920` / `1080` |

## 6. scene 文件

scene 是片段，不是完整 HTML 页面。正确示例（就是本模板的第一屏）：

```html
<template>
  <style>
    #root {
      position: absolute;
      inset: 0;
      background: #f4efe6;
      color: #16140f;
      font-family: "Noto Sans SC", sans-serif;
    }

    #s-hello-title {
      position: absolute;
      left: 192px;
      top: 340px;
      width: 1536px;
      font-size: 140px;
      line-height: 1.1;
      font-weight: 700;
      letter-spacing: -0.03em;
    }
  </style>

  <div id="root" data-composition-id="s-hello" data-width="1920" data-height="1080">
    <h1 id="s-hello-title" class="clip" data-start="0.2" data-duration="11.4">
      第一屏说什么
    </h1>
  </div>

  <script>
    const tl = gsap.timeline({ paused: true });

    tl.fromTo(
      "#s-hello-title",
      { opacity: 0, y: 48 },
      { opacity: 1, y: 0, duration: 0.6, ease: "power3.out" },
      0.2,
    );

    window.__timelines["s-hello"] = tl;
  </script>
</template>
```

规则：

- 全部样式、标记、脚本都在 `<template>` 内。
- scene 根写成 `<div id="root">`，用 `position: absolute; inset: 0`，不要写死 1920×1080 像素。
- scene 内所有元素 id 加 `s-<screen-id>-` 前缀，避免跨屏冲突。
- 时间轴必须 `paused: true`，并注册到 `window.__timelines["s-<screen-id>"]`；异步构建时注册必须是最后一步。
- 用 `fromTo`，不要用 `from`：scene 会被反复 seek，`from` 的起始状态会漂移。
- 不要在 scene 里 `play()` / `pause()` / seek 媒体，时钟由运行时负责。
- 所有可见状态必须是时间轴时间的函数：不用 `Date.now()`、`setInterval()`、未播种的 `Math.random()`。

## 7. 时间规则

- `data-start` 和 `data-duration` 都是**数字秒**，不是毫秒、不是帧。
- 屏幕按 `data-start` 严格升序，区间不能重叠；允许空隙，但空隙不会出现在任何一屏里，通常说明时间没排好。
- 根 `data-duration` 必须 ≥ 最后一屏的 `start + duration`。
- 单屏 10–30 秒，最长不超过 45 秒；一门课 6–10 屏、总时长 2–5 分钟。
- 一屏的 duration 是教学节拍：入场 + 讲解 + 结尾停留。不要卡着「文字读完的时间」。
- 屏幕要在结束前落到稳定状态，最后一帧就是学习者停留阅读的帧；不要在最后一刻还在动。
- 平台播放器可以把当前屏进度拖到最后，或直接「跳到最后」（`End`）：它会暂停在本屏最后一帧并标记讲完。因此最后一帧必须是完整、稳定、可读的最终状态；关键信息不能只存在于动画中途，也不要假设动画一定从头播完。逐屏进度和跳到最后属于平台外壳，不需要也不应该在 composition 里实现。
- scene 时间轴可以比 host 的 `data-duration` 短，短的部分保持最后一帧。

## 8. 资源、字体与预算

资源规则：

- 所有路径相对，从 `assets/` 开始，不要以前导 `/` 开头。
- scene 文件里引用素材也写 `assets/...`（按 composition 工程根解析），不要写 `../assets/...`。
- 不允许外部资源加载：`script[src]`、会加载资源的 `link[href]`、`img/source/video/audio[src]`、`poster`、CSS `url()`、`@import` 都不能指向课程包外部。
- 普通 `<a href>` 外链可以用于引用和致谢，但要加 `rel="noopener noreferrer"`，且不能自动加载。
- GSAP 放在 `assets/vendor/gsap.min.js`，在根 `index.html` 里本地引用，版本 3.15.0。
- 字体必须本地：`@font-face` 的 `src` 指向 `assets/fonts/...`；中文正文用自托管的 Noto Sans SC 子集，不要用 Google Fonts 或系统字体作为唯一方案。
  - 模板自带的 woff2 是**预生成子集**（常用字 + 模板文案）。课程新写了子集外的字会缺字形；由平台侧运行 `python scripts/sync_runtime.py` 按课程文案重新生成子集，作者不要用 CDN 字体绕过。
- 图片用 WebP / AVIF；音频用 AAC / MP3 / Opus。
- 第三方库放 `assets/vendor/`，带 LICENSE，并在 `STORYBOARD.md` 记录版本。

预算：

| 项目 | 上限 |
| --- | --- |
| 封面 | 300KB |
| 单张图片 | 500KB |
| 单屏素材 | 3MB |
| 整门课（不含视频） | 15MB |
| 字体子集 | 2MB |
| 单个 HTML 文件 | 200KB |

超预算先优化素材，不要先放宽上限。

## 9. 禁止项

- 外部网络请求、CDN 字体/脚本/图片、Google Fonts。
- `fetch`、XHR、WebSocket、动态数据。
- `Date.now()`、`setInterval()`、未播种的 `Math.random()` 当动画时钟。
- 深色场景、深色主题；课程只用亮色纸面（见 `STYLE.md`）。
- 在 composition 里放站点导航、课程进度、返回按钮。
- 一屏讲两个中心概念；关键信息只存在于动画里，暂停后读不到。
- 正文小于 40px，或对比度不足。
- 直接编辑构建产物；手写 `start` / `duration` 到 `course.json`。
- 在 scene 里 `play()` / `pause()` / seek 媒体。
- 把 `node_modules/`、`renders/`、`.hyperframes/`、MP4 打进交付文件夹。

## 10. 构建错误码 → 修复

每条错误都带课程 slug、文件路径、屏幕 id、字段名和期望值；按这五样定位即可。

### 清单与结构

| 错误码 | 含义 | 修复 |
| --- | --- | --- |
| `manifest_invalid` | `course.json` 不是合法 JSON、字段类型/长度/枚举不对，或出现未知字段 | 看报错里的 `field`，按 4.2–4.7 的规则改；有音频却没写 `transcript` 也报这个 |
| `slug_mismatch` | `slug` 和目录名不一致 | 平台导入会自动按 slug 建目录；只有直接把文件夹放进平台 `courses/` 时才需要两者一致 |
| `slug_reserved` | `slug` 还是占位符或保留名 | 改成课程自己的小写连字符 slug |
| `course_exists` | 平台里同 slug 课程已存在 | 换 slug，或导入时显式覆盖 |
| `import_failed` | 导入复制、构建或替换过程中失败 | 看错误里的路径和原因；工作区已回滚，修好后重试 |
| `cover_missing` | `cover` 指向的文件不存在 | 补文件或删掉 `cover` |
| `composition_missing` | 找不到 `composition.entry` | 检查 `composition/index.html` 是否存在、路径是否写对 |
| `composition_invalid` | 根 composition 里没有任何 host | 至少挂一屏 host |

### 时间与 host

| 错误码 | 含义 | 修复 |
| --- | --- | --- |
| `root_duration_missing` | 根找不到 `id="root"` 或没有数字 `data-duration` | 补 `<div id="root" data-duration="…">` |
| `root_duration_short` | 根时长不足以覆盖最后一屏 | 把根 `data-duration` 改成 ≥ 最后一屏结束时间 |
| `host_start_invalid` / `host_duration_invalid` | `data-start` / `data-duration` 缺失、不是数字，或 duration ≤ 0 | 改成数字秒，`start` ≥ 0、`duration` > 0 |
| `host_order_invalid` | host 没有按 `data-start` 严格升序 | 重排 host 或修时间 |
| `host_overlap` | 两屏时间重叠 | 调 `data-start` / `data-duration`，让相邻屏不重叠 |
| `host_id_mismatch` | host 的 `id` 或 `data-composition-id` 不是 `s-<screen-id>` | 改成与 `data-screen-id` 对应的 `s-<id>` |
| `host_track_missing` / `host_track_duplicate` | 缺 `data-track-index`，或两个 host 用了同一个 | 每屏一个唯一整数 |
| `composition_size_invalid` | 根 `data-width` / `data-height` 与清单不一致 | 都改成 1920 / 1080 |
| `screen_id_invalid` / `screen_id_duplicate` | 屏幕 id 不合命名规则或重复 | 改成 `^[a-z][a-z0-9-]*$` 的唯一值 |
| `screen_meta_orphan` | `course.json` 有屏幕，composition 里没有 host | 补 host，或删元数据 |
| `screen_host_orphan` | composition 有 host，`course.json` 里没有元数据 | 补元数据，或删 host |

### scene 与资源

| 错误码 | 含义 | 修复 |
| --- | --- | --- |
| `scene_missing` | `data-composition-src` 指向的文件不存在，或没写这个属性 | 补文件或改路径（相对 `compositions/`） |
| `scene_invalid` | scene 缺 `<template>`，或缺 `id="root"` | 按第 6 节的结构重写 |
| `scene_id_mismatch` | scene 的 `data-composition-id` 与 host 不一致 | 三处统一成 `s-<id>` |
| `timeline_missing` | scene 没有注册 `window.__timelines["s-<id>"]` | 补注册，并确认 key 拼写一致 |
| `external_asset` | HTML/CSS 里有外部资源加载 | 下载到本地 `assets/`，改相对路径 |
| `absolute_asset_path` | 资源路径以 `/` 开头 | 改成 `assets/...` |
| `asset_outside_bundle` | 资源路径 escaped 出课程包（`../`） | 把素材放进 `composition/assets/` |
| `asset_missing` | 引用的本地文件不存在 | 补文件或改路径 |
| `forbidden_clock` | 用了 `Date.now()` / `setInterval()` / `Math.random()` | 改成时间轴上的 tween |
| `vendor_missing` | 缺 `assets/vendor/gsap.min.js` | 从模板复制或重新同步 |
| `asset_budget_exceeded` | 单文件或整门课超预算 | 压缩/删减素材，见第 8 节 |

## 11. 验收清单

内容：

- [ ] 每屏只有一个中心论题，能一句话说出来。
- [ ] 术语第一次出现有解释或类比；事实都有来源，没有编造的数据、引文、结论。
- [ ] 课程有开场、推进、回顾，不是知识点平铺。
- [ ] 讲义（`transcript`）和屏幕文字一致。

元数据：

- [ ] `slug` 已替换占位符，符合命名规则。
- [ ] `title`、`subtitle`、`summary`、`outcomes`、`takeaways` 已换成真实内容，没有残留「待替换」。
- [ ] `level`、`tags`、`order`、`featured` 合理。
- [ ] `accent` 是 `#RRGGBB`，与课程气质一致，对比度足够。
- [ ] 封面存在时 ≤ 300KB；没有封面时接受排版封面。
- [ ] `audio` 和实际音频一致；有音频的屏都有 `transcript`。
- [ ] 交付前 `status` 改成 `published`（否则平台默认跳过构建）。

composition：

- [ ] 根 `data-duration` 覆盖最后一屏。
- [ ] 每屏 host 的 `id`、`data-composition-id`、scene 的文件 id 和时间轴 key 四处一致。
- [ ] 时间严格升序、不重叠。
- [ ] 每个 scene 通过 `npm run check`，0% / 50% / 90% 快照都看过。
- [ ] 没有外部资源加载、CDN、Google Fonts；没有 `Date.now()` / `setInterval()` / 未播种随机数。
- [ ] GSAP、字体都是本地文件。
- [ ] 最后一帧稳定；单屏 10–30 秒；整门课 2–5 分钟。

视觉：

- [ ] 关键文字在 192px 标题安全区内，正文不压边。
- [ ] 正文 ≥ 40px，关键文字 ≥ 32px。
- [ ] 对比度：正文 ≥ 4.5:1，大字号 ≥ 3:1。
- [ ] 一屏最多两个文字层级；亮色纸面，没有深色场景。
- [ ] 中文断行自然，每行 18–28 字，没有溢出。

播放：

- [ ] 断网后在静态服务器下能完整播放，Network 面板没有外部请求。
- [ ] 封面不用滚动就能看到「返回课程库」入口；开始播放后页眉隐藏，由控制条第一个控件退出课程（平台外壳提供，入口来自 `site.homeUrl`）。
- [ ] 暂停、切屏、重播、拖动当前屏进度、跳到最后（`End`）、讲义、全屏正常（由平台播放器提供，作者只需保证 composition 正确）。
- [ ] 每一屏的最后一帧是完整、可读的最终画面；拖到末尾或跳到最后时停下的就是这一帧。
- [ ] `prefers-reduced-motion` 下不自动播放。

## 12. 与平台契约的关系

本文是作者版摘要。完整平台契约（解析算法、构建流水线、课程页、进度同步、导入流程）见平台仓库的 `docs/course-contract.md`；视觉规范见 `DESIGN.md` 第 8 节。本文与平台文档冲突时以平台为准；字段校验以 `app/catalog/models.py` 为准。
