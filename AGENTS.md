# AGENTS.md

这个仓库构建 **AI Learning**：一个用网页动画讲 AI 的教学平台。课程是自包含的静态包，站点是 FastAPI + Jinja2 的封面与目录。

## 先读这四份

1. [前端设计契约](DESIGN.md) —— 视觉、文案、动效、课程 composition 的唯一决策来源；做任何页面或课程视觉改动先读它。
2. [Agent 开发方案](docs/agent-development-plan.md) —— 唯一的执行计划：阶段、验收标准、每门新课的生产模板。
3. [架构设计](docs/architecture.md) —— 关键决策、运行时、构建、部署和风险。
4. [课程契约](docs/course-contract.md) —— 一门课必须长什么样，字段、目录、时间规则和验收清单。

新增课程、改课程模板或对接外部作者时，再读 [course-template/README.md](course-template/README.md)；交给外部 AI 的是 `course-template/AGENTS.md`。

## 不可协商

- 课程必须能作为独立静态包部署；没有 API、数据库或登录态也能完整播放。
- 主链路不输出 MP4，不使用 SPA 框架。
- 视频仍不是主链路；后台设置页可以按需生成课程视频，产物留在服务器 `data/videos/`，不进 Git、不进构建产物。
- 课程内容放在文件里；用户、会话、进度和课程水印配置放在 SQLite。数据库属于站点，不属于课程包。水印文字是部署方身份信息，不进 Git、不写 `course.json`。
- 课程模板包 `course-template/` 是独立交付物：它不在 `courses/` 下参与构建；改课程字段、目录或时间规则时，同一任务内同步更新模板包里的作者文档和骨架。
- 导入只做三件事：校验、把课程源文件复制进 `courses/<slug>/`、构建；数据库只在 `course_imports` 表登记来源，课程内容不写库。
- 运行时不引用 CDN；player、runtime、GSAP、字体全部本地。
- 一门课一个 HyperFrames composition，一屏一个 scene。
- 课程任务只修改 `courses/<slug>/`，平台改动另开任务。
- HyperFrames 版本固定，升级要先跑播放器契约测试。
- 前端与课程视觉必须遵守 [DESIGN.md](DESIGN.md)：只做亮色纸面，颜色/圆角/层级只来自 `design/tokens.css`，界面文案零 em-dash，动效必须有理由且尊重 reduced-motion。
- 改视觉决策前先改 DESIGN.md；改令牌只改 `design/tokens.css` 再跑 `python scripts/sync_runtime.py`。

## 工作方式

- 一次任务只做一个阶段，完成该阶段全部验收项再结束。
- **每次开发都在 `.worktree/` 下的 git 工作树里进行**（见下方「分支与工作树」）；主工作树只做集成，不直接开发、提交或合并。
- 不直接编辑 `dist/`；它是构建产物。
- 新增课程用 `python scripts/new_course.py <slug> --title "..."`；外部作者的课程用 `python scripts/import_course.py`（或开发环境 `/import` 页面）导入，不要手工拼 `dist/`。
- 每次任务收尾都按下方「提交规则」提交，不攒改动，也不把无关改动混进同一个提交。
- 结束前跑本阶段的验证命令，并报告“验证了什么、没验证什么”。
- 改变架构决策前，先更新架构文档的决策表。

## 分支与工作树（每次开发都在工作树里）

> 🔴 **强制规则：任务一律在 `.worktree/` 下的工作树里进行，不在主工作树直接开发/提交/合并。`main` 是唯一集成分支。**

本机经常有多个 Agent 会话并行开发本项目。多个任务挤在同一个工作区里，切分支、暂存区、未提交改动会互相污染，所以每个任务开一个独立的 git 工作树，任务完成后合并回 `main`。

### 分支模型

- `main` 是唯一集成分支，一切工作的终点；主工作树保持干净，只用来集成、查看和发布。
- 功能用 `feat/<域>-<主题>`，修复用 `fix/<主题>`；合并回 `main` 后删除工作分支。
- 主工作树里可能已经有用户自己的在途改动——不要动它们，也不要替用户提交或回滚。

### 开工作树

```powershell
python scripts/worktree.py add feat/course-xyz        # 从最新 main 切出
python scripts/worktree.py add fix/player-crash --base main
python scripts/worktree.py list                       # 工作树、分支、共享状态
python scripts/worktree.py link                       # 修复/补齐共享目录
```

工作树落在 `<仓库根>/.worktree/<分支名把 / 换成 ->`（已 gitignore）。**不要用裸 `git worktree add`**，脚本额外做了三件在本仓库缺一不可的事：

