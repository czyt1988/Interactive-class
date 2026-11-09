# AGENTS.md

这个文件夹是一份**课程模板包**，也是你生成一门课的工作目录。你的产物不是一段说明，而是一个可以直接交回 AI Learning 平台导入的完整课程文件夹。

先把这三句话记住：

1. 一门课一个 HyperFrames composition，一屏一个 scene。
2. 屏幕顺序和时间由根 composition 决定，编辑信息由 `course.json` 决定。
3. 没有事实来源的内容不要写。宁可少一屏，也不要编一个数字。

本文件是给 AI 的操作指引。给作者看的完整规范在同目录的 `COURSE-CONTRACT.md`（结构、字段、错误码）和 `STYLE.md`（视觉）；本文件与它们冲突时，`COURSE-CONTRACT.md` 优先，平台契约又优先于它。

## 1. 你的任务

在这个目录里产出一门完整课程，最终交给平台导入：

- 产出：`course.json`、`STORYBOARD.md`、`composition/`（根 `index.html` + 每屏一个 scene + 本地资源），可选 `cover.webp`。
- 不产出：平台代码、构建产物、视频、`node_modules/`。
- 验收标准：见第 5 节自检清单；交付前每一条都要能打勾，或者明确写出「未验证及原因」。

模板自带的 `hello` / `world` 两屏是**脚手架**，用来演示结构和写法，不是课程内容。正式课程要把它们替换成真实屏幕；最终交付里不应残留模板占位文案。

## 2. 开工前：先向需求方确认这些输入

缺哪一项就问，不要用「一般来说」自己补。**尤其第 4 项：没有事实来源就不要开始写内容。**

| # | 要确认的输入 | 为什么 |
| --- | --- | --- |
| 1 | 主题与范围 | 讲什么、明确不讲什么；边界不清就会写成知识点平铺 |
| 2 | 目标读者 | 已经知道什么、不需要解释什么；决定术语要不要解释 |
| 3 | 学完能 | 3 条以内，动词开头；整门课围绕它组织 |
| 4 | 事实来源 | 文档、论文、官方博客、截图、页码或链接；谁负责审事实。**没有来源的数字、日期、引文、机构名一律不写** |
| 5 | 屏数与总时长 | 默认 6–10 屏、总时长 2–5 分钟、单屏 10–30 秒；需求方要短演示时以需求方为准，并说明这不是完整课程 |
| 6 | 有没有音频 | 默认没有；旁白需要平台侧的旁白流水线，不要自己临时配音或写死音频时间 |
| 7 | 封面素材 | 有图就给 1600×900、≤300KB 的 WebP；没有就用平台的排版封面，不要自己拼假截图 |
| 8 | 课程强调色 | 一个 `#RRGGBB`；需求方不给就用模板默认的 `#B8452B` |
| 9 | 语言与语气 | 默认简体中文；专业术语保留英文原文 |
| 10 | 是否允许外部链接 | `<a href>` 引用外链允许（不自动加载），但不能用 CDN 加载任何资源 |

如果需求方给不出第 4 项：先做调研并列出待核实清单，把不确定的结论删掉；不要用「据说」「业内普遍认为」糊过去。

## 3. 工作流程（按顺序，每步有验收门）

### 第 1 步：定 slug

- 小写字母、数字、连字符：`^[a-z0-9]+(?:-[a-z0-9]+)*$`，例如 `what-is-a-token`。
- 不能是 `your-course-slug`、`_template`、`template`、`course-template`（平台导入会报 `slug_reserved`）。
- 平台导入时，最终目录名以 `course.json` 的 `slug` 为准；你现在这个文件夹叫什么不重要。
- slug 定了就写进 `course.json`，后面四处 id 都从它派生（见第 4 节）。

### 第 2 步：先写 `STORYBOARD.md`，评审通过再写 HTML

