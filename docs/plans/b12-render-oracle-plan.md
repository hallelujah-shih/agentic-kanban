# b12 等待人横幅/卡片渲染级 oracle 实现计划

> 执行走 strict-sdd-loop 门序（Phase 2 plan 盲审起）；任务步骤用 checkbox 跟踪；
> 任务标题行 `### Task N:` 是 brief 切分锚，勿改格式。

**Goal:** 给 `summary_line || reason || kind` 展示优先逻辑（看板卡片、深潜横幅）建立渲染级
oracle，闭合 known-gaps G13，并翻正 docs/web.md 冒烟项 5 的措辞。

**Architecture:** 夹具侧新增一个带 `summary_line` 的 review 种子（s10）；断言侧在 E1（卡片两腿）
/E5（blocked 降级腿）/新增 E12（review 优先腿）钉渲染文本；`src/` 实现零改动（本批只补 oracle，
不改展示语义）。红证据两路：①断言先写、夹具未写 -> 夹具缺失红；②mutation 探针剥实现腿 -> 断言红。

**Tech Stack:** Playwright 1.64.1（真浏览器 e2e）、SQLite 直写夹具、git（探针恢复）。

**Spec:** docs/web.md（等待人横幅/卡片契约，冒烟项 5）；docs/business-contracts/distill-pipeline.md
Scenario 2 Then（展示半句）；docs/adr/0000-known-gaps.md G13（缺陷原文）。

## 契约三锚

1. **规范逐字原文**
   - docs/web.md:56（冒烟项 5）：「等待人提示：对 awaiting_human 任务确认深潜页与卡片横幅显示
     `kanban approve <id>` 提示（静态文字，非按钮）；横幅/卡片 `summary_line` 在场优先显（评审交接
     一句话），缺失降级显 reason（E5 口径：s3 blocked 无 summary_line，显 reason）」
   - docs/web.md:31（层 0）：「等待人横幅（`awaiting_human.summary_line` 在场显该一句话——评审交接
     「做了什么/先看哪」；缺失显 `reason`——blocked/旧数据降级；静态 CLI 提示保留：kind=review ->
     人面确认: kanban approve <id>，kind=blocked -> 解除阻塞: kanban approve <id>）」
   - docs/business-contracts/distill-pipeline.md:128 Scenario 2 Then：「板等待卡片/深潜等待横幅显示
     该一句话（人不用进深潜就知道「做了什么/先看哪」）」
   - docs/adr/0000-known-gaps.md:25 G13 原文（缺陷与修复方向，含「E5 只断言横幅在场 + CLI 提示，
     未断言 reason 文本」；该行的锚点 `web.py:191-192` 已漂移，现行为 :192-193，闭合行按现行锚点写）
2. **代码锚点**（实测于基 commit b42f950）
   - `src/agent_kanban/api/web.py:192-193` 卡片：`var wait = ... esc(t.awaiting_human.summary_line ||
     t.awaiting_human.reason || t.awaiting_human.kind || "")`
   - `src/agent_kanban/api/web.py:417-419` 深潜横幅：`var hint = ...` / `var whats = s.awaiting_human.summary_line
     || s.awaiting_human.reason || s.awaiting_human.kind || "";` / `html += "<div class='wait-banner'>等待人决策: " + esc(whats)`
   - `src/agent_kanban/services/operations.py:901-906` request_review 强制 summary_line 非空；
     `:919-924` 写 marker：`reason="review requested"`、`kind="review"`、`summary_line=str(summary_line).strip()`
   - `src/agent_kanban/services/operations.py:1148-1152` mark_blocked 强制 reason 非空；
     `:1161` 写 marker：`{"reason": reason, "evidence": ..., "kind": "blocked"}`
     （另有 `l_blocked_reason_empty` 用例背书 reason 非空）
   - `tests/e2e/seed.py`（TITLES 表 + MCP 动作段 + manifest）、`tests/e2e/smoke.spec.js:80-99`（E1）、
     `:266-274`（E5）、`:300-306`（E7）