1. **复用依赖，不重新下载**：`.venv`（Python 依赖）、`tools/node_modules`（HyperFrames / GSAP）、`tools/ffmpeg` 以目录联接（Windows junction / POSIX 软链接）挂进工作树；`courses/*/narration/cache/` 的旁白缓存也直接共享。新工作树几秒内就能跑 `pytest` / `ruff` / 构建课程，不联网、不 `pip install`、不 `npm install`。
2. **复制会被写坏的生成物**：`runtime/vendor` 和 `.env` 复制一份。工作树里重跑 `sync_runtime.py` 或改本地配置，不会污染主工作树。
3. **安全拆除**：Windows 目录联接在不同工具/版本里的递归删除行为不一致，可能跟随到目标目录（主工作树的 `.venv`、`node_modules`）。`remove` 先拆联接再删工作树，拒绝递归删除仍含联接的目录；工作树有未提交改动时拒绝删除（`--force` 才丢弃）。

创建工作树时会顺手预构建 `dist/`（`--no-build` 跳过），新工作树直接双击 `start.cmd` 就能起站点。

### 共享的代价（必须守的纪律）

- **不要在 worktree 里 `pip install` / `npm install`**：写的是共享的 `.venv` / `tools/node_modules`，会波及主工作树和并行会话（`bootstrap.py` 检测到共享联接是否就直接拒绝重装）。需要装依赖时在主工作树装，工作树自动可见。
- **升级 `tools/package.json` 里的固定版本**是串行步骤：在主工作树 `npm install` + `python scripts/sync_runtime.py`，再在工作树里 `link` 刷新复制出来的 `runtime/vendor`（`link` 会重拷内容有变化的副本）。
- **重做旁白也是串行步骤**：`build_narration.py` 会写共享的 `courses/*/narration/cache/`，不要多个工作树同时重建同一门课的旁白。
- **不要手工 `rm -rf .worktree/<名字>`**：Windows 下可能跟着目录联接删到主工作树的目标目录；删除一律用 `remove`（有未提交改动会拒绝，确认丢弃才 `--force`）。
- **工作树里起站点换端口**：主工作树默认 8081，工作树用 `$env:APP_PORT=8082`（PowerShell）或 `set APP_PORT=8082`（CMD），避免抢端口。
- `dist/`、`data/`、`.pytest_cache/` 等产物都是工作树私有的，不共享，也不要复制回主工作树。

### 在工作树里干活

- 命令与主工作树一致：`pytest -q && ruff check .`、`python scripts/build_courses.py --all`、`python scripts/sync_runtime.py`。
- 仓库根已由根 `conftest.py` 和构建脚本放进 `sys.path`：测试与构建脚本导入的是**当前检出**的 `app`，不会因为共享 `.venv` 的 editable install 跑到主工作树。自己写的一次性脚本若要 `import app`，从仓库根用 `python -m` 或先 `set PYTHONPATH=%CD%`。
- 起站点用 `python -m uvicorn app.main:app`（`uvicorn` 控制台脚本不会把当前目录放进 `sys.path`，会导入主工作树；双击 `start.cmd` 的 launcher 已处理这一点）。
- 提交规则不变：验收通过后在工作树里提交（Conventional Commits），WIP 提交在任务结束前整理干净。

### 合并回 `main`

- 动手前先 `git -C <工作树> merge main`（收尾前再合一次），让冲突提前暴露，而不是攒到合并那一刻。
- `python scripts/worktree.py merge feat/course-xyz --remove`：
  1. 默认先在工作树里跑 `pytest -q` + `ruff check .` 作为合并门禁（分支没有工作树时会拒绝；确实已自行验证过才加 `--no-verify`）；
  2. 再以 `--ff-only` 合并回 `main`（`main` 检出在工作树且工作区干净时在该树合并；没有检出时用临时工作树；有在途改动则拒绝）；
  3. 成功后删除工作树与分支；分支若正检出在主工作树，先切回 `main` 再加 `--remove`。
- 无法快进说明 `main` 已经前进：先在工作树里 `git merge main`、解决冲突并提交，再重跑 `merge`；或加 `--merge` 生成合并提交（之后要在主工作树重跑验收）。
- `--merge` 遇到冲突会自动 `git merge --abort` 回滚，主工作树不会被留在冲突状态；修好冲突再重试。
- 合并后主工作树 `git status` 应该干净，**任务完成 = 已合并回 `main` 并清理工作树与分支**，不要把冲突、分叉或“没合并”的状态留给下一个任务。
- 站点正在主工作树运行时，合并后重建 `dist/` 并重启再看效果；是否 `git push` 按「提交规则 → 提交之后」执行。

## 提交规则

每次任务收尾都必须提交一次，让仓库和本地工作区保持同步；不需要用户再额外说“提交”。

### 什么时候提交

- 一个任务一次提交：验收项全部做完、验证命令通过之后提交。
- 提交发生在任务的工作树里；**任务完成 = 已合并回 `main` 并删除工作树与分支**（见上节），不是“本地提交完就算完”。
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
- 工作树模式的任务，收尾时用 `python scripts/worktree.py merge <分支> --remove` 合并并清理；合并后主工作树 `git status` 也应干净。
- 配置了 remote 就 `git push` 同步；没有 remote 时本地提交即可，并在报告里写“未推送”。

