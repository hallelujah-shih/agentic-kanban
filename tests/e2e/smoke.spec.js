// tests/e2e/smoke.spec.js —— e2e 冒烟 16 spec（plan T3 契约表；声明序=执行序，workers=1 共享单服务单 DB）
//
// 选择器登记表（壳 = src/agent_kanban/api/web.py board_shell():91 / detail_shell():302，零产品改动）：
//   看板: #board-root .cols（四列容器，仅在板 tab 渲染成功后存在）/ .card（卡片 <a>）
//         .card .ct（卡片标题文本）/ .col .col-hd .cname（列头状态中文名 待认领/进行中/阻塞/返工）
//         .card .wait（看板行等待人横幅，文本 "等待人: <reason> kanban approve <id>"）
//         #top-count（顶栏计数 "N 个在板需求"）/ #new-btn #new-form #nf-title #nf-acc #nf-jira #nf-msg
//         .tab[data-tab=active|done|archived]（三 tab）/ .done-row .dt（终态行标题）/ .done-row .pill（状态徽章）
//   深潜: #detail-root h1（标题）/ div.sec:has(h2 描述)（描述节，inner 为 white-space:pre-wrap div）
//         .wait-banner（深潜等待人横幅 "等待人决策: .. （..: kanban approve <id>）"，
//         summary_line 在场优先显，缺失显 reason——web.md 修订版）
//         #ev-kind #ev-sev（事件流过滤 select）/ #ev-list .ev（事件平铺行，内含 .badge 文本 "kind/severity"）
//         #ev-list details.evh:not(.bk)（人面事件行；.evh-t = 提纲位文本，空 title 降级显 kind 标签）
//         #ev-list details.bk（簿记组，summary 文本 "簿记 N"，默认收起；展开 .ev 平铺行）
//         div.sec:has(h2 验收对照) li（验收对照行）/ li .badge.gap（覆盖缺口徽章，文本 "覆盖缺口"）
//         button[data-op=archive] / button 文本 "delete" / #op-msg（操作反馈）
//
// 口径登记（执行者实读壳+代码+活体探针，逐条）：
// [C1] E1 置顶：web.md:27/46 "需要关注需求置顶（attention_ids）" vs 现行四列壳（b05e73b UI 重构起，
//      renderActive 无排序，列序=状态序）= 存量分歧（基 commit 前已在），交 user 裁决（回报 Q2）；
//      裁决前 e2e 不断言置顶顺序（同 plan E4d 先例：留断言=镜像现实现=陷阱库 3）。
//      且 "(attention 行)" 前提不成立：活体探针实测本种子集 attention_ids=[]（s3 为 BLOCKED 需求态，
//      _derived_signals 无需求级 blocked 信号；口径同 tests/ac_cases_g.py:216-222）。
//      s3 看板行实际信号 = .wait 等待人横幅（E1 断言此；E5 断言深潜横幅）。
// [C2] E2 状态口径：壳卡片无独立 state 标签（状态由列表达），逐行状态一致 = 卡片位于
//      .cname == stateZh(JSON state) 的列（stateZh 映射见壳 web.py:64）。
// [C3] E3c 事件计数：seed 时 s3 事件链=恰好 3（state_change×2+progress_note×1，seed.py 预探针输出）；
//      服务启动对账（api/main.py:55 -> reconcile.py:27-37 "waiting" 信号 != active -> :87-89）
//      对 s3 确定性追加恰好 1 条 kind=reconcile（活体探针实测 seq 4，system:reconcile）。
//      故深潜页过滤前事件行 = 4（组成断言逐 kind 钉死）；过滤后计数与 plan 表一致
//      （state_change=2、progress_note=1，reconcile 被排除=负方向判别增强）。
// [C4] E4a source 口径：/board JSON 无 source 字段（web.md:12 契约 + view.board 实测）；
//      source/source_ref 在 GET /requirements/{id} JSON（view.detail）。断言改走 detail JSON。
// [C5] E3b 缺口标红：壳实际缺口标记 = .badge.gap "覆盖缺口" 徽章（--amber 琥珀色；web.md:29 写
//      "标红"，实际为琥珀徽章 = 措辞级差异，登记不裁决）。断言锚 .badge.gap + 文本。
// [C6] E6 SSE 触发口径：create（POST /requirements）不写事件（operations.new_requirement 无
//      add_event；壳自述 web.py:292 "create 不写事件，SSE 无触发器——主动重拉"），裸 create 无法
//      触发已打开页面的 SSE 刷新。按 web.md:51 机制（"另一进程推进状态 -> 2s 内自动刷新"），
//      本 spec 在 create 后追加一条 note 事件（POST /requirements/{id}/note，写 kind=note）作 SSE
//      触发器；断言保持 plan 原文（新标题 15s 内上板，expect.poll 禁固定 sleep）。
//      页面出现新卡必经 es.onmessage->loadBoard（壳无定时器重拉），即 SSE 驱动。
// [C7] E1/E7 夹具变更（s9 在板）：s9 = CLAIMED 非终态在板（E9/E10 专用夹具：XSS headline +
//      直 SQL 两条旧形状事件），seed 扩容＝契约变更 -> E1 在板 6->7、E7 CLAIMED 集合
//      [s6]->[s6,s9]。红步红因＝期望值未更新（陷阱库 3 预先声明），非壳缺陷；
//      绿步同步期望值＝夹具扩容的契约推论（非镜像实现凑绿）。
// [C8] E3c/E11 簿记 3 = state_change×2 + 启动对账 reconcile×1（[C3] s3 链不变）；人面行=1
//      （progress_note，提纲=seed headline，manifest s3_headline）。E9/E10 s9 人面链=3
//      （progress_note XSS headline + note 空 title + progress_note 旧 "progress"）；
//      s9 CLAIMED 活跃租约无 reconcile（与 s3 区别）。
// [C9] 夹具扩容（s10 review 种子带 summary_line）：E1 在板 7->8、E7 CLAIMED 集合
//      [s6,s9]->[s6,s9,s10]；红步红因＝期望值未更新（陷阱库 3），非壳缺陷。
//      反证位＝五处 mutation 探针（web.py:193/:418 剥腿 ×4 + 顺序颠倒 ×1），红日志留档。
//      精确文本的前缀/提示字面锚壳实现（选择器登记表 smoke.spec.js:6/:10）与 web.md:31 的
//      「人面确认:」/「解除阻塞:」措辞。
//
// 种子：webServer command 先跑 tests/e2e/seed.py 写 <AK_E2E_DB>.seeds.json 清单
// （s1-s7 必建 + s9 + s10；预探针触发后备则 s8，e5_target 指向 E5 对象）。