3. **逐例期望**
   - e2e 基线 15 spec / 15 PASS（AGENTS.md:39、docs/ops/ci-verification.md:11）-> 本批后 16/16
   - 全量 run_ac 基线 1090/1090（AGENTS.md:38）——本批不触碰后端套件，期望无回退
   - 生产 DB 只读侦察（2026-10-31）：`awaiting_human` 非空行 0 条；`kind` 兜底腿在 canonical API 下不可达
     （见不修清单 3）

## 档位判定（ledger 同步）

- 写错的最坏后果：新增断言镜像实现（绿但无判别力），或夹具扩容期望值未同步导致后续批次复验判据
  失效；展示逻辑被改坏时板面无红。
- 通道表命中行：全六门（命中条件＝新测试语义：新增断言 oracle + 新增测试资产；后果面 A/B，
  不触单向门/安全清单/影响面④，故不触发 Phase 0.5 BCD）。

## 影响面

- ①对外接口/工件格式：无（`src/` 零改动，`/board` 与 detail JSON 形状不变）
- ②新入口/信任边界/凭据/反序列化：无
- ③热路径/资源：无
- ④业务规则变化：无（展示逻辑不变，只补 oracle 与文档措辞）

## 证据仪器（冻结口径）

- e2e 仪器：Playwright 1.64.1（package.json `^1.64.1`）、node v24.21.0；夹具 DB
  `AK_E2E_DB=/home/shih/.tmp-ak-m16/b12-render-oracle/ak-e2e.db`（webServer 段每次 run 前
  `rm -f ${AK_E2E_DB}*` 重建，确定性前提）；`TMPDIR=/home/shih/.tmp-ak-m16/b12-render-oracle/tmp`。
- 夹具变更（新增 s10）＝仪器改动：基线 15/15 作废，重新基线 16/16（预算＝本批 e2e 跑次：全量 4 次
  ＋ 单 spec 探针 5 次），旧 15/15 证据标 superseded。
- mutation 探针不改变仪器（跑完 `git checkout` 恢复）；红绿证据同源＝同一 spec 文件、同一基 commit。

## 不修清单（file:line + 理由 + 登记位置）

1. `src/agent_kanban/api/web.py:192-193`、`:417-419` — 实现零改动：本批补 oracle，不改展示语义；
   登记＝本 plan 正文 + G13 闭合行。
2. `tests/e2e/smoke.spec.js:102-104`（E2 的逐 id 列表不含 s9/s10）— 同测试的集合等价断言
   （页面标题集合 == JSON 标题集合）已覆盖全部在板任务，逐 id 列表是冗余；登记＝本 plan 不修清单。
3. `|| kind` 兜底腿无渲染级 fixture — canonical 路径不可达：mark_blocked 强制 reason 非空
   （operations.py:1148-1152 + `l_blocked_reason_empty` 用例），request_review 强制 summary_line 非空
   （operations.py:901-906），故「无 summary_line 且无 reason」的 marker 只能由直写 SQL 造出；
   造 fixture 钉死不可达分支属无收益断言。登记＝G13 闭合行的盲区段。
4. `docs/ops/skill-package-verification.md:52`、`docs/plans/*`、`docs/superpowers/*`、
   `docs/ops/ci-verification.md:12`（b10 证据行）中的 `15/15` — 历史批次证据记录，非活基线，不改；
   登记＝本 plan 不修清单。
5. `tests/ac_cases_l.py:777`（G14，`l_latest_first(vii)` 平凡真）— 文件集与本批无交集，按并批判据
   不并批，独立批次立项；登记＝known-gaps G14 行（已存在）。
6. `tests/e2e/seed.py:140-157` 预探针 / s8 后备路径 — 不动；但 E1 的「8 个在板需求」计数断言与该
   死路径耦合：若预探针触发（s3 marker 被清 -> 建 s8），在板数变 9，E1 计数断言必红＝显性红逼修
   真实机制，非本批缺陷。删除该路径不优先：删掉即移除显性红探针（陷阱库 1：竞争窗宁可显性红，
   不可侥幸绿）。登记＝本 plan Review Focus 第 5 条 + G13 闭合行盲区段。

## Review Focus（spec 未说、断言未直接覆盖的输入类）

