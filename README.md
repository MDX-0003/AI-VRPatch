# vrpatch

360° ERP 视频（等距柱状投影全景）的**视口选区 + AI 重绘贴回**工具。

工作方式：在 360 视频上锁定一个固定矩形视口（viewport）和其中的内圈（inner，人物区），
把视口画面连同掩膜交给外部 AI 工具重绘人物；`vrpatch-merge` 再把重绘结果流式贴回全景——
**视口 footprint 之外的 panorama 逐像素不变**，内圈以多频带融合消除接缝，外圈保持原画面作锚。

## 核心功能

| 命令 | 功能 |
| --- | --- |
| `vrpatch-extract` | 360 视频 → 视口 clip（mp4）+ `clip.json` sidecar + 内圈掩膜 png |
| `vrpatch-merge` | 360 视频 + AI 重绘 clip + sidecar → 贴回后的 360 视频（流式，ffmpeg/libx264） |
| `vrpatch-pick` | 本地 web 选区：全景点选视口中心、视口内拖拽内圈，写回 `case.toml` |

## 快速开始

```bash
uv sync --extra dev            # 开发（含 pytest）；web 选区另加 --extra web
uv run pytest                  # 全量测试，秒级，不依赖大素材

# 跑通自带案例（源视频已就位，sha256 加载时自动校验）
uv run vrpatch-extract case cases/canal_dance/case.toml
uv run vrpatch-merge --input cases/canal_dance/source/Mono_dance_4k.mp4 \
    --ai cases/canal_dance/derived/clip.mp4 \
    --sidecar cases/canal_dance/derived/clip.json \
    --output cases/canal_dance/derived/out.mp4
uv run vrpatch-pick cases/canal_dance/case.toml   # http://127.0.0.1:8760/
```

## 文档

- [docs/README.md](docs/README.md) — 文档分层与索引
- [docs/knowledge/architecture.md](docs/knowledge/architecture.md) — 架构与各核心功能底层链路
- [docs/knowledge/projection-contract.md](docs/knowledge/projection-contract.md) — ERP↔视口投影数学契约
- [docs/knowledge/verification.md](docs/knowledge/verification.md) — 像素回归门槛与验证记录
- [CLAUDE.md](CLAUDE.md) — 开发硬性规则与代码/提交规范

环境要求：Python 3.11、[uv](https://docs.astral.sh/uv/)、ffmpeg 在 PATH 上。