const { test, expect } = require('@playwright/test');
const fs = require('fs');

const DB = process.env.AK_E2E_DB || '/tmp/ak-e2e.db';
const BASE = `http://127.0.0.1:${process.env.E2E_PORT || 18765}`;
const SEEDS = JSON.parse(fs.readFileSync(DB + '.seeds.json', 'utf8'));
const T = SEEDS.titles;

// 卡片定位：标题唯一（e2e-sN-* 前缀）
const cardByTitle = (page, title) =>
  page.locator('.card', { has: page.locator('.ct', { hasText: title }) });

// 看板渲染完成锚（board-root 成功渲染 .cols；"加载中…" 消失）
async function boardReady(page) {
  await page.goto('/');
  await expect(page.locator('#board-root .cols')).toBeVisible();
  await expect(page.locator('#board-root')).not.toContainText('加载中');
}

const stateZh = { OPEN: '待认领', CLAIMED: '进行中', BLOCKED: '阻塞', REOPEN: '返工' }; // 壳 web.py:64

async function jget(url) {
  const r = await fetch(BASE + url);
  return { status: r.status, body: await r.json() };
}

test('E1 看板渲染与信号', async ({ page }) => {
  const dialogs = [];
  page.on('dialog', (d) => { dialogs.push(d.message()); d.dismiss().catch(() => {}); });
  await boardReady(page);
  // 8 条在板种子标题全部渲染（各恰 1 卡；含 s9/s10＝夹具扩容契约推论，[C7][C9]）
  for (const k of ['s1', 's2', 's3', 's4', 's5', 's6', 's9', 's10']) {
    await expect(cardByTitle(page, T[k]), `${k} 卡在场`).toHaveCount(1);
  }
  // 在板总数恰 8（集合等价的计数投影；s7 DONE 不在板，[C7][C9]）
  await expect(page.locator('#top-count')).toHaveText('8 个在板需求');
  await expect(cardByTitle(page, T.s7), 's7(DONE) 不在板').toHaveCount(0);
  // s3 看板行信号 = 等待人横幅（[C1]：attention 前提不成立，置顶顺序不断言，交 Q2）
  const s3wait = cardByTitle(page, T.s3).locator('.wait');
  await expect(s3wait, 's3 等待人横幅').toHaveCount(1);
  await expect(s3wait).toContainText('等待人:');
  await expect(s3wait).toContainText('kanban approve ' + SEEDS.s3);
  await expect(s3wait).toHaveText(`等待人: ${SEEDS.s3_reason} kanban approve ${SEEDS.s3}`);
  const s10wait = cardByTitle(page, T.s10).locator('.wait');
  await expect(s10wait, 's10 等待人横幅').toHaveCount(1);
  await expect(s10wait).toHaveText(`等待人: ${SEEDS.s10_summary_line} kanban approve ${SEEDS.s10}`);
  // 渲染期间无 XSS/异常 dialog
  expect(dialogs).toEqual([]);
});