1. 优先级腿的反证位：四条可达腿（卡片 summary/reason、横幅 summary/reason）各有剥腿探针
   （Task 1 Step 5-8），另有一处顺序颠倒探针（Step 9）钉「优先」语义本身。
2. 夹具扩容与服务启动对账的交互：s10 有 awaiting marker -> 启动 reconcile 对 s10 追加 1 条
   `reconcile` 事件（同 s3 口径，smoke.spec.js [C3]）。E12 不断言事件计数，故无期望值耦合；
   若后续给 E12 加计数断言，必须按此口径。
3. `summary_line` 文本的转义：断言用纯文本锚（不含 `<`），转义防线由 E9 覆盖；本批不重复。
4. 计数断言脆性：`#top-count` 硬编码「8 个在板需求」——夹具再扩容时须同步（陷阱库 3 同类面）。
5. s8 后备路径与 E1 计数断言耦合（不修清单 6）：预探针触发即 E1 红，属显性红而非侥幸绿。
6. kind-only 兜底腿不可达（不修清单 3）——若审者认为该腿值得钉，需造直写 SQL 夹具；裁决归 plan 审。

---

### Task 1: e2e 夹具与渲染断言

**Files:**
- Modify: `tests/e2e/smoke.spec.js`（E1、E5、E7、新增 E12、头注释口径登记）
- Modify: `tests/e2e/seed.py`（常量区、TITLES 表、MCP 动作段、manifest、docstring 种子清单）

**Interfaces:**
- Consumes: `ac_lib.seed_req(db, title) -> str`、`ac_lib.MCP(db).start()` / `call_ok(tool, args)`、
  `request_review` 服务端契约（operations.py:880-937：state=CLAIMED + evidence 至少一项 +
  summary_line 非空；无子任务时 assessments 省略合法）
- Produces: manifest 键 `s10`、`s10_summary_line`、`s3_reason`；spec 新增 test `E12`（共 16 spec）

- [ ] **Step 0: 环境就绪**

```bash
uv sync
npm ci
```

Expected: 两个命令 rc=0；`.venv/bin/python` 与 `node_modules/@playwright/test` 存在（worktree 不继承
主仓 .venv/node_modules，见 AGENTS.md ops 教训）。

- [ ] **Step 1: 写断言（先不扩夹具）**

`tests/e2e/smoke.spec.js` E1 内，标题循环与计数改为：

```js
  for (const k of ['s1', 's2', 's3', 's4', 's5', 's6', 's9', 's10']) {
    await expect(cardByTitle(page, T[k]), `${k} 卡在场`).toHaveCount(1);
  }
  await expect(page.locator('#top-count')).toHaveText('8 个在板需求');
```

E1 内 s3 断言之后追加（卡片两腿，精确文本）：

```js
  await expect(s3wait).toHaveText(`等待人: ${SEEDS.s3_reason} kanban approve ${SEEDS.s3}`);
  const s10wait = cardByTitle(page, T.s10).locator('.wait');
  await expect(s10wait, 's10 等待人横幅').toHaveCount(1);
  await expect(s10wait).toHaveText(`等待人: ${SEEDS.s10_summary_line} kanban approve ${SEEDS.s10}`);
```

E5 内追加（降级腿文本钉死，精确文本）：

```js
  await expect(banner).toHaveText(`等待人决策: ${SEEDS.s3_reason} （解除阻塞: kanban approve ${SEEDS[target]}）`);
```

E7 内改集合：

```js
  expect(body.tasks.map((t) => t.requirement_id).sort())
    .toEqual([SEEDS.s6, SEEDS.s9, SEEDS.s10].sort());
```

文件末尾（E11 之后）新增 E12：

```js
test('E12 深潜 s10：等待横幅显 summary_line（review 优先腿）', async ({ page }) => {
  await boardReady(page);
  await cardByTitle(page, T.s10).click();
  await expect(page.locator('#detail-root h1')).toHaveText(T.s10);
  const banner = page.locator('.wait-banner');
  await expect(banner, '等待人横幅在场').toHaveCount(1);
  await expect(banner).toHaveText(
    `等待人决策: ${SEEDS.s10_summary_line} （人面确认: kanban approve ${SEEDS.s10}）`);
});
```

