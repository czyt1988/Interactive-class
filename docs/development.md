# 开发指南

这份文档给日常维护平台的人：仓库里什么放在哪、改完怎么构建、怎么在并行会话里开工作树。第一次安装见[快速开始](getting-started.md)；Agent 的强制规则见 [AGENTS.md](../AGENTS.md)。

## 仓库结构

```text
ai-learning/
├─ README.md                     # 项目入口：产品、快速开始、文档索引
├─ AGENTS.md                     # 给后续 Agent 的规则入口（工作树、提交、不可协商项）
├─ DESIGN.md                     # 前端设计契约（视觉/文案/动效/课程画面）
├─ pyproject.toml                # 依赖、ruff、pytest 配置
├─ alembic.ini                   # 数据库迁移配置
├─ start.cmd                     # Windows 双击启动站点
├─ build.cmd                     # Windows 双击重建
├─ restart.cmd                   # Windows 双击重启
├─ stop.cmd                      # Windows 双击停止
├─ app/                          # FastAPI 应用
│  ├─ main.py                    # create_app、健康检查、错误模型、静态挂载
│  ├─ config.py                  # 路径、环境变量、站点信息
│  ├─ db.py                      # SQLite / SQLAlchemy engine + pragmas
│  ├─ models.py                  # users / sessions / progress / course_imports / course_watermarks / course_clips
│  ├─ schemas.py                 # 进度 API 的请求/响应
│  ├─ deps.py                    # settings / catalog / db 依赖
│  ├─ auth/sessions.py           # 匿名会话、HttpOnly Cookie
│  ├─ repositories/progress.py   # 进度读写
│  ├─ catalog/                   # 课程契约模型、解析器、资产扫描、目录加载、导入、水印、片头片尾
│  ├─ videos/                    # 后台视频渲染：工具链发现、进程渲染、任务与产物
│  ├─ api/                       # /api/courses、/api/progress、/api/health
│  ├─ web/routes.py              # 首页、课程库、关于、sitemap
│  ├─ web/admin.py               # 后台设置、视频生成/下载、状态轮询、水印与片头片尾配置
│  ├─ web/import_routes.py       # /import 课程导入页（仅开发环境）
│  ├─ templates/                 # Jinja2 模板（含课程卡片、后台页、水印/片头片尾配置页、导入页与登录页）
│  └─ static/                    # 站点 CSS、字体、favicon、后台与导入样式
├─ migrations/                   # Alembic 迁移（0001_initial … 0004_course_clips）
├─ data/                         # SQLite 文件与后台生成的视频，不提交
│  ├─ videos/                    # 在线生成的 MP4 与元数据
│  └─ clip-previews/             # 片头片尾的临时预览课程包（可删，不进 Git）
├─ runtime/                      # 课程外壳运行时（所有课程共用）
│  ├─ shell.html.j2              # 课程页面模板
│  ├─ course-deck.js             # 播放器适配层 + 状态机
│  ├─ course-deck.css
│  ├─ vendor/                    # HyperFrames player / runtime（不进 Git）
│  └─ VERSION.json               # 固定版本 + 每个文件的 SHA-256
├─ design/                       # 设计令牌与字体源文件
├─ docs/                         # 产品、开发、课程、后台、部署文档
│  ├─ README.md                  # 文档导航
│  ├─ product.md                 # 产品说明：为什么做、学习体验、设计原则
│  ├─ getting-started.md         # 安装、启动、Windows 双击脚本
│  ├─ development.md             # 本文件：目录、构建、工作树
│  ├─ course-authoring.md        # 添加课程、模板包与导入
│  ├─ admin.md                   # 后台视频、水印、片头片尾
│  ├─ deployment.md              # 单机部署与 GitHub Pages
│  ├─ release-notes.md           # 版本记录与下一步
│  ├─ architecture.md            # 架构设计
│  ├─ course-contract.md         # 课程契约
│  ├─ agent-development-plan.md  # Agent 开发方案
│  └─ screenshots/               # 文档与 README 用的截图
├─ course-template/              # 独立课程模板包：交给外部作者或 AI 用
│  ├─ AGENTS.md                  # 给 AI 的课程生成指引
│  ├─ COURSE-CONTRACT.md         # 作者版规范
│  ├─ STYLE.md                   # 课程画面视觉规范
│  ├─ course.json                # 合法占位清单
│  ├─ STORYBOARD.md              # 分镜脚手架
│  └─ composition/               # 两屏骨架 + 本地字体 / GSAP
├─ course-inbox/                 # 外部课程收件箱，供导入使用（不进 Git）
├─ clips/                        # 全站共享的片头/片尾模板（后台按课选择）
│  ├─ intro-title-page/          # 片头：通用开源说明 + GitHub / Gitee 地址
│  └─ outro-colophon/            # 片尾：开源落款 + 一句收束
├─ courses/
│  ├─ ai-first-sees/             # 第一门课：从会聊天到会干活，AI Agent 入门
│  └─ <slug>/                    # 每门课一个目录
│     ├─ course.json
│     ├─ cover.webp              # 可选
│     ├─ STORYBOARD.md           # 课程脚本，不进入构建产物
│     └─ composition/            # HyperFrames 工程
│        ├─ index.html
│        ├─ compositions/
│        └─ assets/              # course.css、fonts/、vendor/gsap.min.js
├─ scripts/
│  ├─ sync_runtime.py            # 拉取 player/runtime/GSAP、子集化字体、同步令牌
│  ├─ build_courses.py           # 校验 + 构建课程包
│  ├─ new_course.py              # 从课程模板生成新课程脚手架
│  ├─ import_course.py           # 导入外部课程文件夹
│  ├─ build_narration.py         # 旁白音频/时间/字幕流水线
│  ├─ curate_narration.py        # 从大纲整理旁白文本
│  ├─ verify_course.py           # 课程包独立验收
│  ├─ bootstrap.py               # 双击启动器的环境准备：.venv、依赖、资源、构建、迁移
│  ├─ build.py                   # build.cmd 的一键重建：后端检查、运行时/字体、迁移、课程
│  ├─ env.cmd                    # start.cmd / restart.cmd / build.cmd 调用的环境检查（GBK）
│  ├─ serve.py                   # 用正确 MIME 类型静态服务课程包
│  ├─ launcher.py                # start / restart / stop 的实现
│  ├─ export_site.py             # 导出可静态发布的 dist/site/
│  └─ worktree.py                # 并行开发：git 工作树 + 复用依赖
├─ tests/
│  ├─ fixtures/courses/          # 合法与非法课程夹具
│  └─ e2e/                       # 独立静态服务器上的浏览器验收
├─ tools/package.json            # 固定的 HyperFrames / GSAP 版本（只在创作期用）
├─ .worktree/                    # 任务工作树（git worktree，不进 Git）
└─ dist/                         # 构建产物，不提交
   ├─ build.json                 # 构建时间、课程数、内容哈希
   └─ courses/<slug>/
```