test('E2 看板数据与 /board JSON 一致', async ({ page }) => {
  await boardReady(page);
  const { status, body } = await jget('/board');
  expect(status).toBe(200);
  // 逐种子 id 在场
  for (const k of ['s1', 's2', 's3', 's4', 's5', 's6']) {
    expect(body.tasks.map((t) => t.requirement_id), `${k} id 在场`).toContain(SEEDS[k]);
  }
  // 页面标题集合 == JSON 标题集合（集合断言，执行序无关）
  const pageTitles = await page.locator('.card .ct').allTextContents();
  expect([...pageTitles].sort()).toEqual([...body.tasks.map((t) => t.title)].sort());
  // 逐行：卡片 title 文本 == JSON title（toHaveCount(1) 已保证定位到本行卡）
  //      + 卡片位于 JSON state 对应列（[C2]）
  for (const t of body.tasks) {
    const card = cardByTitle(page, t.title);
    await expect(card).toHaveCount(1);
    const col = page.locator('.col').filter({
      has: page.locator('.card', { has: page.locator('.ct', { hasText: t.title }) }),
    });
    await expect(col, `${t.title} 所在列唯一`).toHaveCount(1);
    await expect(col.locator('.col-hd .cname')).toHaveText(stateZh[t.state]);
  }
});

test('E3a 深潜 s1：description 纯文本呈现 + XSS 中和', async ({ page }) => {
  const dialogs = [];
  page.on('dialog', (d) => { dialogs.push(d.message()); d.dismiss().catch(() => {}); });
  await boardReady(page);
  await cardByTitle(page, T.s1).click();
  await expect(page.locator('#detail-root h1'), '深潜渲染完成').toHaveText(T.s1);
  const desc = page.locator('div.sec').filter({ has: page.locator('h2', { hasText: /^描述$/ }) });
  await expect(desc).toHaveCount(1);
  // XSS 中和（真浏览器对抗位）：该节 img 元素数 = 0，对抗内容以纯文本呈现
  await expect(desc.locator('img')).toHaveCount(0);
  await expect(desc).toContainText('<img src=x onerror=alert(1)>');
  await expect(desc).toContainText('"double"');
  await expect(desc).toContainText("'single'");
  // 换行保留（pre-wrap 纯文本）
  const inner = await desc.locator('div[style*="white-space"]').innerText();
  expect(inner).toMatch(/line1.*\nline2 换行保留/s);
  // onerror 未触发 = 无 dialog
  expect(dialogs, 'XSS 未触发 dialog').toEqual([]);
});

test('E3b 深潜 s2：验收对照 2 行 + 覆盖缺口标记在场', async ({ page }) => {
  await boardReady(page);
  await cardByTitle(page, T.s2).click();
  await expect(page.locator('#detail-root h1')).toHaveText(T.s2);
  const accSec = page.locator('div.sec').filter({ has: page.locator('h2', { hasText: /^验收对照$/ }) });
  const rows = accSec.locator('li');
  await expect(rows, '验收对照 2 行').toHaveCount(2);
  for (const item of ['e2e 锚A', 'e2e 锚B']) {
    const row = rows.filter({ hasText: item });
    await expect(row, `${item} 行唯一`).toHaveCount(1);
    // 缺口标记（[C5]：壳实际形态 = .badge.gap "覆盖缺口" 徽章）
    await expect(row.locator('.badge.gap')).toHaveText('覆盖缺口');
  }
});

