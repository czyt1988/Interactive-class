# AGENTS.md

这个仓库构建 **AI Learning**：一个用网页动画讲 AI 的教学平台。课程是自包含的静态包，站点是 FastAPI + Jinja2 的封面与目录。

## 先读这四份

1. [前端设计契约](DESIGN.md) —— 视觉、文案、动效、课程 composition 的唯一决策来源；做任何页面或课程视觉改动先读它。
2. [Agent 开发方案](docs/agent-development-plan.md) —— 唯一的执行计划：阶段、验收标准、每门新课的生产模板。
3. [架构设计](docs/architecture.md) —— 关键决策、运行时、构建、部署和风险。
4. [课程契约](docs/course-contract.md) —— 一门课必须长什么样，字段、目录、时间规则和验收清单。

## 不可协商

- 课程必须能作为独立静态包部署；没有 API、数据库或登录态也能完整播放。
- 主链路不输出 MP4，不使用 SPA 框架。
- 课程内容放在文件里；用户、会话和进度放在 SQLite。数据库属于站点，不属于课程包。
- 运行时不引用 CDN；player、runtime、GSAP、字体全部本地。
- 一门课一个 HyperFrames composition，一屏一个 scene。
- 课程任务只修改 `courses/<slug>/`，平台改动另开任务。
- HyperFrames 版本固定，升级要先跑播放器契约测试。
- 前端与课程视觉必须遵守 [DESIGN.md](DESIGN.md)：只做亮色纸面，颜色/圆角/层级只来自 `design/tokens.css`，界面文案零 em-dash，动效必须有理由且尊重 reduced-motion。
- 改视觉决策前先改 DESIGN.md；改令牌只改 `design/tokens.css` 再跑 `python scripts/sync_runtime.py`。

## 工作方式

- 一次任务只做一个阶段，完成该阶段全部验收项再结束。
- 不直接编辑 `dist/`；它是构建产物。
- 每次任务收尾都按下方「提交规则」提交，不攒改动，也不把无关改动混进同一个提交。
- 结束前跑本阶段的验证命令，并报告“验证了什么、没验证什么”。
- 改变架构决策前，先更新架构文档的决策表。

## 提交规则

每次任务收尾都必须提交一次，让仓库和本地工作区保持同步；不需要用户再额外说“提交”。

### 什么时候提交

- 一个任务一次提交：验收项全部做完、验证命令通过之后提交。
- 任务分几个阶段时，每个阶段结束提交一次；中途的 WIP 提交要在任务结束前整理干净。
- 提交前先看 `git status --short`，只暂存本任务改动的文件。看到不属于本任务的改动，先停下问用户，不要顺手带进去。
- 分路径 `git add`，不要无脑 `git add -A`；暂存后用 `git diff --cached --stat` 和 `git diff --cached` 复核一遍再提交。
- 用户明确要求“把当前项目全部提交”时，可以整仓暂存，但仍要逐项复核暂存清单。

### 提交前验证

按改动范围至少跑：

- 所有任务：`pytest -q && ruff check .`
- 改课程或运行时：`python scripts/build_courses.py --all`
- 改 `design/tokens.css`、字体或 vendor：`python scripts/sync_runtime.py`，并确认 `runtime/VERSION.json` 的 hash 更新
- 改站点或课程视觉：按 [DESIGN.md](DESIGN.md) 的验收方式补截图或 Playwright 检查

验证不过不提交。跑不了的验证要在提交信息和给用户的报告里说明原因。

### 提交信息

- 用 Conventional Commits：`<type>(<scope>): <中文一句话>`；type 取 `feat`、`fix`、`docs`、`chore`、`refactor`、`test`、`build`、`perf`、`style`。
- scope 用模块名或课程 slug，例如 `feat(course): ...`、`fix(runtime): ...`、`docs(agents): ...`。
- 标题说清楚做了什么，不写“update”“修改”这类空话；正文写动机、影响面和没验证的部分。
- 一个提交只做一件事；发现“顺便改了”的内容，拆成另一个提交。
- 不使用 `--no-verify` 跳过 hook；hook 失败先修问题。

