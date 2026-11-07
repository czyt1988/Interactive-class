# AGENTS.md

这个仓库构建 **AI Learning**：一个用网页动画讲 AI 的教学平台。课程是自包含的静态包，站点是 FastAPI + Jinja2 的封面与目录。

## 先读这三份

1. [Agent 开发方案](docs/agent-development-plan.md) —— 唯一的执行计划：阶段、验收标准、每门新课的生产模板。
2. [架构设计](docs/architecture.md) —— 关键决策、运行时、构建、部署和风险。
3. [课程契约](docs/course-contract.md) —— 一门课必须长什么样，字段、目录、时间规则和验收清单。

## 不可协商

- 课程必须能作为独立静态包部署；没有 API、数据库或登录态也能完整播放。
- 主链路不输出 MP4，不使用 SPA 框架。
- 课程内容放在文件里；用户、会话和进度放在 SQLite。数据库属于站点，不属于课程包。
- 运行时不引用 CDN；player、runtime、GSAP、字体全部本地。
- 一门课一个 HyperFrames composition，一屏一个 scene。
- 课程任务只修改 `courses/<slug>/`，平台改动另开任务。
- HyperFrames 版本固定，升级要先跑播放器契约测试。

## 工作方式

- 一次任务只做一个阶段，完成该阶段全部验收项再结束。
- 不直接编辑 `dist/`；它是构建产物。
- 不自动 commit，除非用户明确要求。
- 结束前跑本阶段的验证命令，并报告“验证了什么、没验证什么”。
- 改变架构决策前，先更新架构文档的决策表。

## 当前状态

v0.2：平台骨架已经落地，第一门课已经可播放。

- 已有：FastAPI 站点（首页 / 课程库 / 关于 / 404 / API）、课程契约与解析器、构建流水线、课程外壳（封面、切屏、控制条、讲义、完成页、错误页）、SQLite + Alembic 匿名进度、Playwright 独立部署与播放器测试。
- 已有课程：`courses/ai-first-sees/`（「AI 第一次看懂世界」，9 屏 / 2:57）。
- 还没做：CI、Docker/部署、课程脚手架脚本、登录、搜索。

先跑一遍这三条，确认环境是通的：

```bash
python scripts/sync_runtime.py          # 布置 player / runtime / GSAP / 字体
python scripts/build_courses.py --all   # 生成 dist/courses/<slug>/
pytest -q && ruff check .
```
