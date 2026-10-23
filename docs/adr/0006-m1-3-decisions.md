# ADR 0006 - M1-3 裁决（G10 写口径定案 / renew 触活例外 / 归档=强制导出不加密 / reconcile ACTIVE 维持）

状态: 已裁决（2026-10-23，M1-3；docs/plans/m1-3-plan.md 审#P2-1/P2-2 折入）
关联: docs/adr/0000-known-gaps.md G9/G10；docs/adr/0003-m0-decisions.md（G9 登记 / G10 登记 / reconcile 无 ACTIVE 闭合事件）；docs/PRD.md §1 C7 / §2 / §3.2 / §4.2 / §6；docs/plans/m1-3-plan.md
问题: M1 裁决 G10（读计活动的连接级模型）、renew 触活口径例外、归档是否加密、ADR 0003「reconcile ACTIVE 闭合事件」M1 可选项是否实现

## 裁决

1. **G10 维持写口径 + 静默读意图内声明（审#P2-1）**：`last_activity_at` 仅 agent 面写操作更新（现状，PRD §3.2 activity 行澄清）。**agent 只读不写被标 SUSPECT 是意图内**——看板是记录面，无写 = 无进展证据；等待场景由 `awaiting_human` 豁免（既有，不因连接失活盖过「等待人裁决」）。**连接级模型（读计活动的连接建立/存活判定）不引入**（与 ADR 0003 G10 声明一致）；known-gaps G10 行闭合标注 = 裁决维持写口径，非实现读计活动。
2. **renew 触活例外语义（审#P2-2）**：`last_activity_at` = claim 最近活跃时间戳，来源可为 agent 写（MCP 写操作）或 renew（人续租证明）。renew 属人面操作，但其更新 `last_activity_at` 为既有行为（续租证明），PRD §3.2 activity 行声明该例外。
3. **归档 = prune 强制导出文件（timestamped JSON 0600）；加密不做**：清理前强制导出（导出失败中止清理，PRD §6）；导出文件权限 0600；加密不做——单用户本地 + 0600 + 威胁模型 A 残余 G1（本机 shell 可直接写 SQLite）不可防，加密仅增加表面不增加实质保障。
4. **reconcile ACTIVE 闭合事件维持 ADR 0003 不实现**：ADR 0003「M1 可选项：同一 claim 观测到非 active -> active 转移时写闭合事件（有前次非 active 观测才写，限噪）」——裁决不实现。时点观测自愈（view 展示前以当前事实重判，陈旧事件不可能产生陈旧显示）+ 视图重推导已覆盖观测需求；契约变更成本 > 收益。

## 影响

- PRD：§1 C7 措辞对齐（回溯保证 = 未清理的完整链；整删需求以归档为准）、§2 事件 kind 全集补 `renew`（审#P2-3）、§3.2 activity 行澄清（写口径 + renew 例外）、§4.2 prune 命令行、§6 数据保留行改写（终态需求级原子窗口 + 量级主要由活跃需求数决定，审#P1-2/P1-A/P2-D）。
- known-gaps：G9-a（数据保留清理命令）闭合 = M1-3.3 prune CLI；G9-b（重试成本超限判定）拆 M1-4 BCD（属 ④ 派生状态系统）；G10 闭合 = 裁决维持写口径。
- 实现批次：M1-3.2 renew 写事件（kind='renew'）；M1-3.3 prune CLI + history_note（审#P2-A）；M1-3.4 G5 基准。