## 当前状态

v0.10：课程水印改为站点部署配置：每门课可在后台配置四角角标水印和满屏平铺水印，配置保存在 SQLite 的 `course_watermarks` 表（不进 Git、不写课程源文件），保存后重新构建；构建从数据库读配置并把水印层写进课程 composition，所以网页播放和导出的 MP4 带同一层。播放页仍是全视口舞台 + 通栏控制条，课程模板仍是独立包，外部作者可以用它让 AI 生成课程并通过导入流程直接加入课程库；视频仍是后台按需生成的附属产物。

- 已有：FastAPI 站点（首页 / 课程库 / 关于 / 404 / API）、课程契约与解析器、构建流水线、课程外壳（封面、切屏、全视口播放页、通栏控制条、逐屏进度拖动与「跳到最后」、字幕/配音开关、讲义、完成页、错误页）、SQLite + Alembic 匿名进度、Playwright 独立部署与播放器测试。
- 已有后台：`/admin` 列出课程与屏数、显示视频是否已生成、在线调用 HyperFrames CLI 渲染 MP4 并下载；产物在 `data/videos/`，可用 `ADMIN_TOKEN` 加访问密码（见架构 7.11 与 README「在线生成课程视频」）。每门课还有「水印配置」页 `/admin/courses/<slug>/watermark`：角标水印 + 满屏平铺水印，16:9 预览，保存时写站点数据库 `course_watermarks` 表（不进 Git）并重新构建（见课程契约 3.7、7.8 与架构 7.12）。
- 已有模板与导入：`course-template/` 是独立交付包（`AGENTS.md` 给 AI、`COURSE-CONTRACT.md`/`STYLE.md` 给作者）；`scripts/new_course.py` 生成脚手架；`scripts/import_course.py` 和开发环境 `/import` 页面把外部课程校验、复制到 `courses/<slug>/`、构建并登记 `course_imports` 来源（见课程契约 7.7）。
- 已有课程：`courses/ai-first-sees/`（「从会聊天到会干活：AI Agent 入门」）。按 `courses-outline/ai-first-sees/outline.md` 的 29 镜头长版落地，共 28 屏 / 29:54（旁白 `rate +0%`；原 S28 safety 并入 S27，收尾为 S28）；每屏一页，旁白驱动动画，底部旁白条烧进画面，`playback: "continuous"` 像视频一样自动接续。
- 旁白流水线：`courses/ai-first-sees/narration/scenes.json` 是文本源（`scripts/curate_narration.py` 从大纲解析），`scripts/build_narration.py` 用 edge-tts 生成音频/时间/字幕并重写根 composition、`course.json` 和 scene 时间块；重跑脚本是唯一的时间来源（`--rate` 控语速，当前 `+0%`，必须带符号；`narration/cache/` 按 voice + rate + 旁白文本指纹失效）。音频是本地 OGG/Opus 静态文件，播放不依赖网络。视频导出在 `composition/` 里跑 `npx hyperframes render`（需要 ffmpeg/ffprobe 在 PATH 上）。
- 视觉现状：站点与整门课统一浅色纸面，四幕只换强调色（看=青绿、说=暖黄、做=电光蓝、群雄=蓝紫、用=珊瑚红）；真实 logo / 截图 / 历史照片只作为小证据卡出现。课程页封面顶部另有吸顶的「返回课程库」入口，播放时控制条第一个按钮也是「返回课程库」；旁白课程另有「字幕」「配音」两个独立开关，偏好存 localStorage（架构 D11-D13 与 [DESIGN.md](DESIGN.md) 8.4）。
- 还没做：CI、Docker/部署、登录、搜索。

先跑一遍这三条，确认环境是通的：

```bash
python scripts/sync_runtime.py          # 布置 player / runtime / GSAP / 字体
python scripts/build_courses.py --all   # 生成 dist/courses/<slug>/
pytest -q && ruff check .
# 只有重做旁白/时间时才需要（需要 edge-tts、mutagen、soundfile 和网络）：
python scripts/build_narration.py --no-tts   # 复用缓存重建时间/根 composition/ui 清单
```

新任务从工作树开始（规则见「分支与工作树」，工作树里跑同样这几条命令）：

```bash
python scripts/worktree.py add feat/<域>-<主题>   # 建工作树并复用 .venv / node_modules，不联网
```

Windows 上不用逐条敲：双击 `start.cmd` 时，`scripts/bootstrap.py` 会自动建 `.venv`、装依赖、同步运行时（`--skip-fonts`，字体子集用仓库里已提交的）、构建课程并迁移数据库；改完项目（课程、设计令牌、站点代码、数据库迁移）后双击 `build.cmd`，它调用 `scripts/build.py` 每次都完整跑「后端导入检查 → 完整 `sync_runtime.py`（含字体子集）→ `alembic upgrade head` → `build_courses.py --all`」，完成后再双击 `start.cmd`（站点正在运行就双击 `restart.cmd`）。