头注释「口径登记」段追加：

```js
// [C9] 夹具扩容（s10 review 种子带 summary_line）：E1 在板 7->8、E7 CLAIMED 集合
//      [s6,s9]->[s6,s9,s10]；红步红因＝期望值未更新（陷阱库 3），非壳缺陷。
//      反证位＝五处 mutation 探针（web.py:193/:418 剥腿 ×4 + 顺序颠倒 ×1），红日志留档。
//      精确文本的前缀/提示字面锚壳实现（选择器登记表 smoke.spec.js:6/:10）与 web.md:31 的
//      「人面确认:」/「解除阻塞:」措辞。
```

- [ ] **Step 2: 跑 e2e 确认红（夹具未扩，断言已写）**

```bash
TMPDIR=/home/shih/.tmp-ak-m16/b12-render-oracle/tmp \
AK_E2E_DB=/home/shih/.tmp-ak-m16/b12-render-oracle/ak-e2e.db \
npx playwright test > /home/shih/.tmp-ak-m16/b12-render-oracle/red-fixture.log 2>&1
rc=$?
echo "rc=$rc"
grep -E "^ *[0-9]+ failed" /home/shih/.tmp-ak-m16/b12-render-oracle/red-fixture.log
grep -E "^[0-9]+\) tests/e2e/smoke.spec.js" /home/shih/.tmp-ak-m16/b12-render-oracle/red-fixture.log
tail -2 /home/shih/.tmp-ak-m16/b12-render-oracle/red-fixture.log
```

Expected: `rc=1`；失败 3 条（E1、E5、E12），汇总行含 `3 failed`（manifest 无
`s10`/`s10_summary_line`/`s3_reason`，在板数仍 7）。E7 不红＝`toEqual` 忽略数组尾部
undefined 元素（`[s6,s9]` vs `[s6,s9,undefined]` 判等），机制自证留档
red-e7-deviation.log；折入轮加 `expect(SEEDS.s10).toBeTruthy()` 守卫闭合该盲区
（守卫的红态「manifest 无 s10」canonical 不可达，无红出生证，登记 G13 盲区段）。

- [ ] **Step 3: 扩夹具（seed.py）**

常量区新增：

```python
S10_SUMMARY = "e2e 评审交接：补渲染断言，先看 E12 横幅"
```

`TITLES` 表新增一行：

```python
    "s10": "e2e-s10-review-summary",
```

`main()` 中 s9 创建之后（在 `for k, v in ids.items(): print(...)` 之前）：

```python
    ids["s10"] = ac_lib.seed_req(db, TITLES["s10"])
```

MCP 动作段（`_claim(mcp, ids["s9"])` + s9 update_progress 之后、`mcp.close()` 之前）追加：

```python
        _claim(mcp, ids["s10"])
        mcp.call_ok("request_review", {
            "requirement_id": ids["s10"],
            "evidence": {"test_summary": "e2e 夹具自检"},
            "summary_line": S10_SUMMARY,
        })
```

manifest 字典新增两键（与 `s3_headline` 同段）：

```python
        "s3_reason": S3_REASON,
        "s10_summary_line": S10_SUMMARY,
```

docstring 种子清单：`8 种子（预探针触发后备则 9）` 改为 `9 种子（预探针触发后备则 10）`，并补一行：

```
  s10 claim+request_review(summary_line)（E12 review 优先腿 + E1 卡片 summary_line 腿夹具）
```

- [ ] **Step 4: 跑 e2e 确认绿**

```bash
TMPDIR=/home/shih/.tmp-ak-m16/b12-render-oracle/tmp \
AK_E2E_DB=/home/shih/.tmp-ak-m16/b12-render-oracle/ak-e2e.db \
npx playwright test > /home/shih/.tmp-ak-m16/b12-render-oracle/e2e-green-base.log 2>&1
rc=$?
echo "rc=$rc"; tail -3 /home/shih/.tmp-ak-m16/b12-render-oracle/e2e-green-base.log
python3 -c "import json;m=json.load(open('/home/shih/.tmp-ak-m16/b12-render-oracle/ak-e2e.db.seeds.json'));print(sorted(k for k in m if k.startswith('s')));print(m['s10_summary_line'], m['s3_reason'])"
```

