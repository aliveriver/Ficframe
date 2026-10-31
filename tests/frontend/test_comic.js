const assert = require('node:assert/strict');
const test = require('node:test');
const comic = require('../../web/comic.js');

const project = () => ({ schema_version: 1, id: 'comic/一', revision: 3, title: '测试', characters: [], pages: [{ id: 'page 1', width: 1200, height: 1700, panels: [{ id: 'p1', rect: { x: .1, y: .2, w: .4, h: .5 }, balloons: [] }] }] });

test('drag clamps at page edges and preserves size without mutating source', () => {
  const rect = { x: .1, y: .2, w: .4, h: .5 };
  assert.deepEqual(comic.transformRect(rect, 2, -2), { x: .6, y: 0, w: .4, h: .5 });
  assert.deepEqual(rect, { x: .1, y: .2, w: .4, h: .5 });
});
test('drawing a panel works in either direction and stays within page', () => {
  assert.deepEqual(comic.rectFromPoints({ x: .8, y: .9 }, { x: .2, y: .3 }), { x: .2, y: .3, w: .8 - .2, h: .9 - .3 });
  assert.deepEqual(comic.rectFromPoints({ x: .2, y: .3 }, { x: 2, y: 2 }), { x: .2, y: .3, w: .8, h: .7 });
});
test('resize preserves origin, enforces minimum size and stays in bounds', () => {
  assert.deepEqual(comic.transformRect({ x: .8, y: .7, w: .1, h: .2 }, 1, -1, true), { x: .8, y: .7, w: 1 - .8, h: .01 });
  assert.deepEqual(comic.normalizeRect({ x: -3, y: 2, w: 4, h: .4 }), { x: 0, y: .6, w: 1, h: .4 });
});
test('mode inheritance honors explicit overrides including clean and blank', () => {
  const p = { lettering_mode: 'text' }, pg = { lettering_mode: 'blank' }, panel = { lettering_mode: 'inherit' };
  assert.equal(comic.effectiveMode(p, pg, panel), 'blank');
  assert.equal(comic.effectiveMode(p, pg, { lettering_mode: 'clean' }), 'clean');
  assert.equal(comic.effectiveMode(p, pg, panel, 'text'), 'text');
  assert.equal(comic.effectiveMode({}, {}, {}), 'text');
});
test('preview is revision keyed and export encodes selected pages and optional mode', () => {
  const p = project();
  assert.equal(comic.previewUrl(p, p.pages[0]), '/api/comics/comic%2F%E4%B8%80/preview/page%201?revision=3');
  const url = new URL(comic.exportUrl(p, 'pdf', 'blank', ['a', 'b']), 'http://localhost');
  assert.equal(url.searchParams.get('page_ids'), 'a,b'); assert.equal(url.searchParams.get('mode'), 'blank');
  assert.equal(new URL(comic.exportUrl(p, 'png', ''), 'http://localhost').searchParams.has('mode'), false);
});
test('advanced project validation catches duplicate entities and invalid page shapes', () => {
  const p = project(); assert.equal(comic.validateProject(p), p);
  p.pages[0].panels[0].balloons.push({ id: 'p1' }); assert.throws(() => comic.validateProject(p), /唯一 ID/);
  assert.throws(() => comic.validateProject({ pages: [], characters: {} }), /数组/);
  const bad = project(); bad.pages[0].width = 0; assert.throws(() => comic.validateProject(bad), /尺寸/);
});
test('save queue serializes concurrent flushes and keeps in-flight edits with latest revision', async () => {
  let p = project(), version = 1, release;
  const writes = [];
  const queue = comic.createSaveQueue({ getProject: () => p, getVersion: () => version, request: async (_, options) => {
    const snapshot = JSON.parse(options.body); writes.push(snapshot);
    if (writes.length === 1) await new Promise(resolve => { release = resolve; });
    return { ...snapshot, revision: snapshot.revision + 1 };
  } });
  const first = queue.flush(); await new Promise(resolve => setImmediate(resolve));
  p.title = '保存期间输入'; version++;
  const second = queue.flush(); release(); await Promise.all([first, second]);
  assert.equal(writes.length, 2); assert.equal(writes[0].title, '测试'); assert.equal(writes[1].title, '保存期间输入');
  assert.deepEqual(writes.map(v => v.revision), [3, 4]); assert.equal(p.revision, 5); assert.equal(queue.savedVersion, 2);
});
test('conflict retains local changes and queue can retry without swallowing rejection', async () => {
  const p = project(); let fail = true;
  const queue = comic.createSaveQueue({ getProject: () => p, getVersion: () => 1, request: async () => {
    if (fail) throw new Error('409'); return { ...p, revision: 4 };
  } });
  await assert.rejects(queue.flush(), /409/); assert.equal(queue.savedVersion, 0); assert.equal(p.revision, 3);
  fail = false; await queue.flush(); assert.equal(queue.savedVersion, 1); assert.equal(p.revision, 4);
});
test('a response for an old project cannot overwrite newly selected project', async () => {
  let p = project(), release;
  const queue = comic.createSaveQueue({ getProject: () => p, getVersion: () => 1, request: async () => { await new Promise(resolve => { release = resolve; }); return { revision: 9 }; } });
  const pending = queue.flush(); await new Promise(resolve => setImmediate(resolve));
  p = { ...project(), id: 'another', revision: 1 }; release(); await pending;
  assert.equal(p.revision, 1);
});
test('failed and cancelled tasks are terminal so recovery can refresh the project', () => {
  for (const status of ['succeeded', 'failed', 'cancelled', 'completed']) assert.equal(comic.terminal(status), true);
  assert.equal(comic.terminal('running'), false);
});
