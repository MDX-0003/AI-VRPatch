---
name: merge-draft-inner-decoupling
description: merge 融合框取活草稿的设计与视口守卫；inner 双角色、坐标锚定、文档漂移、冒烟残留四个坑的详细记录
metadata:
  type: project
---

2026-09-21 定稿（用户验收）：**融合框（inner）是活的创作参数，视口（yaw/pitch/fov/尺寸）才是版本资产**。`api_merge` 每次按下时读 case.toml 草稿 inner，以 `--inner` 传给 merge CLI，并传 `--report` 落 `derived/out_<版本>.merge.json` 记录实际使用的框；前置守卫 `case.viewports_match`（yaw 按 ±180 循环比较、pitch/fov 容差 0.05°=半步摇杆、宽高须精确相等），不一致返回 409「当前视口与视频切分时有所偏差，请重置视口」，前端 `runMerge` 的 `alert(j.error)` 原样弹出——**后端错误文案即 UI，前端零改动、零 ?v=N 递增**。

**Why（需求根源）**：视口没变时重跑 extract 抽出的 clip.mp4 逐像素相同，却要烧一个版本号、重选一遍 AI 结果——过去挪一下融合框就要走这一整套。固化的从来不是草稿（草稿一直活在 case.toml 里），是 merge 的**取值来源**（网页只拼 `--sidecar`、从不用 CLI 早就有的 `--inner`）。改交互前先查 CLI 是否已有覆盖口，能省一次新机制设计。

**踩过的坑（详细）**：

1. **inner 是两个参数，不是一个**。extract 时刻它生成 clip_mask.png（黑=AI 重绘区、白=锚定区），是「给 AI 的指令」，理应随版本冻结；merge 时刻它是「贴哪、融哪」的混合窗口（拉普拉斯+羽化的取值域），是创作决策。解耦只许解后者。当时考虑过「inner 不再写入 clip.json」——**错**：字段集是对外契约（硬性规则 2、test_case 冻结），删字段还毁掉掩膜出处记录和 reset-draft 的恢复源。正确姿势：**写侧一字不动，只改读侧**（merge 显式传 --inner；CLI 不传时仍回落版本值，CLI 用户与像素基线双向兼容）。

2. **inner 坐标锚定的是草稿视口，merge 合成用的却是版本视口**。用户在预览图上拖的框是相对「草稿视口」的像素坐标；extract 之后只要摇过摇杆或点过新中心（摇杆一步 0.1° ≈ 3.3px @ 59°fov/1920 宽），草稿 inner 对版本内容就是错位的，直接传会把框贴到没画过的地方。守卫因此不可省，且**失败必须显式 409 拒绝，禁止静默回退用版本 inner**——静默回退正是用户要消灭的那种隐式耦合。yaw 比较必须用 ±180 循环距离（摇杆跨过 ±180 后两值数值差 359.x、语义只差零点几度）；容差 0.05° 是半步摇杆：再大会漏检真实挪动，再小会把往返浮点噪声误判成漂移。

3. **文档漂移差点误导设计**。CLAUDE.md 硬性规则 9 与 .claude/memory（case-toml-vs-clip-json、MEMORY.md 索引）残留「几何指纹 + --force」的描述，而该机制 2026-09-20 简化定稿时已从代码删除（目录归属即配对）——本次讨论起初还基于指纹模型推演配对风险，直到读代码才发现 `merge.py` 根本没有 --force。教训：**砍机制必须三处同删**：CLAUDE.md 规则、对应 memory 文件、MEMORY.md 索引；动 merge/配对代码前先 grep 代码确认文档描述的校验是否还存在。

4. **在线冒烟只能测拒绝路径，且会留残留**。放行路径会真启动 8K 合并并覆盖用户成品 `out_<版本>.mp4`——绝不在线跑，放行逻辑用 fake Queue 单测断言 argv 即可。拒绝路径在线测完，`_set_section` 的文本重写会把 [viewport]/[inner] 节挪到 case.toml 文件尾（语义不变但留 diff），测完 `git checkout -- case.toml` 还原字节级原状。另两个 Windows 控制台坑：findstr 搜 UTF-8 中文静默失灵；curl 打印的中文在 GBK 控制台显示为乱码——都是显示/工具层问题不是数据问题，文案断言用 Python urllib 读字节比对。

**How to apply**: 改 merge/web 交互前先读 [[case-toml-vs-clip-json]]（几何各取哪个）与 [[extract-version-pairing]]（版本模型）；动守卫容差前重读坑 2 的容差推导；重置按钮是视口+inner 一起恢复的，为合并旧版本而重置会覆盖进行中的下一版选区——这是用户拍板接受的「无额外 UI」代价，别好心加切换开关。