Expected: `rc=0`，`16 passed`；manifest 的 `s*` 键含 s1..s7、s9、s10、s8（None 后备位）及派生键
`s3_awaiting_human`/`s3_event_kinds`/`s3_headline`/`s3_reason`/`s9_event_kinds`/`s10_summary_line`；
`s10_summary_line` = 「e2e 评审交接：补渲染断言，先看 E12 横幅」，`s3_reason` = 「e2e 阻塞原因」。

- [ ] **Step 5: 反证探针 A（卡片 summary_line 腿）**

探针用 python 改写（锚串存在性断言，避免 sed 分隔符与 JS `|` 冲突），跑后立即恢复：

```bash
.venv/bin/python - <<'EOF'
import pathlib
p = pathlib.Path("src/agent_kanban/api/web.py")
s = p.read_text()
old = 'esc(t.awaiting_human.summary_line || t.awaiting_human.reason || t.awaiting_human.kind || "")'
new = 'esc(t.awaiting_human.reason || t.awaiting_human.kind || "")'
assert s.count(old) == 1
p.write_text(s.replace(old, new))
EOF
TMPDIR=/home/shih/.tmp-ak-m16/b12-render-oracle/tmp \
AK_E2E_DB=/home/shih/.tmp-ak-m16/b12-render-oracle/ak-e2e.db \
npx playwright test -g "E1 看板渲染与信号" > /home/shih/.tmp-ak-m16/b12-render-oracle/red-probe-A.log 2>&1
rc=$?
git checkout src/agent_kanban/api/web.py
echo "rc=$rc"
```

Expected: `rc=1`（E1 的 s10 精确文本断言处失败，报错含 `review requested`）；恢复后
`git status --short` 只剩 tests/e2e 两文件。

- [ ] **Step 6: 反证探针 B（卡片 reason 腿）**

```bash
.venv/bin/python - <<'EOF'
import pathlib
p = pathlib.Path("src/agent_kanban/api/web.py")
s = p.read_text()
old = 'esc(t.awaiting_human.summary_line || t.awaiting_human.reason || t.awaiting_human.kind || "")'
new = 'esc(t.awaiting_human.summary_line || t.awaiting_human.kind || "")'
assert s.count(old) == 1
p.write_text(s.replace(old, new))
EOF
TMPDIR=/home/shih/.tmp-ak-m16/b12-render-oracle/tmp \
AK_E2E_DB=/home/shih/.tmp-ak-m16/b12-render-oracle/ak-e2e.db \
npx playwright test -g "E1 看板渲染与信号" > /home/shih/.tmp-ak-m16/b12-render-oracle/red-probe-B.log 2>&1
rc=$?
git checkout src/agent_kanban/api/web.py
echo "rc=$rc"
```

Expected: `rc=1`（E1 的 s3 精确文本断言处失败，s3 横幅显 `blocked`）。

- [ ] **Step 7: 反证探针 C（横幅 summary_line 腿）**

```bash
.venv/bin/python - <<'EOF'
import pathlib
p = pathlib.Path("src/agent_kanban/api/web.py")
s = p.read_text()
old = 'var whats = s.awaiting_human.summary_line || s.awaiting_human.reason || s.awaiting_human.kind || "";'
new = 'var whats = s.awaiting_human.reason || s.awaiting_human.kind || "";'
assert s.count(old) == 1
p.write_text(s.replace(old, new))
EOF
TMPDIR=/home/shih/.tmp-ak-m16/b12-render-oracle/tmp \
AK_E2E_DB=/home/shih/.tmp-ak-m16/b12-render-oracle/ak-e2e.db \
npx playwright test -g "E12" > /home/shih/.tmp-ak-m16/b12-render-oracle/red-probe-C.log 2>&1
rc=$?
git checkout src/agent_kanban/api/web.py
echo "rc=$rc"
```

Expected: `rc=1`（E12 精确文本断言处失败，横幅显 `review requested`）。

- [ ] **Step 8: 反证探针 D（横幅 reason 降级腿，钉 E5 新断言）**

