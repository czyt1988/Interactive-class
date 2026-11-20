# 架构设计：页间课堂

> 版本 v0.1 · 2026-11
> 本文基于 HyperFrames 0.9.19 的 composition、player 和 runtime 能力设计。升级 HyperFrames 前，先读第 9.8 节。

## 一页结论

- 站点是**封面和目录**：FastAPI + Jinja2 服务端渲染，链接到课程，不把课程嵌进 iframe。
- 课程是**独立静态包**：自带播放器运行时、composition、字体和封面，可以单独部署。
- 一门课一个 HyperFrames composition，一屏一个 scene；播放器用 `range-start` / `range-end` 播放当前屏。
- 构建期合并 `course.json` 和 composition 时间；Web 进程只读 `dist/` 里的解析后清单。
- 课程内容用文件，用户/会话/进度用 SQLite；课程包不依赖数据库也能播放。
- 没有 SPA、没有 MP4 主链路、没有运行时 CDN。
- MP4 仍不是主链路；后台设置页可以按需渲染并下载视频，产物留在服务器的 `data/videos/`，不进 Git、不进构建产物。
- 手机竖屏以讲义阅读为主，不承诺完整 16:9 动画体验。

下面的章节解释这些决定、边界和代价。

## 0. 文档说明

这份文档记录的是**架构决策**，不是实现说明。代码还没有开始写；后续实现以本文和[课程契约](course-contract.md)为准。

文中使用三个规范性词：

- **必须**：不满足就不能上线。
- **应该**：默认这样做，偏离时要在代码或文档里说明原因。
- **可以**：可选能力，按课程或阶段决定。

相关文档：

- [课程契约](course-contract.md)：一门课具体长什么样，字段、目录、时间规则和验收清单。
- [Agent 开发方案](agent-development-plan.md)：按阶段执行的任务和完成标准。

---

## 1. 目标与非目标

### 1.1 目标

| 编号 | 目标 | 可验证的信号 |
| --- | --- | --- |
| G1 | 一屏一个概念，学习者手动推进 | 每屏只有一个中心论题；下一屏由学习者触发 |
| G2 | 每门课可以脱离网站独立运行 | 把构建产物放进任意静态服务器，所有屏都能播放 |
| G3 | 新增课程不改站点代码 | 只新增 `courses/<slug>/`，构建后自动出现在课程库 |
| G4 | 清晰、快、可访问 | 文字是真实文本；首帧在常见宽带下 2.5 秒内出现；键盘可操作；有讲义 |
| G5 | 运维简单 | 生产环境只有一个 Python 进程和一个 SQLite 文件；不需要 Node、外部数据库或视频转码 |

### 1.2 非目标

- 不在 v1 做完整账号体系：登录、注册、找回密码、付费、证书和讨论区属于后续阶段。v1 先把 SQLite 数据层、匿名会话和进度 API 做好，让账号可以在此基础上长出来。
- 不把课程内容放进数据库。课程清单和 composition 是文件，用 Git 版本化；数据库只存用户状态。导入的 `course_imports` 表只登记来源（slug、路径、哈希、时间），不改变这条边界。
- 不把 MP4 作为主要分发格式。
- 不在 v1 做随堂测验、分支剧情和复杂交互。
- 不在 v1 为手机竖屏单独制作一套 composition。
- 不做多语言界面。中文优先，字段预留 `language`。
- 不做课程内容管理系统。课程源文件在 Git 里，用代码评审的方式管理。

### 1.3 成功标准

平台完成时，下面六件事同时成立：

1. 新增一门课只需要动 `courses/<slug>/`，站点代码零改动。
2. 构建产物 `dist/courses/<slug>/` 用 `python -m http.server` 打开，封面、每一屏、上一屏/下一屏、讲义都正常。
3. 课程页面在断网（除本地静态服务器外）时没有外部请求。
4. 只用键盘可以完成“开始 → 下一屏 → 暂停 → 看讲义 → 结束”的全流程。
5. CI 能拦住：清单不合法、时间范围越界、外部资源引用、播放器契约回归、数据库迁移失败。
6. SQLite 能从空库迁移到 head，备份可恢复；没有数据库时课程仍然可以完整播放。

---

## 2. 设计约束

1. **浏览器是最终运行环境。** 目标浏览器是最近两个版本的 Chrome、Edge、Safari、Firefox。不支持 IE。
2. **动画画布固定为 1920×1080、30fps。** 课程 composition 按这个尺寸设计；播放器负责等比缩放。
3. **遵守 HyperFrames composition 契约。** 时间轴必须是暂停的、可 seek 的；所有可见状态是时间的函数；运行时不发起网络请求、不使用真实时钟和未播种随机数。
4. **后台使用 FastAPI。** 站点页面、目录 API 和静态文件服务都在 Python 侧完成。
5. **课程产物必须是静态文件。** 不依赖 FastAPI、数据库或任何运行时 API。
6. **中文优先。** 字体、断行、标点和排版按中文阅读习惯设计；代码标识符和 JSON 字段用英文。
7. **课程内容是可信内容。** 课程由项目维护者/Agent 编写并经过构建校验，不是用户上传内容；因此可以接受比 UGC 平台更宽松的 CSP。
8. **桌面和横屏优先。** 手机竖屏不以“完整动画体验”为目标，以“可读的讲义模式”为目标。
9. **SQLite 是应用数据库。** 单文件、本地、WAL 模式；存用户、会话和进度。课程包不依赖它；数据库迁移用 Alembic。出现多实例写入或后台任务竞争时，再评估 Postgres。

---

## 3. 关键决策

| ID | 决策 | 为什么 | 代价 | 什么时候重新考虑 |
| --- | --- | --- | --- | --- |
| D1 | 课程是独立静态包；站点只做封面、目录和引导；站点**链接**课程，不把课程嵌进 iframe | 课程可以单独部署、单独打开；站点改版不影响课程；两边的故障域分开 | 设计令牌需要在站点和课程之间同步；无法从站点直接读取课程内部状态 | 如果以后需要站内无缝切换、统一账号进度或课程内嵌预览 |
| D2 | 一门课一个 HyperFrames 工程；一屏一个 scene；播放顺序和时间由根 composition 决定 | 共享字体和素材；只创建一个播放器实例；HyperFrames 原生支持 scene 时间轴；课程包结构简单 | 整个课程是一个长文档；单个 scene 的故障可能影响整门课；超长课程需要拆分 | 单门课超过 15 屏、素材超过 50MB，或需要每屏独立的画布尺寸 |
| D3 | 使用官方 `<hyperframes-player>` 和官方 runtime，不自己实现渲染器；运行时文件随课程打包 | 官方播放器已经处理 iframe、runtime 注入、媒体同步、资源就绪、缩放和场景挂载；自己重写会持续追版本 | 依赖 player 的 `range-start`/`range-end` 和事件语义；这些接口不是稳定的公共 API | player 升级导致契约测试失败，或 range 行为不可用 |
| D4 | 站点用 FastAPI + Jinja2 服务端渲染；课程外壳用原生 ES module，不上 SPA 框架，不上打包器 | 站点只有封面、目录和引导，不需要客户端状态；服务端渲染对 SEO、首屏和运维都更简单；课程外壳的复杂度集中在一个小控制器里 | 页面交互不如 SPA 丰富；以后做学习面板可能要加 islands 或独立子应用 | 出现账号、学习看板、站内搜索等需要大量客户端状态的页面 |
| D5 | 课程内容用文件；用户、会话和进度用 SQLite；不把课程内容放进数据库 | 课程内容适合 Git 版本化和静态构建；用户状态是可变数据，需要事务和迁移；SQLite 单文件、零服务、足够支撑早期用户和登录 | 多一个迁移/备份责任；SQLite 是单写者，写入并发有限 | 多实例部署、后台任务竞争或写入量明显上升时，评估 Postgres；课程需要在线编辑时，再考虑 CMS |
| D6 | 构建期解析 composition 时间并生成课程清单；运行期只读解析后的清单 | 错误在构建时暴露；浏览器不做 HTML 解析；站点和课程使用同一份解析结果 | 多一个构建步骤；课程创作后要重新构建才能看到站点更新 | 需要边写边看的实时预览（可以加 watch，但不改变架构） |
| D7 | 产品只输出网页，不输出 MP4 | 文字清晰、体积小、可检索、可交互、可访问；改一句话不需要重新编码 | 受浏览器性能、自动播放策略、移动端缩放限制；不能像视频一样离线转发 | 需要做社交媒体短片或归档时，作为附属导出，不改变主形态 |
| D8 | 课程运行时完全自包含，不引用 CDN | 独立部署、离线可用、版本可复现、不会被第三方 CDN 故障影响 | 每个课程包多几百 KB 运行时；升级要同步所有课程 | 永不为了核心运行时引入 CDN；以后视频/大图可以走媒体 CDN |
| D9 | 桌面/横屏优先；手机竖屏提供讲义阅读模式，不承诺完整动画体验 | 1920×1080 的动画在 390px 宽的竖屏上会把正文缩到不可读；与其做假移动端，不如提供诚实的替代 | 移动端学习体验受限 | 有明确的移动端学习需求，且愿意为课程制作竖屏 composition |
| D10 | 站点与默认课程统一亮色纸面；课程外壳不再使用深色舞台；暂不提供明暗切换 | 课程里的动画本来就是纸色场景，深色外壳只在封面、控制条和讲义之间制造割裂；统一后站点到课程是一次连续的阅读。明暗切换先不做，等有真实需求再加 | 课程页少了“放映室”的沉浸感；以后做深色模式要成对维护两套表层令牌 | 用户明确要求深色学习模式 |
| D11 | 长视频课程以旁白为时钟：一个 S 一页、旁白音频驱动时间、底部旁白条烧进画面、`playback: "continuous"` 整条根时间轴当视频播 | 用户要把课程直接导出成视频；按页拆分会把连续叙事切成碎片。旁白同时是字幕和时长依据，导出 MP4 时字幕与声音都在画面里 | 时间由生成脚本决定，作者不能手改；每页要比短课长（30–80 秒），一页讲完一个 S | 大纲改成短课拆分，或播放器/渲染器不再支持连续播放 |
| D12 | 长视频课程统一浅色纸面；四幕只换强调色，「黑屋」等比喻用暖灯、墨色剪影和牛皮纸笔记本画在纸面上（仅 `playback: "continuous"` + `audio: true` 的课程） | 用户明确要求整门课不要深色背景：上一版深墨/黑屋页与前后浅色页割裂。叙事靠道具、光影和运动表达，不靠页面底色；D12 取代原「纸面/深墨/黑屋三种底色」方案 | 少了一种用底色切换幕的强标记，需要靠编号、强调色和道具维持节奏 | 用户要求恢复深色叙事场景，或大纲改版 |
| D13 | 旁白课程的播放器提供暂停、字幕开关、配音开关，偏好存 localStorage | 用户要求能停、能取消字幕、能取消配音。字幕开关隐藏画面底部旁白条，不打断时间轴；配音开关静音但不暂停时间轴。根 composition 通过 HyperFrames 的父级 control 消息接收字幕偏好 | 多两个控制条按钮和一条消息通道；偏好只在本机保存 | 播放器契约变化，或需要账号级偏好同步 |
| D14 | MP4 不是主链路，但后台设置页可以在服务器上按需渲染课程视频：从 `dist/courses/<slug>/composition/` 复制到临时工作目录，调用固定版本 HyperFrames CLI，输出到 `data/videos/`，同一时间只跑一个任务 | 用户不想把视频提交进 Git，也不希望部署产物内置视频；按需生成让视频只存在于服务器数据目录，可重建、可删除。渲染源用构建产物，和网页播放的是同一份 composition | 生产机需要 Node、Chromium、FFmpeg 等创作期依赖；一次渲染耗时接近视频时长；后台写接口需要访问控制（`ADMIN_TOKEN`） | 视频成为主要分发形态，或需要多机并发渲染（改为独立渲染服务/任务队列） |
| D15 | 课程模板抽成仓库根的独立包 `course-template/`：两屏可构建骨架 + 给 AI 的 `AGENTS.md` + 作者版 `COURSE-CONTRACT.md`/`STYLE.md`；平台内用 `scripts/new_course.py` 复制它生成脚手架 | 多人协作时，外部作者不需要克隆平台仓库；把整个文件夹交给 AI 当工作目录，规则自包含。模板移出 `courses/` 后不会被构建或课程扫描误当成课程，也让「平台代码」和「课程结构」的边界更清楚 | 模板文档与平台课程契约有重复，需要靠测试和同一任务内的同步更新防漂移；模板里的字体/GSAP 仍由 `sync_runtime.py` 统一生成 | 出现第二套模板（例如长视频课专用）且无法用同一骨架覆盖时 |
| D16 | 外部课程通过导入流水线进入平台：`scripts/import_course.py` 或开发环境 `/import` 页面校验 → 在隐藏 staging 目录构建 → 原子替换 `courses/<slug>/` 与 `dist/courses/<slug>/`；成功后只在 SQLite 的 `course_imports` 表登记来源 | 用户希望「把生成好的文件夹直接放进软件配置的目录，选中导入」就能加入课程库。导入把校验和构建放在落盘之前，失败不会留下半个课程；数据库登记来源方便多人协作时追溯，但课程内容仍然只存在于文件和 `dist/`，不破坏 D5 | 导入需要 `scripts/` 作者工具（生产镜像没有），因此页面默认只在 dev 开放；来源路径是本地信息，换机器后只能作为历史记录 | 需要多人在线提交课程（那时应做上传/审核后台，而不是本地目录导入） |
| D17 | 课程播放页全视口：舞台区占满控制条以上高度，16:9 画布在可用区域等比最大化，控制条在画布外通栏；当前屏进度可拖动，并提供「跳到最后」（`End`） | 用户需要快速看到最终画面，也要像视频一样拖动定位。16:9 画布嵌在阅读列里太小，两侧留白浪费空间；控制条与画布分离后，画布可以吃满屏幕高度 | 控制条不再与画布同宽，16:9 两侧出现纸色留边；末帧成为必须可读的验收项（拖动、跳到最后都会直接停在那里）；封面、完成页与播放页的高度策略不同 | 出现逐帧编辑、分支互动，或需要移动端竖屏专门版式时重新考虑 |
| D18 | 本机双击启动器自带环境准备：`scripts\env.cmd` 找系统 Python，`scripts\bootstrap.py` 创建 `.venv`、`pip install -e ".[dev]"`、`npm install` + `sync_runtime.py --skip-fonts` 同步播放器资源、构建 `dist/`、`alembic upgrade head`，然后交给 `scripts/launcher.py` 起服务 | 用户是新手，第一次双击 `start.cmd` 只看到「没有找到虚拟环境」，照着 README 逐条敲命令不现实。把准备做成幂等的检查，缺什么补什么，双击一个文件就能从空仓库跑到可访问的站点；准备逻辑放在 Python 里可以测试，批处理只做引导 | 启动器第一次接触网络和 Node.js（之后不需要）；仓库多一层需要随依赖、构建步骤同步维护的准备逻辑；`--skip-fonts` 意味着字体子集仍由作者改动后手动重建 | 出现安装包 / 桌面 app 形态，或需要完全离线的一次性分发时，把准备逻辑换成安装器 |
| D19 | 并行开发任务各自在 `.worktree/` 下的独立 git 工作树里进行，完成后合并回 `main`；`scripts/worktree.py` 负责创建/查看/合并/删除工作树，并把主工作树的 `.venv`、`tools/node_modules`、`tools/ffmpeg`、`courses/*/narration/cache/` 以目录联接共享，把 `runtime/vendor` 与 `.env` 复制进工作树（`link` 负责刷新副本）；根 `conftest.py` 与构建脚本把仓库根放进 `sys.path`，避免共享虚拟环境的 editable install 把导入劫持到主工作树；删除前校验未提交改动，合并冲突自动回滚 | 多个 Agent 会话并行开发时，共用工作区会互相污染（切分支、暂存区、未提交改动）；共享已装依赖与创作工具让新工作树几秒内可跑测试、构建课程，不重复联网安装；复制写侧生成物保证工作树里重跑同步脚本或改本地配置不影响主工作树；删除/合并的安全检查避免误丢未提交改动或把主工作树留在冲突态 | 依赖目录共享意味着在工作树里 `pip install` / `npm install` / 重做旁白会写主工作树或共享缓存，必须串行处理（启动器对重装会直接拒绝）；`dist/`、`data/` 与主工作树各自独立，需要各自构建与迁移；多一层需要在任务收尾时合并与清理的流程 | 需要每个任务独立依赖版本、跨机器分发生成物，或迁移到 CI/容器化并行时 |
| D20 | 课程水印是站点部署配置，不是课程内容：配置存在 SQLite 的 `course_watermarks` 表（`data/` 已 gitignore，不进 Git、不写 `courses/<slug>/course.json`），构建时由 `scripts/build_courses.py` 读库并把水印层写进构建产物的 composition 入口；后台 `/admin/courses/<slug>/watermark` 编辑数据库行并同步重新构建 | 水印文字通常是作者/公司/部门等身份信息，用户明确要求它不被 Git 跟踪，历史里已有的旧水印也要清理；数据库属于站点、`data/` 不进版本库，正好承载这类「这台部署给谁看」的配置。构建产物仍把水印烘进 composition，所以独立部署的课程包自带水印、运行时不依赖数据库，D5 的「课程包不依赖数据库」仍然成立。写进 composition 而不是页面外壳，是因为网页播放器和 MP4 渲染器消费同一份 composition | 构建（含 `build_courses.py` 命令行）需要能访问站点数据库；库或表缺失时构建按「未配置水印」继续，所以新克隆的仓库默认没有水印。后台保存仍需要 `courses/` 与 `scripts/` 才能重建，生产镜像只装 `app/` 和 `dist/` 时配置页只读。换库/迁移数据会丢水印，需要重新配置；改水印后旧视频会因内容哈希变化被标记为过期 | 水印需要按观看者动态生成（用户名、时间戳）时，改为运行期渲染或图片服务，并重新评估权限与缓存 |
| D21 | 片头/片尾是站点共享模板库 `clips/<id>/` 里的一屏：构建时由 `scripts/build_courses.py` 渲染模板（`{{course.title}}` 等占位符带入每门课的信息）并插入构建产物的 composition，片头在最前、片尾在最后，原有 host 与 `<audio>` 的 `data-start` 整体后移；选择存在 SQLite 的 `course_clips` 表，后台 `/admin/courses/<slug>/clips` 选择并同步重建 | 用户要在每门课开始/结尾讲清课程主题、开源项目地址和制作方式，视频导出也要带。做成 composition 的一屏，网页播放与 MP4 消费同一份，独立部署的课程包自带这些屏、不需要数据库，D1/D5 仍然成立；模板全站共用、占位符带入课程信息，避免每门课复制一份；选择存站点库，课程源文件不含部署选择 | 片头/片尾是静默的（不配旁白、音乐），需要声音时要扩展 `clip.json` 与渲染；插入会让正课时间整体后移，`contentHash` 必须把选择和渲染后的模板算进去，否则视频过期判断会漏；模板在构建期校验，无效模板让构建失败而不是静默跳过 | 片头需要旁白/音乐、按观看者动态生成，或模板多到需要独立的模板管理界面时 |