- 按文件里的说明填：学习者、学完能、屏幕表（每屏的一句话论题 / 看见什么 / 动画如何论证 / 屏幕文字 / 讲义 / 时长）。
- **把 storyboard 交给需求方确认。** 没通过不要进入实现；返工成本最低的地方就是这里。
- 事实来源也在这一步写清楚。

### 第 3 步：改 `course.json`

- 逐项替换所有「待替换」占位文案，交付前不能残留「待替换」三个字。
- 检查长度硬限制：`title` 2–40 字符、`summary` 40–160、`screens[].title` ≤40、`screens[].summary` ≤120、`tags` ≤5 个且每个 ≤12 字符、`outcomes` / `takeaways` 为 2–4 条或留空。
- `screens[]` 的顺序、`id`、文案要和 `STORYBOARD.md` 一致。
- **不要写 `start` / `duration` / `index`**，这些由平台从 composition 解析后生成。
- `status` 开发期保持 `draft`，**交付前改成 `published`**（平台默认只构建 published）。
- `credits.author` 写真实作者；`credits.sources` 写事实来源。

### 第 4 步：逐屏写 scene

- 以 `composition/compositions/01-hello.html` 为样板：`<template>` 包裹、`<div id="root">`、`paused: true` 的 GSAP 时间轴、注册 `window.__timelines["s-<id>"]`、用 `fromTo`。
- 一屏一个文件，文件名 `NN-<screen-id>.html`；每屏的元素 id 加 `s-<screen-id>-` 前缀。
- 时间轴里只用屏内相对时间（0 到这一屏的时长）；屏与屏之间的衔接由根 composition 管。
- **一次只做一屏**，从第一屏做到最后一屏。每写完一屏：

  ```bash
  cd composition
  npm run check      # HyperFrames 自检，必须过
  npm run snapshot   # 看 0% / 50% / 90% 三帧
  ```

  环境里没有 Node 或跑不了 HyperFrames，也不能跳过：在交付说明里写清哪一屏没跑过 check。
- 每屏自检：一个论题、最多两个文字层级、关键文字在安全区内、最后一帧稳定、屏幕文字和 `course.json` 的 `transcript` 一致。

### 第 5 步：接根 composition

- 在 `composition/index.html` 里把 host 换成真实屏幕，按 `data-start` 升序排列。
- 每屏设置 `data-start` / `data-duration`（数字秒，不重叠），`data-track-index` 用唯一整数。
- 修改根 `data-duration`，让它 ≥ 最后一屏的 `start + duration`，建议正好相等。
- 四处 id 必须一致：`course.json` 的 `screens[].id`、host 的 `id`、scene 的 `data-composition-id`、scene 注册的时间轴 key；统一写成 `s-<id>`。
- 模板里的两条 host 是示例，多余的删掉；不要留空 host。

### 第 6 步：全量自检

按第 5 节从头到尾跑一遍。重点：`npm run check` 全过、时间不重叠、没有外部资源、没有禁用时钟、slug 已替换、`status` 已改、没有残留「待替换」。

### 第 7 步：交付

- 交付物是**整个课程文件夹**：`course.json`、`STORYBOARD.md`、`composition/`，可选 `cover.webp`。
- 清理后再交：删掉 `composition/node_modules/`、`composition/renders/`、`composition/.hyperframes/`、`*.mp4`。
- 交付时写一段简短说明：屏数、总时长、事实来源清单、哪些项没验证及原因。

## 4. 硬规则

### 结构

- **一门课一个 composition，一屏一个 scene。** 不要拆成多个 composition，也不要把多屏塞进一个 scene。
- 根 `index.html`：`<div id="root" data-composition-id="main" data-duration="…" data-width="1920" data-height="1080">`，`data-duration` 必须是数字秒；根时间轴注册成空时间轴，**不要把 scene 时间轴 `add()` 进去**。
- 每个 host 必须有：`id="s-<id>"`、`data-screen-id`、`data-composition-id="s-<id>"`、`data-composition-src="compositions/NN-<id>.html"`、`data-start`、`data-duration`、唯一的 `data-track-index`、`data-width="1920"`、`data-height="1080"`；建议加 `data-track-kind="graphics"`。
- scene 必须是 `<template>` 片段，里面有 `<div id="root">`（双引号），不是完整 HTML 页面。
- `composition/package.json` 只用于本地 `npm run check` / `snapshot` / `preview`，脚本固定 `hyperframes@0.9.19`；**不需要 `hyperframes.json`**，平台不读它，构建也会跳过它。
- 时间轴必须 `paused: true`，并注册 `window.__timelines["s-<id>"]`；用 `fromTo`，不用 `from`。