test('E3c 深潜 s3：事件流提纲优先（人面/簿记分组 + 过滤覆盖分组）', async ({ page }) => {
  await boardReady(page);
  await cardByTitle(page, T.s3).click();
  await expect(page.locator('#detail-root h1')).toHaveText(T.s3);
  const human = page.locator('#ev-list details.evh:not(.bk)');
  const bk = page.locator('#ev-list details.bk');
  // 默认（无过滤）：人面行 = 1（progress_note，提纲=seed headline）（[C3][C8]：s3 链 4 事件 = 人面 1 + 簿记 3）
  await expect(human, '人面事件行=1').toHaveCount(1);
  await expect(human.first().locator('.evh-t'), '提纲=seed headline').toHaveText(SEEDS.s3_headline);
  await expect(human.first().locator('.badge')).toHaveText('progress_note/info');
  // 簿记组在场且计数=3，默认收起
  await expect(bk, '簿记组在场').toHaveCount(1);
  await expect(bk.locator('summary')).toHaveText('簿记 3');
  await expect(bk).not.toHaveAttribute('open');
  // kind 过滤 state_change -> 平铺 2 行（过滤覆盖分组）
  await page.selectOption('#ev-kind', 'state_change');
  const evs = page.locator('#ev-list .ev');
  await expect(evs, 'state_change 过滤平铺=2').toHaveCount(2);
  for (let i = 0; i < 2; i++) {
    await expect(evs.nth(i).locator('.badge')).toHaveText('state_change/info');
  }
  // 负方向排除仍有效（progress_note/reconcile 不在场）
  await expect(page.locator('#ev-list')).not.toContainText('progress_note/info');
  await expect(page.locator('#ev-list')).not.toContainText('reconcile/info');
  // 对称位：progress_note -> 1
  await page.selectOption('#ev-kind', 'progress_note');
  await expect(evs, 'progress_note 过滤=1').toHaveCount(1);
  await expect(evs.first().locator('.badge')).toHaveText('progress_note/info');
});

test('E4a 顶栏新建两连发 + source 口径', async ({ page }) => {
  const ts = Date.now();
  const t1 = `e2e-new1-${ts}`;
  const t2 = `e2e-new2-${ts}`;
  const jira = 'https://jira.example.com/browse/E2E-100';
  await boardReady(page);

  await page.click('#new-btn');
  await expect(page.locator('#new-form')).toBeVisible();
  await page.fill('#nf-title', t1);
  await page.fill('#nf-acc', 'e2e 锚线一\ne2e 锚线二');
  await page.fill('#nf-jira', jira);
  await page.click('#new-form button.primary');
  await expect(page.locator('#nf-msg')).toHaveText('已创建');
  await expect(page.locator('#new-form')).toHaveCSS('display', 'none');

  await page.click('#new-btn');
  await expect(page.locator('#new-form')).toBeVisible();
  await page.fill('#nf-title', t2);
  await page.click('#new-form button.primary');
  await expect(page.locator('#nf-msg')).toHaveText('已创建');

  // 两新标题均出现在看板（poll ≤10s）
  await expect(cardByTitle(page, t1), 'new1 上板').toHaveCount(1, { timeout: 10000 });
  await expect(cardByTitle(page, t2), 'new2 上板').toHaveCount(1, { timeout: 10000 });

  // source 断言（[C4]）：/board JSON 无 source 字段（契约）；source 走 GET /requirements/{id}
  const { status, body } = await jget('/board');
  expect(status).toBe(200);
  const task1 = body.tasks.find((t) => t.title === t1);
  const task2 = body.tasks.find((t) => t.title === t2);
  expect(task1, 'new1 在 /board').toBeTruthy();
  expect(task2, 'new2 在 /board').toBeTruthy();
  expect(task1).not.toHaveProperty('source'); // web.md:12：/board 行无 source
  const d1 = (await jget(`/requirements/${task1.requirement_id}`)).body;
  expect(d1.source).toBe('jira');
  expect(d1.source_ref).toBe(jira);
  expect(d1.acceptance.map((a) => a.item)).toEqual(['e2e 锚线一', 'e2e 锚线二']);
  const d2 = (await jget(`/requirements/${task2.requirement_id}`)).body;
  expect(d2.source).toBe('manual'); // 默认 source
});

