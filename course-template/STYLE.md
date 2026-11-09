# 课程视觉规范（composition）

> 本文是平台 `DESIGN.md` 第 8 节和 `design/tokens.css` 的作者版摘要：写 scene 时按这里取值就够了。
> 完整规范以平台 `DESIGN.md` 为准；本文与之冲突时以平台为准。

## 1. 一句话总则

**亮色纸面、墨色文字、一个强调色、一屏一个论题。** 视觉为论证服务，不为装饰服务。

## 2. 纸面与墨色

场景是固定 1920×1080 的画布。场景根背景只能是纸色，文字只能用墨色系。scene 里直接写下面的色值（scene 不加载 `tokens.css`，这些值就是令牌的当前实现）：

| 用途 | 色值 | 说明 |
| --- | --- | --- |
| 场景底色 `--paper` | `#f4efe6` | 暖纸色，默认用它 |
| 纸面高一层 `--paper-raised` | `#faf6ee` | 卡片、证据卡表面 |
| 纸面深一层 `--paper-deep` | `#ece3d3` | 内嵌画板、分隔底；不放大段文字 |
| 主文字 `--ink` | `#16140f` | 暖近黑，非纯黑 |
| 次级文字 `--ink-soft` | `#514b40` | 正文、导语；纸面上约 7.5:1 |
| 元信息 `--ink-faint` | `#6b6355` | 小字、注释；纸面上 ≥ 4.5:1 |
| 常规线条 `--line` | `#d9cfbf` | 分隔线 |
| 强调线条 `--line-strong` | `#b9ad99` | 需要看得见的边框 |
| 装饰强调 `--accent` | `#b8452b` | 锈红：大标题、印章、下划线、短横线 |
| 强调文字 `--accent-text` | `#a33a20` | 小字用这个版本，约 5.76:1 |
| 柔和底纹 `--accent-soft` | `#f0d9cf` | 选中态、底纹 |
| 反白文字 `--accent-ink` | `#fff8f0` | 只放在实心强调色上 |

规则：

- **禁止深色场景、深色主题。** 所有课程都是亮色纸面，长课也一样。
- 不使用纯黑 `#000000`、纯白 `#ffffff`；阴影用 `rgba(22, 20, 15, …)`。
- 一个页面只有一个界面强调色（锈红）；课程强调色是**课程身份**，来自 `course.json` 的 `accent`，不是界面色。
- 课程强调色一屏最多一个，只做重点，不做整屏底色。
- 强调色当文字用时必须和墨色混合到 ≥ 4.5:1：`color-mix(in srgb, #b8452b 62%, #16140f)`，或直接用 `--accent-text`。

## 3. 字号阶梯

| 元素 | 字号 | 规则 |
| --- | --- | --- |
| 镜头标记 / kicker | 28–32px 等宽 | 字距 0.12–0.14em；中文不加 uppercase |
| 场景主标题 | 96–180px / 1.1 / 700 | 默认 96；3–5 字短标题可到 120–180 |
| 章节 / 副标题 | 72–96px | 与主标题形成明确层级，不要夹在中间 |
| 场景正文 | 40–56px / 1.4–1.5 | 一段不超过 3 行 |
| 卡片主文字 | 36–42px | 卡片内边距 28px |
| 标签 / 注释 | 28–36px 等宽 | 数字、单位、来源用等宽更像注脚 |
| 关键文字下限 | 32px | 再小就不是给大屏看的 |

规则：

- **一屏最多两个文字层级。** 标题 + 正文就够；需要第三个层级时，改用颜色或线条区分，不要再加字号。
- 中文标题大字号收紧字距（-0.02 到 -0.045em）；正文不动字距。
- 标题最多两行；超过说明字号太大或文案太长，先改文案。
- 不做斜体中文、不做渐变文字。

## 4. 画布与安全区

- 画布 1920×1080，30fps。
- 标题安全区：左右各 192px，顶部 96px；正文内容宽度 1536px。
- 底部信息基线约 866px；底部 180px 作为安全边距，旁白课程的旁白条也落在这里，重要内容不要压进去。
- 播放器在 16:9 画布之外提供控制条：控制条通栏贴在画布下方，画布按视口可用区域等比最大化，两侧可能留纸色边。不要把关键文字压在画布最边缘，也不要依赖某个固定视口宽高比设计版式。
- 文字不要贴边；装饰线不要穿过正文。
- 中文每行 18–28 字，行高 1.5–1.7；不要两端对齐制造大空隙。
- 对比度：正文 ≥ 4.5:1，大号文字 ≥ 3:1。