### 3.1 三个需要展开的决定

**为什么站点不把课程嵌进 iframe。**
嵌进去看起来更“平台化”，但会带来双滚动条、焦点管理、全屏、移动端高度、课程和站点样式互相污染、课程无法独立部署等问题。链接出去之后，课程是一个完整的页面，站点是一个目录；两边的边界清晰，课程也可以被单独分享。站点的课程卡片承担“封面和引导”的职责，进入课程后由课程自己负责体验。

**为什么一门课只用一个 composition。**
一屏一个独立 HTML 当然更隔离，但课程需要共享字体、配色、素材和播放器，而且学习者希望“下一屏”是瞬时的，不是重新加载一个页面。HyperFrames 的 scene 机制本来就是为这种时间轴上的分段设计的：每个 scene 有独立的时间轴，根 composition 负责把它们挂在时间线上。播放器只加载一次，切屏只是 seek 到新的 range。代价是单门课不能无限增长；第 6.7 节给了拆分阈值。

**为什么用 SQLite，而不是把课程也塞进数据库。**
课程内容是“发布物”：它应该可评审、可回滚、可独立部署，Git 和静态构建比数据库更合适。用户、会话、进度是“运行态数据”：它会变化、需要事务、需要和登录关联，放进数据库更合适。SQLite 是单文件、零服务、支持事务和 WAL，对这个规模足够；以后真要上多实例，SQLAlchemy 和 Alembic 也让迁移到 Postgres 不必重写业务层。课程包不依赖数据库，所以数据库坏了不会影响已有课程播放。

---

## 4. 系统上下文

```text
┌─────────────┐        ┌──────────────────────────────────────────────┐
│ 课程作者     │        │ 构建流水线（Python，CI 或本地）                │
│ / Agent     │───────▶│ 校验 course.json + composition               │
└─────────────┘        │ 解析每屏时间 → 渲染课程页面 → 拷贝运行时       │
                       └──────────────────┬───────────────────────────┘
                                          │ 写入
                                          ▼
                       ┌──────────────────────────────────────────────┐
                       │ dist/courses/<slug>/                         │
                       │ index.html · course.json · composition/      │
                       │ runtime/ · cover.webp · LICENSES/            │
                       └──────────────────┬───────────────────────────┘
                                          │ 静态文件
                                          ▼
┌─────────────┐        ┌──────────────────────────────┐        ┌─────────────┐
│ 学习者       │───────▶│ FastAPI + Jinja2              │───────▶│ 浏览器       │
│             │        │ / · /courses · /api/*         │        │             │
└─────────────┘        │ 读 dist/ 生成目录             │        │ 课程页面     │
                       │ 读写 SQLite                   │        │  ├─ 封面     │
                       └──────────┬───────────────────┘        │  ├─ 播放器   │
                                  │ SQLAlchemy                │  └─ 讲义     │
                                  ▼                           └──────┬──────┘
                       ┌──────────────────────────────┐               │ iframe
                       │ SQLite (data/app.db)          │               ▼
                       │ users · sessions · progress   │        ┌─────────────┐
                       └──────────────────────────────┘        │ composition │
                                                               │ + runtime   │
                                                               └─────────────┘
```

浏览器和 FastAPI 之间还有一条可选的同源进度同步：课程页可以调用 `/api/progress/*`，也可以完全不调用。课程包在没有这条链路时仍能播放，进度退回 `localStorage`。分离部署（课程在 CDN、API 在站点）默认关闭同步，避免 CORS 和第三方 cookie 的复杂度。

三条关键流向：

1. **作者 → 课程源 → 构建产物。** 课程源在 `courses/<slug>/`，构建产物在 `dist/courses/<slug>/`。构建是唯一的打包入口。
2. **学习者 → 站点 → 课程。** 站点页面由 FastAPI 服务端渲染；课程卡片直接链接到静态课程页。课程页不依赖站点 API；同源进度同步是可选增强。
3. **课程页 → player → composition。** 浏览器加载课程页，player 创建 iframe，runtime 注入并驱动 composition。整个过程在课程包内部完成。
4. **浏览器 ↔ FastAPI → SQLite（可选）。** 课程页在站点同源部署时可以上报/读取进度；FastAPI 用 SQLAlchemy 读写 SQLite。没有这条链路时，课程页使用本地进度。

信任边界：课程内容是项目内可信内容；站点接收的学习进度输入有限且经过校验；课程包本身不接收用户输入、不依赖登录态。数据库属于站点，不属于课程包。

---

## 5. 运行时架构

### 5.1 四层职责

| 层 | 载体 | 负责 | 不负责 |
| --- | --- | --- | --- |
| 课程页面 | `index.html`（构建生成） | 封面、章节大纲、播放器容器、控制条、目录、讲义、完成页、SEO | 动画本身、scene 时间轴 |
| 课程外壳 | `runtime/course-deck.js` + CSS | 状态机、切屏、目录跳屏、进度、键盘/触摸、全屏、深链、本地进度、可选同源进度同步 | 解析 composition、直接操作 scene |
| 播放器 | `<hyperframes-player>` | iframe、runtime 注入、媒体同步、缩放、资源就绪、播放/暂停/seek | 课程导航、封面、目录、讲义 |
| composition | `composition/index.html` + scenes | 每一屏的视觉、文字、动画、节奏 | 导航、进度、站点信息 |

这四层里，课程外壳是唯一需要写业务逻辑的地方；它的复杂度应该被控制在一个可测试的小控制器里。

### 5.2 播放器契约

课程页面里的播放器元素大致长这样（示例省略了 `src`，它由课程外壳在用户点击“开始”后设置）：

```html
<hyperframes-player
  id="hf-player"
  runtime-src="./runtime/vendor/hyperframe.runtime.iife.js"
  width="1920"
  height="1080"
  poster="./cover.webp"
  muted
  disable-click-to-play
></hyperframes-player>
```

用到的属性：

| 属性 | 用途 |
| --- | --- |
| `src` | 指向课程根 composition；建议在用户点击“开始”后才设置，避免封面阶段就加载 |
| `runtime-src` | 指向课程包内的 runtime；**必须**设置，否则 player 会从 CDN 加载 |
| `width` / `height` | 首帧布局尺寸，避免加载时跳动 |
| `poster` | 加载期间的封面；只有 `cover` 存在时设置，避免 404 |
| `muted` | 初始静音；有音频的课程在用户点击开始后再取消静音 |
| `range-start` / `range-end` | 当前屏在根时间轴上的绝对秒数 |
| `disable-click-to-play` | 禁用 player 自己的点击播放，交给课程外壳处理，避免双重触发 |
| `interactive` | 只有需要点击/输入的课程才设置；纯动画课程不设置 |

用到的事件：

| 事件 | 用途 |
| --- | --- |
| `ready` | 时间轴已就绪，拿到总时长 |
| `durationchange` | 总时长变化 |
| `painted` | 首帧已绘制，可以撤掉加载遮罩 |
| `ended` | 当前 range 播放结束；课程外壳据此显示“下一屏”或自动推进 |
| `timeupdate` | 更新屏内进度 |
| `play` / `pause` | 同步控制条状态 |
| `error` | 进入降级页面 |
| `rangeclamped` | range 越界，记录并修正配置 |

用到的属性和方法：`currentTime`、`duration`、`paused`、`ready`、`painted`、`play()`、`pause()`、`seek()`。

**约束：** 课程外壳只能使用上面这些公开属性和事件，不能读取 player 的 shadow DOM，不能依赖内部类名或内部状态。

### 5.3 一次“开始”和一次“下一屏”

开始：

1. 学习者点击封面上的“开始学习”。这是一个用户手势，用来解锁音频。
2. 课程外壳隐藏封面，显示舞台和加载遮罩。
3. 设置 `src`（`runtime-src` 和 `poster` 已经在页面里）。从这一刻开始才加载 composition。
4. player 创建 iframe，注入 runtime。runtime 读取根 composition，挂载 scene，等待首帧资源。
5. player 依次触发 `ready` 和 `painted`。外壳记录总时长，撤掉遮罩。
6. 外壳设置当前屏的 `range-start` / `range-end`，调用 `play()`。
7. runtime 从 range 起点开始播放；`timeupdate` 驱动进度条。
8. 到达 range 终点时 runtime 暂停并触发 `ended`。外壳显示“下一屏”；如果该屏 `autoAdvance` 为真，则在短暂停留后自动推进。

下一屏：

