> 层: index    时效: 随新增文档更新

# docs

| 层 | 位置 | 判定规则 | 内容 |
| --- | --- | --- | --- |
| 入口 | `/README.md` | — | 功能总览、安装、快速上手 |
| 契约 | `/CLAUDE.md` | — | 文件布局、硬性规则、代码/提交规范 |
| knowledge | `knowledge/` | 长期有效的设计事实；随代码演进**覆盖更新**，头部带 `> 层:` `> 时效:` | `architecture.md` 架构与链路 · `projection-contract.md` 投影数学契约 · `verification.md` 回归门槛与记录 |

规则：knowledge 文档头部必须有 `> 层:` 与 `> 时效:` 声明；冻结类内容（projection-contract、verification 的基线参数）修改必须连带重跑对应回归并在文中更新结论与日期。
