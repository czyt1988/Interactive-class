# 文档导航

根目录的 [README](../README.md) 只保留产品入口、快速开始和主要链接；操作细节和规则放在 `docs/` 下，按任务找一份读。

## 第一次接触

| 文档 | 什么时候读 |
| --- | --- |
| [产品说明](product.md) | 想知道项目为什么存在、课程长什么样、为什么不用 MP4 |
| [快速开始](getting-started.md) | 第一次在本机跑起来；Windows 双击启动、端口和常见故障也在这里 |

## 开发平台

| 文档 | 什么时候读 |
| --- | --- |
| [开发指南](development.md) | 目录结构、日常构建与测试、git 工作树并行开发、提交 |
| [架构设计](architecture.md) | 系统边界、关键决策、运行时、构建、部署和风险 |
| [前端设计契约](../DESIGN.md) | 视觉、文案、动效和课程 composition 的唯一准则 |
| [Agent 开发方案](agent-development-plan.md) | 分阶段计划、验收标准、每门新课的生产模板 |

## 写课程

| 文档 | 什么时候读 |
| --- | --- |
| [添加与导入课程](course-authoring.md) | 从脚手架到上线，以及把外部课程带进课程库 |
| [课程契约](course-contract.md) | `course.json` 字段、目录、时间规则、错误码和验收清单 |
| [课程模板包](../course-template/README.md) | 交给外部作者或 AI 的独立课程骨架 |
| [片头片尾模板库](../clips/README.md) | `clip.json` 字段、scene 规则和占位符 |

## 后台与发布

| 文档 | 什么时候读 |
| --- | --- |
| [后台与运维](admin.md) | 视频生成、课程水印、片头片尾，以及后台依赖和配置 |
| [部署与发布](deployment.md) | 单机部署、GitHub Pages 静态发布、备份与回滚 |
| [版本记录](release-notes.md) | 当前版本、历史版本和 v1.0 方向 |
| [播放器 range spike](spikes/player-range.md) | 早期对 HyperFrames 播放器 range 行为的技术验证 |

## 文档约定

- **README 只做入口**：新的细节写进 `docs/` 下最贴近任务的一份，不再往 README 里堆。
- **一份文档解决一类任务**：产品理念在 `product.md`，操作步骤在对应的任务文档，规则细节在 `architecture.md` 和 `course-contract.md`。
- **改命令、路径、字段时同步改文档**：同一提交里更新引用；移动文档时检查 README、AGENTS.md 和代码里的链接。
- **课程作者优先读课程模板包**：`course-template/AGENTS.md` 和 `COURSE-CONTRACT.md` 是给外部作者的独立文档，不要求他们克隆整个平台仓库。
- **文档里的相对链接要能点开**：新增或移动文件后跑 `pytest -q tests/test_docs_links.py`。