1. 外壳调用 `pause()`，落下转场遮罩。
2. 更新 `range-start` / `range-end`。
3. 调用 `seek(start)`，再调用 `play()`。
4. 等第一个进入新 range 的 `timeupdate`，或 180–240ms 的转场定时器（最长 600ms）后撤掉遮罩。不要依赖 `painted`：它通常只在首帧/资源就绪时触发一次。
5. 更新章节标题、进度、URL hash、本地进度。

上一屏同理，只是目标 range 不同。

目录跳屏：

1. 控制条上的「目录」按钮（快捷键 `O`）打开右侧抽屉，按顺序列出每屏的序号、标题和起始时间；当前屏条目标 `aria-current="step"`。
2. 点任意一屏：外壳先关抽屉，再按「下一屏」同样的方式 `pause()` → 更新 `range-start` / `range-end` → `seek(start)` → `play()`，并更新当前屏标题、URL hash 和本地进度。
3. 深链打开和 `playback: "continuous"` 的课程同样适用；跳屏只是换 range，不重建 player，也不重新加载 composition。

逐屏 seek 和「跳到最后」：

1. 拖动当前屏进度条：外壳先 `pause()`，记住松手后是否继续播放，并离开 `ended` 状态；`input` 事件按 `screen.start + 屏内秒数` 调用 `seek()`。暂停态调用 `seek()` 也会把 composition 画到目标时间，画面跟着滑杆走。
2. 松手：如果拖动前在播放就 `play()`；拖到本屏末尾（距终点 0.1 秒以内）等同「跳到最后」。
3. 「跳到最后」或 `End`：`pause()`，`seek()` 到本屏 `range-end` 之前约 20ms（避开播放器更早触发 `ended` 的边界），把本屏标记为已讲完，课程总进度推进到本屏末尾。
4. 短课停在当前屏最后一帧，等学习者点「下一屏」；`playback: "continuous"` 的旁白课程不离开整条时间轴，只是暂停在 scene 末尾，继续播放会自然进入下一屏。
5. 末帧因此是必须可读的帧：拖到末尾、跳到最后、自然播完，停下的都是同一帧。作者不能把关键信息只放在动画中途。

### 5.4 状态机

```text
cover ──start──▶ loading ──ready+painted──▶ ready ──play──▶ playing
                    │                         ▲               │
                    │ error                   │               ├─pause──▶ paused
                    ▼                         │               │            │
                  error ◀─────────────────────┘               │◀──play─────┘
                                                              │
                                                         range end
                                                              ▼
                                                           ended ──next──▶ loading
                                                              │
                                                          last screen
                                                              ▼
                                                           complete
```

| 状态 | UI | 允许的动作 |
| --- | --- | --- |
| `cover` | 封面、目标、大纲、开始按钮 | 开始；继续上次（本地或同源服务端进度） |
| `loading` | 封面淡出、舞台遮罩、进度提示 | 取消/返回封面 |
| `ready` | 舞台、控制条、第一帧 | 播放；上一屏/下一屏 |
| `playing` | 舞台、暂停按钮、进度 | 暂停；上一屏/下一屏；拖动当前屏进度；跳到最后（`End`）；全屏；目录；讲义 |
| `paused` | 舞台、播放按钮 | 播放；上一屏/下一屏；拖动当前屏进度；跳到最后（`End`）；重播；目录 |
| `ended` | 舞台停在最后一帧、强调“下一屏” | 下一屏；重播；目录；讲义；拖动当前屏进度（拖回中间会离开末帧）；跳到最后（`End`） |
| `complete` | 课程回顾、返回课程库 | 重看；返回 |
| `error` | 错误说明、封面/大纲、重试 | 重试；返回封面 |

状态迁移必须由显式方法完成（`start()`、`goTo()`、`next()`、`prev()`、`toggle()`、`finish()`），不要在事件回调里直接改 UI。

### 5.5 播放器适配层

`course-deck.js` 不直接散落 player 调用，而是通过一个薄适配层：

```text
createPlayerAdapter(el) -> {
  load({ src, runtimeSrc, poster }),
  setRange(start, end),
  play(), pause(), seek(seconds),
  get time(), get duration(), get ready(), get painted(),
  on(event, handler), destroy()
}
```

适配层负责三件事：

1. 把 `range-start` / `range-end` 的读写和 `seek` 的顺序封装起来。两个属性分开设置时会产生中间态（新的 start 可能大于旧的 end），适配层要先设置 end 再设置 start，或先清空再一起设置，并监听 `rangeclamped` 判断是否被截断。
2. 如果 player 的 range 行为在某个版本里不可靠，在这里降级为“seek 到起点 + 监听时间 + 到点暂停”，并合成一个 `ended` 事件。
3. 把所有 player 事件转换成课程外壳能理解的稳定事件，隔离版本差异。

这不是过度设计。player 的 range 接口不是文档里最稳定的公共 API，升级时必须靠这一层做兼容，而不是改遍整个外壳。

### 5.6 加载、转场和失败

- **加载遮罩**：封面到第一屏之间必须有；从第二屏开始，切屏用 180–240ms 的淡入淡出遮罩，避免看到 seek 过程中的中间帧。
- **撤遮罩时机**：第一屏优先等 `painted`；后续切屏等第一个进入新 range 的 `timeupdate` 或 180–240ms 定时器，最长 600ms。`painted` 通常只触发一次，不要拿它当每次切屏的信号。
- **失败降级**：player 报错或 10 秒内没有 `ready`，显示错误页，保留封面、课程大纲和讲义入口。不要留一个空白 iframe。
- **重试**：销毁并重建 player 元素，重新设置 `src`。不要复用已经进入错误状态的 iframe。
- **日志**：控制台输出课程 slug、屏 id、player 版本；不上报个人信息。

### 5.7 音频策略

- 没有音频的课程，player 始终 `muted`，不显示音量按钮。
- 有音频的课程，`audio: true`。封面上的“开始学习”是用户手势，可以在此时取消静音；如果浏览器仍然拦截，回退为静音播放，并显示“开启声音”按钮。
- 不从页面加载时自动播放带声音的动画。
- 有语音的屏幕必须有讲义文本；讲义不是可选装饰，是无障碍替代。
- 音频文件必须本地化，和课程一起分发。

### 5.8 深链、历史和进度

- 屏幕深链使用 hash：`/courses/<slug>/#s=<screen-id>`。hash 不参与服务端路由，静态部署也能用。
- 手动切屏 `pushState`，自动推进 `replaceState`，保证浏览器后退键符合预期。
- 加载时如果有合法 hash，直接进入该屏，但**不自动播放**：显示该屏第一帧和播放按钮，等用户手势。这样既支持分享，也不违反自动播放策略。
- 本地进度存在 `localStorage`，键为 `ai-learning:progress:<slug>`，值为 `{ screenId, updatedAt }`。封面显示“继续上次”，如果记录无效则忽略。
- 如果构建时注入了同源 `progressEndpoint` 和 `progressOrigin`，课程外壳还可以把进度同步到 SQLite：加载时 GET 一次，切屏/完成时 PUT（去抖、失败静默）。服务端进度比本地新时，才用它做“继续上次”；本地进度永远先写，服务端失败不影响播放。
- 构建同时注入 `progressOrigin`。只有 `location.origin === progressOrigin` 时才发起同步；课程包被复制到别的域名/端口时自动跳过，不会产生 404 或跨域请求。
- 服务端进度挂在匿名用户上；登录后可以升级成账号进度，实现跨设备。跨设备同步不是 v1 的承诺，但数据模型从第一天就按这个方向设计。
- 分离部署（课程在 CDN、API 在站点）默认不注入 `progressEndpoint`，避免 CORS 和第三方 cookie；课程仍然有本地进度。

### 5.9 减少动态效果

`prefers-reduced-motion: reduce` 时：

- 不自动播放动画；显示封面或当前屏的静态帧。
- 提供“仍要播放动画”的显式按钮。
- 页面级过渡（淡入、位移）关闭或缩短到 0。
- 讲义默认展开，保证信息可达。

### 5.10 全屏、键盘和触摸

- 全屏作用于“舞台 + 控制条”的容器，不只作用于 player；否则全屏后没有控制条。
- 键盘：`←` / `→` 上一屏/下一屏，`Space` 播放/暂停，`End` 跳到本屏结尾，`F` 全屏，`T` 讲义，`O` 目录，`Esc` 退出全屏或关闭目录/讲义。焦点在输入框内时不拦截（当前屏进度条是原生 range，方向键和 `End` 交给控件自己处理）。
- 触摸：舞台左右滑动切屏，阈值 48px；控制条区域不触发滑动。滑动过程中不切换，松手后判断。
- 所有按钮有可见的 `:focus-visible` 样式；图标按钮有 `aria-label`。

### 5.11 为什么不用官方 slideshow 组件

HyperFrames 自带 `hyperframes-slideshow`，已经实现了 slide 导航、演讲者模式、备注和分支。它证明“根 composition + scene 时间”的路线是可行的，但它是为演示场景设计的：

- 它有演讲者窗口、Present 按钮、观众模式等课程不需要的界面。
- 它的清单格式和交互模型不是我们的课程模型。
- 我们需要封面、目标、章节大纲、讲义、完成页、课程级进度和独立部署的样式。
- 它的内部实现使用了 `Date.now()` 和定时器，不适合作为我们课程外壳的依赖。

所以课程外壳自己写，只复用 `<hyperframes-player>`。这是一个有意识的取舍：导航逻辑很小，产品界面和课程模型必须自己掌控。

---

## 6. 课程包

### 6.1 源与产物

课程有两个源，构建时合并：

| 源 | 回答的问题 | 权威性 |
| --- | --- | --- |
| `course.json` | 这门课叫什么、讲什么、每屏的标题和讲义是什么 | 编辑信息的唯一来源 |
| `composition/index.html` | 每屏在时间轴上的顺序、起点和长度 | 播放时间和顺序的唯一来源 |

构建产物是第三个东西：**解析后的课程清单**。它把两者合并，补上 `start`、`duration`、`index`、总时长和构建版本，供课程页和 API 读取。

这样做的原因：如果让作者在 `course.json` 里手写时间，时间和 composition 一定会漂移；如果让浏览器运行时去解析 HTML，错误会推迟到用户打开页面才暴露。构建期合并是唯一能同时避免这两个问题的位置。

### 6.2 源目录

```text
courses/<slug>/
├─ course.json                 # 编辑信息
├─ STORYBOARD.md               # 课程脚本，不进入产物
├─ cover.webp                  # 可选，1600×900
└─ composition/                # HyperFrames 工程根
   ├─ index.html               # 根 composition，挂载所有 scene
   ├─ hyperframes.json
   ├─ package.json
   ├─ compositions/
   │  ├─ 01-hook.html
   │  ├─ 02-tokens.html
   │  └─ ...
   └─ assets/
      ├─ course.css
      ├─ fonts/
      ├─ images/
      ├─ audio/
      └─ vendor/
         └─ gsap.min.js
```

`composition/` 本身就是一个合法的 HyperFrames 项目，可以在里面运行 `npx hyperframes preview`、`check`、`snapshot`；只想快速看播放效果时可以用 `npx hyperframes play`。课程任务的主要工作发生在这里。

新课程脚手架从仓库根的独立模板包 `course-template/` 复制（见 D15）；外部作者拿到的也是这个文件夹，生成完成后按 D16 导入。模板不在 `courses/` 下，构建和课程扫描都不会碰到它。

### 6.3 构建产物

```text
dist/courses/<slug>/
├─ index.html                  # 构建生成的课程页（封面 + 播放器外壳 + 内联清单）
├─ course.json                 # 解析后的清单
├─ cover.webp                  # 可选
├─ composition/
│  ├─ index.html
│  ├─ compositions/
│  └─ assets/
├─ runtime/
│  ├─ course-deck.js
│  ├─ course-deck.css
│  ├─ tokens.css
│  ├─ vendor/
│  │  ├─ hyperframes-player.global.js
│  │  ├─ hyperframe.runtime.iife.js
│  │  └─ LICENSES/
│  └─ VERSION.json
└─ LICENSES/
```

不进入产物的东西：`node_modules/`、`.hyperframes/`、`renders/`、`*.mp4`、`STORYBOARD.md`、`package.json`、`hyperframes.json`、`shell.html.j2`、开发脚本、源地图、编辑器配置。产物只保留运行所需文件，避免把课程包变成垃圾桶。后台按需生成的视频同样不进产物，见 7.11。

### 6.4 一屏一个 scene 的约定

根 composition 里，每个屏幕是一个 scene host：

```html
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
```

规则：

- `data-screen-id` 是课程清单里的屏幕 id，必须唯一。
- `id`、`data-composition-id` 和 scene 文件里的时间轴 key 必须一致，统一用 `s-<screen-id>`。
- `data-start`、`data-duration` 必须是数字秒，不允许表达式。课程根是构建解析的对象，保持简单。
- 屏幕按 `data-start` 升序排列，不能重叠。
- 根 `data-duration` 必须覆盖最后一屏的结束时间。
- scene host 的 `data-duration` 是这一屏的**教学节拍**，包含入场、讲解和结尾停留，不是“动画文件多长”。

更完整的字段、写法和校验规则见[课程契约](course-contract.md)。

### 6.5 独立性保证

一个课程包要满足下面所有条件，才算“可以脱离网站单独打开”：