```bash
.venv/bin/python - <<'EOF'
import pathlib
p = pathlib.Path("src/agent_kanban/api/web.py")
s = p.read_text()
old = 'var whats = s.awaiting_human.summary_line || s.awaiting_human.reason || s.awaiting_human.kind || "";'
new = 'var whats = s.awaiting_human.summary_line || s.awaiting_human.kind || "";'
assert s.count(old) == 1
p.write_text(s.replace(old, new))
EOF
TMPDIR=/home/shih/.tmp-ak-m16/b12-render-oracle/tmp \
AK_E2E_DB=/home/shih/.tmp-ak-m16/b12-render-oracle/ak-e2e.db \
npx playwright test -g "E5" > /home/shih/.tmp-ak-m16/b12-render-oracle/red-probe-D.log 2>&1
rc=$?
git checkout src/agent_kanban/api/web.py
echo "rc=$rc"
```

Expected: `rc=1`（E5 精确文本断言处失败，s3 横幅显 `blocked`）。

- [ ] **Step 9: 反证探针 E（顺序颠倒，钉「优先」语义）**

两处同时把 `summary_line` 与 `reason` 顺序交换（两腿都在时显 reason）：

```bash
.venv/bin/python - <<'EOF'
import pathlib
p = pathlib.Path("src/agent_kanban/api/web.py")
s = p.read_text()
a = 'esc(t.awaiting_human.summary_line || t.awaiting_human.reason || t.awaiting_human.kind || "")'
b = 'var whats = s.awaiting_human.summary_line || s.awaiting_human.reason || s.awaiting_human.kind || "";'
assert s.count(a) == 1 and s.count(b) == 1
s = s.replace(a, 'esc(t.awaiting_human.reason || t.awaiting_human.summary_line || t.awaiting_human.kind || "")')
s = s.replace(b, 'var whats = s.awaiting_human.reason || s.awaiting_human.summary_line || s.awaiting_human.kind || "";')
p.write_text(s)
EOF
TMPDIR=/home/shih/.tmp-ak-m16/b12-render-oracle/tmp \
AK_E2E_DB=/home/shih/.tmp-ak-m16/b12-render-oracle/ak-e2e.db \
npx playwright test -g "E1 看板渲染与信号|E12" > /home/shih/.tmp-ak-m16/b12-render-oracle/red-probe-E.log 2>&1
rc=$?
git checkout src/agent_kanban/api/web.py
echo "rc=$rc"
```

Expected: `rc=1`，两条 spec（E1、E12）皆红（s10 有 summary_line 与 generic reason 双值，顺序颠倒即显
`review requested`）。

- [ ] **Step 10: 复跑全量 e2e 确认绿并留档**

```bash
TMPDIR=/home/shih/.tmp-ak-m16/b12-render-oracle/tmp \
AK_E2E_DB=/home/shih/.tmp-ak-m16/b12-render-oracle/ak-e2e.db \
npx playwright test > /home/shih/.tmp-ak-m16/b12-render-oracle/e2e-green-final.log 2>&1
rc=$?
echo "rc=$rc"; tail -3 /home/shih/.tmp-ak-m16/b12-render-oracle/e2e-green-final.log
git status --short
```

Expected: `rc=0`，`16 passed`；`git status --short` 只剩 tests/e2e 两文件（探针已恢复）。

- [ ] **Step 11: 提交**

```bash
git add tests/e2e/seed.py tests/e2e/smoke.spec.js
git commit -m "b12 T1: e2e 渲染级 oracle（s10 review 种子 + E1/E5/E12 断言，四腿反证探针留档）"
git show --stat HEAD
```

Expected: `git status --short` 空；`git show --stat HEAD` 只含两个文件。

---

### Task 2: 文档翻正与登记

**Files:**
- Modify: `docs/web.md:56`（冒烟项 5 措辞）
- Modify: `docs/adr/0000-known-gaps.md:25`（G13 闭合 + 盲区登记）
- Modify: `AGENTS.md:39`、`AGENTS.md:43`（e2e 基线 15/15 -> 16/16）
- Modify: `docs/ops/ci-verification.md:11`（活基线 15/15 -> 16/16）
- Modify: `.github/workflows/ci.yml:91`（存量漂移：job 步骤名「12 spec」->「16 spec」）