## 5. 动效

- 动画承担论证：只用 GSAP 时间轴驱动 `transform` / `opacity`，不动 `top/left/width/height`。
- 入场 0.3–0.6 秒，缓动用 `power2.out` / `power3.out`；不要弹跳、旋转、闪烁堆叠。
- 每次揭示后至少停留 1 秒，让学习者读完再出现下一个动作。
- 不使用无限循环；需要循环时用有限次数。
- 不加持续的模糊、发光、滤镜。
- 动画在结束前落到稳定帧；最后一帧就是暂停时学习者看到的帧。
- 所有自动播放、循环和视差都要尊重 `prefers-reduced-motion`（平台播放器负责降级，scene 不要自己抢时钟）。

判断标准：**删掉这个动画，论证还成立吗？** 成立就是装饰，删掉。

## 6. 构图配方 A：标题 + 导语 + 一条强调线

最稳的开场屏。大标题立论题，一条短横线做视觉落点，导语补一句限定。模板的 `01-hello.html` 就是这一版。

```html
<div id="root" data-composition-id="s-hello" data-width="1920" data-height="1080">
  <h1 id="s-hello-title" class="clip" data-start="0.2" data-duration="11.4">第一屏说什么</h1>
  <div id="s-hello-rule" class="clip" data-start="0.8" data-duration="10.8"></div>
  <p id="s-hello-lead" class="clip" data-start="1.2" data-duration="10.4">
    这一屏只讲一件事：用一句话写出论题。
  </p>
</div>
```

```css
#s-hello-title {
  position: absolute;
  left: 192px;
  top: 340px;
  width: 1536px;
  font-size: 140px;
  line-height: 1.1;
  font-weight: 700;
  letter-spacing: -0.03em;
}

#s-hello-rule {
  position: absolute;
  left: 192px;
  top: 560px;
  width: 1180px;
  height: 2px;
  background: #b8452b;
  transform-origin: left center;
}

#s-hello-lead {
  position: absolute;
  left: 192px;
  top: 610px;
  width: 1180px;
  font-size: 46px;
  line-height: 1.6;
  color: #514b40;
}
```

适合：开场、章节页、结论页。一条强调线只出现一次。

## 7. 构图配方 B：左论题 + 右证据卡

讲「一个结论 + 一个证据」时用。左栏是论题，右栏一张纸色卡片放数字、来源或对照。两栏宽度不相等，避免对称呆板。

```css
#s-world-title {
  position: absolute;
  left: 192px;
  top: 300px;
  width: 820px;
  font-size: 112px;
  line-height: 1.12;
  font-weight: 700;
  letter-spacing: -0.03em;
}

#s-world-lead {
  position: absolute;
  left: 192px;
  top: 620px;
  width: 760px;
  font-size: 44px;
  line-height: 1.55;
  color: #514b40;
}

#s-world-card {
  position: absolute;
  left: 1104px;
  top: 260px;
  width: 624px;
  padding: 44px 48px;
  background: #faf6ee;
  border: 1px solid #d9cfbf;
  border-radius: 16px;
}

#s-world-card-label {
  font-family: ui-monospace, monospace;
  font-size: 30px;
  letter-spacing: 0.12em;
  color: #a33a20;
}

#s-world-card-text {
  margin-top: 24px;
  font-size: 40px;
  line-height: 1.45;
  color: #16140f;
}
```

适合：一个事实、一个对比、一个数字。**不要三张完全一样的等宽卡片平铺**；至少改变尺寸或位置。

## 8. 禁止项（视觉）

- 深色背景、深色模式、第二强调色、紫色渐变、霓虹光晕、渐变标题。
- 纯黑、纯白；冷灰与暖灰混用。
- 三张完全相同的等宽功能卡；连续三段相同版式。
- 装饰性彩色圆点、装饰性编号、滚动提示、城市/时间条、照片署名。
- 假截图：用 div 拼的终端、仪表盘、任务列表；假版本号、假数据、假状态条。
- 手绘装饰性 SVG、引入图标库；图标只用文本字符（`← → ↑ ↓ × ✓`）或 CSS 形状。
- 关键文字小于 32px、正文小于 40px、正文压到安全区外。
- 用滤镜做持续的模糊或发光；用 CSS 和 GSAP 同时动画同一个元素的 transform。

完整规范见平台 `DESIGN.md` 第 8 节；配色令牌的源文件是 `design/tokens.css`。