1. 所有资源引用都是相对路径，没有前导 `/`。
2. 没有外部**资源加载**：`script[src]`、`link[rel=stylesheet|preload|modulepreload]`、`img[src]`、`source[src]`、`video[src]`、`audio[src]`、`iframe[src]`、`poster`、CSS `url()`、`@import` 都指向课程包内部。普通 `<a href>`、`<link rel="canonical">` 和 meta 属性可以指外部，但不能自动加载；外链加 `rel="noopener noreferrer"`。
3. player 和 runtime 来自 `./runtime/`，GSAP 来自 `./composition/assets/vendor/`，字体来自 `./composition/assets/fonts/`。
4. 注意路径基准：课程页 HTML 里的 `./composition/...` 相对页面；`runtime/course-deck.css` 里的字体 `url()` 相对 CSS 文件，必须写 `../composition/assets/fonts/...`。不要把两种基准混用。
5. 课程页不依赖 FastAPI、数据库或登录态；同源进度同步只能是可选增强，API 不可用时本地进度仍然工作。
6. 返回课程库的入口都来自 `course.json` 的 `site.homeUrl`：封面页首的吸顶课程页眉、播放态控制条第一个控件、完成页和错误页的返回按钮；如果为 `null`，整条页眉不渲染，这些返回入口也都不显示。
7. 用普通静态服务器（不是 FastAPI）打开时，所有功能正常。
8. 不要求 `file://` 直接双击打开。player 需要同源 iframe 和 runtime 注入，`file://` 的 origin 是不透明的；独立打开指“独立 HTTP 静态部署”。

第 7 条会变成 CI 里的一个固定测试，不是靠人工记得。

### 6.6 版本与缓存

- `runtime/VERSION.json` 记录 HyperFrames、player、runtime、GSAP 和课程外壳的版本/哈希。
- 构建产物里的 `course.json` 带 `build.runtimeVersion` 和 `build.contentHash`。
- 课程页 HTML 不缓存或短缓存；`runtime/vendor/*` 可以长缓存；composition 素材用中等缓存。具体头见 9.6。
- 课程更新后要能立刻看到，不能因为缓存继续播放旧 scene。构建时给 runtime、CSS、JS 和 `course.json` 加内容哈希查询参数，HTML 本身用 no-cache/ETag。

### 6.7 什么时候拆分课程

单门课保持一个 composition，直到出现下面任一情况：

- 超过 15 屏，或根文档超过 1.5MB（不含媒体）。
- 单门课媒体超过 50MB，首屏加载明显变慢。
- 需要每屏不同的画布尺寸或帧率。
- 单个 scene 的故障会拖垮整门课，且无法通过代码隔离解决。

拆分方式：把课程拆成多个“章节包”，每个包仍是一个独立的课程 URL，站点用后续契约里的 `series` 字段把它们组织成一条学习路径。不要在一个课程包里塞两个播放器。

---

## 7. 后端设计

### 7.1 模块

```text
app/
├─ main.py                 # create_app、lifespan、路由和 mount
├─ config.py               # 路径、环境变量、站点信息、DATABASE_URL
├─ db.py                   # SQLAlchemy engine/session、SQLite pragmas
├─ models.py               # User / Session / CourseProgress / ScreenProgress / CourseImport / CourseWatermark
├─ schemas.py              # 进度 API 的 Pydantic 请求/响应
├─ auth/
│  └─ sessions.py          # 匿名会话、cookie、未来的登录会话
├─ repositories/
│  └─ progress.py          # 进度的读写和 upsert
├─ catalog/
│  ├─ models.py            # 课程清单 Pydantic 模型
│  ├─ composition.py       # 解析根 composition 的 screen host
│  ├─ resolver.py          # 合并 course.json + composition，校验
│  ├─ importing.py         # 外部课程导入：校验、staging 构建、原子落盘、来源记录
│  ├─ watermark.py         # 课程水印：表单解析、构建时注入 composition、重建
│  ├─ watermark_store.py   # 课程水印的数据库读写（站点配置，不进 Git）
│  └─ loader.py            # 扫描 dist/、缓存、错误收集
├─ api/
│  ├─ courses.py           # 只读课程 JSON API
│  └─ progress.py          # 学习进度 API
├─ web/
│  ├─ routes.py            # 首页、课程库、关于、404
│  ├─ admin.py             # 后台设置、视频生成、课程水印配置
│  └─ import_routes.py     # /import 课程导入页（仅开发环境）
├─ templates/
└─ static/

migrations/                # Alembic
data/                      # SQLite 文件，gitignored
```

`catalog` 是一个深模块：对外只暴露 `load_catalog()`、`get_course(slug)` 和 `resolve_course(source)` 之类的接口；扫描、解析、合并、校验、缓存都藏在里面。Web 和 API 都依赖它，构建脚本也复用它，避免出现两套时间解析逻辑。`catalog/importing.py` 复用 resolver 和构建期资产校验；它对 `scripts/` 的依赖是函数内延迟 import，所以生产镜像只装 `app/` 时导入模块本身仍然可用，只是 `/import` 页面在 dev 才启用（见 D16）。

数据库是另一个独立边界：`db` + `models` + `repositories` 负责用户状态；`catalog` 不读数据库，数据库也不存课程内容。这样课程目录可以继续从 `dist/` 重建，用户数据可以单独备份和迁移。

### 7.2 目录加载流程

Web 进程的**目录部分**只读构建产物，不解析 `courses/` 源，也不在运行期解析 composition；唯一例外是后台水印配置页，它读写站点数据库里的水印配置并触发单门课重建（见 7.12），目录加载本身仍然只读 `dist/`、不读 `course_watermarks`。构建是目录数据的唯一入口，水印配置是另一条站点侧写路径；用户状态与水印配置都走 SQLite，课程内容不混进去。

启动时（`lifespan`）：

1. 扫描 `dist/courses/*/course.json`，跳过没有清单的目录。
2. 解析 `course.json` 为 `ResolvedCourse`，校验字段、屏幕顺序、时间范围、统计和构建元数据。
3. 如果 `VERIFY_COURSE_BUNDLES=1`（单机部署默认），检查同目录的 `index.html`、`composition/`、`runtime/` 是否存在；缺失的课程标记为 invalid。分离部署把课程资源放在 CDN、站点只保留清单时，把这个开关设为 0。
4. 按 `order`、`featured`、发布时间排序，生成 `Catalog`。
5. 缓存结果，并用清单文件 mtime / 目录签名失效。构建完成后下一次请求就能看到新课程，不需要重启进程；请求路径只做廉价的 `stat`，不重复解析 composition。

源课程到解析清单的转换发生在构建期（见 9.1）。这样生产镜像只需要 `app/` 和 `dist/`，不需要课程源文件、Node 或 HyperFrames。导入（D16）是开发/创作环境的作者工具：它把外部文件夹校验后复制进 `courses/` 并构建，生产站点仍然只读 `dist/`；`/import` 页面在 `ENV=prod` 下不开放。

错误策略：

- 单门课不合法：默认记录错误、从站点目录排除，但进程继续启动。
- `STRICT_CATALOG=1`：任何不合法课程都让启动失败。CI 和生产使用严格模式。
- `/api/health` 返回课程总数、已发布数、无效数、错误列表。
- 不在生产环境暴露完整的异常堆栈。

### 7.3 解析规则

以下规则由构建和 CI 执行；Web 进程不解析 composition。

`composition.py` 只做一件事：从根 composition HTML 里读出 screen host。它必须：

- 用 `html.parser`，不用正则表达式匹配标签结构。
- 只读取带 `data-screen-id` 的元素。
- 读取 `id`、`data-composition-id`、`data-composition-src`、`data-start`、`data-duration`。
- 验证 `data-start` / `data-duration` 是有限的非负数；`duration > 0`。
- 验证 host 按 `data-start` 严格升序，且区间不重叠。
- 读取根 `data-duration`，验证它覆盖最后一屏。
- 把 `data-composition-src` 交给 resolver；resolver 负责验证文件存在、scene 的 `data-composition-id` 和时间轴 key。

解析和合并链路必须有单元测试，覆盖：正常、缺字段、重复 id、时间倒序、重叠、越界、scene 文件缺失、scene id 不匹配。

### 7.4 模型

| 模型 | 作用 |
| --- | --- |
| `CourseSource` | `course.json` 的源结构：编辑信息 + 屏幕元数据，不含时间；构建使用 |
| `ScreenMeta` | 单屏的 id、标题、kicker、摘要、讲义、autoAdvance；构建使用 |
| `CompositionInfo` | entry、width、height、fps；构建使用 |
| `WatermarkConfig` | 可选课程水印：角标（四个角最多各一条）和满屏平铺；构建/Web 使用，值来自数据库 |
| `CourseWatermark` | 水印持久化：`course_slug` + 配置 JSON + `updated_at`；只在站点数据库，不进课程源文件 |
| `ScreenHost` | 从 composition 解析出来的 id、start、duration、source 文件；构建使用 |
| `ResolvedScreen` | 合并后的屏幕：元数据 + index + start + duration；Web/API 使用 |
| `ResolvedCourse` | 课程页/API 使用的完整模型 |
| `CourseSummary` | 课程卡片使用的轻量模型 |
| `Catalog` | 课程列表 + 错误 + 统计 |

模型用 Pydantic v2。源模型 `extra="forbid"`，避免拼错字段被静默忽略。解析后的模型可以多字段，但不能少字段。

