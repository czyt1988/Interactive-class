# course-template：AI Learning 课程模板包

这是 AI Learning 平台的**独立课程模板包**：一个两屏、可构建的最小课程骨架，加上给外部 AI 和作者看的规范文档。它从平台仓库的 `courses/_template/` 抽出来，不再放在 `courses/` 下参与平台构建，可以整个文件夹交给外部作者或外部 AI。

产物是一份可以直接导入平台的课程文件夹，不是本模板本身。

## 这是什么

| 文件 | 作用 |
| --- | --- |
| `AGENTS.md` | 给 AI 的操作指引：任务、输入清单、工作流程、硬规则、自检、交付。**外部 AI 第一份读它** |
| `COURSE-CONTRACT.md` | 作者版完整规范：目录、字段、命名、时间、资源预算、禁止项、错误码、验收清单 |
| `STYLE.md` | composition 视觉规范：纸色与墨色、字号阶梯、安全区、动效、两个构图配方 |
| `STORYBOARD.md` | 分镜脚手架，带填写说明；正式课程先写它 |
| `course.json` | 合法占位清单（`slug: your-course-slug`，`status: draft`），逐项替换 |
| `composition/` | 根 `index.html` + 两屏 scene（`hello` / `world`）+ 本地字体与 GSAP |

## 为什么独立

- **可整体交付**：外部作者不需要克隆平台仓库，拿到一个文件夹就能开工。
- **不污染课程目录**：平台构建只扫描 `courses/<slug>/`；模板留在仓库根，不会被误构建，也不会被平台测试当成课程。
- **文档自包含**：`AGENTS.md`、`COURSE-CONTRACT.md`、`STYLE.md` 都在包里，工作目录里就有人和 AI 需要的全部规则。

## 用法 A：交给 AI 生成课程

1. 把**整个文件夹**作为 AI 的工作目录（或作为上下文一起给）。
2. 让 AI 先读 `AGENTS.md`，再按其中的「开工前必须确认的输入」给出主题、目标读者、学完能、事实来源、屏数时长、是否有音频、封面素材、强调色。
3. AI 会按流程产出：定 slug → 写 `STORYBOARD.md` 并给你评审 → 改 `course.json` → 逐屏写 scene → 接根 composition → 自检 → 交付。
4. 你只需要评审 `STORYBOARD.md` 和最终交付说明；缺事实来源时不要放行。

## 用法 B：自己手写

```bash
# 1. 复制模板为新课程（目录名先随意，最终以 course.json 的 slug 为准）
cp -r course-template my-new-course

# 2. 改 course.json：slug / title / subtitle / summary / outcomes / accent，并删掉所有「待替换」

# 3. 逐屏改 composition/compositions/*.html，再接 composition/index.html 的 host 与时间

# 4. 本地自检（需要 Node）
cd my-new-course/composition
npm run check
npm run snapshot
```

写之前至少通读 `COURSE-CONTRACT.md` 第 4–7 节和 `STYLE.md`。

## 交付与导入

课程文件夹里有 `course.json`、`STORYBOARD.md`、`composition/`（可选 `cover.webp`）就是一份完整交付物。交付前把 `status` 改成 `published`，否则平台默认跳过构建。

导入到平台，任选一种：

1. **收件箱导入**：把课程文件夹放进平台仓库根的 `course-inbox/<slug>/`（该目录不进 Git），然后：

   ```bash
   python scripts/import_course.py --inbox
   # 也可以只导入一个文件夹
   python scripts/import_course.py <课程文件夹>
   ```

   开发环境也可以打开平台的 `/import` 页面点导入。

2. **直接放进课程目录**：把文件夹复制成平台仓库的 `courses/<slug>/`（目录名必须等于 `slug`），然后：

   ```bash
   python scripts/build_courses.py --course <slug>
   ```

   只校验不写产物：`python scripts/build_courses.py --course <slug> --check-only`。

导入流程会先校验、扫描资源、构建，全部通过后才落盘；失败会返回错误码，不会留下半个课程。导入成功后打开 `/courses/<slug>/` 做人工验收。

## 校验失败怎么看

- 错误会带课程 slug、文件路径、屏幕 id、字段名和期望值；先按这五项定位。
- 先查 `COURSE-CONTRACT.md` 第 10 节的错误码表；`AGENTS.md` 第 7 节有最常见的十几种。
- 只校验不落盘：`python scripts/import_course.py --dry-run <课程文件夹>`。
- 最常见的三类：`slug` 还是占位符（`slug_reserved`）、根 `data-duration` 不够长（`root_duration_short`）、外部资源引用（`external_asset`）。

## 版本

- HyperFrames 固定 `0.9.19`（`composition/package.json` 的脚本里写死，不要用 `latest`）。
- GSAP 固定 `3.15.0`（`composition/assets/vendor/gsap.min.js`，由平台同步脚本生成）。
- 字体是自托管的 Noto Sans SC 子集（`composition/assets/fonts/`）。它是**预生成的字符子集**，只覆盖常用字和模板现有文案；课程新写的生僻字可能缺字形。平台导入后运行 `python scripts/sync_runtime.py` 会按课程文案重新生成子集，作者不要用 CDN 字体绕过。
- 不要求 `hyperframes.json`：平台现有课程都没有它，构建也会跳过它。

升级 HyperFrames / GSAP 需要平台侧统一升级并重建所有课程，不要在单门课里单独升级。

## 不要改的文件

- `composition/assets/vendor/gsap.min.js`、`composition/assets/fonts/*.woff2`：由平台同步脚本生成，改了就和其他课程不一致。
- `composition/package.json` 里的版本号：只允许改 `name` 为 `course-<slug>`。
- 构建产物、平台代码：模板包里没有这两类东西，也不应该创建。