test('E4b 深潜 s4 archive -> 回看板，已归档 tab 在场', async ({ page }) => {
  await boardReady(page);
  await cardByTitle(page, T.s4).click();
  await expect(page.locator('#detail-root h1')).toHaveText(T.s4);
  await page.click('button[data-op="archive"]');
  // 终态操作成功 -> 回看板（web.md:42）
  await expect(page).toHaveURL(/\/$/);
  await expect(page.locator('#board-root .cols')).toBeVisible();
  await expect(cardByTitle(page, T.s4), 's4 离开在板').toHaveCount(0);
  await page.click('.tab[data-tab="archived"]');
  const rows = page.locator('.done-row');
  await expect(rows, '已归档恰 1 行').toHaveCount(1);
  await expect(rows.first(), 's4 在已归档 tab').toContainText(T.s4);
});

test('E4c 深潜 s5 delete：错误标题被拒，正确标题删成功', async ({ page }) => {
  const accepts = ['e2e-wrong-title', T.s5]; // 第 1 次 prompt 输错误标题，第 2 次输正确标题
  let n = 0;
  page.on('dialog', (dialog) => dialog.accept(accepts[n++ % accepts.length]));
  await boardReady(page);
  await cardByTitle(page, T.s5).click();
  await expect(page.locator('#detail-root h1')).toHaveText(T.s5);

  // 第一次：错误标题 -> 停留深潜页，内联拒绝
  await page.click('button:has-text("delete")');
  await expect(page.locator('#op-msg')).toHaveText('标题不匹配，已取消删除');
  await expect(page).toHaveURL(new RegExp(`/requirements/${SEEDS.s5}$`));

  // 第二次：正确标题 -> 回看板，s5 行消失
  await page.click('button:has-text("delete")');
  await expect(page).toHaveURL(/\/$/);
  await expect(page.locator('#board-root .cols')).toBeVisible();
  await expect(cardByTitle(page, T.s5), 's5 已删').toHaveCount(0);
});

test('E5 深潜 s3：等待人横幅含 kanban approve 静态文案', async ({ page }) => {
  const target = SEEDS.e5_target; // 预探针结论：s3（或后备 s8）
  await boardReady(page);
  await cardByTitle(page, T[target]).click();
  await expect(page.locator('#detail-root h1')).toHaveText(T[target]);
  const banner = page.locator('.wait-banner');
  await expect(banner, '等待人横幅在场').toHaveCount(1);
  await expect(banner).toContainText('等待人决策:');
  await expect(banner).toContainText('kanban approve ' + SEEDS[target]);
  await expect(banner).toHaveText(`等待人决策: ${SEEDS.s3_reason} （解除阻塞: kanban approve ${SEEDS[target]}）`);
});

test('E6 另一进程推进 -> SSE 刷新，新标题 15s 内上板', async ({ page }) => {
  const title = `e2e-live-${Date.now()}`;
  await boardReady(page);
  await expect(cardByTitle(page, title), '前置：未上板').toHaveCount(0);
  // 另一进程（node fetch，非壳表单路径）创建 + note 事件触发 SSE（[C6]）
  const created = await fetch(BASE + '/requirements', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  });
  expect(created.status).toBe(201);
  const cid = (await created.json()).requirement_id;
  const noted = await fetch(BASE + `/requirements/${cid}/note`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content: 'e2e-live' }),
  });
  expect(noted.status).toBe(200);
  // 新标题 15s 内出现在看板（SSE 重拉；expect.poll，禁固定 sleep）
  await expect.poll(
    async () => (await page.locator('.card .ct', { hasText: title }).count()),
    { timeout: 15000, message: '新标题 15s 内上板（SSE 驱动）' },
  ).toBe(1);
});

test('E7 /board?status=CLAIMED 过滤强断言', async () => {
  const { status, body } = await jget('/board?status=CLAIMED');
  expect(status).toBe(200);
  // 此时 s4 已归档(E4b)、s5 已删(E4c)、s1/s2 及 E4a/E6 新建均 OPEN、s3 BLOCKED、s7 DONE、
  // s9/s10 CLAIMED（夹具扩容契约推论，[C7][C9]：[s6]->[s6,s9,s10]；id 随机序，双侧 sort 后比较）
  expect(body.tasks.map((t) => t.requirement_id).sort())
    .toEqual([SEEDS.s6, SEEDS.s9, SEEDS.s10].sort());
});