### 时间

- 一律用**秒**（不是毫秒、不是帧）。
- 屏按 `data-start` 严格升序、区间不重叠；允许空隙但没有必要。
- 根 `data-duration` 覆盖最后一屏；一屏在结束前已经落到稳定帧。
- 平台播放器可能把当前屏进度拖到最后，或直接「跳到最后」（`End`）：它会暂停在本屏最后一帧并标记讲完。所以每一屏的最后一帧必须是完整、稳定、可读的最终状态，关键信息不能只存在于动画中途，也不要假设动画一定从头播完。
- 单屏 10–30 秒（最长 45 秒）；正式课程 6–10 屏、2–5 分钟；需求方明确要短演示时按第 2 节第 5 项处理。
- 不要手写时间到 `course.json`。

### 画布与视觉

- 1920×1080，30fps。
- 只用亮色纸面，禁止深色场景；色值、字号阶梯、安全区、构图和禁止项全部按 `STYLE.md`。
- 一屏一个论题、最多两个文字层级；中文每行 18–28 字；正文 ≥40px；对比度正文 ≥4.5:1。
- 标题安全区左右 192px、顶部 96px；底部 180px 作为安全边距（旁白课程的旁白条也落在这里）。平台控制条在 16:9 画布之外，不需要为它预留画面空间。

### 资源

- 所有路径相对 `assets/...`；不能以 `/` 开头、不能 `../` 逃出课程包。
- 禁止外部加载：`script[src]`、加载资源的 `link[href]`、`img/source/video/audio[src]`、`poster`、CSS `url()`、`@import`。CDN、Google Fonts 一律不行。
- GSAP 用模板自带的 `assets/vendor/gsap.min.js`（3.15.0 固定），在根 `index.html` 本地引用。
- 字体用模板自带的 `assets/fonts/NotoSansSC-VF.woff2`，用 `@font-face` 本地引用；不要换 CDN 字体。
  - 注意：这是**预生成的字符子集**，覆盖常用字和模板现有文案，但你自己新写的生僻字可能没有字形。用 `npm run snapshot` 看有没有豆腐块；缺字形时由平台侧重新生成子集（`python scripts/sync_runtime.py`），作者不要用 CDN 字体绕过。
- 禁止 `fetch`、XHR、WebSocket、动态数据；禁止 `Date.now()`、`setInterval()`、未播种的 `Math.random()` 当动画时钟。
- 预算：整门课 ≤15MB、单张图片 ≤500KB、封面 ≤300KB、字体子集 ≤2MB、单个 HTML ≤200KB。

### 讲义

- 讲义（`screens[].transcript`）必须和屏幕文字一致；改一边就改另一边。
- 有音频时每屏必须有 `transcript`（无障碍要求，不是可选项）。

## 5. 自检清单

逐条执行，不要「看起来差不多」。

**内容与元数据**

- [ ] `slug` 已替换、符合 `^[a-z0-9]+(?:-[a-z0-9]+)*$`、不是保留名。
- [ ] `title` / `subtitle` / `summary` / `outcomes` / `takeaways` 是真实内容，没有残留「待替换」。
- [ ] 长度都在限制内（见 `COURSE-CONTRACT.md` 4.2）。
- [ ] `status` 已改成 `published`。
- [ ] 每屏一个论题，`screens[]` 与 `STORYBOARD.md` 一致。
- [ ] 讲义和屏幕文字一致；事实都有来源。

