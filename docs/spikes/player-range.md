# Spike：`<hyperframes-player>` 的 range 行为

> 日期：2026-11-07 · HyperFrames 0.9.19 · Chromium（Playwright，系统 Chrome）
> 对应阶段：Phase 3a（播放器适配层）

## 结论

`range-start` / `range-end` 在 0.9.19 上可用，**不需要降级成自建时钟**。

- 设置 `range-start` / `range-end` 后调用 `play()`，播放器会从 `range-start` 开始播，在 `range-end` 停下，并派发一次 `ended`。
- `ended` 触发时 `currentTime` 停在 `range-end` 附近（2 秒屏实测 2.0 左右，容差 < 0.05s）。
- `seek(start)` 之后再 `play()` 能立刻进入新 range；适配层用「第一个落进新 range 的 `timeupdate`」撤转场遮罩，实测 < 100ms，远低于 600ms 上限。
- `ready` / `painted` 只在加载期触发一次，**不能**当作每次切屏的信号；切屏以 `timeupdate` 为准。
- `rangeclamped` 会在 range 超出根时长时触发，`detail` 带 `{rangeStart, rangeEnd, duration}`。

## 实测到的两个坑

1. **属性写入顺序**：先写 `range-start` 再写 `range-end`，中间会出现 start > end 的瞬间，播放器会 clamp 并回写。适配层固定先写 `range-end`、再写 `range-start`，并记住上一次的 range，避免重复写属性触发重新加载。
2. **`window.__timelines` 的初始化时机**：根 composition 的脚本可能比 runtime 先跑。根 composition 里要写
   `window.__timelines = window.__timelines || {};`，否则会报
   `Cannot set properties of undefined (setting 'main')`。这是实际踩到的错误，已经写进 `course-template/` 和课程契约。

## 适配层接口（`runtime/course-deck.js`）

```text
createPlayerAdapter(el) -> {
  load({ src, runtimeSrc, poster }),
  setRange(start, end),          # 先 end 后 start，并去重
  seek(seconds), play(), pause(),
  get time / duration / ready / painted,
  on(event, handler), destroy()
}
```

课程外壳只通过这一层调用播放器，不直接读写 range 属性，也不碰 shadow DOM。

## 覆盖这个结论的测试

`tests/e2e/test_standalone.py`：

- `test_start_plays_first_screen`：开始后进入 playing 状态。
- `test_ended_fires_at_range_end`：2 秒屏自然播完，`is-ended` 出现，`currentTime` 落在 1.5–2.6s。
- `test_next_and_prev_switch_screens`：切到第二屏再切回第一屏。
- `test_standalone_bundle_makes_no_external_requests`：无外部请求、无 console error。

## 尚未验证

- Safari / Firefox：`<hyperframes-player>` 内部的 iframe 与媒体行为不同，需要单独跑一轮。
- 长 range（> 5 分钟）与低帧率设备上的 `ended` 精度。
- 音频课程在用户手势解锁后的 range 行为。