**Interfaces:**
- Consumes: Task 1 的断言集合（E1/E5/E12）与留档日志路径
- Produces: 无代码接口；文档口径与基线数字一致

- [ ] **Step 1: 翻正 web.md 冒烟项 5**

把 `docs/web.md:56` 整行替换为：

```markdown
5. 等待人提示：对 awaiting_human 任务确认深潜页与卡片横幅显示 `kanban approve <id>` 提示（静态文字，非按钮）；横幅/卡片文本按 `summary_line` 优先（评审交接一句话），缺失降级显 `reason`——渲染级断言覆盖四腿：E1（卡片：s10 显 summary_line、s3 显 reason）、E5（深潜横幅：blocked 显 reason）、E12（深潜横幅：review 显 summary_line 且不显 generic reason）。`kind` 兜底腿经 canonical API 不可达（mark_blocked 强制 reason 非空、request_review 强制 summary_line 非空），无渲染级断言，盲区登记见 docs/adr/0000-known-gaps.md G13。
```

- [ ] **Step 2: 闭合 G13 并登记盲区**

`docs/adr/0000-known-gaps.md` G13 行的「升级路径」与「生效点」两列改为：

```markdown
已闭合（2026-10-31，b12-render-oracle）：e2e 新增 s10 review 种子（带 summary_line）+ 渲染级精确文本断言 E1（卡片两腿）/E5（blocked 降级腿显 reason）/E12（review 优先腿显 summary_line，精确文本钉死故 generic reason 不可能同时在场）；反证位＝五处 mutation 探针（web.py:193 剥 summary_line 腿 -> E1 红；web.py:193 剥 reason 腿 -> E1 红；web.py:418 剥 summary_line 腿 -> E12 红；web.py:418 剥 reason 腿 -> E5 红；两处顺序颠倒 -> E1+E12 红），红日志留档 /home/shih/.tmp-ak-m16/b12-render-oracle/red-probe-{A,B,C,D,E}.log；web.md 冒烟项 5 措辞翻正；基线 15/15->16/16。残余盲区：`kind` 兜底腿 canonical 不可达（reason/summary_line 均服务端强制非空），无渲染级 oracle，接受；s8 后备路径与 E1 计数断言耦合（预探针触发则在板 9 -> E1 显性红），保留作显性红探针 | 2026-10-31 闭合（b12）
```

同一 commit 内把该行「残余」列的锚点 `web.py:191-192` / `web.py:417` 翻正为
`web.py:192-193` / `web.py:417-419`（现行代码实测）。

- [ ] **Step 3: 基线数字同步**

`AGENTS.md:39`、`AGENTS.md:43`、`docs/ops/ci-verification.md:11` 的 `15/15` 改为 `16/16`；
`.github/workflows/ci.yml:91` 的 `e2e 冒烟（12 spec，workers=1）` 改为 `e2e 冒烟（16 spec，workers=1）`。

- [ ] **Step 4: 静态检查 + corpus 门**

```bash
.venv/bin/python -m py_compile tests/e2e/seed.py
node --check tests/e2e/smoke.spec.js
.venv/bin/python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"
grep -n "15/15" AGENTS.md docs/ops/ci-verification.md
TMPDIR=/home/shih/.tmp-ak-m16/b12-render-oracle/tmp PYTHONPATH=$PWD/src \
.venv/bin/python tests/run_ac.py --only s_surface_bidirectional
```

Expected: py_compile 无错；node --check 无错；yaml 解析无异常；grep 只剩
`docs/ops/ci-verification.md:12`（b10 历史证据行，不修清单 4）；`s_surface_bidirectional` 全绿
（docs/web.md 与 AGENTS.md 属 corpus 门，ac_cases_s.py:41-42）。

- [ ] **Step 5: 提交**