**composition 与资源**

- [ ] 根 `data-width` / `data-height` 是 1920 / 1080；`data-duration` 覆盖最后一屏。
- [ ] 每屏四处 id 一致：`screens[].id`、host `id`、scene `data-composition-id`、时间轴 key。
- [ ] `data-start` 升序、不重叠；`data-track-index` 唯一。
- [ ] 每个 scene 都有 `<template>`、`<div id="root">`、paused 时间轴、`window.__timelines["s-…"]`。
- [ ] 每一屏的最后一帧是完整、稳定、可读的最终状态；拖动当前屏进度或跳到最后时看到的就是这一帧，关键信息不只存在于动画中途。
- [ ] `assets/vendor/gsap.min.js`、`assets/fonts/NotoSansSC-VF.woff2` 都在，并且是本地引用。
- [ ] composition 里（排除 `assets/vendor/` 里的第三方库）搜不到外部加载和禁用时钟：

  ```bash
  cd composition
  rg -n --glob '!assets/vendor/**' "https?://|Date\.now\(|setInterval\(|Math\.random\(" .
  # 只应命中 <a href> 的引用链接；资源加载和真实时钟一律不允许。
  # 没有 rg 就用 grep -rn 或 PowerShell 的 Select-String。
  ```

- [ ] 没有 `node_modules/`、`renders/`、`.hyperframes/`、`*.mp4` 混进交付文件夹。

**运行验证（能做就做，做不了就写「未验证」）**

- [ ] `cd composition && npm run check` 通过。
- [ ] 每屏 `npm run snapshot` 看过 0% / 50% / 90%，文字不溢出、不低对比、最后一帧稳定。
- [ ] 平台构建完成后，断网、用静态服务器打开构建出的课程页，Network 面板没有外部请求。
- [ ] 平台仓库在手边时：

  ```bash
  python scripts/import_course.py --dry-run <课程文件夹>          # 只校验、不落盘
  # 或
  python scripts/build_courses.py --course <slug> --check-only    # 只校验、不构建
  ```

- [ ] 打开「减少动态效果」，确认没有自动播放、讲义可读。

## 6. 交付方式

把课程交回平台，任选一种：

1. **整个文件夹压缩**成一个 zip 交给需求方。
2. 复制到平台仓库根的 `course-inbox/<slug>/`（这个目录不进 Git），然后在平台仓库里运行：

   ```bash
   python scripts/import_course.py --inbox
   # 也可以只导入一个文件夹
   python scripts/import_course.py <你的课程文件夹>
   ```

   开发环境还可以打开平台的 `/import` 页面，在网页上点导入。

平台导入会：校验 `course.json`（字段、长度、未知字段、保留 slug）→ 扫描 composition 的外部资源和禁用时钟 → 构建 → **全部通过后**才复制到 `courses/<slug>/` 并原子替换 `dist/courses/<slug>/`；失败会报错误码并回滚，不会留下半个课程。导入成功后，打开平台 `/courses/<slug>/` 做最后一遍人工验收。

如果你不走导入、直接把文件夹放进平台 `courses/<slug>/`：目录名必须等于 `slug`，然后 `python scripts/build_courses.py --course <slug>`；`draft` 课程需要加 `--include-drafts`，或先改成 `published`。

## 7. 常见错误 → 修复