### 7.5 路由

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/` | 首页：教学形态、精选课程展陈、课程库入口 |
| GET | `/courses` | 课程库：全部已发布课程，支持 `level` / `tag` 过滤 |
| GET | `/courses/` | 重定向到 `/courses`，避免和静态目录冲突 |
| GET | `/about` | 方法论、课程制作方式、致谢 |
| GET | `/courses/<slug>/` | 静态课程页（由 `StaticFiles(html=True)` 提供） |
| GET | `/admin` | 后台设置：课程列表、视频状态、生成/下载入口、水印入口 |
| POST | `/admin/login` | 校验 `ADMIN_TOKEN`，写后台会话 Cookie（未配置密码时不启用） |
| GET | `/admin/courses/<slug>/watermark` | 课程水印配置页：角标 + 满屏平铺，带 16:9 预览 |
| POST | `/admin/courses/<slug>/watermark` | 保存水印到站点数据库（`course_watermarks` 表）并同步重新构建课程包 |
| POST | `/admin/videos/<slug>/render` | 在服务器上开始渲染该课程视频（单任务） |
| GET | `/admin/videos/<slug>/download` | 下载已生成的课程视频 |
| GET | `/admin/status` | 后台轮询用的视频状态 JSON |
| GET | `/import` | 课程导入页（仅开发环境；收件箱候选、校验状态、最近导入） |
| POST | `/import` | 执行导入（仅开发环境；同源检查；写入 `courses/` 并构建） |
| GET | `/api/courses` | 已发布课程摘要列表 |
| GET | `/api/courses/<slug>` | 单门课的解析后清单 |
| GET | `/healthz` | 进程健康检查 |
| GET | `/api/health` | 目录健康：数量、错误、构建状态 |

路由顺序很重要：`/courses` 和 `/courses/` 必须在 `mount("/courses", ...)` 之前注册，否则会被静态目录吞掉。`/courses/<slug>` 不带斜杠时，由 `StaticFiles` 重定向到带斜杠的目录。

站点不提供单独的“课程详情页”。课程卡片直接进入课程页，课程页的封面就是详情。这样避免同一份信息在两个页面里维护。

### 7.6 静态文件

- `/static/*`：站点 CSS、JS、字体、图片。
- `/courses/*`：`dist/courses/`，`html=True`。

缓存策略：

| 路径 | 缓存 |
| --- | --- |
| `/courses/<slug>/` 和 `index.html` | `no-cache`（ETag + Last-Modified 重校验） |
| `/courses/<slug>/course.json` | `no-cache` |
| `/courses/<slug>/composition/**`（含 `index.html`） | `no-cache` |
| `/courses/<slug>/runtime/**`（vendor 之外） | `no-cache` |
| `/courses/<slug>/runtime/vendor/*` | 长缓存（1 年，immutable，URL 带 `?v=` 破坏缓存） |
| `/static/*` | 中等缓存 |

课程包是**原地重建**的：同一个 URL 下的 HTML、清单、composition 和外壳脚本都会在保存水印或重新构建后变化，所以除固定版本的 player vendor 之外都必须重校验。漏掉 `Cache-Control` 时浏览器会按 `Last-Modified` 做启发式缓存（约为已过时长的 10%，可长达一个多小时），普通导航直接复用旧页面，看起来就像“水印没生效”。`app/main.py` 的中间件统一给 `/courses/*` 设置上表策略，ETag 让重复访问只花一次 304。

生产环境可以把这个 mount 换成 Nginx/CDN；FastAPI 的行为作为本地开发和单机部署的默认值。

### 7.7 配置

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `ENV` | `dev` | `dev` / `prod` |
| `SITE_TITLE` | `页间课堂` | 站点标题 |
| `SITE_URL` | `http://127.0.0.1:8000` | 生成绝对 URL、OG、canonical |
| `COURSES_SRC_DIR` | `<repo>/courses` | 课程源；构建脚本使用；Web 只在后台水印配置页重建课程包时按需读 |
| `COURSES_DIST_DIR` | `<repo>/dist/courses` | 构建产物；Web/API 的数据源 |
| `COURSE_BASE_URL` | `/courses` | 课程卡片链接前缀；分离部署时设为 CDN 绝对地址 |
| `DATABASE_URL` | `sqlite:///./data/app.db` | SQLite 文件路径；测试用临时文件/内存库 |
| `STRICT_CATALOG` | `dev` 为 0，`prod` 为 1 | 是否因解析清单/产物错误阻止启动 |
| `INCLUDE_DRAFTS` | `dev` 为 1，`prod` 为 0 | 是否在站点显示构建进去的草稿 |
| `VERIFY_COURSE_BUNDLES` | `1` | 是否检查本地课程包文件；分离部署设为 `0` |
| `SESSION_COOKIE_SECURE` | `prod` 为 1，`dev` 为 0 | 会话 Cookie 是否只走 HTTPS |
| `ADMIN_TOKEN` | 空（不设防） | 后台管理密码；设置后 `/admin` 及其写接口要求登录 |
| `VIDEO_OUTPUT_DIR` | `data/videos` | 在线生成的视频和元数据目录 |
| `VIDEO_WORK_DIR` | `data/videos/.work` | 渲染临时工作目录（复制 composition、日志） |
| `VIDEO_QUALITY` | `looks` | HyperFrames 渲染质量：`draft` / `looks` / `delivery` |
| `VIDEO_RENDER_TIMEOUT_SECONDS` | `7200` | 单次渲染超时，防止进程永久占用 |
| `VIDEO_HYPERFRAMES_CLI` | 空（自动发现） | `hyperframes.mjs` 的路径；空时依次尝试仓库 `tools/`、PATH、npx |
| `VIDEO_HYPERFRAMES_VERSION` | `0.9.19` | npx 兜底时固定使用的版本 |
| `VIDEO_NODE_BIN` / `VIDEO_NPX_BIN` | `node` / `npx` | Node 与 npx 可执行文件 |
| `VIDEO_FFMPEG_DIR` | 空（自动发现） | 存放 `ffmpeg` / `ffprobe` 的目录；空时依次尝试仓库 `tools/ffmpeg/bin` 和 PATH |
| `COURSES_INBOX_DIR` | `<repo>/course-inbox` | 外部课程收件箱；`/import` 页面与 `import_course.py --inbox` 使用，Web 只在开发环境读 |
| `COURSE_IMPORT_ENABLED` | `dev` 为 1，`prod` 为 0 | 是否开放 `/import` 课程导入页 |

配置用 `pydantic-settings`，从环境变量和 `.env` 读取。不要在生产环境读取仓库相对路径以外的用户输入。

### 7.8 安全

- 课程内容是可信静态内容；站点只有一个受限的进度写接口，攻击面仍然很小。
- 站点页面使用较严格的 CSP；课程页因为 player 注入和内联清单，需要允许 `'unsafe-inline'` 的脚本。这个差异要在部署配置里写清楚。
- 进度 API 是唯一的写入口：校验 slug/screen id、限制请求体大小、检查 `Origin`；SQLAlchemy 参数化查询，不拼 SQL。
- 会话 Cookie 必须 `HttpOnly`；生产加 `Secure`；`SameSite=Lax`；不把 token 写进日志。未来登录接口加 CSRF、速率限制和会话轮换。
- 数据库文件不放在 Web 根目录下，用 volume 和最小权限；备份文件同样不要公开。
- `StaticFiles` 负责路径规范化，不要让自定义路由拼接未校验的文件路径。
- 不要把草稿构建进生产产物。`status` 过滤在构建期完成，而不是只靠前端隐藏。
- `/import` 是开发/创作工具：默认只在 `ENV=dev` 开放；POST 只接受收件箱的直接子目录名（防路径逃逸）并检查同源 `Origin`。生产部署保持 `COURSE_IMPORT_ENABLED=0`，不要把它当成上传入口。
- 不把密钥、内网地址、绝对路径写进课程清单或构建产物。
- 开启 `X-Content-Type-Options: nosniff`、`Referrer-Policy: strict-origin-when-cross-origin`，生产环境加 HSTS。

### 7.9 SQLite 的定位

课程目录是只读的、随代码发布的、数量很少的，继续放在 `dist/` 里，由 `catalog` 读取。数据库不存课程内容，也不做课程搜索的索引。

数据库只存“运行态数据”：

- 匿名学习者、未来的注册用户；
- 登录会话；
- 课程进度、屏幕完成状态；
- 以后可能加收藏、学习记录、课程完成证书。

为什么是 SQLite：

- 单文件、零服务、零连接池，备份就是复制/`VACUUM INTO`；对这个规模的课程站足够。
- 支持事务、外键、WAL，能撑住“登录 + 进度”这类低写入负载。
- 本地开发不需要 Docker 或外部数据库。
- SQLAlchemy + Alembic 让以后迁移到 Postgres 不必重写业务层。

SQLite 的限制也要写清楚：

- **单写者。** 写事务串行；不要做长事务，不要在请求里做大批量写。用 WAL、`busy_timeout` 和短事务。
- **不适合多实例共享。** 一个应用实例、一个本地文件最稳；多实例部署时先迁移到 Postgres。
- **迁移需要 batch 模式。** Alembic 配置 `render_as_batch=True`，因为 SQLite 的 `ALTER TABLE` 能力有限。
- **备份不是复制一个正在写的文件。** 用 SQLite backup API 或 `VACUUM INTO`，并在迁移前做一次。

### 7.10 数据层与账号演进

技术栈：

- SQLAlchemy 2.0，同步 `Session`（FastAPI 的同步依赖在线程池里跑，足够这个规模）。
- Alembic 迁移，`render_as_batch=True`。
- SQLite 文件路径来自 `DATABASE_URL`，默认 `sqlite:///./data/app.db`。
- 连接初始化时设置 `journal_mode=WAL`、`foreign_keys=ON`、`busy_timeout=5000`、`synchronous=NORMAL`。

#### 表

| 表 | 关键字段 | 说明 |
| --- | --- | --- |
| `users` | `id`、`email`、`password_hash`、`display_name`、`is_anonymous`、`created_at`、`updated_at` | 匿名用户和未来注册用户共用一张表；匿名用户 `email/password_hash` 为空 |
| `sessions` | `id`、`user_id`、`token_hash`、`created_at`、`expires_at`、`last_seen_at` | 匿名会话和登录会话共用；只存 token 哈希，不存明文 |
| `course_progress` | `user_id`、`course_slug`、`last_screen_id`、`started_at`、`updated_at`、`completed_at` | 每用户每课程一行；`last_screen_id` 用于“继续上次” |
| `screen_progress` | `user_id`、`course_slug`、`screen_id`、`completed_at`、`updated_at` | 复合主键；用于完成度、回顾、未来的学习看板 |
| `course_imports` | `id`、`slug`（唯一）、`title`、`source_path`、`source_hash`、`content_hash`、`screens`、`duration_seconds`、`imported_at`、`updated_at` | 导入来源记录：哪门课、从哪个文件夹、导入了什么内容。只记来源，不存课程内容；课程目录仍以 `dist/` 为准 |

约束：

- `users.email` 唯一（大小写归一后）；SQLite 允许多个 `NULL`，匿名用户不受影响。
- `sessions.token_hash` 唯一；token 是 32 字节随机值，Cookie 里放原文，数据库只存 SHA-256。
- `course_slug`、`screen_id` 不是数据库外键：课程是文件，API 写入前用 catalog 校验 slug 和屏幕 id，避免数据库和课程包互相绑定。
- `course_imports.slug` 也不是外键：它记录导入来源，课程从 `dist/` 消失后记录仍可保留用于追溯；清理策略由运维决定。
- 时间统一 UTC；API 输出 ISO 8601。
- 外键开启 `ON DELETE CASCADE`：删用户时删会话和进度。

#### 匿名会话

- 第一次写进度时创建匿名 `users` 行 + `sessions` 行，并设置 HttpOnly Cookie（名称 `al_session`）：`Secure`（生产）、`SameSite=Lax`、`Path=/`、有效期 180 天。
- 只读 `GET` 不创建用户，避免爬虫和空会话把表撑大。
- Cookie 里只放随机 token；数据库存哈希。会话过期后按匿名用户重新开始。
- 匿名进度可以升级成账号进度：注册时把 email/password 绑到同一个 `users` 行；登录到已有账号时，把匿名进度按 `updated_at` 合并进去，再清理匿名会话。合并逻辑必须幂等。

#### 进度 API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/progress/{course_slug}` | 当前匿名/登录用户的进度；无会话返回空进度，不创建用户 |
| PUT | `/api/progress/{course_slug}` | `{screenId, completed?}`；创建匿名会话（如需要）、upsert 进度 |
| GET | `/api/progress` | 当前用户所有课程进度；未来学习看板使用 |

规则：

- 写入前校验 `course_slug` 和 `screen_id` 存在于当前 catalog；不存在的直接 404/422，不写脏数据。
- `PUT` 只接受 JSON；同源请求；检查 `Origin`，默认不开放 CORS。
- 课程完成：当某课程所有屏幕都有 `screen_progress` 时，写 `course_progress.completed_at`；屏幕总数从 catalog 取，不在数据库里复制。
- 进度只存课程 slug、屏幕 id 和时间；不存讲义内容、搜索词或行为轨迹。匿名会话不接第三方分析。
- 进度写入失败不能阻断课程播放；课程外壳捕获错误、保留本地进度。
- 未来登录后的写接口需要 CSRF token、会话轮换和速率限制；v1 的进度接口风险较低，但也要限制请求体大小和字段长度。

#### 未来登录

数据库从第一天就按“可登录”设计，但 v1 不实现登录。以后加：

- `POST /api/auth/register`、`/api/auth/login`、`/api/auth/logout`；
- Argon2id 密码哈希；
- 登录成功后轮换 session token；
- CSRF、登录速率限制、邮箱验证、找回密码；
- 匿名进度合并到账号。

认证用 **服务端 session + HttpOnly Cookie**，不把 JWT 放 `localStorage`。这样课程页不需要处理 token，XSS 也拿不到长期凭证。

#### 迁移与备份

- 迁移只在部署/CI 执行：`alembic upgrade head`；不要在应用启动时自动迁移，避免多进程竞争。
- 迁移前备份：`sqlite3 data/app.db ".backup 'data/backups/app-<timestamp>.db'"` 或 `VACUUM INTO`。
- 恢复演练：把备份复制到临时目录，跑一次 `alembic current` 和关键查询。
- `data/` 不进 Git；Docker 用 volume；文件权限只给运行用户。
- `/healthz` 只检查进程；`/readyz` 检查数据库连接和 schema version；`/api/health` 返回目录、DB、迁移版本。

### 7.11 在线视频生成（后台）

主链路不变：网页仍是课程主形态，MP4 只是后台按需导出的附属产物。

- **入口。** `/admin` 后台设置页列出全部课程、屏数、时长、视频是否已生成，以及生成和下载按钮。页脚有一个「后台设置」文字入口。
- **渲染源。** `dist/courses/<slug>/composition/`，也就是站点播放的同一份构建产物。课程水印在构建时已经写进这份 composition，所以导出的 MP4 和网页播放画面带同一层水印。视频渲染不读 `courses/` 源，也不需要创作期的 `package.json` 或 `hyperframes.json`；后台水印配置页是另一个写路径，见 7.12。
- **渲染器。** 固定版本 HyperFrames CLI。发现顺序：`VIDEO_HYPERFRAMES_CLI` → 仓库内 `tools/node_modules/hyperframes/bin/hyperframes.mjs` → PATH 上的 `hyperframes` → `npx --yes hyperframes@<版本>`。需要 Node 22+、Chromium（`npx hyperframes browser ensure`）和 FFmpeg/FFprobe。
- **任务模型。** 进程内单任务：同一时间只渲染一个视频，重复请求返回「已有视频正在生成」。渲染前把 composition 复制到 `VIDEO_WORK_DIR` 下的临时目录，避免污染 `dist/`（它可能是只读挂载）并隔离并发；结束后清理工作目录。
- **产物。** `data/videos/<slug>.mp4` 与元数据 `data/videos/<slug>.json`（生成时间、大小、时长、质量档、内容哈希、上次尝试结果）。失败时保留 `data/videos/<slug>.render.log` 供运维排查，页面只给可执行的说明。`data/` 不进 Git，视频不进构建产物。
- **一致性。** 元数据记录构建时的 `course.build.contentHash`；课程重新构建后，页面提示「课程已更新」并允许重新生成。生成失败不会删掉上一版视频，仍可下载旧版本。
- **重启与超时。** 启动时把遗留的 `running` 记录标记为中断并清理工作目录，不自动续跑。渲染超过 `VIDEO_RENDER_TIMEOUT_SECONDS`（默认 2 小时）会被终止。
- **访问控制。** 默认无鉴权，只适合本机或内网。设置 `ADMIN_TOKEN` 后，`/admin` 与生成、下载、状态接口都要求后台 Cookie 或 `X-Admin-Token`；渲染 POST 还检查同源 `Origin`，避免任意站点触发重任务。生产环境应同时放在反向代理的访问控制之后。
- **分离部署。** `VERIFY_COURSE_BUNDLES=0` 时本机没有课程包，后台只显示课程、不提供生成；这是预期行为，视频应在那台持有课程包和渲染环境的机器上生成。

### 7.12 课程水印配置（后台）

水印是**站点部署配置**，不是课程内容：配置存在 SQLite 的 `course_watermarks` 表，构建时从库里读出并写进构建产物的 composition 入口，独立部署的课程包因此自带水印（D20）。数据库行不进 Git；`courses/<slug>/course.json` 不再有 `watermark` 字段，源文件里出现该字段会被严格模型当作未知字段拒绝。写进 composition 而不是课程页外壳，是因为网页播放器和 MP4 渲染器消费的是同一份 composition：一个层同时覆盖播放与导出。

- **入口。** `/admin` 每门课的登记行有「水印配置」链接；页面是 `/admin/courses/<slug>/watermark`，复用后台「登记表」版式，带 16:9 预览。
- **读取。** `app/catalog/watermark_store.py` 按 slug 读 `course_watermarks`；库或表不存在时按「未配置水印」处理，新克隆、尚未迁移的库也能构建。页面展示的是库里的值，不看 `course.json`。
- **写入。** 表单提交后 `app/catalog/watermark.py` 校验字段，`watermark_store.save()` 写入或删除数据库行，然后延迟导入 `scripts.build_courses.build_course` 把配置传进去重建这一门课；同一进程内用模块级锁串行化保存。构建失败时页面列出 `code / file / field` 级别的错误，数据库里保留已保存的配置；构建用 rename 换入新包，失败会恢复旧包，所以 `dist/` 仍是上一版。
- **为什么用数据库。** 水印文字是部署方的身份信息（作者、公司、部门），用户要求它不被 Git 跟踪，历史里已经提交过的旧水印也要清理；数据库属于站点、`data/` 已 gitignore，正好承载这类配置，同时构建产物仍让独立课程包自带水印。代价是构建要能访问站点数据库，且生产镜像只装 `app/` 和 `dist/` 时配置页只读（重建需要课程源）。
- **为什么同步重建。** 单门课重建是复制文件 + 渲染 Jinja，耗时在秒级；和 `/import` 一样用同步表单，省掉任务队列与轮询状态。
- **安全。** 与后台其他写接口一致：`ADMIN_TOKEN`、后台 Cookie 或 `X-Admin-Token`、同源 `Origin` 检查、`no-store`、`noindex`；slug 必须是合法课程，配置只写这一门课的行。
- **视觉。** 角标水印贴画布四角，满屏平铺水印按 16:9 网格重复；两者都只覆盖播放画布，`pointer-events: none`、无动画、不挡控制条，全屏保留，导出的 MP4 里同样存在。字号以 1920×1080 画布的设计像素表示；水印层写在 composition 内层，播放器缩放画布时等比缩放，渲染器按 1:1 输出。

### 7.13 片头 / 片尾（后台）

片头/片尾是**站点共享模板 + 每门课的选择**，不是课程字段：模板放在仓库根的 `clips/<id>/`（`clip.json` + `<template>` scene），选择存在 SQLite 的 `course_clips` 表；构建时把模板渲染成课程 composition 的一屏。设计决策见 D21，视觉规则见 DESIGN.md 8.6。

- **入口。** `/admin` 每门课的登记行有「片头片尾」链接；页面是 `/admin/courses/<slug>/clips`，复用后台「登记表」版式。片头、片尾各一组单选（不插入 + 模板），每个模板带标题、时长和按本课渲染的 16:9 末帧预览。
- **读取。** `app/catalog/clip_store.py` 按 slug 读 `course_clips`；库/表缺失按「未配置」处理，新克隆也能构建。`app/catalog/clips.py` 扫描 `clips/`，校验 `clip.json`、scene 的 `<template>`/composition id/时间轴、禁用时钟和「不加载外部资源」，无效模板只在后台列表里报告，不参与构建。
- **注入。** `scripts/build_courses.py` 解析课程后运行 `plan_clips()`（只校验、算时间、算 hash），复制 composition 后再 `inject_clips()`：写 `compositions/clip-<id>.html`，把 host 插到 `#root` 的最前/最后，原 host 和 `<audio>` 的 `data-start` 加片头时长，根 `data-duration` 加总时长。构建后的清单把这两屏作为 `kind: intro/outro` 的普通屏写进 `screens[]`，课程页目录据此标「片头/片尾」。
- **选择存数据库的理由。** 模板是全站共享的部署内容，不是某门课写的；存在 `course_clips`（`data/` 不进 Git）让课程源文件保持干净。构建产物自带渲染后的 scene，独立部署的课程包播放时不需要数据库。
- **内容哈希。** `contentHash` 混入选择、渲染后的模板（含占位符结果）以及站点的 `PROJECT_URL`；换片头、改模板或改项目地址都会让旧视频被标记为过期。
- **重建。** 保存先写库、再延迟导入 `build_course` 重建这一门课；同一进程内模块级锁串行化。构建失败时页面列出 `code / file / field` 级错误，库里的选择保留，下一次构建仍会尝试。
- **字体。** `scripts/sync_runtime.py` 把 `clips/` 的文案并入站点、模板和每门课的字体子集；片头里的字不会因为不在课程正文里而回退到系统字体。
- **预览。** 后台的「预览」不写库、不碰 `dist/`：`app/catalog/clip_preview.py` 用同一套 `build_course` 在 `data/clip-previews/<slug>-<kind>-<id>/` 下重建一份只含该模板的课程包，然后重定向到 `/admin/clip-previews/<token>/<slug>/index.html?preview=<id>&back=...`。这个路由要过后台登录，预览页和它的 composition 走 `/courses` 同级的 CSP 豁免，并加 `no-store`、`noindex`。播放器带 `preview` 参数时直接进入课堂、只播这一屏，顶部有预览条；进度读写被禁用，播完停在末帧，不会跳进正课或完成页。预览包是可丢弃产物，删掉后下一次点击会重建。
- **限制。** 片头/片尾是静默的一屏（不配旁白/音乐），插入时正课时间整体后移；没有选择时构建输出与旧版逐字节一致。生产镜像只装 `app/` 和 `dist/` 时没有课程源，页面只读，预览也会因为缺少源文件而报错。

---

## 8. 前端设计

### 8.1 为什么不是 SPA

站点需要的是：一个封面、一个课程库、一个关于页、若干课程卡片。这些内容适合服务端渲染。用 React/Next 会带来：

- 一套 Node 构建链和额外的部署产物；
- 客户端路由与静态课程路由的冲突；
- 首屏需要等 JS 才能看到内容；
- 为一个目录页维护 API 客户端和状态管理。

课程播放的交互复杂度在课程外壳里，不在站点。课程外壳用原生 ES module 写一个几百行的控制器，足够，也更容易被单独测试。以后如果要做学习看板，可以在站点下另开一个 `/dashboard` 或独立的 islands/子应用，不需要重构课程包。

### 8.2 站点页面

| 页面 | 内容 |
| --- | --- |
| 首页 | 教学形态（会停的动画幻灯片）、精选课程展陈（堆叠幻灯片/课程像）、课程库入口 |
| 课程库 | 课程卡片网格、级别/标签过滤、空状态 |
| 关于 | 方法论、课程制作流程、第三方致谢 |
| 404 | 回到首页/课程库 |

课程卡片显示：序号、标题、副标题、一句话承诺、级别、时长、屏数、强调色、封面。卡片是链接，不是弹窗；点击直接进入课程页。站点和课程库的卡片都留了“两张纸从后面露出来”的层次，让目录页读起来像一叠印刷品，而不是平铺的网格。

首页不搬运任何一节课的内容：它用一叠示意幻灯片讲清“一屏一个概念”的教学形态，再在下方列出课程。示意幻灯片会自己慢慢换一张，指针进入时停下来并摊开；`prefers-reduced-motion` 下是静态的一叠。首页没有深色区块，也不提供明暗切换。

站点不自动播放任何课程动画。封面动效克制，课程动画才是主角。

### 8.3 课程外壳

课程页是构建生成的静态 HTML，包含：

1. **课程页眉**：吸顶在页面最上方的一条导航，只包含「← 返回课程库」的真实链接，`href` 来自 `site.homeUrl`、文案来自 `site.backLabel`；只在封面可见，页首不用滚动就能点到；播放态、完成页和错误页隐藏，返回分别由控制条第一个控件和页面按钮承担；`site.homeUrl` 为 `null` 时整条页眉不渲染。
2. **封面**：课程标题、副标题、目标列表、章节大纲、时长/级别/屏数、开始按钮、继续上次。
3. **舞台**：播放态下页面就是播放器：`.deck-shell` 通栏、高 `100dvh`、页面无滚动；舞台区占满控制条以上的全部高度，16:9 画布在可用区域里等比最大化，四周留纸色边。封面、完成页和错误页仍是居中的阅读列；不套黑色放映框。
4. **控制条**：通栏贴在舞台下方，顺序为退出课程（回到课程库）、上一屏、播放/暂停、下一屏、跳到最后、重播本屏、目录、讲义、字幕、配音（有音频时）、全屏、当前屏进度。退出是第一个控件，并且是真实链接：JavaScript 负责暂停并销毁播放器、退出全屏，脚本失效时链接仍可离开。观众学到一半想走，不必点完所有屏。「跳到最后」只在播放态出现，停在当前屏末帧并标记讲完，快捷键 `End`。控制条右侧是当前屏进度：可拖动的原生 range，拖动时暂停、松手恢复，拖到末端等同跳到最后；课程总进度是 2px 细条，按全课时间连续增长，不按屏跳变。
5. **章节信息**：当前屏的 kicker、标题、一句话摘要。
6. **目录抽屉**：从右侧滑出的纸色面板，按顺序列出全部屏的序号、标题和起始时间，当前屏高亮（`aria-current="step"`）；点任意一屏先关抽屉，再跳转并播放；与讲义抽屉互斥，共用遮罩，焦点进入抽屉、关闭回触发按钮，Esc 关闭；深链和连续播放课程同样适用。条目来自 `course.json` 的 `screens[].title`，由课程页服务端渲染，作者不用在 composition 里做导航。
7. **讲义抽屉**：当前屏的完整文本，键盘可访问，支持前后屏切换；与目录抽屉互斥。
8. **完成页**：要点回顾、重看、返回课程库。
9. **错误页**：错误说明、重试、返回封面。
10. **水印层**（可选）：构建时按数据库里的课程水印配置写进 composition 内层；角标贴四角，满屏平铺按网格重复。水印不拦截指针事件、不参与时间轴、不遮控制条，进入全屏仍然可见，导出的 MP4 也带同一层。

封面和大纲是无 JS 也能读的静态 HTML；播放器部分才是 JS 增强。这样即使脚本加载失败，学习者至少能看到课程讲什么、每屏标题是什么。

进度是可选增强，不是播放前置条件。构建时如果课程页和站点 API 同源，就注入 `progressEndpoint` 和 `progressOrigin`；课程外壳先写 `localStorage`，再异步 GET/PUT 服务端进度。只有 `location.origin === progressOrigin` 才同步；服务端失败、离线、独立部署、没有 Cookie，都退回本地进度。课程包本身永远不要求数据库存在。

### 8.4 设计系统

视觉与文案的**完整规则见 [DESIGN.md](../DESIGN.md)**，本节只记录架构层约束。站点和课程共用一套基础令牌，语气也一致：

- **站点**：暖纸色背景、墨色文字、编辑器式的排版；像一本课程目录。
- **课程**：同一套暖纸色、墨色和细线，排得更像一叠放映页：封面、控制条、讲义都是纸面，每门课一个强调色。深色舞台已经退役（见 D10）；以后要做明暗切换，在令牌层成对提供表层色，不在单个课程里写死（落地规则见 DESIGN.md 第 11 节）。
- **强调色**：站点固定用锈红；课程强调色只出现在进度、圆点、当前屏、封面装饰上，正文和按钮仍用墨色，避免小字对比度不足。
- **字体**：中文用自托管的 Noto Sans SC 子集；拉丁标签/数字可以用一套几何无衬线；代码/标签用等宽字体。
- **字体子集**：用 `pyftsubset` 生成可变字重子集，字符集覆盖常用 3500 汉字、站点文案和课程文案；生僻字回退系统 `sans-serif`，不要让页面因缺字变成方框。
- **网格**：12 列，最大宽度 1280–1440；课程舞台不受网格限制。
- **圆角**：站点 12–16px；舞台 0 或很小，避免“卡片里嵌视频”的感觉。
- **动效**：站点 150–250ms；课程转场 180–240ms；课程内容动效由 composition 自己决定。

令牌放在 `design/tokens.css`，站点和课程构建时各自取一份，避免出现两套颜色。课程可以用 `accent` 覆盖强调色，但不应该重写字体和基础色。

### 8.5 响应式与移动端

- 站点：三列 → 两列 → 单列；导航折叠；卡片信息不依赖 hover。
- 课程：横屏/桌面优先。播放态用 flex 列占满 `100dvh`：舞台区弹性伸缩，16:9 画布用容器查询单位（`cqw` / `cqh`）在可用区域内取能放下的最大尺寸；控制条在画布外通栏。封面、完成页和错误页仍按阅读列排版。
- 手机竖屏：显示“请横屏观看”的建议，同时提供“阅读讲义”入口。用户可以强行继续看缩放后的动画，但产品不承诺可读性。
- 触控目标至少 44×44px；滑动切屏不能和按钮点击冲突。
- 播放态高度优先用 `100dvh`，`100vh` 只作为旧浏览器的回退，避免移动浏览器地址栏导致内容被裁。

### 8.6 无障碍

- 课程页有明确的标题层级：`h1` 课程名，`h2` 当前屏标题，讲义用正文结构。
- 切屏时通过 `aria-live="polite"` 播报“第 3 屏，共 8 屏，标题……”。
- 控制条按钮有 `aria-label`、`aria-pressed`（播放/暂停、静音）。
- 当前屏进度是原生 `<input type="range">`：鼠标、触摸、键盘（方向键、`Home` / `End`）都能操作；`aria-label` 说明「当前屏进度，可拖动」，`aria-valuetext` 播报「当前时间 / 本屏时长」，不只靠长度表达进度。
- 键盘可以完成全部操作；焦点顺序合理；讲义或目录打开后焦点进入抽屉，关闭后回到触发按钮；两个抽屉互斥，同一时间只开一个；目录里的当前屏条目标 `aria-current="step"`。
- 颜色对比：正文至少 4.5:1，大号文字至少 3:1。
- 动画不是唯一的信息载体：每屏有摘要和讲义；有音频就有文字稿。
- `prefers-reduced-motion` 有明确行为（见 5.9）。
- iframe 里的内容对屏幕阅读器不友好，所以课程页必须在 iframe 外提供等价文本。这是课程外壳不可省略的部分。

### 8.7 性能预算

| 项目 | 预算 |
| --- | --- |
| 课程封面首屏（HTML/CSS/字体/player JS，gzip） | ≤ 2.5MB |
| 首屏动画所需素材 | ≤ 3MB |
| 单门课总素材（不含视频） | ≤ 15MB |
| 首帧时间（常见宽带，桌面） | ≤ 2.5s |
| 首帧时间（中端笔记本，本地服务器） | ≤ 4s |
| 动画帧率 | 目标 60fps，最低 30fps |
| 课程页外部请求 | 0 |

做法：

- 封面阶段不设置 player 的 `src`，不加载 composition。
- player 脚本体积可控，随课程页加载；封面阶段只加载封面、字体和外壳，不加载 iframe。
- 字体子集化、预加载；composition 等字体就绪后再播。
- 图片用 WebP/AVIF，音频用 AAC/Opus，视频只在必要屏幕使用，且本地化。
- scene 里的图片/视频加 `loading="lazy"` 或按时间预加载；不要把所有媒体塞进首屏。
- 构建期检查单文件大小和总大小，超预算让 CI 失败或警告。

### 8.8 SEO 与分享

- 站点页面服务端渲染，带 title、description、canonical、OG。
- 课程页构建时注入 title、description、OG 图（封面）、`LearningResource` JSON-LD。
- 课程页的封面包含课程目标、章节标题和摘要，这些是静态 HTML，可被索引。
- 生成 `sitemap.xml` 和 `robots.txt`；课程页和站点页面都列入。
- 分享链接使用课程 URL；深链 hash 不影响抓取。

### 8.9 无 JS 降级

- 站点：课程库、过滤、课程卡片全部可用。
- 课程页：封面、目标、大纲、每屏摘要可见；显示 `<noscript>` 说明“动画需要 JavaScript；可以先阅读课程大纲”。
- 不把关键信息只放在 JS 生成的 DOM 里。

---

## 9. 构建与发布

### 9.1 流水线

```text
courses/<slug>/
   │
   ├─ 1. 解析 course.json（Pydantic）
   ├─ 2. 解析 composition/index.html 的 screen host（html.parser）
   ├─ 3. 合并、校验（resolver）
   ├─ 4. 校验 scene 文件、资源、字体、GSAP、外部资源加载
   ├─ 5. 渲染课程页（Jinja2 shell），按部署方式注入同源 `progressEndpoint` / `progressOrigin`
   ├─ 6. 拷贝 composition（排除 node_modules/.hyperframes/renders/package.json/hyperframes.json）
   ├─ 7. 拷贝 runtime、vendor、design tokens
   ├─ 8. 写解析后的 course.json
   ├─ 9. 写 LICENSES、VERSION
   └─ 10. 输出 dist/courses/<slug>/
```

构建是幂等的：同样的输入产生同样的输出（时间戳字段除外）。构建失败必须给出具体文件、字段和修复建议。生产环境构建时先写临时目录，再原子替换 `dist/courses/<slug>/`，避免服务过程中看到半个课程包。

### 9.2 运行时打包

| 文件 | 来源 | 说明 |
| --- | --- | --- |
| `hyperframes-player.global.js` | `tools/node_modules/hyperframes/dist/` | 官方 web component |
| `hyperframe.runtime.iife.js` | 同上 | 注入 composition 的 runtime |
| `gsap.min.js` | `tools/node_modules/gsap/dist/` | 放在 `composition/assets/vendor/` |
| `NotoSansSC-*.woff2` | `design/fonts/` | 子集化后放进 `composition/assets/fonts/` |
| `course-deck.js` / `.css` | `runtime/` | 课程外壳 |
| `tokens.css` | `design/` | 设计令牌 |

原则：

- 版本固定，不用 `latest`。
- 每个文件记录 SHA-256，`VERSION.json` 可查；vendor URL 带版本/哈希查询参数，避免长缓存锁死旧 runtime。
- 许可证文件随包分发：HyperFrames（Apache-2.0）、GSAP、字体（OFL）。
- 课程包里不出现 `node_modules`、源地图、编辑器缓存。

### 9.3 课程页生成

课程页用 Jinja2 模板渲染，模板在 `runtime/shell.html.j2`。模板接收：

- `course`：解析后的课程清单；
- `site`：站点标题、首页 URL、课程库 URL；
- `theme`：强调色、封面 URL；
- `progress`：同源进度接口地址和 `progressOrigin`；为 `null` 或 origin 不匹配时，课程页只使用本地进度；
- `build`：版本、内容哈希。

生成的 HTML 包含：

- meta/OG/JSON-LD；
- 封面和大纲的静态 HTML；
- 舞台、控制条、目录和讲义抽屉、完成页；
- 内联的解析后清单（`<script type="application/json" id="course-data">`）；
- player 和课程外壳脚本的引用。

内联清单要做 `</script>` 转义。课程页不在运行时 fetch `course.json`，减少一次请求和一个失败点；`course.json` 仍然保留，供 API、调试和外部工具读取。

### 9.4 校验与外部资源扫描

构建必须检查：

- 清单字段、枚举、slug、文件存在性。
- 每屏元数据和 composition host 一一对应。
- 时间顺序、重叠、根时长。
- 每个 scene 文件存在，`data-composition-id` 和时间轴 key 匹配。
- 所有会发起资源请求的属性（`script[src]`、`link[rel=stylesheet|preload|modulepreload]`、`img[src]`、`source[src]`、`video[src]`、`audio[src]`、`iframe[src]`、`poster`、CSS `url()`、`@import`）不含外部协议；`<a href>`、`<link rel="canonical">` 和 meta 属性不作为资源加载检查。
- GSAP、字体、runtime 文件存在且哈希匹配。
- 单文件/总大小预算。
- 没有 `Date.now()`、`setInterval`、未播种的 `Math.random()` 作为动画时钟（允许在非动画的工具代码里出现，构建脚本按文件范围检查）。
- `composition/index.html` 的根 `data-duration` ≥ 最后一屏结束时间。

外部资源扫描允许 `data:` URI、`#` 锚点、`mailto:`、普通 `<a>` 外链和 canonical/meta；对注释里的 URL 做白名单/忽略，避免误报。

### 9.5 独立部署验收

每个课程包构建后，CI 执行：

1. 在 `dist/courses/<slug>/` 启动一个普通静态服务器（例如 `python -m http.server 8081`），不启动 FastAPI，也不启动数据库。
2. 用 Playwright 打开 `http://127.0.0.1:8081/`。
3. 点击开始，等待第一屏；点击下一屏，等待第二屏；打开讲义；检查控制台没有错误。
4. 断言页面发出的请求没有跨域外部请求，也没有对 `/api/*` 的依赖。
5. 断言页面标题、封面、课程大纲可见；本地进度可以“继续上次”。

这个测试是“课程可以脱离网站”唯一的硬证明。任何课程包不通过，不能发布。

HyperFrames 的 `publish` 可以快速托管一个项目预览，但它把课程放到第三方服务，和“课程包可复制、可自托管”的目标冲突。本项目不把它作为分发路径；需要临时分享时可以用，但不进入构建和部署流程。

### 9.6 缓存与 CDN

| 内容 | 策略 |
| --- | --- |
| 课程页 HTML | `no-cache` + ETag；构建后用 `?v=<hash>` 加载脚本/样式 |
| `course.json` | 短缓存（5 分钟） |
| composition HTML/JS/CSS | 中等缓存（1 小时） |
| 图片/字体/音频 | 长缓存，文件名带内容哈希或查询参数 |
| runtime/vendor | 1 年 immutable |
| 站点静态 | 1 天 |

分离部署时：

- 站点 `COURSE_BASE_URL=https://cdn.example.com/courses`。
- 课程页的 `site.homeUrl` 设成站点绝对地址；如果课程要独立分发，设成 `null`。
- CDN 需要允许课程页被直接访问，不需要 CORS；分离部署不注入进度接口，课程页不调用 API。
- CDN 的 404 行为要可预测，不能把缺失资源回退成 HTML。

### 9.7 CI 质量门

必须通过：

1. Python：`ruff check`、`ruff format --check`、`pytest`。
2. 构建：全部已发布课程构建成功，产物文件齐全。
3. HyperFrames：每门课的 `composition/` 通过 `npx hyperframes@0.9.19 check`。
4. 播放器契约：range/ended 的 Playwright（Python）测试。
5. 独立部署：静态服务器上的课程能播放。
6. 站点 E2E：首页 → 课程库 → 课程 → 下一屏 → 返回。
7. 无障碍：站点和课程页的 axe 检查，键盘路径测试。
8. 外部资源扫描：0 个外部资源加载（引用链接除外）。
9. 预算：首屏和总大小不超限。
10. 数据库：迁移链可从空库升到 head；进度 API 的 upsert、匿名会话、slug/screen 校验有测试；备份/恢复步骤演练过。

`check` 和快照需要 Node 22、Chrome；CI 里用固定版本，不使用 `latest`。

### 9.8 升级 HyperFrames

1. 在 `tools/package.json` 里改固定版本。
2. 运行 `scripts/sync_runtime.py`，更新 player/runtime 和 `VERSION.json`。
3. 先跑播放器契约测试：range 起点、range 终点、`ended`、`seek`、切换下一屏。
4. 重建所有课程，跑 `check` 和至少两门课的逐屏快照。
5. 人工看两门课：首帧、切屏、末帧、音频、移动端。
6. 更新文档里的版本号和兼容性说明。

如果契约测试失败，不要改课程外壳去适配；先在适配层做兼容，或者停留在旧版本。升级不是例行公事，是一次有回归风险的依赖变更。

### 9.9 本机一键启动与重建

双击脚本是第一次接触这个仓库的人唯一会用的入口，所以它不能停在「没有找到虚拟环境」；启动、重启和重建共用同一套环境准备。三层各管一件事：

```text
start.cmd / restart.cmd / build.cmd   GBK 编码的批处理，只负责：
  └─ call scripts\env.cmd             1. 找系统 Python 3.11+（py -3.13 / -3.12 / -3.11 / python / python3）
                                      2. 调 bootstrap.py：没有 .venv 时用系统 Python，有 .venv 时用虚拟环境 Python
  └─ .venv\Scripts\python.exe
       ├─ scripts\launcher.py         start / restart：端口、进程、运行记录；准备环境必须在它之前完成
       └─ scripts\build.py            build：每次完整重建（后端检查、运行时/字体、迁移、课程）
```

`scripts/env.cmd` 只管「找到能跑 Python 的解释器」；`scripts/bootstrap.py` 用标准库实现全部检查，每一步先看产物是否就绪，再决定是否执行：

| 步骤 | 就绪判据 | 缺失时执行 |
| --- | --- | --- |
| 虚拟环境 | `.venv\Scripts\python.exe` 存在且版本不低于 3.11 | `python -m venv .venv` |
| 项目依赖 | 在 `.venv` 里能 import 运行期模块 | `pip install -e ".[dev]"` |
| 播放器资源 | `runtime/vendor/` 两个文件 + `runtime/VERSION.json` + 每门课的 `assets/vendor/gsap.min.js` | `npm install`（缺 `tools/node_modules` 时）+ `sync_runtime.py --skip-fonts` |
| 课程产物 | `dist/courses/` 与 `dist/build.json` | `build_courses.py --all` |
| 数据库 | `alembic upgrade head` 幂等，直接执行 | 同左 |

约定：

- 准备逻辑只用标准库，因为第一次运行时 `.venv` 和依赖都还不存在，只能由系统 Python 执行。
- 已在 `.venv` 里运行时不再探测解释器版本（直接读 `sys.version_info`），模块检查走 `importlib.util.find_spec`，就绪机器上整轮检查只有一次 `alembic` 子进程。
- `--skip-fonts` 沿用 `runtime/VERSION.json` 里已记录的字体哈希：双击启动不是创作流程，字体子集仍由作者改完文案后手动跑 `sync_runtime.py` 重建。
- 本机迁移只属于双击启动器；生产仍然在部署时执行 `alembic upgrade head`，不在应用启动时迁移（见 12.3）。
- 失败一律以「原因 + 一条下一步」的中文提示收尾，批处理让窗口停住，不闪退。

`build.cmd` 是「改完之后重建」的双击入口，和 `start.cmd` 共用同一套环境检查：先 `call scripts\env.cmd` 保证 `.venv` 与依赖可用，再由 `scripts/build.py` 每次都完整执行四步：

1. `import app.main` 检查后端依赖与模块导入，尽早暴露坏代码；
2. 完整版 `sync_runtime.py`（不带 `--skip-fonts`，按最新课程/站点文案重新生成字体子集，并同步令牌与 vendor）；
3. `alembic upgrade head`，让随后的课程构建读到当前的水印表；
4. `build_courses.py --all`，重建全部已发布课程包；`--site-url` 取自 `start.cmd` 的 `APP_PORT`/`APP_HOST`，保证本地端口上的进度同步同源。

与 `bootstrap.py` 的「缺什么补什么」相反，它每次都重建，因为目标就是拾取改动；构建本身仍只写 `dist/`、SQLite 和字体子集等生成物。`python scripts/build.py --course <slug>` 可以只重建一门课，`--site-url` 可以覆盖部署地址。

---

## 10. 数据模型与 API

### 10.1 模型关系

```text
CourseSource 1 ─── * ScreenMeta
      │
      │ resolve（与 composition 合并）
      ▼
ResolvedCourse 1 ─── * ResolvedScreen
      │
      └── CompositionInfo
```

`CourseSource` 是编辑视图；`ResolvedCourse` 是运行视图。站点卡片用 `CourseSummary`，课程页和 API 用 `ResolvedCourse`。

### 10.2 API

`GET /api/courses`：

```json
{
  "courses": [
    {
      "slug": "what-is-a-token",
      "title": "AI 眼中的文字",
      "subtitle": "从 token 开始，理解大模型如何阅读",
      "summary": "一句话被切成 token 之后，模型才真正开始工作。",
      "level": "beginner",
      "tags": ["LLM", "token"],
      "accent": "#E4572E",
      "coverUrl": "/courses/what-is-a-token/cover.webp",
      "courseUrl": "/courses/what-is-a-token/",
      "screenCount": 8,
      "durationSeconds": 132,
      "estimatedMinutes": 3,
      "featured": true
    }
  ]
}
```

`GET /api/courses/<slug>`：返回完整 `ResolvedCourse`，包含 `screens[].start`、`duration`、`transcript` 等字段。

`GET /api/progress/{course_slug}`：返回当前匿名/登录用户的进度；无会话返回空进度，不创建用户。

`PUT /api/progress/{course_slug}`：写入 `{screenId, completed?}`；同源请求；写入前校验课程和屏幕存在。

`GET /api/health`：

```json
{
  "status": "ok",
  "published": 3,
  "drafts": 1,
  "unbuilt": 0,
  "db": {"ok": true, "schemaVersion": "0003"},
  "errors": []
}
```

课程 API 是只读的；进度 API 是唯一的写入口，只写用户状态。没有账号注册/登录接口（v1）。所有写接口都要限制请求体大小、校验 slug/screen id、检查 `Origin`；未来登录接口再加 CSRF 和速率限制。

### 10.3 数据库模型

```text
users 1 ─── * sessions
  │
  └─ 1 ─── * course_progress 1 ─── * screen_progress

course_imports（导入来源登记，与用户/进度无关）
```

- `users`：匿名用户和未来注册用户共用；`is_anonymous` 区分。
- `sessions`：匿名/登录会话；只存 token 哈希。
- `course_progress`：每用户每课程一行，记录 `last_screen_id`、完成时间。
- `screen_progress`：每用户每课程每屏一行，记录完成时间。
- `course_imports`：每 slug 一行，记录导入来源路径、来源哈希、内容哈希和导入时间；课程内容不在库里，课程目录仍以 `dist/` 为准。

课程包仍然是静态的；进度通过站点 API 读写，不进入课程包。没有数据库时，课程页退回 `localStorage`，课程继续独立部署。导入来源记录同理：数据库不可用时导入照常完成，只是不记来源。详细字段、匿名会话、迁移和备份见 7.9–7.10。

---

## 11. 测试策略

### 11.1 测试金字塔

| 层 | 测什么 | 工具 |
| --- | --- | --- |
| 单元 | 清单校验、composition 解析、时间合并、slug/URL 规则、进度仓库 | pytest |
| 契约 | player 的 range/ended/seek 行为、适配层降级 | Playwright（Python） |
| 集成 | 构建产物文件、静态服务、课程/进度 API、SQLite 迁移 | pytest + TestClient |
| 端到端 | 站点 → 课程 → 切屏 → 讲义 → 完成 → 进度 | Playwright（Python） |
| 独立部署 | 普通静态服务器上的课程包（无 API/数据库） | Playwright（Python）+ `http.server` |
| 视觉 | 每屏代表帧、首帧、末帧 | `hyperframes snapshot` + 人工/截图对比 |
| 无障碍 | 键盘、焦点、axe、减少动态效果 | Playwright（Python）+ axe |
| 性能 | 首屏、首帧、请求数、包大小 | Playwright（Python）/Lighthouse |

### 11.2 必须存在的测试

1. `test_resolver`：正常合并；缺屏幕元数据；多出屏幕元数据；重复 id；时间倒序；时间重叠；超出根时长；scene 文件缺失；scene id 不匹配。
2. `test_build`：构建输出文件齐全；排除 `node_modules`；解析后的 `course.json` 时间正确；构建幂等；同源/分离部署的 `progressEndpoint` / `progressOrigin` 注入正确。
3. `test_progress`：匿名会话创建；GET 不创建用户；PUT upsert；未知课程/屏幕拒绝；cookie 过期；重复写入幂等。
4. `test_migrations`：空库升到 head；迁移后关键表/索引存在；备份文件可打开。
5. `test_player_contract`：两屏 fixture；设置 range；播放到 `ended`；切换到第二屏；`seek` 后播放；错误路径。
6. `test_standalone`：静态服务器上的课程包可以完成“开始 → 下一屏 → 讲义”，不需要 API/数据库；目录能打开、按顺序列出每屏标题，点任意一屏跳到那一屏并播放，当前屏高亮；播放页占满视口、无页面滚动、控制条通栏；拖动当前屏进度后画面跟随、松手恢复；「跳到最后」与 `End` 停在末帧并标记讲完。
7. `test_site`：首页、课程库、过滤、404、课程链接。
8. `test_a11y`：课程页无严重 axe 问题；键盘可以完成主流程。
9. `test_no_external`：构建产物没有外部资源加载（允许引用链接）。
10. `test_budget`：首屏和总大小不超预算。
11. `test_import` / `test_new_course`：外部课程文件夹校验、staging 构建、原子落盘、失败回滚；占位 slug / 保留 slug / 目标已存在 / 覆盖导入 / 原地重建；`course_imports` upsert；从 `course-template/` 生成可构建脚手架。
12. `test_course_template`：模板包结构齐全、无外部资源、复制并改 slug 后可解析与构建、作者文档指引齐全。
13. `test_import_web`：`/import` 的 GET/POST、收件箱候选与校验状态、路径逃逸拒绝、prod/未启用时 404、导入后目录与数据库记录。
14. `test_bootstrap`：就绪机器只跑一次迁移、不重复安装；缺 `.venv` / 依赖 / 播放器资源 / `dist/` 时分别补齐；缺 Python 3.11+ 或 Node.js 22+ 时给出带下载地址的中文提示；`start.cmd` / `restart.cmd` / `stop.cmd` 保持 GBK 并走同一套环境准备。
15. `test_build_script`：一键构建的后端检查 → 字体/令牌同步 → 迁移 → 课程构建四步顺序；`--site-url` 默认取自 `start.cmd`、可显式覆盖；`--course` 只重建指定课程；任一步失败即中止；`build.cmd` 以 GBK 包装 `env.cmd` 与 `build.py`。

### 11.3 测试数据

- `tests/fixtures/courses/valid-two-screen/`：最小合法课程，两屏，2 秒一屏，纯色/文字，不依赖外部素材。
- `tests/fixtures/courses/invalid-*`：每个错误一个 fixture，断言错误码和错误字段。
- 样板课本身也是回归测试对象，但不要把所有课程都塞进单元测试；课程级检查用构建流水线。

### 11.4 人工验收

自动化测不出“讲得好不好”。每门课发布前至少人工看三遍：

1. **第一遍，当学习者。** 不看脚本，是否能跟上？哪一屏走神？
2. **第二遍，当审稿人。** 每屏的中心论题是否只有一个？字幕/正文是否有错别字？术语第一次出现是否解释？
3. **第三遍，当挑刺的人。** 暂停在任意一帧是否可读？最后一帧是否稳定？手机横屏是否能用？键盘是否顺手？

---

## 12. 部署

### 12.1 单机拓扑

```text
浏览器
  │
  ▼
Nginx / Caddy
  ├─ /static/*  ──▶ FastAPI 或静态目录
  ├─ /courses/* ──▶ FastAPI StaticFiles 或静态目录
  └─ /*         ──▶ FastAPI (uvicorn)
                         │
                         ▼
                   SQLite data/app.db
```

一个 Python 进程、一个 `dist/` 目录、一个 SQLite 文件。适合早期和小规模；SQLite 用 WAL，应用默认单 worker。需要多实例时先迁移到 Postgres。

### 12.2 分离拓扑

```text
浏览器
  ├─ 站点页面 + API + SQLite ──▶ FastAPI（站点主机）
  └─ 课程包 / 静态资源       ──▶ CDN / 对象存储
```

课程包是纯静态的，可以独立部署、独立缓存、独立回滚。站点保留课程目录所需的解析清单（`dist/courses/*/course.json`，通常只有几 KB）、SQLite 和进度 API；课程资源和页面走 CDN。`COURSE_BASE_URL` 指向 CDN。分离部署默认不注入同源进度接口，课程页只使用本地进度；要开同步就得处理 CORS 和 Cookie 策略，v1 不做。

### 12.3 容器

- 基础镜像：`python:3.12-slim`。
- 只安装运行时依赖：fastapi、uvicorn、jinja2、pydantic-settings、sqlalchemy、alembic。
- 拷贝 `app/`、`dist/`、`alembic.ini`、`migrations/`。
- `data/` 用 volume 挂载；`DATABASE_URL` 指向 volume 里的文件。不要把数据库文件放进镜像；volume 属主给运行用户。
- 部署时执行 `alembic upgrade head`，再启动应用；不在应用启动时自动迁移。
- 不安装 Node、Chrome、FFmpeg。构建在 CI 完成。
- 健康检查：`GET /healthz`；就绪检查：`GET /readyz`（含 DB 和 schema version）。
- 静态文件可以由 Nginx 直接服务，减少 Python 进程的 I/O。

### 12.4 可观测性

- 结构化日志：启动时记录课程数量、构建版本、错误数量、DB schema version；请求日志记录路径、状态码、耗时。
- `/healthz` 只检查进程；`/readyz` 检查数据库连接和迁移版本；`/api/health` 检查目录、构建状态和 DB。
- 不在日志里打印课程讲义全文、密码、会话 token 或完整进度。
- 每天备份 SQLite（`VACUUM INTO` 或 backup API），保留 7–30 天；迁移前额外备份一次。
- 回滚：镜像/`dist/` 回滚 + 数据库迁移只能向前兼容；破坏性迁移先备份，必要时用备份恢复。不要假设“回滚镜像就能回滚 schema”。

---

## 13. 风险与缓解

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| player 的 range 接口在升级后变化 | 切屏失效，课程卡在第一屏 | 适配层 + 契约测试 + 固定版本；必要时降级为 seek + 时间监听 |
| 一门课 composition 过大 | 首屏慢、内存高、scene 故障影响全课 | 预算、懒加载、15 屏/50MB 拆分阈值 |
| 手机竖屏文字不可读 | 移动端学习体验差 | 横屏提示 + 讲义模式；不承诺竖屏动画 |
| 中文字体太大 | 首屏慢 | 子集化、预加载、单字体多字重；预算检查 |
| 自动播放被拦截 | 有音频的课程首屏无声 | 显式开始手势、静音回退、声音按钮 |
| 构建解析 HTML 太脆弱 | 构建失败或时间错误 | 固定根结构、`html.parser`、单元测试、严格报错 |
| SQLite 写入锁/多实例 | 写入失败或响应变慢 | WAL、短事务、`busy_timeout`、单 worker；多实例前迁移 Postgres |
| SQLite 文件损坏/误删 | 用户进度丢失 | 每日备份、迁移前备份、恢复演练、volume 权限 |
| 匿名会话被滥用 | 空用户/垃圾进度 | GET 不创建用户、请求体限制、Origin 检查、会话过期；未来加速率限制 |
| 登录功能引入安全问题 | 账号泄露 | Argon2id、HttpOnly Cookie、CSRF、速率限制、会话轮换；上线前做安全评审 |
| 课程内容“动画很炫但没讲清” | 产品失去意义 | 课程契约 + storyboard 评审 + 逐屏“一句话论题”检查 |
| 范围蔓延成通用 LMS | 进度停滞 | 非目标清单；v1 只做课程和目录 |
| 第三方许可证 | 发布风险 | 随包分发 LICENSE；发布前核对 GSAP/字体授权 |
| Safari 的 iframe/媒体差异 | 部分用户播放异常 | 目标浏览器测试；player 已处理部分 Safari 特例；保留降级页 |

---

## 14. 开放问题

下面这些问题不影响当前架构，但需要在实现前定下来。括号里是默认建议。

| 问题 | 默认建议 |
| --- | --- |
| 项目正式名称和视觉识别 | 已定：站点叫「页间课堂」，AI Learning 是第一个课程系列；视觉沿用暖纸印刷系统 |
| 第一门样板课的主题 | “什么是 token”，6–8 屏，2–3 分钟 |
| 是否需要语音讲解 | v1 不做；先保证文字和动画；音频能力保留 |
| 是否需要账号/登录 | v1 只做匿名会话和进度；“注册/登录/跨设备”作为下一阶段，SQLite schema 已按可登录设计 |
| 数据库是否随 v1 发布 | 是；SQLite + Alembic，先支撑匿名进度，再长出账号 |
| 移动端优先级 | 桌面/横屏优先；竖屏讲义模式 |
| 部署目标 | 先单机 Docker；课程包可直接上 CDN |
| 是否允许课程自定义外壳 | v1 不允许；用封面、强调色和文案做区分 |
| 课程长度 | 6–10 屏，2–5 分钟；超过 15 屏考虑拆系列 |

---

## 附录 A：路由总表

| 路径 | 类型 | 说明 |
| --- | --- | --- |
| `/` | 动态 | 首页 |
| `/courses` | 动态 | 课程库 |
| `/courses/` | 重定向 | → `/courses` |
| `/about` | 动态 | 方法论 |
| `/courses/<slug>/` | 静态 | 课程页 |
| `/courses/<slug>/composition/...` | 静态 | composition 资源 |
| `/courses/<slug>/runtime/...` | 静态 | 课程外壳运行时 |
| `/import` | 动态（仅开发环境） | 课程导入页：收件箱候选、校验状态、最近导入 |
| `/api/courses` | JSON | 课程摘要 |
| `/api/courses/<slug>` | JSON | 课程详情 |
| `/api/progress/<course_slug>` | JSON | 当前用户进度（GET/PUT） |
| `/api/progress` | JSON | 当前用户全部进度 |
| `/healthz` | JSON | 进程健康 |
| `/readyz` | JSON | DB 连接和 schema 版本 |
| `/api/health` | JSON | 目录、DB、构建健康 |

## 附录 B：术语

| 术语 | 含义 |
| --- | --- |
| 课程（Course） | 一个独立的教学单元，有封面、若干屏、一个 URL |
| 屏（Screen） | 一次讲解占据一个屏幕的节拍；对应 composition 里的一个 scene |
| 课程包（Bundle） | 构建后可以独立部署的静态目录 |
| composition | HyperFrames 工程；根 `index.html` 挂载所有 scene |
| scene | 一个屏幕的动画文件，位于 `composition/compositions/` |
| 课程外壳（Deck） | 课程页上负责封面、切屏、控制、讲义的 JS/CSS |
| 播放器（Player） | `<hyperframes-player>` web component，负责 iframe 和 runtime |
| runtime | 注入 composition、驱动 GSAP 时间轴的脚本 |
| 解析后清单（Resolved manifest） | 合并了编辑信息和 composition 时间的 `course.json` |
| 独立部署 | 课程包放在普通静态服务器上，不依赖 FastAPI、数据库或登录态 |
| SQLite | 站点侧的单文件数据库，存用户、会话和进度 |
| 匿名会话 | 没有登录、但有一个稳定 ID 来保存进度的会话；可升级成账号 |