几条边界：

- `app/` 是站点，`runtime/` 是课程外壳，两者都不属于某一门课；课程任务只改 `courses/<slug>/`。
- `dist/` 是构建产物，每次都重建，不要直接编辑。
- 课程内容用文件，用户、会话、进度、水印和片头片尾选择用 SQLite；数据库属于站点，不属于课程包。
- `data/`、`runtime/vendor/`、`courses/*/narration/cache/` 都是生成物，已被 gitignore。

## 日常工作流

```bash
python -m uvicorn app.main:app --reload        # 站点
python scripts/build_courses.py --all          # 重建全部课程
python scripts/build_courses.py --course <slug>  # 只重建一门课
pytest -q && ruff check .                      # 提交前验证
```

改完项目后，按[快速开始](getting-started.md#windows-双击启动)里的说明双击 `build.cmd`，再双击 `start.cmd`（或 `restart.cmd`）看最新版本。

## 每次改动跑什么

| 改动范围 | 至少跑 |
| --- | --- |
| 任意 | `pytest -q && ruff check .` |
| 课程或运行时 | 上面的命令 + `python scripts/build_courses.py --all` |
| `design/tokens.css`、字体或 vendor | 上面的命令 + `python scripts/sync_runtime.py`，并确认 `runtime/VERSION.json` 的 hash 更新 |
| 站点或课程视觉 | 按 [DESIGN.md](../DESIGN.md) 的验收方式补截图或 Playwright 检查 |
| 旁白或课程时间 | `python scripts/build_narration.py`（需要 edge-tts、mutagen、soundfile 和网络；`--no-tts` 只复用缓存重建时间） |

验证不过不提交。跑不了的验证要在提交信息和给用户的报告里说明原因。

## 并行开发（git 工作树）

本仓库的开发任务都在独立的 git 工作树里进行，主工作树只负责集成。完整规则见 [AGENTS.md](../AGENTS.md#分支与工作树每次开发都在工作树里)，常用命令：

```powershell
python scripts/worktree.py add feat/course-xyz              # 新建 .worktree\feat-course-xyz
python scripts/worktree.py list                             # 查看工作树、分支与共享状态
python scripts/worktree.py merge feat/course-xyz --remove   # 验证 + 合并回 main + 清理
```

创建工作树时会共享主工作树的 `.venv`、`tools/node_modules`、`tools/ffmpeg`（Windows 目录联接 / POSIX 软链接），并复制 `runtime/vendor` 与 `.env`，所以不需要重新联网安装依赖，新工作树几秒内就能跑测试、构建课程、双击 `start.cmd` 起站点。旁白 TTS 缓存也直接共享，重做旁白不用重新合成已有片段。

共享的代价是依赖目录属于主工作树：

- **不要在 worktree 里 `pip install` / `npm install`**，写的是共享环境，会波及主工作树和并行会话；启动器检测到共享环境会拒绝重装。
- 重做旁白是串行步骤，不要多个工作树同时重建同一门课的旁白。
- 依赖或本地配置变化后，`python scripts/worktree.py link` 会补齐缺失项并刷新 `runtime/vendor`、`.env` 副本。
- 删除工作树请用 `remove`，不要手工删目录；工作树有未提交改动时 `remove` 会拒绝，确认丢弃才加 `--force`。
- 工作树里起站点换端口：`$env:APP_PORT=8082`（PowerShell）或 `set APP_PORT=8082`（CMD），避免抢主工作树的 8081。
- `merge` 默认要求分支有工作树才能跑合并前验证；冲突时会自动回滚主工作树，修好再重试。

## 提交

- 一个任务一次提交；验收项全部做完、验证命令通过之后再提交。
- 用 Conventional Commits：`<type>(<scope>): <中文一句话>`，type 取 `feat`、`fix`、`docs`、`chore`、`refactor`、`test`、`build`、`perf`、`style`。
- 分路径 `git add`，提交前看 `git status --short` 和 `git diff --cached`；不属于本任务的改动先停下问用户。
- 不提交 `dist/`、`data/`、视频、字体缓存和本地工具；`.gitignore` 是权威清单。
- 工作树任务收尾用 `python scripts/worktree.py merge <分支> --remove` 合并回 `main` 并清理。

完整的提交规则、不要提交的东西和验证要求见 [AGENTS.md](../AGENTS.md#提交规则)。