```bash
git add docs/web.md docs/adr/0000-known-gaps.md AGENTS.md docs/ops/ci-verification.md .github/workflows/ci.yml
git commit -m "b12 T2: web.md 项 5 措辞翻正 + G13 闭合与盲区登记 + e2e 基线 15/15->16/16（含 ci.yml 存量 spec 数漂移）"
git status --short
```

Expected: `git status --short` 空。

---

### Task 3: 最高 tier 复验与证据登记

**Files:**
- Modify: `docs/ops/ci-verification.md`（新增 b12 证据行，紧接 b10 行 :12）

**Interfaces:**
- Consumes: Task 1/2 的产物与日志
- Produces: 本批最高 tier 证据行（活基线 16/16 + 全量 1090/1090 + docker 默认轨）

- [ ] **Step 1: 全量后端套件**

```bash
TMPDIR=/home/shih/.tmp-ak-m16/b12-render-oracle/tmp \
PYTHONPATH=$PWD/src .venv/bin/python -u tests/run_ac.py > /home/shih/.tmp-ak-m16/b12-render-oracle/green-full.log 2>&1
rc=$?
echo "rc=$rc"; tail -3 /home/shih/.tmp-ak-m16/b12-render-oracle/green-full.log
```

Expected: `rc=0`，断言计数 1090/1090（本批不触碰后端套件；若计数不同，以实跑数字为准并在证据行写实际值）。

- [ ] **Step 2: e2e 全量**

同 Task 1 Step 10 的命令，日志留档 `e2e-green-final.log`。Expected: `rc=0`，`16 passed`。

- [ ] **Step 3: docker 默认轨 build + smoke**

```bash
docker build -t ak-b12-smoke . > /home/shih/.tmp-ak-m16/b12-render-oracle/docker-smoke.log 2>&1
rc=$?
echo "build rc=$rc" | tee -a /home/shih/.tmp-ak-m16/b12-render-oracle/docker-smoke.log
cid=$(docker run -d --rm --network host -e AGENT_KANBAN_PORT=18799 \
  -v /home/shih/.tmp-ak-m16/b12-render-oracle/scratch:/data ak-b12-smoke 2>> /home/shih/.tmp-ak-m16/b12-render-oracle/docker-smoke.log)
rc=$?
echo "run rc=$rc cid=$cid" | tee -a /home/shih/.tmp-ak-m16/b12-render-oracle/docker-smoke.log
if [ "$rc" = 0 ]; then
  for i in $(seq 1 20); do code=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18799/healthz); [ "$code" = "200" ] && break; sleep 1; done
  echo "healthz=$code" | tee -a /home/shih/.tmp-ak-m16/b12-render-oracle/docker-smoke.log
  docker stop "$cid"
fi
```

Expected: `build rc=0`、`run rc=0`、`healthz=200`（`docker stop` 因 `--rm` 即清理），三者均写入
`docker-smoke.log`。禁裸 `docker compose up`（compose 挂生产 ~/.agent-kanban:/data 且撞生产 8765
端口）。若 18799 被占，换空闲端口并同步 curl 端口。

- [ ] **Step 4: 写证据行并提交**

在 `docs/ops/ci-verification.md` b10 行之后新增一行（数字取实跑日志，commit 取
`git rev-parse --short HEAD` 实取值）：

```markdown
  - b12 批次本地最高 tier 证据（2026-10-31，worktree b12-render-oracle @ <实取 sha>）: 全量 1090/1090（green-full.log rc=0）+ e2e 16/16（e2e-green-final.log）+ docker 默认轨 build + smoke healthz 200；批次产物 /home/shih/.tmp-ak-m16/b12-render-oracle/
```

```bash
git add docs/ops/ci-verification.md
git commit -m "b12 T3: 最高 tier 复验证据登记（全量 1090/1090 + e2e 16/16 + docker build/healthz）"
```

Expected: commit 成功；`git status --short` 空。

---

## 收尾（plan 级附注，不属于任何 Task brief）

- 派发方复验（Phase 5）：折入前重跑最高 tier（全量 + e2e + docker）。
- 合入走 PR（永不直推 main），merge 由 user 裁决。
- 域外发现（本批不修，须报告并登记）：`docs/ops/skill-package-verification.md:52` 的 15/15 为历史
  证据行，不改（不修清单 4）。