test('E8 三 tab：已完成 s7 在场，回在板 s1 在场', async ({ page }) => {
  await boardReady(page);
  await page.click('.tab[data-tab="done"]');
  const rows = page.locator('.done-row');
  await expect(rows, '已完成恰 1 行').toHaveCount(1);
  await expect(rows.first(), 's7 在已完成 tab').toContainText(T.s7);
  await expect(rows.first().locator('.pill')).toHaveText('已完成');
  await page.click('.tab[data-tab="active"]');
  await expect(page.locator('#board-root .cols')).toBeVisible();
  await expect(cardByTitle(page, T.s1), '回在板 s1 在场').toHaveCount(1);
});

test('E9 深潜 s9：headline 提纲 + 展开全文 + XSS 中和', async ({ page }) => {
  const dialogs = [];
  page.on('dialog', (d) => { dialogs.push(d.message()); d.dismiss().catch(() => {}); });
  await boardReady(page);
  await cardByTitle(page, T.s9).click();
  await expect(page.locator('#detail-root h1')).toHaveText(T.s9);
  // XSS 提纲行在场（转义形态在场 = esc 生效）
  const row = page.locator('#ev-list details.evh:not(.bk)')
    .filter({ hasText: '<img src=x onerror=alert(1)>' });
  await expect(row, 'XSS 提纲行在场').toHaveCount(1);
  // 无 IMG 元素注入（安全 oracle）
  await expect(page.locator('img'), '无 IMG 注入').toHaveCount(0);
  // 默认收起；点开见 content 全文
  await expect(row).not.toHaveAttribute('open');
  await row.locator('summary').click();
  await expect(row, '展开见全文').toContainText('e2e s9 展开全文');
  expect(dialogs, 'XSS 未触发 dialog').toEqual([]);
});

test('E10 深潜 s9：旧数据容忍（空 title 显 kind 标签 / 旧 progress 原样 / 不崩）', async ({ page }) => {
  await boardReady(page);
  await cardByTitle(page, T.s9).click();
  await expect(page.locator('#detail-root h1')).toHaveText(T.s9);
  await expect(page.locator('#detail-root')).not.toContainText('加载失败');
  // s9 人面链 = 3：progress_note(XSS headline) + note(空 title) + progress_note(旧 "progress")（[C8]）
  const rows = page.locator('#ev-list details.evh:not(.bk)');
  await expect(rows, 's9 人面行=3').toHaveCount(3);
  // 空 title 行：提纲位显 kind 标签
  const emptyRow = rows.filter({ has: page.locator('.evh-t', { hasText: /^note$/ }) });
  await expect(emptyRow, '空 title 行提纲=kind 标签').toHaveCount(1);
  // 旧 "progress" 行：原样显示（不做特殊识别）
  const progRow = rows.filter({ has: page.locator('.evh-t', { hasText: /^progress$/ }) });
  await expect(progRow, '旧 progress 行原样').toHaveCount(1);
});

test('E11 深潜 s3：簿记折叠（计数 + 默认收起 + 展开平铺 3 行）', async ({ page }) => {
  await boardReady(page);
  await cardByTitle(page, T.s3).click();
  await expect(page.locator('#detail-root h1')).toHaveText(T.s3);
  const bk = page.locator('#ev-list details.bk');
  await expect(bk, '簿记组在场').toHaveCount(1);
  // 标题计数=3（[C3][C8]：state_change×2 + reconcile×1），默认收起（closed）
  await expect(bk.locator('summary')).toHaveText('簿记 3');
  await expect(bk).not.toHaveAttribute('open');
  // 人面行未被吞入簿记：s3 人面 = 1
  await expect(page.locator('#ev-list details.evh:not(.bk)'), '人面行=1').toHaveCount(1);
  // 展开后 3 平铺行（badge 组成钉死）
  await bk.locator('summary').click();
  const rows = bk.locator('.ev');
  await expect(rows, '展开平铺 3 行').toHaveCount(3);
  const badges = (await rows.locator('.badge').allTextContents()).sort();
  expect(badges).toEqual(['reconcile/info', 'state_change/info', 'state_change/info']);
});

test('E12 深潜 s10：等待横幅显 summary_line（review 优先腿）', async ({ page }) => {
  await boardReady(page);
  await cardByTitle(page, T.s10).click();
  await expect(page.locator('#detail-root h1')).toHaveText(T.s10);
  const banner = page.locator('.wait-banner');
  await expect(banner, '等待人横幅在场').toHaveCount(1);
  await expect(banner).toHaveText(
    `等待人决策: ${SEEDS.s10_summary_line} （人面确认: kanban approve ${SEEDS.s10}）`);
});
