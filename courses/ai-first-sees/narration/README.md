# 旁白与时间：这门课怎么重做

这门课（`courses/ai-first-sees`）是「一个 S 一页」的长视频课程。旁白不是附件，而是**时钟**：每页时长、字幕、根 composition 的 `data-start` / `data-duration` 都由旁白音频推导。

## 文本源

- `narration/scenes.json`：28 个 S 的最终文本与场景元数据（标题、幕、主题色、画面/动画备注、旁白）。全部场景 `theme: "paper"`，整门课浅色纸面。
- `narration/scenes.from-outline.json`：从 `courses-outline/ai-first-sees/outline.md`（29 镜头长版；S28 safety 已并入 S27，课程落地 28 屏）解析出的原始镜头表，供 `scripts/curate_narration.py` 重新生成 `scenes.json`。改镜头、删减页面只需要改大纲，然后重跑 curate。
- `narration/timings.json` / `narration/scenes.timed.json`：每页起止、音频时长与分句 cue 表（由 `build_narration.py` 生成，供场景作者对齐动效）。
- 事实口径以 `courses-outline/ai-first-sees/outline.md` 里的「事实/口径」小节为准。
- 真实素材（logo / 截图 / 照片）由 `scripts/prepare_course_media.py` 压缩进 `composition/assets/media/`，源文件在 `courses-outline/ai-first-sees/素材/`。

## 重做旁白（需要网络与可选依赖）

```powershell
# 一次性安装创作依赖（运行课程本身不需要）
.\.venv\Scripts\python.exe -m pip install edge-tts mutagen soundfile

# 1) 从大纲重新生成文本源（改口径/删改镜头后跑）
.\.venv\Scripts\python.exe scripts\curate_narration.py

# 2) 生成音频、句子时间、字幕、根 composition、course.json 和每页时间块
.\.venv\Scripts\python.exe scripts\build_narration.py

# 或复用 narration/cache 里已有的 TTS，只重算时间和字幕
.\.venv\Scripts\python.exe scripts\build_narration.py --no-tts

# 压缩大纲素材进课程包（需要带 Pillow 的 Python）
python scripts\prepare_course_media.py
```

### 改语速或音色

```powershell
# 语速必须是带符号的百分比（edge-tts 拒收不带符号的 "0%"）
.\.venv\Scripts\python.exe scripts\build_narration.py --rate "+0%"

# 也可以换音色；普通话候选见 edge-tts --list-voices
.\.venv\Scripts\python.exe scripts\build_narration.py --voice zh-CN-YunyangNeural --rate "+0%"
```

当前配置：`zh-CN-YunxiNeural`、`rate +0%`（约 5.6 字/秒，全片 29:54）。`narration/cache/` 的复用键包含 voice、rate 和旁白文本指纹，任意一项变了都会自动重新合成，只有完全一致才复用（`--no-tts` 也只接受完全匹配的缓存）。改完记得跑 `python scripts/build_courses.py --all` 重建 `dist/`。

产物：

- `composition/assets/audio/s<NN>-<id>.ogg`：一页一条旁白（OGG/Opus，约 6.9 MB / 30 分钟）。这是本地静态文件，播放时不需要网络，也不调用任何线上 TTS。
- `composition/assets/fonts/NotoSansSC-VF.woff2`：由 `scripts/sync_runtime.py` 按本课实际用字重新子集化。
- `composition/index.html`：根 composition，含每页 scene host 和每页一条 `<audio>`。
- `course.json`：每页 `transcript`、`autoAdvance`、`playback: "continuous"`。
- 每个 `composition/compositions/<NN>-<id>.html`：页面结构 + `<!-- CAPTIONS -->` 字幕块 + `// TIMING` 时间块。

**不要手改**上面这些生成内容（尤其 `data-start` / `data-duration` 和字幕时间）。改画面/动效时只改 scene 文件的 `<style>`、`.stage` 和 `// MOTION` 块。

## 视频导出

```powershell
$env:Path = "C:\src\ai-learning\tools\ffmpeg\bin;" + $env:Path   # 需要 ffmpeg / ffprobe
cd courses\ai-first-sees\composition
npx --yes hyperframes@0.9.19 render -o ..\renders\ai-agent-101.mp4 --quality looks
```

旁白字幕在 1920×1080 画布底部，音频是根 composition 里的 `<audio>`；导出的 MP4 带烧录字幕和声音，不需要后期再对轨。

## 视觉与动效

画面、动效规则、共享样式和每页 cue 表见 [`AUTHORING.md`](AUTHORING.md)。
