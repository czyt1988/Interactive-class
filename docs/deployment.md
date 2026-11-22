# 部署与发布

两种发布方式：把 FastAPI 站点跑在服务器上（有后台、进度 API 和视频生成），或导出静态目录发布到 GitHub Pages（只读公开站）。课程包本身是静态的，两种方式共用同一份构建产物。

## 单机部署

单机拓扑是一个 Python 进程、一个 `dist/` 目录和一个 SQLite 文件，前面可以放 Nginx 或 Caddy：

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

部署步骤：

```bash
pip install -e .                         # 只装运行时依赖，不装 dev
python scripts/sync_runtime.py           # 播放器 / 运行时 / GSAP / 字体
python scripts/build_courses.py --all    # 构建到 dist/
alembic upgrade head                     # 迁移数据库
python -m uvicorn app.main:app --host 0.0.0.0 --port 8080
```

构建在部署前完成，生产镜像或服务器不需要 Node、Chromium 和 FFmpeg；只有启用后台在线生成视频时才需要它们，见[后台与运维](admin.md#服务器前提)。

生产环境至少检查这些变量（完整清单见 `.env.example`）：

| 变量 | 生产值 | 作用 |
| --- | --- | --- |
| `ENV` | `prod` | 关闭开发页面，启用生产行为 |
| `SITE_URL` | 公开地址 | 规范链接、sitemap、课程分享地址 |
| `SITE_BASE_PATH` | `/` 或子路径 | 站点挂了子路径时填写；根路径留空 |
| `DATABASE_URL` | `sqlite:////绝对路径/app.db` | 数据库放到持久化目录，不要放进代码目录 |
| `ADMIN_TOKEN` | 强随机值 | 公网必填；留空等于后台不设防 |
| `SESSION_COOKIE_SECURE` | `1` | HTTPS 下设 Secure Cookie |
| `STRICT_CATALOG` | `1` | 课程清单有问题时启动失败，而不是静默跳过 |
| `VERIFY_COURSE_BUNDLES` | 单机 `1`，分离部署 `0` | 启动时是否校验本机课程包 |

运维要点：

- SQLite 开 WAL，应用默认单 worker；需要多实例时先迁移到 Postgres。
- 迁移只在部署阶段执行，不在应用启动时自动跑。
- `/static/*` 和 `/courses/*` 交给 Nginx 直接服务可以减轻 Python 的 I/O。
- 健康检查：`/healthz` 只检查进程，`/readyz` 检查数据库连接和迁移版本，`/api/health` 返回目录、DB 和构建状态。
- 单机拓扑的决策和容器化要点见[架构设计](architecture.md) 12.1 和 12.3。

## 发布到 GitHub Pages

站点主体是 FastAPI 应用，而 GitHub Pages 只能托管静态文件，所以发布的是**静态导出版**：首页、课程库、关于、404，加上每门课的静态包。`scripts/export_site.py` 用真实应用把这几页渲染一次，再逐条检查站内引用；`.github/workflows/pages.yml` 在每次推送 `main` 时构建并发布。

这份产物**没有**：后台 `/admin`、`/api/progress` 进度同步、视频生成、片头预览。课程页的进度存在浏览器 `localStorage`；课程水印是部署方身份信息，不会出现在公开产物里。需要这些能力时用上面的单机部署。

一次性准备：

1. 在 GitHub 建一个仓库（免费计划的 Pages 要求仓库公开），把 `main` 推上去。
2. 仓库 Settings → Pages → Source 选 **GitHub Actions**。
3. 推送 `main`，或在 Actions 里手动运行「发布到 GitHub Pages」。

地址按仓库名自动推导：仓库不是 `<owner>.github.io` 时，站点在 `https://<owner>.github.io/<repo>/`，脚本自动加 `/<repo>` 前缀；用户页仓库（`<owner>.github.io`）不加前缀。需要覆盖时，在 Settings → Variables 里设 `SITE_URL`、`SITE_BASE_PATH`；自定义片头/片尾模板的项目地址用 `PROJECT_URL`，自带的通用片头和片尾直接写死 GitHub 与 Gitee 两个地址。自定义域名写成 `SITE_URL=https://learn.example.com` + `SITE_BASE_PATH=/`（`/` 表示根路径）。

本地先看效果：

```bash
python scripts/sync_runtime.py
python scripts/export_site.py --site-url https://example.github.io --base-path ""
python scripts/serve.py dist/site --port 8081
```

带子路径的产物（`--base-path /interactive-class`）里，链接以 `/interactive-class/...` 开头，导出脚本会验证每条引用都落在 `dist/site` 里；直接用 `http.server` 服务根目录时这些链接打不开，属于预期。

片头/片尾：后台选择存在 SQLite 的 `course_clips` 表，CI 读不到，所以公开站用提交在 `deploy/publish.json` 里的选择：

```json
{
  "clips": {
    "ai-first-sees": { "intro": "intro-title-page" }
  }
}
```

本地点一次后台预览确认效果，再提交这份配置；不想要片头就删掉对应条目。

静态发布的完整流程、链接检查和子路径规则见[架构设计](architecture.md) 9.10 和 12.5。

## 课程更新与缓存

- **更新课程**：改 `courses/<slug>/`，跑 `python scripts/build_courses.py --course <slug>`；站点下一次请求读新的 `dist/` 清单，不需要重启。改水印或片头片尾时，后台保存会自动重建这一门课。
- **缓存**：站点给课程页和课程包发 `Cache-Control: no-cache`，只有固定版本的 player 文件是长缓存。前面有 Nginx、CDN 或对象存储时，确认它们没有覆盖缓存头；如果覆盖了，课程更新后要手动刷新对应路径。
- **视频**：课程重新构建后内容哈希变化，已生成的旧视频会被标记为过期，重新生成即可；旧文件不会自动删除。
- **回滚**：切回上一版课程源或旧 `dist/` 重建。课程包是静态目录，回滚一门课不影响其他课程和数据库。

## 备份与回滚

- **数据库**：每天备份 SQLite（`sqlite3 data/app.db ".backup 'data/backups/app-<timestamp>.db'"` 或 `VACUUM INTO`），保留 7–30 天；迁移前额外备份一次。
- **恢复演练**：把备份复制到临时目录，跑一次 `alembic current` 和关键查询，确认能用再放回。
- **课程产物**：`dist/` 可随时重建；回滚时换回上一版 `dist/` 或重新构建对应提交。
- **迁移**：数据库迁移只向前兼容。不要假设回滚镜像就能回滚 schema；破坏性迁移先备份，必要时用备份恢复。
- **视频**：`data/videos/` 不进 Git、不参与构建，可以整目录删除或按课程删除，需要时重新生成。

可观测性和备份策略见[架构设计](architecture.md) 12.4。
