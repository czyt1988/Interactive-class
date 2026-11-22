# 添加与导入课程

课程是自包含的静态包：新增一门课只动 `courses/<slug>/`，不改站点代码。字段、目录和时间规则的完整定义在[课程契约](course-contract.md)，视觉规范在 [DESIGN.md](../DESIGN.md) 和课程模板包的 `STYLE.md`。

## 添加一门课程

1. 先生成脚手架：`python scripts/new_course.py <slug> --title "课程标题"`（从 `course-template/` 复制 `course.json`、`STORYBOARD.md`、`composition/`）。外部作者也可以拿整个 `course-template/` 按它的 `AGENTS.md` 生成，再用下面的导入流程带进来。
2. 写 `STORYBOARD.md`：每屏一句话，说明这一屏让学习者看见什么、动画如何论证。
3. 改 `course.json`：标题、承诺、目标、每一屏的文案；交付前把 `status` 改成 `published`。
4. 在 `composition/` 里用 HyperFrames 做每一屏的 scene，并在根 composition 里挂好时间。
5. 运行 `python scripts/build_courses.py --course <slug>`，打开两个地址验收：站点里的 `/courses/<slug>/`，以及 `python scripts/serve.py` 打开的同一个目录。

构建完成后，课程清单、封面、目录和 API 会自动更新。

课程任务只修改 `courses/<slug>/`；需要改站点、运行时或课程契约时，那是平台任务，另开一个工作树。

## 课程模板包

`course-template/` 是独立的课程模板包：两屏可构建骨架 + 给作者和 AI 的文档。它不放在 `courses/` 下参与构建，可以整个文件夹交给外部作者或其他 AI，放进 AI 的工作目录后由其中的 `AGENTS.md` 指引生成课程。

```text
course-template/
├─ AGENTS.md            # 给 AI 的操作指引：输入、流程、硬规则、自检、交付
├─ COURSE-CONTRACT.md   # 作者版规范：目录、字段、时间、资源、错误码
├─ STYLE.md             # 课程画面视觉规范（纸色、字阶、安全区、动效）
├─ course.json          # 合法占位清单（slug 仍是 your-course-slug）
├─ STORYBOARD.md        # 分镜脚手架
└─ composition/         # 根 composition + 两屏 scene + 本地字体 / GSAP
```

模板包的完整用法见 [course-template/README.md](../course-template/README.md)。

## 导入外部课程

外部作者产出的课程文件夹有两种方式进入站点。

### 方式一：收件箱导入（推荐）

把整个课程文件夹放进仓库根的 `course-inbox/`（该目录不进 Git），然后：

```bash
python scripts/import_course.py --inbox            # 批量导入收件箱
python scripts/import_course.py <课程文件夹>       # 只导入一个
python scripts/import_course.py --dry-run <文件夹>  # 只校验，不落盘
```

开发环境也可以打开 `/import` 页面：列出收件箱里的课程、校验状态和「导入」按钮，并显示最近导入记录；生产环境（`ENV=prod`）不开放这个页面。导入会先校验、再在隐藏临时目录里构建，全部通过才原子替换 `courses/<slug>/` 和 `dist/courses/<slug>/`，失败会回滚。成功后站点下一次请求就能看到新课，不用重启。

### 方式二：直接放进课程目录

复制成 `courses/<slug>/`（目录名必须等于 `course.json` 的 `slug`），运行：

```bash
python scripts/build_courses.py --course <slug>
```

也可以用 `python scripts/import_course.py courses/<slug>` 校验并原地重建。只校验不写产物：

```bash
python scripts/build_courses.py --course <slug> --check-only
```

导入成功后会在 SQLite 的 `course_imports` 表更新一条来源记录（slug、标题、来源路径、内容哈希、屏数、时长、导入时间）。课程内容仍然在文件里，数据库只记来源；表没迁移或数据库不可用时导入照常完成，只打印警告。

## 导入配置

完整说明见 `.env.example`：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `COURSES_INBOX_DIR` | `course-inbox` | 导入收件箱目录 |
| `COURSE_IMPORT_ENABLED` | `dev` 为 1，`prod` 为 0 | 是否开放 `/import` 页面 |

导入的字段、错误码和验收规则见[课程契约](course-contract.md) 7.7 和 9。

## 字体子集

模板自带的字体是预生成的字符子集；导入的课程如果用了子集外的新字，跑一次 `python scripts/sync_runtime.py` 会按课程文案重新生成子集。作者不要用 CDN 字体绕过，构建会拒绝外部资源。

## 有旁白的课程

长视频课程把旁白、字幕和每屏时长都写进 composition。文本源是 `courses/<slug>/narration/scenes.json`，`scripts/build_narration.py` 生成音频、时间与字幕，并重写根 composition、`course.json` 和每屏时间块。音频是本地 OGG/Opus 静态文件，播放不依赖网络。

当前样板课的流水线和命令见 [`courses/ai-first-sees/narration/README.md`](../courses/ai-first-sees/narration/README.md)。重跑旁白是串行步骤：它会写共享的 `courses/<slug>/narration/cache/`，不要多个工作树同时重建同一门课的旁白。
