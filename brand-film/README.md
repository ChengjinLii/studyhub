# StudyHub 品牌宣传片工程

30 秒品牌片的全部源代码与素材：竖屏 1080 × 1920（`StudyHub_Brand_Film.mp4`）和横屏 1920 × 1080（`StudyHub_Brand_Film_16x9.mp4`），30 fps，H.264 + AAC 立体声。

## 原理

- **画面**：`src/film.html` 加载 `src/film.js`。`window.renderFrame(t)` 只依赖时间 t 生成整帧 SVG，同一 t 总是得到同一画面。`render/render.mjs` 用本机 Chrome（puppeteer-core）逐帧截图。
- **声音**：`audio/compose.py` 用 numpy 从正弦波和带种子的噪声合成配乐与音效，不使用任何采样素材。
- **同步**：画面和声音都从 `src/cues.json` 读取时间点（120 BPM，每拍 0.5 秒）。
- **两个画幅**：`?layout=landscape` 时加载 `src/landscape/scenes/`（版式与交接约定在 `src/landscape/layout.js`），默认是竖屏 `src/scenes/`。两版共用 `cues.json` 和同一条声音。
- **运动模糊**：每帧渲染 16 个子帧（180° 快门），由 ffmpeg `tmix` 平均；`cues.json` 的 `blur.off` 窗口（全屏色场擦除、Logo 落地）不加模糊。中间帧在 `.work/` 下，编码后删除（`--keep-frames` 保留）。
- **母带**：ffmpeg 两遍 `loudnorm`，目标 −14 LUFS 综合响度；真峰值目标 −2 dBTP，成片实测 −1.9 dBTP（要求 ≤ −1 dBTP）。

## 目录

| 路径 | 内容 |
|---|---|
| `src/cues.json` | 时间表（画面与声音共用） |
| `src/core.js` | 缓动、圆角矩形形变基元、文字与机器人 Logo 绘制 |
| `src/shared.js` | 跨场景共用元素与交接约定 |
| `src/scenes/s1.js` … `s6.js` | 竖屏六个场景 |
| `src/landscape/` | 横屏版式（`layout.js`）与六个场景 |
| `tests/test_tooling.sh` | 渲染工具回归测试 |
| `audio/compose.py` | 配乐与音效合成 |
| `render/render.mjs` | 逐帧渲染（静帧、片段、子帧） |
| `render/build.sh` | 一键构建：音频 → 帧 → 编码 → 响度母带 |
| `render/qc.sh` | 成片检测：规格、黑帧、冻结帧、响度、真峰值 |
| `assets/fonts/` | 字体与 SIL OFL 1.1 许可证 |
| `docs/storyboard.md` | 脚本、分镜、音画节奏表 |
| `docs/PRODUCTION_NOTES.md` | 制作说明：创意、素材来源、数据依据、检测结果 |
| `docs/review_backlog.md` | 审阅发现、修复与未处理事项 |
| `out/` | 交付包：成片、制作说明、源代码副本、关键静帧、检测报告、审阅记录（git 只跟踪其中两个成片） |

## 依赖

- macOS 或 Linux；Google Chrome（默认路径 `/Applications/Google Chrome.app`，其他路径用环境变量 `CHROME_PATH` 指定）
- Node.js ≥ 18、npm；`npm install`（只安装 `puppeteer-core@23.11.1`，不下载浏览器）
- Python ≥ 3.9 与 numpy
- ffmpeg（需 libx264、aac、loudnorm、ebur128）

## 命令

```bash
npm install

# 完整成片：竖屏 1080 × 1920 与横屏 1920 × 1080（16 子帧运动模糊），各约 10 分钟（Apple M4）
bash render/build.sh --out StudyHub_Brand_Film.mp4
bash render/build.sh --layout landscape --out StudyHub_Brand_Film_16x9.mp4

# 低分辨率快速预览（540 × 960，无运动模糊）
bash render/build.sh --scale 0.5 --blur 1 --out .work/preview.mp4

# 片段
bash render/build.sh --from 3 --to 8 --blur 1 --out .work/clip.mp4

# 静帧（文件名 t_秒.png；横屏加 --layout landscape）
node render/render.mjs --times 1.5,4.8,17,27.5,29.9 --out .work/keyframes

# 工具回归测试
bash tests/test_tooling.sh

# 只生成音频（mix.wav、music.wav、sfx.wav、cue_report.json）
python3 audio/compose.py --out .work/audio

# 成片检测
bash render/qc.sh StudyHub_Brand_Film.mp4
```

## 修改

- 改时间：只改 `src/cues.json`，画面和声音会一起变化。
- 改文案：场景文字在 `src/cues.json`（标题、口号、数据）和各场景文件里（界面文案）。
- 改颜色：`src/core.js` 的 `C`。
