# Agent 开发方案

> 状态：v0.1，架构阶段。
> 这份文档是后续开发任务的**唯一执行计划**。先读[架构设计](architecture.md)和[课程契约](course-contract.md)，再开始任何一个阶段。

## 0. 怎么用这份文档

- 一次任务只做一个阶段，除非用户明确要求连续执行。
- 每个阶段有目标、任务、验收标准和验证命令。**验收标准全部满足才算完成**，不要用“基本可用”代替。
- 阶段有依赖顺序。不要跳过 Phase 1 直接做播放器，也不要在 Phase 0 就引入课程内容。
- 每门新课程是一个独立任务，走第 14 节的模板。课程任务不修改平台代码。
- 架构决策变了，先更新[架构设计](architecture.md)的决策表，再改代码。不要在代码里悄悄改变方向。

## 1. 不可协商的约束

这些约束来自产品定义，不是实现偏好。违反其中任何一条，先停下来和用户确认。

1. **课程必须是独立静态包。** `dist/courses/<slug>/` 放进任何静态服务器都能完整播放。
2. **课程页在没有 API、数据库或登录态时完整可用。** 同源进度同步只能是可选增强，不能成为播放前置条件。
3. **不把 MP4 作为运行时输出或主要分发格式。**
4. **不使用 SPA 框架做站点。** 站点是 FastAPI + Jinja2 服务端渲染；课程外壳是原生 ES module。
5. **SQLite 是应用数据库。** 课程内容仍在文件里；SQLite 存用户、会话和进度。数据库属于站点，不属于课程包。
6. **不在运行时引用 CDN。** player、runtime、GSAP、字体全部本地。
7. **一门课一个 HyperFrames composition，一屏一个 scene。**
8. **课程任务只修改 `courses/<slug>/`。** 需要平台能力时另开任务。
9. **HyperFrames 版本固定。** 不升级 `latest`；升级走第 9.8 节（架构文档）的流程。
10. **每个课程包必须通过独立静态服务器验收。** 这是硬门槛，不是建议。
11. **数据库迁移只通过 Alembic。** 不用 `create_all()` 代替线上迁移，不在应用启动时自动迁移。

## 2. 每个任务的工作方式

开始：

