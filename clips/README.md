# 片头 / 片尾库

这里放**全站共享**的片头、片尾模板。所谓片头，就是课程 composition 里多出来的一屏：构建时由
`scripts/build_courses.py` 把它插到课程最前面（或最后面），网页播放和导出的 MP4 都会带上。
它不属于任何一门课的 `course.json`。

每门课用哪一个片头/片尾，在后台 `课程后台 → 片头片尾` 里选择；选择保存在站点数据库
（`course_clips` 表），不进 Git，也不写课程源文件。默认不插任何片头/片尾。

## 目录结构

```
clips/
  intro-title-page/
    clip.json      # 元数据：id、kind、时长、目录里显示的文案
    scene.html     # 一屏 scene，<template> 片段，和课程 scene 同构
  outro-colophon/
    clip.json
    scene.html
```

自带的 `intro-title-page` 是**通用开源片头**：7 秒，不印课程标题、屏数或时长，只说明
本视频由 DeepSeek harness + DeepSeek-V4.1 flash 生成，并写出本仓库的 GitHub 与 Gitee
地址。它不使用占位符；换 fork 或换项目时直接改 `scene.html` 里的两个地址。

自带的 `outro-colophon` 是**通用开源片尾**：9 秒，重复同样的制作方式和两个地址，并用
一句「这是一个人人都能动手的时代：过去要一个团队才能做的事，现在一个人也能开始」
收束。它同样不使用占位符；换 fork 时一并改地址。

新增一个片头/片尾：复制一个文件夹，改 `clip.json` 的 `id`（必须与文件夹同名，且以
`intro-` 或 `outro-` 开头）、`kind`、`title`、`summary`、`duration`，再写 `scene.html`。
保存后刷新后台页面即可看到（构建会重新扫描目录）。

## `clip.json`

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `schemaVersion` | 是 | 固定 `1` |
| `id` | 是 | 小写字母、数字、连字符，1–32 字符；等于文件夹名，以 `intro-`/`outro-` 开头 |
| `kind` | 是 | `intro` 或 `outro` |
| `title` | 是 | 播放器目录里的标题，≤40 字 |
| `summary` | 是 | 播放器目录里的摘要，≤120 字 |
| `description` | 否 | 后台选择页里的一句说明，≤200 字 |
| `kicker` | 否 | 播放器控制条上的小标签，例如「片头」 |
| `transcript` | 否 | 讲义抽屉里的文字，≤2000 字 |
| `duration` | 是 | 这一屏的时长（秒），5–30；必须覆盖时间轴最后一个动画 |
| `scene` | 否 | scene 文件名，默认 `scene.html` |

## `scene.html`

和课程 scene 的规则完全一样（见 [课程契约](../docs/course-contract.md) 4.4）：

- `<template>` 包裹；里面是 `<style>`、`<div id="root">`、`<script>`。
- `data-composition-id` 必须是 `s-<id>`；时间轴注册为 `window.__timelines["s-<id>"]`。
- 时间轴 `paused: true`，用 `fromTo`，只动 `opacity` / `transform`。
- 时间从 0 开始，最后一帧要稳定、完整；播放器可能直接跳到这一屏的结尾。
- 画面 1920×1080，亮色纸面，遵守 [DESIGN.md](../DESIGN.md) 第 8 节。
- **自包含**：不能引用图片、字体文件、CDN 或任何外部资源；需要图形就用内联 CSS/SVG。
  字体用 `"Noto Sans SC"`（课程 composition 已经通过 `@font-face` 注册）和系统等宽字体。
- 不要在 scene 里做导航、进度条、返回按钮，那些由播放器提供。

## 占位符

片头/片尾是全站共用的，所以 scene 里可以用这些占位符，构建时按当前课程替换（HTML 转义）。
自带的两条通用模板不使用占位符，下面的占位符供自定义模板使用：

| 占位符 | 替换成 |
| --- | --- |
| `{{course.title}}` | 课程标题 |
| `{{course.subtitle}}` | 课程副标题，没有时为空 |
| `{{course.lead}}` | 片头用的一句话：副标题，没有副标题时取截断后的摘要 |
| `{{course.summary}}` | 课程完整摘要 |
| `{{course.slug}}` | 课程 slug |
| `{{course.url}}` | 课程页绝对地址 |
| `{{course.accent}}` | 课程强调色（`#RRGGBB`） |
| `{{course.titleSize}}` | 按标题长度算出的标题字号（px 数字） |
| `{{course.screenCount}}` | 正课屏数（不含片头/片尾） |
| `{{course.meta}}` | 「28 屏 · 29:54」这样的课程信息 |
| `{{site.title}}` | 站点名 |
| `{{project.url}}` | `PROJECT_URL`，开源项目地址 |
| `{{project.label}}` | 去掉 `https://` 的项目地址，适合印在画面上 |
| `{{project.labelSize}}` | 按地址长度算出的字号（px 数字） |

出现未知占位符会让构建失败，而不是把 `{{...}}` 原样印到画面上。改完 scene 或 `clip.json`
后要重建课程包才会生效（后台保存一次片头/片尾会自动重建）。