### 不要提交的东西

- 视频与渲染产物：`*.mp4`、`*.webm`、`*.mov`、`*.mkv`、`*.avi`、`*.m4v`、`*.flv`、`*.wmv`、`renders/`、`courses/*/renders/`。课程是 HTML 静态包，视频只是本地导出结果，占空间且可重建。
- 构建产物与缓存：`dist/`、`runtime/vendor/`、`*.egg-info/`、`courses/*/narration/cache/`、`courses/*/composition/.snaps-*/`、`courses/*/composition/.review-*/`、`courses/*/composition/.thumbnails/`
- 环境与本地状态：`.venv*/`、`node_modules/`、`.hyperframes/`、`.run/`、`.tmp/`、`*.log`、`.env`、`.vscode/`
- 本地工具：`tools/ffmpeg/`
- 上游素材：`大纲/`（可复现的文本源已提交在 `courses/*/narration/scenes*.json`）
- 单个文件超过 20 MB 的资产默认不进库，先问用户；播放必需的字体子集（woff2）和课程 OGG 旁白除外，且应尽量压缩/子集化。

`.gitignore` 是这份清单的权威版本。新增一类产物时，先在 `.gitignore` 里加规则，再提交代码，不要提交完再补。

### 提交之后

- `git status` 应该干净（只剩被忽略的构建产物）。不干净说明有漏提交或误提交，先查清楚。
- 配置了 remote 就 `git push` 同步；没有 remote 时本地提交即可，并在报告里写“未推送”。

## 当前状态

v0.4：第一门长视频课程按新版导演脚本（22 镜头）重做，整门课浅色纸面，可连续播放，也可导出 MP4。

- 已有：FastAPI 站点（首页 / 课程库 / 关于 / 404 / API）、课程契约与解析器、构建流水线、课程外壳（封面、切屏、控制条、字幕/配音开关、讲义、完成页、错误页）、SQLite + Alembic 匿名进度、Playwright 独立部署与播放器测试。
- 已有课程：`courses/ai-first-sees/`（「从会聊天到会干活：AI Agent 入门」）。按 `大纲/AI-Agent-入门课/02-逐页脚本.md` 的 22 个镜头落地，共 22 屏 / 21:42；每屏一页，旁白驱动动画，底部旁白条烧进画面，`playback: "continuous"` 像视频一样自动接续。
- 旁白流水线：`courses/ai-first-sees/narration/scenes.json` 是文本源（`scripts/curate_narration.py` 从大纲解析），`scripts/build_narration.py` 用 edge-tts 生成音频/时间/字幕并重写根 composition、`course.json` 和 scene 时间块；重跑脚本是唯一的时间来源。音频是本地 OGG/Opus 静态文件，播放不依赖网络。视频导出在 `composition/` 里跑 `npx hyperframes render`（需要 ffmpeg/ffprobe 在 PATH 上）。
- 视觉现状：站点与整门课统一浅色纸面，四幕只换强调色（看=青绿、说=暖黄、做=电光蓝、群雄=蓝紫、用=珊瑚红）；真实 logo / 截图 / 历史照片只作为小证据卡出现。课程控制条第一个按钮是「返回课程库」；旁白课程另有「字幕」「配音」两个独立开关，偏好存 localStorage（架构 D11-D13 与 [DESIGN.md](DESIGN.md) 8.4）。
- 还没做：CI、Docker/部署、课程脚手架脚本、登录、搜索。

先跑一遍这三条，确认环境是通的：

```bash
python scripts/sync_runtime.py          # 布置 player / runtime / GSAP / 字体
python scripts/build_courses.py --all   # 生成 dist/courses/<slug>/
pytest -q && ruff check .
# 只有重做旁白/时间时才需要（需要 edge-tts、mutagen、soundfile 和网络）：
python scripts/build_narration.py --no-tts   # 复用缓存重建时间/根 composition/ui 清单
```