1. 读这份计划的相关阶段、[架构设计](architecture.md)、[课程契约](course-contract.md)。
2. 看 `git status`，确认工作区是干净的（上一个任务应已按[提交规则](../AGENTS.md#提交规则)提交）；有未提交改动先问清来源，不要顺手用掉。
3. 找到当前阶段未满足的验收项，列一个短 todo。
4. 只改本任务需要的文件；不要顺手重构无关模块。

结束：

1. 跑本阶段的验证命令。
2. 更新文档中因实现而变化的部分（命令、字段、路径、版本）。
3. 报告：完成了什么、验证了什么、没验证什么、下一步是什么。
4. 按 [AGENTS.md](../AGENTS.md#提交规则) 提交本任务改动；提交前确认暂存区没有无关文件，提交失败或验证跑不了要说明原因。

命令示例以 bash 语法为主；Windows PowerShell 下把 `curl` 写成 `curl.exe`，续行用反引号或写成一行。脚本本身用 Python 实现，不依赖 shell 方言。

## 3. 阶段总览

| 阶段 | 产出 | 依赖 | 完成信号 |
| --- | --- | --- | --- |
| 0 | FastAPI 骨架、配置、健康检查、基础模板 | — | `uvicorn` 能起，`/healthz` 200 |
| 1 | 课程模型、composition 解析、合并校验、目录 API | 0 | 合法 fixture 解析成功，非法 fixture 报具体错误 |
| 2 | 运行时打包、课程构建、静态服务 | 1 | fixture 构建成独立静态包，普通静态服务器能打开 |
| 2.5 | SQLite、Alembic、匿名会话、进度 API | 0、1 | 空库迁移到 head；进度 API 可写可读；无 API 时课程仍可用 |
| 3a | 播放器适配层 spike | 2 | 两屏 fixture 能按 range 播放并在终点触发 `ended` |
| 3b | 课程外壳（封面、切屏、控制、讲义） | 3a、2.5 | 完整走完开始→下一屏→讲义→完成；无 API 也能用 |
| 4 | 站点首页、课程库、关于、404 | 1、2 | 课程卡片能进入课程，移动端和 SEO 达标 |
| 5 | 样板课“什么是 token” | 3b、4 | 一门完整课程在站点和独立部署下都通过 |
| 6 | CI、E2E、无障碍、性能、独立部署测试 | 5 | CI 能拦住契约/外部资源/独立部署回归 |
| 7 | Docker、部署、缓存、回滚 | 6 | 生产 URL 可访问，课程可播放，回滚有文档 |
| 8 | 课程脚手架、课程任务模板、升级流程 | 7 | 新课程零平台改动完成并发布 |

阶段 3 拆成 3a/3b 是有意的：range 行为是当前最大的技术风险，先用最小 spike 验证，再投入 UI。

### 3.1 实施状态（2026-11-08）

| 阶段 | 状态 | 证据 / 备注 |
| --- | --- | --- |
| 0 仓库地基 | ✅ 完成 | `pyproject.toml`、`app/main.py`、`/healthz`、`tests/test_health.py` |
| 1 课程契约与目录 | ✅ 完成 | `app/catalog/*`、18 个 resolver 测试、非法夹具逐条报错误码 |
| 2 构建与运行时打包 | ✅ 完成 | `scripts/sync_runtime.py`、`scripts/build_courses.py`、资产扫描、`tests/test_build.py` |
| 2.5 SQLite 数据层 | ✅ 完成 | `app/db.py`、`app/models.py`、`migrations/0001_initial`、匿名会话、进度 API、`tests/test_progress.py`、`tests/test_migrations.py` |
| 3a 播放器适配层 | ✅ 完成 | `runtime/course-deck.js` 的 `createPlayerAdapter`；`tests/e2e/test_standalone.py` 验证 range 终点 `ended` |
| 3b 课程外壳 | ✅ 完成 | 封面、切屏、控制条、讲义抽屉、完成页、错误页、深链、`localStorage` 进度、键盘 |
| 4 站点外壳 | ✅ 完成 | 首页、课程库（含 level/tag 过滤）、关于、404、sitemap、robots |
| 5 样板课 | ✅ 完成（长视频版 v2） | `courses/ai-first-sees/` 按新版 `大纲/AI-Agent-入门课/02-逐页脚本.md`（22 镜头）完整落地：22 屏 / 18:38（旁白 `rate +0%`），整门课浅色纸面，旁白驱动、底部字幕烧进画面、连续播放，播放器可暂停/关字幕/关配音；`hyperframes check` 没有 craft error，layout 的 6 条 `content_overlap` 见 3.2 |
| 6 CI 与质量门 | ⬜ 未开始 | 本地已能跑全部检查（101 个测试、ruff、HyperFrames check），但没有 CI 配置文件 |
| 7 发布 | ⬜ 未开始 | 无 Dockerfile、无反代配置、无生产 URL |
| 8 课程规模化 | ✅ 完成 | 独立模板包 `course-template/`、`scripts/new_course.py`、`scripts/import_course.py`、开发环境 `/import` 导入页、`course_imports` 来源记录 |

实施中与原计划不同的四处，均已同步到文档：

1. **构建输出目录**：`--out-dir` 指课程包根目录（默认 `dist/courses`），不自动追加 `courses/`。
2. **`python -m http.server` 在 Windows 上可能把 `.js` 当 `text/plain`**，导致 ES module 被拒。独立部署验收改用 `scripts/serve.py`（固定 MIME）。
3. **字体可选**：课程外壳只在课程自带 `composition/assets/fonts/*.woff2` 时注入 `@font-face`；测试夹具因此不需要 190KB 字体。
4. **长视频课程**：`ai-first-sees` 采用 S 编号一页、旁白音频为时钟、`playback: "continuous"` 连续播放。它超出短课「6–10 屏 / 2–5 分钟」的上限，按课程契约 4.11 的中长视频例外验收；时间由 `scripts/build_narration.py` 生成，作者不手写。

### 3.2 未验证的事项

- 没有在 Safari / Firefox 上跑过；`tests/e2e` 目前只用 Chromium。长视频课程的旁白连续播放与 OGG/Opus 解码已在 Chromium 验证，Safari 的自动播放策略尚未验证。
- 没有真机移动端验收；只做了窄视口截图。
- `hyperframes check`（本地把 `tools/ffmpeg/bin` 加进 PATH）：craft 0 error；50 条 craft warning 是 28 条 `line_unread` + 22 条 `text_below_floor`（字幕停留时间和装饰性小字，既有）。layout 还有 6 条 `content_overlap` error（S17 / S19 的场景文字排版，既有，未在进度条任务里修）。
- 2026-11 按产品要求移除画布内的旁白进度条（它在 iframe 里拖不动，和播放器底部的 seek 条重复）。代价是 13 段纯静止约 3.8 秒的旁白段会重新触发 `dead_stretch` 警告；没有用 `data-hold` 去掩盖——旁白驱动场景里「字幕在走、画面暂时不动」是真实的静止。
- 全片 MP4 已用 ffmpeg 校验：1920×1080 / 30fps / H.264 + AAC，21m33.5s，有声音；没有在电视和低端手机上做码率/兼容性实测。
- 课程导入在 TestClient、真实构建流水线和 Playwright 自检（1440px / 390px、真实点击导入、CSP、同源 Origin）中验证过；没有在 TLS 终止的反向代理后验证同源 Origin，也没有在 Safari / Firefox 上打开过 `/import`。
- 播放页全视口布局与逐屏进度是 2026-11 这轮改的：浏览器验收范围是 Chromium 下 1920×1080 / 1600×900 / 1366×768 / 390×844，用真实鼠标拖动当前屏进度、跳到最后、`End`、确认播放页无滚动；未验证 Safari / Firefox 和真机触摸。

---

## 4. Phase 0：仓库地基

### 目标

一个能启动、能测试、能渲染占位首页的 FastAPI 应用。还没有课程、播放器或构建。

### 任务

1. 创建 `pyproject.toml`：
   - Python ≥ 3.11；
   - 运行时依赖：`fastapi`、`uvicorn[standard]`、`jinja2`、`pydantic-settings`、`sqlalchemy`、`alembic`；
   - 开发依赖：`pytest`、`httpx`、`ruff`、`playwright`、`pytest-playwright`；
   - 配置 ruff 和 pytest。
2. 创建 `.gitignore`：`.venv/`、`__pycache__/`、`.pytest_cache/`、`.ruff_cache/`、`dist/`、`data/`、`*.db`、`*.sqlite3`、`node_modules/`、`.hyperframes/`、`renders/`、`.env`、`*.mp4`。
3. 创建 `.env.example`，字段与架构文档 7.7 一致（含 `DATABASE_URL`）。
4. 创建 `app/config.py`：BASE_DIR、课程源/产物目录、站点标题、环境、`DATABASE_URL`。
5. 创建 `app/main.py`：`create_app()`、Jinja2 模板、静态目录、`GET /healthz`、`GET /` 占位页。
6. 创建 `app/templates/base.html`、`home.html`；`app/static/site.css` 只放基础 reset 和排版。
7. 创建 `tests/test_health.py`：`/healthz` 返回 200 和 `{status: "ok"}`；`/` 返回 200 且包含站点名。
8. 在 README 的“项目状态”里把 Phase 0 标为进行中/完成（按实际）。

### 验收

- [ ] `python -m venv .venv` 后安装成功。
- [ ] `uvicorn app.main:app --reload` 能启动。
- [ ] `GET /healthz` 返回 200，JSON 有 `status: "ok"`。
- [ ] `GET /` 返回 200，包含 `AI Learning`。
- [ ] `pytest -q` 全绿。
- [ ] `ruff check .` 通过。
- [ ] 没有引入课程内容或播放器代码；数据库在 Phase 2.5 建立。

### 验证命令

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -e ".[dev]"
python -m playwright install chromium
uvicorn app.main:app --reload
pytest -q
ruff check .
```

### 不做什么

不做课程目录、不做构建、不做播放器、不做复杂首页视觉。Phase 0 只证明“进程能起、模板能渲染、测试能跑”。

---

## 5. Phase 1：课程契约与目录

### 目标

把 `course.json` 和 `composition/index.html` 合并成可靠的 `ResolvedCourse`，并暴露只读目录 API。这是整个平台的数据地基。

### 任务

1. `app/catalog/models.py`：
   - `CourseSource`、`ScreenMeta`、`CompositionInfo`、`ScreenHost`、`ResolvedScreen`、`ResolvedCourse`、`CourseSummary`、`Catalog`；
   - 源模型 `extra="forbid"`；
   - 字段和[课程契约](course-contract.md)第 3 节一一对应。
2. `app/catalog/composition.py`：
   - 用 `html.parser` 解析根 composition；
   - 提取带 `data-screen-id` 的 host；
   - 读取 `id`、`data-composition-id`、`data-composition-src`、`data-start`、`data-duration`；
   - 读取根 `data-duration`；
   - 不解析 scene 内容（scene id 检查由 resolver 做文件级检查）。
3. `app/catalog/resolver.py`：
   - 排序、去重、匹配元数据；
   - 校验时间、重叠、根时长、scene 文件存在、scene id 匹配；
   - 生成 `ResolvedCourse` 和统计；
   - 错误对象包含课程 slug、文件、屏幕 id、字段、期望值。
4. `app/catalog/loader.py`：
   - 扫描 `dist/courses/*/course.json`（构建后的解析清单），不读 `courses/` 源，不解析 composition；
   - 缓存目录，并按 `course.json` 的 mtime / 目录签名失效；构建后无需重启；
   - 错误策略：默认跳过并记录；`STRICT_CATALOG=1` 时启动失败；
   - 检查同目录 `index.html`、`composition/`、`runtime/` 是否存在，缺失标记 invalid；该检查可通过 `VERIFY_COURSE_BUNDLES=0` 关闭（分离部署）。
5. `app/api/courses.py`：
   - `GET /api/courses`；
   - `GET /api/courses/{slug}`；
   - `GET /api/health`。
6. 测试 fixture：
   - `tests/fixtures/courses/valid-two-screen/`：源 `course.json` + `composition/index.html` + 两个 scene 占位文件，用于 resolver 测试；
   - `tests/fixtures/dist/courses/valid-two-screen/course.json`：解析后的清单，用于 loader/API 测试；
   - 每个错误一个独立 fixture：源侧错误（缺元数据、重复 id、时间倒置、重叠、根时长不足、scene 缺失、scene id 不匹配）和解析清单侧错误（缺字段、时间越界、产物缺失）。
7. 单元测试覆盖[课程契约](course-contract.md) 5.2 的每个错误码。
8. 统一错误模型：API 返回 `{error: {code, message, details}}`，不要抛裸 500。

### 验收

- [ ] 合法源 fixture 经 resolver 解析出正确的屏数、顺序、start/duration、总时长。
- [ ] 合法解析清单 fixture 能被 loader 读入，生成 `Catalog`。
- [ ] 每个错误 fixture 返回对应的错误码和字段，不是泛化异常。
- [ ] 重复 id、时间重叠、根时长不足、scene 文件缺失、scene id 不匹配都有测试。
- [ ] 开启 `VERIFY_COURSE_BUNDLES` 时，解析清单缺少 `index.html`/`composition/`/`runtime/` 会标记 invalid。
- [ ] `GET /api/courses` 返回摘要，不返回完整讲义。
- [ ] `GET /api/courses/<slug>` 返回完整解析结果。
- [ ] `STRICT_CATALOG=1` 时，非法课程让启动失败；默认模式跳过并记录。
- [ ] 解析器不依赖 Node、不调用 HyperFrames CLI。
- [ ] `pytest` 全绿，`ruff` 通过。

### 验证命令

```bash
pytest tests/test_resolver.py -q
pytest -q
curl http://127.0.0.1:8000/api/courses
curl http://127.0.0.1:8000/api/health
```

### 不做什么

不做构建产物、不做课程页、不做播放器。Phase 1 只解决“课程数据能不能被可靠地读出来”。

---

## 6. Phase 2：构建与运行时打包

### 目标

把一门源课程构建成 `dist/courses/<slug>/` 的独立静态包，并让 FastAPI 能服务它。此阶段课程页可以是最小占位，但文件必须齐全、路径必须正确。

### 任务

1. 创建 `tools/package.json`，固定：
   - `hyperframes@0.9.19`；
   - `gsap@3.15.0`。
   不要用 `latest`。
2. 创建 `scripts/sync_runtime.py`：
   - 从 `tools/node_modules/hyperframes/dist/` 拷贝 `hyperframes-player.global.js`、`hyperframe.runtime.iife.js`；
   - 拷贝 GSAP、字体到 `course-template/composition/assets/` 以及所有已有课程；
   - 拷贝 `design/tokens.css` 到 `runtime/tokens.css`（课程外壳共用）和 `app/static/tokens.css`（站点）；字体同步到 `app/static/fonts/`；
   - 写 `runtime/VERSION.json`（版本 + SHA-256）；
   - 拷贝 LICENSE/NOTICE。
3. 创建 `runtime/` 最小骨架：
   - `shell.html.j2`：先渲染封面、标题、大纲和一个占位舞台；
   - `course-deck.css`：基础布局；
   - `course-deck.js`：先只做封面/舞台切换占位，完整逻辑在 Phase 3b；
   - `vendor/` 由 sync 脚本填充。
4. 创建 `scripts/build_courses.py`：
   - 使用 Phase 1 的 resolver；
   - 扫描源时跳过 `_` 和 `.` 开头的目录（独立模板包 `course-template/` 不在 `courses/` 下）；
   - 校验 scene 文件、vendor、字体、外部资源加载、大小预算；
   - 用 Jinja2 渲染 `shell.html.j2`；
   - 拷贝 composition（排除 `node_modules`、`.hyperframes`、`renders`、`*.mp4`、`package.json`、`hyperframes.json`、源地图）；
   - 拷贝 runtime（排除 `shell.html.j2`）、LICENSES；
   - 写解析后的 `course.json`；
   - 支持 `--course <slug>`、`--all`、`--check-only`、`--include-drafts`，以及测试用的 `--source-dir` / `--out-dir`。
5. 创建 `course-template/`（独立模板包；当时先放在 `courses/_template/`，Phase 8 抽出）：
   - `course.json` 模板；
   - `STORYBOARD.md` 模板；
   - `composition/` 最小两屏工程；
   - 本地 GSAP、字体、`course.css`；
   - `package.json` 固定版本。
6. 在 `app/main.py` 挂载 `/courses` 到 `dist/courses`（`html=True`）。
7. 构建一个 fixture 课程并纳入测试。fixture 放在 `tests/fixtures/courses/valid-two-screen/`，测试通过 `--source-dir` / `--out-dir` 或直接调用 build 函数指向临时目录，不污染真实的 `courses/` 目录。
8. 测试：
   - 产物文件齐全；
   - 解析后的时间正确；
   - 排除规则生效；
   - 重复构建幂等（除时间戳）；
   - 外部资源加载被拒绝；
   - 缺失 vendor 被拒绝；
   - `python -m http.server` 能返回课程页和 composition。
9. 运行 `npx hyperframes@0.9.19 check` 验证 fixture composition。

### 验收

- [ ] `python scripts/build_courses.py --source-dir tests/fixtures/courses --out-dir .tmp/dist --course valid-two-screen` 生成完整 `.tmp/dist/courses/valid-two-screen/`。
- [ ] 产物包含 `index.html`、`course.json`、`composition/`、`runtime/`、`LICENSES/`。
- [ ] 产物不包含 `node_modules/`、`.hyperframes/`、`renders/`、`*.mp4`、`STORYBOARD.md`、`package.json`、`hyperframes.json`、`shell.html.j2`。
- [ ] 课程页里的 player `runtime-src` 指向 `./runtime/vendor/hyperframe.runtime.iife.js`。
- [ ] composition 里的 GSAP 指向 `assets/vendor/gsap.min.js`，不是 CDN。
- [ ] `python -m http.server 8081 -d .tmp/dist/courses/valid-two-screen` 能返回 200。
- [ ] 构建产物没有外部资源加载；引用/致谢外链除外。
- [ ] 非法课程构建失败，错误信息包含文件/字段/屏幕 id。
- [ ] `npx hyperframes@0.9.19 check` 在 fixture 的 `composition/` 下通过。
- [ ] FastAPI 的静态 mount 能服务该产物（测试时把 `COURSES_DIST_DIR` 指向 `.tmp/dist`）。
- [ ] `GET /api/courses` 能读到构建产物里的课程；`GET /api/courses/<slug>` 返回解析清单。
- [ ] `pytest`、`ruff` 全绿。

### 验证命令

```bash
cd tools
npm install
cd ..
python scripts/sync_runtime.py
python scripts/build_courses.py --source-dir tests/fixtures/courses --out-dir .tmp/dist --course valid-two-screen
python -m http.server 8081 -d .tmp/dist/courses/valid-two-screen
npx --yes hyperframes@0.9.19 check   # 在 fixture 的 composition/ 下
pytest tests/test_build.py -q
```

### 不做什么

不做完整课程外壳、不做站点首页、不做样板课。Phase 2 的课程页可以是“能打开、能显示标题”的最小版本。

---

## 6.5 Phase 2.5：SQLite 数据层

### 目标

建立 SQLite 数据层、匿名会话和进度 API，让“用户状态”从第一天就有正确的落点。课程页仍然不依赖它；这一步是为未来登录和跨设备进度打地基。

### 任务

1. `app/db.py`：
   - SQLAlchemy 2.0 engine/session；
   - SQLite `check_same_thread=False`；
   - 连接事件设置 `journal_mode=WAL`、`foreign_keys=ON`、`busy_timeout=5000`、`synchronous=NORMAL`；
   - `DATABASE_URL` 从配置读取，默认 `sqlite:///./data/app.db`。
2. `app/models.py`：
   - `User`：`id`、`email`（可空唯一）、`password_hash`（可空）、`display_name`、`is_anonymous`、时间戳；
   - `Session`：`id`、`user_id`、`token_hash`（唯一）、`expires_at`、时间戳；
   - `CourseProgress`：`user_id` + `course_slug` 复合主键、`last_screen_id`、时间戳；
   - `ScreenProgress`：`user_id` + `course_slug` + `screen_id` 复合主键、`completed_at`、时间戳；
   - 外键 `ON DELETE CASCADE`；必要索引。
3. Alembic：
   - `alembic init migrations`；
   - `render_as_batch=True`；
   - 生成第一版迁移；
   - `alembic upgrade head` 能从空库建出全部表/索引。
4. `app/auth/sessions.py`：
   - 生成 32 字节随机 token、SHA-256 哈希；
   - Cookie：`HttpOnly`、生产 `Secure`、`SameSite=Lax`、`Path=/`、180 天；
   - `get_optional_learner`：有合法会话返回用户，没有返回 `None`；
   - `get_or_create_learner`：只在写进度时创建匿名用户和会话；设置 Cookie；
   - 过期会话处理。
5. `app/repositories/progress.py`：
   - `get_progress(user, course_slug)`；
   - `upsert_progress(user, course_slug, screen_id, completed)`；
   - 写入前用 catalog 校验 `course_slug` 和 `screen_id`；
   - `course_progress` 与 `screen_progress` 同事务更新；
   - 预留账号合并函数（v1 不实现登录）。
6. `app/schemas.py`：
   - `ProgressUpdate`：`screenId`、`completed`；
   - `ProgressResponse`：`lastScreenId`、`completedScreens`、`updatedAt`；
   - 长度/类型限制。
7. `app/api/progress.py`：
   - `GET /api/progress/{course_slug}`：无会话返回空进度，不创建用户；
   - `PUT /api/progress/{course_slug}`：创建匿名会话（如需要）、upsert；
   - `GET /api/progress`：当前用户全部进度；
   - 检查 `Origin`；限制请求体大小；默认不开放 CORS。
8. `app/main.py`：
   - 注入 session 依赖；
   - `GET /readyz`：DB 连接 + schema version；
   - `/api/health` 增加 DB 状态。
9. 测试：
   - 空库迁移到 head；
   - 匿名用户创建、Cookie 设置、会话过期；
   - GET 不创建用户；
   - PUT 幂等 upsert；
   - 未知课程/屏幕拒绝；
   - 请求体超限拒绝；
   - 同一用户两门课互不影响；
   - 数据库文件在 `data/`，不进入 Git。
10. 更新 `.env.example`、README、架构文档的 DB 状态。

### 验收

- [ ] `alembic upgrade head` 在空库成功，表和索引齐全。
- [ ] `PUT /api/progress/<slug>` 第一次调用创建匿名用户/会话并设置 HttpOnly Cookie。
- [ ] `GET /api/progress/<slug>` 无 Cookie 返回空进度，且不创建用户。
- [ ] 同一 `PUT` 重复调用是幂等的。
- [ ] 未知 `course_slug`/`screen_id` 返回 404/422，不写脏数据。
- [ ] `/readyz` 在 DB 正常时 200，DB 不可用时返回非 200。
- [ ] `data/` 被 `.gitignore` 忽略；数据库文件不在 Web 根目录。
- [ ] 课程包不需要 API 也能播放（Phase 2 fixture）。
- [ ] `pytest`、`ruff` 全绿。

### 验证命令

```bash
alembic upgrade head
pytest tests/test_progress.py -q
pytest tests/test_migrations.py -q
curl -i -X PUT http://127.0.0.1:8000/api/progress/valid-two-screen \
  -H "Content-Type: application/json" \
  -d '{"screenId":"hook","completed":true}'
curl http://127.0.0.1:8000/readyz
```

### 不做什么

不做注册/登录/找回密码，不做邮箱验证，不做 Postgres，不做学习看板。Phase 2.5 只建立可用的匿名会话和进度 API。

---

## 7. Phase 3a：播放器适配层 spike

### 目标

在投入 UI 之前，证明 `<hyperframes-player>` 能在课程包里按 `range-start` / `range-end` 播放一屏，并在终点可靠地停下。如果不可靠，确定降级方案。

### 任务

1. 用 Phase 2 的两屏 fixture（每屏 2 秒，纯色/文字）。
2. 在 `runtime/course-deck.js` 里实现最小适配层：
   - `load()`：设置 `src`、`runtime-src`、`poster`；
   - `setRange(start, end)`；
   - `play()`、`pause()`、`seek()`；
   - `on(event, handler)`：`ready`、`painted`、`ended`、`timeupdate`、`error`。
3. 写一个最小 HTML 测试页（可以在 `tests/fixtures/` 下），加载 player 和 runtime，执行：
   - 播放第一屏 range；
   - 记录 `ended` 的时间和 `currentTime`；
   - seek 到第二屏 range；
   - 播放到 `ended`；
   - 切换回第一屏。
4. 用 Playwright 跑这个测试页。
5. 记录结论：
   - range 是否可靠；
   - `ended` 是否在终点触发；
   - `seek` 后是否需要等待；
   - 是否有 Safari/Chrome 差异；
   - 如果 range 不可靠，降级方案是否工作（seek + 时间监听 + 合成 ended）。
6. 把结论写进 `docs/architecture.md` 的 5.5 或单独的 `docs/spikes/player-range.md`，并更新适配层说明。

### 验收

- [ ] 两屏 fixture 能播放第一屏，2 秒左右停在终点。
- [ ] `ended` 触发一次，`currentTime` 在 2 秒附近。
- [ ] 能切到第二屏并播放到终点。
- [ ] 能切回第一屏。
- [ ] 控制台没有 error。
- [ ] 适配层接口稳定，UI 不直接调用 player 的 range 属性。
- [ ] 结论已记录；如果 range 不可用，降级方案已实现并通过同一测试。

### 验证命令

```bash
pytest tests/e2e/test_player_contract.py -q
```

### 停止条件

如果 range 和降级方案都不能可靠地在终点停下，停止 Phase 3b，报告：
- HyperFrames 版本；
- fixture 结构；
- 实际 `currentTime`/事件序列；
- 建议：换 player 版本、改用官方 slideshow、或自建更薄的播放控制。

不要带着“有时能停”的不确定性进入 UI 开发。

---

## 8. Phase 3b：课程外壳

### 目标

完成课程页的封面、舞台、控制条、讲义、完成页和错误页。学完一门课时，体验应该是完整、安静、可控的。

### 任务

1. `runtime/shell.html.j2`：
   - 封面：标题、副标题、目标、先修、大纲、时长/级别/屏数、开始、继续上次；
   - 舞台：player、加载遮罩、转场遮罩；
   - 控制条：上一屏、播放/暂停、下一屏、重播、讲义、声音（有音频）、全屏；
   - 章节信息：kicker、标题、summary；
   - 讲义抽屉；
   - 完成页：takeaways、重看、返回课程库；
   - 错误页；
   - `<noscript>`。
2. `runtime/course-deck.css`：
   - 16:9 舞台、最大高度；
   - 封面/舞台/完成页布局；
   - 控制条和焦点样式；
   - `prefers-reduced-motion`；
   - 手机横屏/竖屏提示；
   - 打印样式（讲义可打印，可选）。
3. `runtime/course-deck.js`：
   - 状态机（见架构 5.4）；
   - 适配层（Phase 3a）；
   - 切屏、进度、hash、`pushState`/`replaceState`；
   - `localStorage` 进度；如果注入 `progressEndpoint` / `progressOrigin` 且 origin 匹配，再异步 GET/PUT 同步（失败静默，不阻塞播放）；
   - 键盘、触摸、全屏；
   - 音频解锁/静音回退；
   - 错误/重试；
   - `aria-live` 播报；
   - 事件埋点（只 dispatch 本地 CustomEvent，不发网络）。
4. 构建集成：
   - 内联解析后的清单；
   - 注入 title/description/OG/JSON-LD；
   - 设置 `site.homeUrl`、`accent`、`audio`、`interactive`；
   - 同源部署时注入 `progressEndpoint` 和 `progressOrigin`，否则为 `null`；
   - 封面 fallback。
5. 三屏 fixture（含讲义、音频可选、一个 `autoAdvance` 屏）。
6. Playwright 测试：
   - 开始 → 第一屏 → 下一屏 → 上一屏；
   - 暂停/继续/重播；
   - 讲义打开/关闭；
   - 全屏进出；
   - 深链打开停在第一帧；
   - 刷新后“继续上次”；
   - `prefers-reduced-motion` 不自动播放；
   - 键盘全流程；
   - 错误注入显示降级页；
   - 无外部请求。
7. axe 检查，修掉 serious/critical。

### 验收

- [ ] 封面可以开始课程，第一屏在 `painted` 后播放。
- [ ] 点击下一屏后 300ms 内出现转场遮罩；新屏在首个进入新 range 的 `timeupdate` 或短转场后出现，不看到明显中间帧。
- [ ] `ended` 后显示“下一屏”；`autoAdvance` 屏自动进入下一屏。
- [ ] 暂停/继续/重播状态正确。
- [ ] 讲义内容与当前屏一致，可用键盘打开/关闭，焦点回到触发按钮。
- [ ] 全屏包含控制条，Esc 退出。
- [ ] 深链 `#s=<id>` 打开后停在该屏，不自动播放。
- [ ] 本地进度能“继续上次”。
- [ ] 没有 `progressEndpoint` 或 origin 不匹配时，课程页不向 `/api/*` 发请求；本地进度正常。
- [ ] 有 `progressEndpoint` 且接口失败时，课程页不报错、不阻塞，本地进度仍然正确。
- [ ] `prefers-reduced-motion` 下不自动播放，讲义可读。
- [ ] 手机竖屏显示横屏建议和讲义入口；横屏可操作。
- [ ] 错误时显示错误页，有重试，不是空白。
- [ ] 控制台无 error；无外部请求。
- [ ] axe 无 serious/critical。
- [ ] 键盘可以完成主流程。

### 验证命令

```bash
pytest tests/e2e/test_course_deck.py -q
pytest -q
ruff check .
```

### 不做什么

不做站点首页、不做课程库、不做真实课程内容。Phase 3b 用 fixture 验证体验。

---

## 9. Phase 4：站点外壳

### 目标

完成首页、课程库、关于、404，让课程可以被发现和进入。站点要像一本课程目录，不像一个 SaaS 仪表盘。

### 任务

1. `app/web/routes.py`：
   - `/`、`/courses`、`/courses/` 重定向、`/about`、404；
   - 服务端过滤 `level`、`tag`；
   - 精选课程逻辑。
2. 模板：
   - `base.html`：头部、导航、页脚、meta；
   - `home.html`：主张、精选课程、课程网格、“怎么学”；
   - `library.html`：课程卡片、过滤、空状态；
   - `about.html`：方法论、制作流程、致谢；
   - `404.html`；
   - `partials/course_card.html`。
3. `app/static/site.css`：
   - 暖纸色/墨色/强调色；
   - 12 列网格；
   - 三列→两列→单列；
   - hover/focus 状态；
   - 无 JS 可用的导航和过滤。
4. SEO：
   - title/description/canonical/OG；
   - `sitemap.xml`、`robots.txt`；
   - 课程卡片链接使用 `COURSE_BASE_URL`。
5. 无 JS 验收：课程库和过滤仍可用。
6. 测试：
   - 页面 200；
   - 过滤结果；
   - 卡片链接；
   - 空状态；
   - 404；
   - meta 标签；
   - 移动端截图。
7. Lighthouse/axe：性能 ≥ 90，无障碍 ≥ 95（按实际环境校准）。

### 验收

- [ ] `/`、`/courses`、`/about` 正常返回。
- [ ] 课程卡片进入 `/courses/<slug>/`。
- [ ] `level` 和 `tag` 过滤正确，空状态友好。
- [ ] 没有 JS 时课程库仍可浏览。
- [ ] 手机、平板、桌面布局正常。
- [ ] 页面有 title/description/canonical/OG。
- [ ] `sitemap.xml` 包含已发布课程。
- [ ] axe 无 serious/critical。
- [ ] 站点不使用 SPA 框架、不自动播放课程动画。

### 验证命令

```bash
pytest tests/test_web.py -q
pytest tests/e2e/test_site.py -q
```

---

## 10. Phase 5：样板课

### 目标

做一门完整的样板课，证明“课程契约 + 构建 + 播放器 + 站点”整条链路成立。建议主题：**什么是 token**，6–8 屏，2–3 分钟。

### 任务

1. 用 `python scripts/new_course.py what-is-a-token --title "..."` 生成脚手架（从 `course-template/` 复制 `course.json`、`STORYBOARD.md`、`composition/`）。
2. 写 `courses/what-is-a-token/STORYBOARD.md`：
   - 学习者是谁；
   - 学完能做什么；
   - 每屏一句话论题、看见什么、动画如何论证、屏幕文字、讲义、时长；
   - 事实来源。
3. 给用户/评审看 storyboard，确认后再做动画。
4. 改 `course.json`。
5. 逐屏做 scene：
   - 每加一屏，跑一次 composition 的 `check`；
   - 每屏 0%/50%/90% 快照；
   - 文字大小、对比度、安全区；
   - 结尾稳定帧。
6. 接根 composition，设置时间。
7. 做封面（可选；没有就用排版封面）。
8. 构建，打开站点课程页，完整走一遍。
9. 用静态服务器独立打开，完整走一遍。
10. 键盘、减少动态效果、手机横屏、Network。
11. 按[课程契约](course-contract.md)第 8 节验收。
12. 确认课程自动出现在目录，检查首页精选/课程库。
13. 记录本课程制作中发现的平台问题；能修的在 Phase 6 前修，不能修的进 backlog。

### 验收

- [ ] 课程有 6–8 屏，每屏一个论题，总时长 2–5 分钟。
- [ ] composition 通过 `check`，每屏快照看过。
- [ ] 没有外部资源加载、CDN、Google Fonts。
- [ ] 构建产物在普通静态服务器上完整播放。
- [ ] 站点课程页完整播放。
- [ ] 键盘、讲义、减少动态效果、深链、本地进度正常；同源 API 可用时进度同步，不可用时不影响播放。
- [ ] 首屏/总大小在预算内。
- [ ] axe 无 serious/critical。
- [ ] 课程卡片出现在课程库，链接正确。
- [ ] 内容事实有来源，术语有解释。
- [ ] 人工三遍评审通过。

### 不做什么

不要为了样板课修改课程契约。如果契约不够用，先改契约和平台，再继续。样板课是契约的第一个真实用户，不是例外。

---

## 11. Phase 6：质量门与 CI

### 目标

把“课程能播放、能独立部署、没有外部依赖、体验达标”变成 CI 能自动拦住的事情。

### 任务

1. Python CI：安装、`ruff check`、`ruff format --check`、`pytest`。
2. Node/HyperFrames CI：
   - Node 22；
   - 安装固定版本；
   - `npx hyperframes browser ensure`；
   - 对每门已发布课程运行 `check`；
   - 课程数量多时用矩阵并行。
3. 构建 CI：`python scripts/build_courses.py --all`。
4. 数据库 CI：
   - 空库跑 `alembic upgrade head`；
   - 进度 API 的匿名会话、upsert、非法 slug/screen；
   - 备份/恢复脚本在临时目录演练。
5. E2E CI：
   - 启动 uvicorn + 临时 SQLite；
   - 站点 → 课程 → 下一屏 → 讲义 → 返回；
   - 独立静态服务器上的课程（不启动 API/DB）；
   - 播放器契约。
6. 外部资源扫描：构建产物 0 个外部资源加载（引用链接除外）。
7. 预算检查：首屏、总大小、单文件。
8. 无障碍：axe + 键盘路径。
9. 链接检查：站点内部链接、课程卡片、sitemap。
10. 安全头：CSP、nosniff、referrer-policy；课程页和站点页分别配置。
11. 文档：CI 命令、失败排查、如何跳过（仅限明确原因）。

### 验收

- [ ] main 分支 CI 全绿。
- [ ] 故意提交一个非法课程，CI 失败并指出字段。
- [ ] 故意加一个 CDN 引用，CI 失败并指出文件。
- [ ] 故意破坏 range 适配层，播放器契约测试失败。
- [ ] 独立部署测试在 CI 中运行（不启动 API/DB）。
- [ ] 空库迁移到 head、进度 API、备份恢复到 CI 中运行。
- [ ] CI 日志能定位到课程 slug、屏幕 id、文件、迁移版本。

### 验证命令

```bash
pytest -q
ruff check .
python scripts/build_courses.py --all
pytest tests/e2e -q
```

---

## 12. Phase 7：发布

### 目标

把站点部署到一个可访问的环境，课程可以播放，缓存和安全头正确，回滚有文档。

### 任务

1. 编写 `Dockerfile`：
   - `python:3.12-slim`；
   - 只装运行时依赖（含 SQLAlchemy、Alembic）；
   - 拷贝 `app/`、`dist/`、`alembic.ini`、`migrations/`；
   - `data/` 用 volume，`DATABASE_URL` 指向 volume；
   - 非 root 用户；
   - `HEALTHCHECK` 调 `/healthz`。
2. 部署流程：先备份 SQLite，再 `alembic upgrade head`，再启动/滚动应用；应用启动不自动迁移。SQLite 默认单 worker；需要多实例时先迁移 Postgres。
3. 编写部署配置（Nginx/Caddy 或平台配置）：
   - `/static/*`、`/courses/*` 的缓存；
   - gzip/brotli；
   - 安全头；
   - 404 行为。
4. 环境变量：`ENV=prod`、`SITE_URL`、`COURSE_BASE_URL`、`DATABASE_URL`、`SESSION_COOKIE_SECURE=1`、`STRICT_CATALOG=1`；单机部署 `VERIFY_COURSE_BUNDLES=1`，分离部署设为 `0`。
5. 部署，跑生产 smoke test：
   - `/`、`/courses`、`/courses/<slug>/`；
   - 开始 → 下一屏；
   - `/healthz`、`/readyz`、`/api/health`；
   - 一次进度 PUT/GET，确认 Cookie 和 DB 写入；
   - 静态资源缓存头。
6. 备份/恢复：
   - 每日 SQLite 备份；
   - 在临时目录恢复一次并查询；
   - 迁移前额外备份。
7. 回滚：
   - 镜像回滚；
   - `dist/` 回滚；
   - 课程单独回滚（静态目录）；
   - 数据库迁移只做向前兼容；破坏性迁移先备份，必要时恢复。
8. 监控/日志：启动日志、错误日志、健康检查、DB schema version。
9. 写 `docs/operations.md`（或 README 的一节）：部署、迁移、备份、恢复、回滚、课程更新、缓存刷新。

### 验收

- [ ] 生产 URL 可访问，`/healthz` 200，`/readyz` 200。
- [ ] 课程页可播放，下一屏正常。
- [ ] 课程包从 CDN/静态服务器加载时也正常。
- [ ] 进度 API 可写可读，Cookie 为 HttpOnly/Secure/SameSite。
- [ ] SQLite 文件在 volume 中，未打进镜像；迁移在部署阶段执行。
- [ ] 备份和恢复在临时环境演练成功。
- [ ] 缓存头符合 9.6。
- [ ] 安全头存在。
- [ ] 课程包在没有 FastAPI/数据库的普通静态服务器上可播放。
- [ ] 回滚步骤演练过一次（含数据库向前兼容说明）。
- [ ] 生产镜像无 Node、Chrome、FFmpeg。

---

## 13. Phase 8：课程规模化

### 目标

让“新增一门课”成为可重复的任务，而不是每次重新理解平台。

### 状态（2026-11-09）

已完成，模板、脚手架、导入和作者文档都落在仓库里：

| 交付 | 位置 | 说明 |
| --- | --- | --- |
| 独立模板包 | `course-template/` | 可直接交给外部作者或其他 AI；`AGENTS.md` 是给 AI 的操作指引，`COURSE-CONTRACT.md` 与 `STYLE.md` 是作者版规范，`composition/` 是可构建的两屏骨架 |
| 脚手架 | `scripts/new_course.py` | 从模板生成 `courses/<slug>/`，替换 slug/title/package name，不覆盖已有目录 |
| 导入 | `scripts/import_course.py`、开发环境 `/import` | 校验 → 临时目录复制 → 构建 → 原子移动到 `courses/<slug>/`；`course_imports` 表记录来源，数据库仍不存课程内容 |
| 收件箱 | `course-inbox/`（不进 Git） | 外部课程文件夹放这里，用 `--inbox` 或页面批量导入 |

原任务里的第 5、6 项（用脚手架从零做第二门课、HyperFrames 升级 playbook）仍按原计划在下一门真实课程里验证；升级流程见[架构设计](architecture.md) 9.8。

### 验收

- [x] `python scripts/new_course.py demo-course --title "演示课程"` 能生成可构建的课程骨架。
- [x] 新课程不需要改 `app/`、`runtime/`、`site` 模板。
- [x] 外部课程文件夹可以通过 `python scripts/import_course.py` 或 `/import` 导入并出现在课程库。
- [x] 课程契约和实际字段/命令一致。
- [x] 新课程任务模板可以直接复制使用。
- [ ] 第二门课通过 Phase 5 的全部验收（等第二门真实课程落地）。

---

## 14. 每门新课的生产模板

这是用户后续“为每一门课单独开一个任务”时使用的模板。课程任务只拥有 `courses/<slug>/`。

### 14.1 输入

开始前必须拿到：

- 课程主题；
- 目标读者（已知道什么、不知道什么）；
- 3 条学完能做到的事；
- 参考材料/事实来源；
- 期望屏数或时长（默认 6–8 屏，2–3 分钟）；
- 是否有音频（默认无）；
- 封面素材（可选）。

缺少事实来源时，不要编造。先把不确定的点列出来问用户。

### 14.2 步骤

1. **读文档。** 读[DESIGN.md](../DESIGN.md)（尤其第 8 节课程 composition 视觉契约）、[课程契约](course-contract.md)、[架构设计](architecture.md)的 5–6 节、本计划第 1 节。
2. **脚手架。** 运行 `python scripts/new_course.py <slug> --title "..."`（等价于从 `course-template/` 复制 `course.json`、`STORYBOARD.md` 和 `composition/`）。
3. **写 storyboard。** 在 `courses/<slug>/STORYBOARD.md` 写：
   - 学习者、学完能、每屏一句话论题；
   - 每屏“看见什么”“动画如何论证”“屏幕文字”“讲义”“时长”；
   - 参考来源。
   没有 storyboard，不进入实现。
4. **改 `course.json`。** 设置 slug/title/summary/outcomes/accent。
5. **逐屏做 scene。** 一次一屏：
   - 先查 HyperFrames registry 有没有可复用的标题/图表/转场，复用时把依赖本地化；
   - 写 scene；
   - 跑 composition 的 `check`；
   - `snapshot` 0%/50%/90%；
   - 修文字、构图、节奏；
   - 再做下一屏。
6. **接根 composition。** 按 storyboard 顺序挂 host，设置数字秒，检查不重叠、根时长覆盖。
7. **构建。** 运行构建，修所有错误；不要手改 `dist/`。
8. **站点验收。** 打开 `/courses/<slug>/`，走完整流程。
9. **独立验收。** 在 `dist/courses/<slug>/` 起静态服务器，再走一遍。
10. **体验验收。** 键盘、讲义、减少动态效果、深链、本地进度、手机横屏、Network。
11. **内容评审。** 三遍：学习者、审稿人、挑刺的人。
12. **提交。** 按 [AGENTS.md](../AGENTS.md#提交规则) 提交：默认只暂存 `courses/<slug>/`；如果改了平台文件，说明原因并拆任务。

### 14.3 文件所有权

| 路径 | 课程任务 |
| --- | --- |
| `courses/<slug>/` | 可以创建/修改 |
| `course-template/` | 只读；需要改时开平台任务 |
| `course-inbox/` | 可以放入待导入的课程文件夹（不进 Git） |
| `app/` | 只读 |
| `runtime/` | 只读 |
| `design/` | 只读 |
| `data/`、`migrations/` | 只读；课程任务不改数据库 |
| `docs/` | 只在课程契约要求时更新课程相关说明；不改架构 |

### 14.4 完成定义

- [ ] `STORYBOARD.md` 完整，事实有来源。
- [ ] `course.json` 通过校验。
- [ ] composition 通过 `check`，每屏快照看过，且每屏符合 [DESIGN.md](../DESIGN.md) 第 8 节（亮色纸面、安全区、字号阶梯、对比度）。
- [ ] 构建通过，产物齐全。
- [ ] 站点课程页完整播放。
- [ ] 独立静态服务器完整播放。
- [ ] 无外部请求、无 console error、无 404。
- [ ] 键盘、讲义、减少动态效果、深链、本地进度正常；同源 API 可用时进度同步，不可用时不影响播放。
- [ ] 首屏/总大小在预算内。
- [ ] axe 无 serious/critical。
- [ ] 课程卡片出现在课程库。
- [ ] 人工三遍评审通过。
- [ ] 已按[提交规则](../AGENTS.md#提交规则)提交，`git status` 干净。

### 14.5 课程任务提示词模板

可以把下面这段直接交给后续 Agent：

```text
你要为 AI Learning 新增一门课程：<课程名>。

先读：
- docs/course-contract.md
- docs/architecture.md 的第 5、6 节
- docs/agent-development-plan.md 的第 1、14 节

课程信息：
- 主题：<...>
- 目标读者：<...>
- 学完能：<...>
- 参考材料：<...>
- 屏数/时长：<...>
- 音频：<有/无>

要求：
1. 先用 `python scripts/new_course.py <slug> --title "..."` 生成脚手架，再写 STORYBOARD.md；不要直接写 HTML。
2. 逐屏实现 composition；每加一屏跑一次 composition 的 check 和 snapshot。
3. 构建后在站点和独立静态服务器上各走一遍。
4. 只修改 courses/<slug>/；需要平台改动时停下来报告。
5. 完成后按课程契约第 8 节逐项验收，并报告未验证项。
```

---

## 15. 平台完成定义

平台 v1.0 完成，需要同时满足：

- [ ] Phase 0–7 的验收全部通过（Phase 8 是上线后的规模化）。
- [ ] 至少一门样板课完整发布。
- [ ] 新增课程不需要改站点代码。
- [ ] 课程包可以在普通静态服务器独立运行。
- [ ] CI 能拦住：非法清单、时间越界、外部资源、播放器契约、独立部署、无障碍严重问题、数据库迁移失败。
- [ ] 生产环境可访问，SQLite 备份/恢复和回滚演练过。
- [ ] 文档与实现一致：README、架构、课程契约、开发方案、运维说明。
- [ ] 没有为了赶进度引入 SPA、MP4 主链路或 CDN 运行时；数据库只用于用户状态，课程内容仍在文件里。

## 16. 停止条件

遇到下面任一情况，停止当前任务，报告并等待决定。不要用临时方案绕过。

1. **播放器契约不成立。** range 不可靠，降级方案也不能在终点稳定停下。
2. **课程需要平台能力。** 例如新的交互、分支、账号进度、定制外壳；这是平台任务，不是课程任务。
3. **事实不确定。** 课程内容缺少来源，或涉及可能错误的数据/结论。
4. **预算严重超标。** 首屏 > 5MB 或整门课 > 30MB，且无法通过压缩/拆分解决。
5. **构建解析器无法处理合法 composition。** 先修解析器/契约，不要手改产物。
6. **许可证不清楚。** 第三方库、字体、音频、GSAP 插件的授权范围不明确。
7. **用户改变产品方向。** 例如要做账号、测验、移动端原生体验；先更新架构，再继续。

## 17. 后续 backlog

不是 v1 范围，但架构应该允许以后加：

- 账号与跨设备进度（基于现有 SQLite schema，后续按需迁移 Postgres）。
- 注册/登录/找回密码/邮箱验证（服务端 session + HttpOnly Cookie + Argon2id）。
- 学习看板（`/api/progress` 已有数据基础）。
- 匿名会话/过期进度清理任务。
- 站内搜索（标题、摘要、标签；后续可加讲义全文）。
- 随堂练习/分支剧情（需要 `interactive` 屏和新的课程契约版本）。
- 语音讲解/TTS（音频 + 字幕 + 讲义）。
- 手机竖屏 composition（每门课两套画布，或响应式 scene）。
- 多语言（`language` 字段 + 站点文案表）。
- 学习路径/系列课程（`series` 字段 + 站点聚合页）。
- 隐私友好的学习事件（本地事件 → 可选上报）。
- 课程封面自动生成、OG 图生成。
- 课程包的社交短片导出（附属产物，不是主链路）。

## 18. 验证命令速查

命令以实现后的脚本名为准；改名时同步更新本节和 README。

| 目的 | 命令 |
| --- | --- |
| 安装 | `pip install -e ".[dev]"` |
| 安装浏览器 | `python -m playwright install chromium` |
| 安装 HyperFrames 工具 | `cd tools && npm install` |
| 数据库迁移 | `alembic upgrade head` |
| 生成迁移 | `alembic revision --autogenerate -m "..."` |
| 开发服务器 | `uvicorn app.main:app --reload` |
| 单元测试 | `pytest -q` |
| 代码检查 | `ruff check .` |
| 同步运行时 | `python scripts/sync_runtime.py` |
| 构建全部课程 | `python scripts/build_courses.py --all` |
| 构建单门课程 | `python scripts/build_courses.py --course <slug>` |
| 只校验不构建 | `python scripts/build_courses.py --check-only` |
| 生成新课程脚手架 | `python scripts/new_course.py <slug> --title "课程标题"` |
| 导入外部课程 | `python scripts/import_course.py <课程文件夹>` |
| 批量导入收件箱 | `python scripts/import_course.py --inbox` |
| 导入前只校验 | `python scripts/import_course.py --dry-run <课程文件夹>` |
| HyperFrames 检查 | 在 `composition/` 下 `npx --yes hyperframes@0.9.19 check` |
| 逐屏快照 | 在 `composition/` 下 `npx --yes hyperframes@0.9.19 snapshot` |
| 独立部署验收 | `python -m http.server 8081 -d dist/courses/<slug>` |
| E2E | `pytest tests/e2e -q` |
| 生产镜像 | `docker build -t ai-learning .` |

## 19. 文档维护

- 实现改变字段、路径、命令时，同步更新[课程契约](course-contract.md)和本计划。
- 架构决策改变时，先更新[架构设计](architecture.md)的决策表，再改代码。
- README 只保留产品理念、体验和高层架构；不要把它变成实现手册。
- 每完成一个阶段，把该阶段的验收项标为完成，并记录遗留问题。
- 不把“以后可能有用”的内容堆进文档；放进 backlog，保持当前文档可执行。
