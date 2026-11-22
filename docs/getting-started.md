# 快速开始

第一次在本机把站点跑起来、改完代码后重新构建，都从这里开始。项目结构和并行开发规则见[开发指南](development.md)。

## 环境要求

- **Python 3.11+**：站点、构建脚本和测试都运行在它上面。
- **Node.js 22+**：只在第一次同步播放器资源（`npm install` + `sync_runtime.py`）和创作课程时用到；站点运行时不依赖 Node。
- **Playwright Chromium**：只有跑浏览器验收（`pytest` 里的 e2e）时才需要，用 `python -m playwright install chromium` 安装。
- **FFmpeg / Chromium**：只有后台在线生成课程视频时才需要，见[后台与运维](admin.md#服务器前提)。

## 首次安装

在仓库根目录：

```bash
python -m venv .venv
.venv\Scripts\activate                 # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"

cd tools && npm install && cd ..       # 固定版本的 HyperFrames + GSAP，只用于创作和同步
python scripts/sync_runtime.py         # 把 player / runtime / GSAP / 字体布置到 runtime 和课程

python scripts/build_courses.py --all  # 生成 dist/courses/<slug>/
alembic upgrade head                   # 建 SQLite 表
python -m uvicorn app.main:app --reload          # http://127.0.0.1:8000
```

Windows 上不想逐条敲命令也没关系：直接双击 `start.cmd`，它会把上面的准备自动做完再启动；改完项目后双击 `build.cmd` 重新构建，再双击 `start.cmd` 就是最新版本。

## 启动与验收

```bash
python -m uvicorn app.main:app --reload                              # 开发服务器
pytest -q                                                            # 单元 + 集成 + 浏览器验收
ruff check .                                                         # 代码检查
python scripts/serve.py dist/courses/ai-first-sees --port 8081       # 课程包独立部署验收
```

> 在 Windows 上用 `python -m http.server` 打开课程包时，`.js` 可能被注册表映射成 `text/plain`，浏览器会拒绝执行 ES module。用 `scripts/serve.py` 验收，它固定了课程包需要的 MIME 类型。

跑不了浏览器验收时用 `pytest -q -m "not e2e"`；报告里要写清楚哪一项没有验证、为什么。完整的验证矩阵见[开发指南](development.md#每次改动跑什么)。

## Windows 双击启动

仓库根目录下的四个脚本面向双击使用（文件以 GBK 保存，匹配中文 Windows 控制台；编辑时请保持 GBK/ANSI 编码，不要另存为 UTF-8）：

| 脚本 | 作用 |
| --- | --- |
| `start.cmd` | 启动站点，默认监听 `0.0.0.0:8081`；第一次双击会自动准备环境 |
| `build.cmd` | 重新构建整个项目：后端导入检查、运行时/字体/令牌同步、数据库迁移、全部课程包 |
| `restart.cmd` | 先停掉正在运行的实例，再按 `start.cmd` 的配置重启 |
| `stop.cmd` | 停止服务 |

**第一次使用只需要双击 `start.cmd`。** 它会先调用 `scripts\env.cmd` 检查环境，缺什么补什么，再交给 `scripts\launcher.py` 启动：

1. 找到本机的 Python 3.11+（找不到时打印下载地址）；
2. 创建 `.venv` 虚拟环境；
3. 安装项目依赖（`pip install -e ".[dev]"`）；
4. 下载固定版本的播放器资源并同步（`npm install` + `python scripts/sync_runtime.py --skip-fonts`）；
5. 构建课程包到 `dist/`；
6. 建好或升级 SQLite 表结构（`alembic upgrade head`）。

这一步要联网，第一次通常几分钟；之后每次双击只做几秒钟的检查，已经就绪的步骤会跳过。开始之前需要 Python 3.11+，第 4 步还需要 Node.js 22+（只在第一次下载播放器资源时用到，之后就绪后启动不再需要 Node）。任何一步失败都会用中文说明原因和下一步怎么做，窗口不会立刻关掉，可以照着提示处理后重新双击。

**改完项目后只需要双击 `build.cmd`。** 它和 `start.cmd` 共用同一套环境检查，然后每次都完整重建，不会因为上次的产物还在就跳过：

1. 检查后端依赖与代码（`import app.main`，缺依赖或模块坏了会先报出来）；
2. 运行完整的 `python scripts/sync_runtime.py`（播放器/运行时/GSAP、设计令牌、按最新课程文案重新生成字体子集）；
3. 执行 `alembic upgrade head` 更新 SQLite 表结构（课程构建要读水印与片头片尾配置）；
4. 运行 `python scripts/build_courses.py --all`，重建全部已发布课程到 `dist/`；课程页里的站点地址自动对齐 `start.cmd` 的 `APP_PORT`，所以本地进度同步仍然有效。

看到「构建完成」后，双击 `start.cmd` 启动最新版本；站点正在运行就双击 `restart.cmd`。构建只写 `dist/`、SQLite 和字体子集这些生成物，不会把产物提交进 Git。

端口和绑定地址写在 `start.cmd` 开头，改这两行后保存即可：

```text
set "APP_PORT=8081"
set "APP_HOST=0.0.0.0"
```

`0.0.0.0` 表示本机和局域网都能访问；只想本机访问就改成 `127.0.0.1`。启动后直接访问 <http://127.0.0.1:8081>。重启会先读取 `.run/service.json` 里记录的当前实例，再按 `start.cmd` 的配置启动新实例；日志直接输出在脚本窗口里。也可以单独运行 `python scripts\bootstrap.py` 只做环境准备（或加 `--quiet` 检查一遍），准备完再双击 `start.cmd` 启动。

## 本机起不来时

- **端口被占用**：改 `start.cmd` 里的 `APP_PORT`，或先双击 `stop.cmd`。项目工作树里的站点用 `$env:APP_PORT=8082` 换端口，避免和主工作树抢 8081。
- **缺少依赖或模块导入失败**：双击 `build.cmd`，它第一步就是 `import app.main`，会给出具体缺什么。
- **课程包打不开或 JS 不执行**：确认是用 `scripts/serve.py` 或站点本身访问，而不是 `python -m http.server` 或双击 HTML 文件。
- **e2e 报浏览器不存在**：运行 `python -m playwright install chromium`。
- **数据库表结构落后**：运行 `alembic upgrade head`；`build.cmd` 每次都会执行这一步。