| 现象 | 原因 | 修复 |
| --- | --- | --- |
| 导入报 `slug_reserved` | slug 还是 `your-course-slug` 之类的占位符 | 改成课程自己的 slug |
| 导入报 `course_exists` | 平台已有同 slug 课程 | 换 slug，或让需求方确认覆盖 |
| `manifest_invalid` | JSON 语法/字段类型/长度/未知字段不对 | 看报错字段，按 `COURSE-CONTRACT.md` 4.2 改；拼错的字段名也算未知字段 |
| `screen_meta_orphan` | `course.json` 有某屏，根 composition 没 host | 补 host，或删掉元数据 |
| `screen_host_orphan` | 根 composition 有 host，`course.json` 没元数据 | 补元数据，或删 host |
| 某屏不显示 | host 的 `id` / `data-composition-id` / scene 内 id / 时间轴 key 不一致 | 四处统一成 `s-<id>` |
| 最后一屏被截断 | 根 `data-duration` 太短 | 改到 ≥ 最后一屏结束时间 |
| 切屏后停在错误帧 | `data-start` 写错或两屏重叠 | 检查时间范围，确保升序不重叠 |
| 动画回看时状态漂移 | 用了 `from` 而不是 `fromTo` | 改成 `fromTo` |
| 字体在别人机器上变了 | 用了系统字体或 CDN | 用本地 `@font-face` + 自带字体文件 |
| 构建报 `external_asset` | 引用了 CDN 或外链资源 | 下载到 `assets/`，改相对路径 |
| 构建报 `asset_missing` | 引用的本地文件不存在或路径算错 | 从 composition 根算路径，统一 `assets/...` |
| 构建报 `forbidden_clock` | 用了真实时钟或随机数 | 改成时间轴上的 tween |
| 手机/小屏看不清 | 正文小于 40px、关键文字小于 32px | 放大字号、删字 |
| 动画结束在运动中间 | 没留稳定帧 | 提前结束动画，把最后一帧做成完整可读的最终画面（播放器可能直接拖到这里） |
| `status` 是 draft 导致导入后没构建 | 平台默认只构建 published | 交付前改 `published`，或导入时说明用 `--include-drafts` |

完整错误码表见 `COURSE-CONTRACT.md` 第 10 节。

## 8. 不要做的事

- 不要修改平台文件：`app/`、`scripts/`、`docs/`、`runtime/`、`design/`，以及平台根目录的 `README.md`、`AGENTS.md`、`DESIGN.md`。课程任务只产出课程文件夹。
- 不要手写或编辑构建产物（`dist/` 之类）；它们每次构建都会被覆盖。
- 不要把 `start` / `duration` / `index` 写进 `course.json`。
- 不要放 `node_modules/`、`renders/`、`.hyperframes/`、视频文件进交付文件夹。
- 不要用 CDN、Google Fonts、外部图片；不要用 `fetch` 拉数据。
- 不要升级 HyperFrames 或 GSAP 版本：`package.json` 固定 `hyperframes@0.9.19`，GSAP 用模板自带的 3.15.0。
- 不要把模板的占位文案当课程内容交付；不要留「待替换」。
- 不要编造数字、日期、引文、机构名；没有来源就删。
- 不要在 composition 里放导航、进度条、跳到最后、返回按钮；这些由平台播放器提供。
- 不要因为跑不了某条命令就假装它通过了；在交付说明里写「未验证」。
- 不要新增 `hyperframes.json`：平台不要求，构建也跳过它。

## 9. 本目录速查

| 文件 | 作用 | 你要不要改 |
| --- | --- | --- |
| `course.json` | 课程清单：元数据 + 每屏文案 | 要，全部换成真实内容 |
| `STORYBOARD.md` | 课程脚本和时间意图 | 要，先写它 |
| `composition/index.html` | 根 composition：host、时间、总时长 | 要，接真实屏幕 |
| `composition/compositions/NN-<id>.html` | 每屏一个 scene | 要，逐屏写 |
| `composition/assets/course.css` | 课程级基础样式和字体声明 | 一般不用改 |
| `composition/assets/fonts/*.woff2` | 本地字体 | 不要换 |
| `composition/assets/vendor/gsap.min.js` | 本地 GSAP 3.15.0 | 不要换 |
| `composition/package.json` | 本地创作脚本，固定 HyperFrames 0.9.19 | 只改 `name` 为 `course-<slug>` |
| `AGENTS.md` | 本文件 | 不用改 |
| `COURSE-CONTRACT.md` | 作者版完整规范 | 查，不用改 |
| `STYLE.md` | 视觉规范 | 查，不用改 |
