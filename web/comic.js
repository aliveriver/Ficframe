(function (global) {
  'use strict';
  const clone = value => JSON.parse(JSON.stringify(value));
  const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
  const modes = [['inherit', '继承上级'], ['text', '文字'], ['blank', '空白气泡'], ['clean', '纯画面']];
  const terminal = status => ['succeeded', 'failed', 'cancelled', 'completed'].includes(status);
  const uid = prefix => `${prefix}_${global.crypto?.randomUUID?.() || `${Date.now()}_${Math.random().toString(36).slice(2)}`}`;
  function normalizeRect(rect = {}) {
    const w = clamp(Number(rect.w) || .1, .01, 1), h = clamp(Number(rect.h) || .1, .01, 1);
    return { x: clamp(Number(rect.x) || 0, 0, 1 - w), y: clamp(Number(rect.y) || 0, 0, 1 - h), w, h };
  }
  function transformRect(rect, dx, dy, resize = false) {
    const r = normalizeRect(rect);
    return resize ? { ...r, w: clamp(r.w + dx, .01, 1 - r.x), h: clamp(r.h + dy, .01, 1 - r.y) }
      : { ...r, x: clamp(r.x + dx, 0, 1 - r.w), y: clamp(r.y + dy, 0, 1 - r.h) };
  }
  function effectiveMode(project, page, panel, override) {
    return [override, panel?.lettering_mode, page?.lettering_mode, project?.lettering_mode, 'text'].find(v => v && v !== 'inherit');
  }
  const encoded = value => encodeURIComponent(value);
  function previewUrl(project, page) { return `/api/comics/${encoded(project.id)}/preview/${encoded(page.id)}?revision=${encoded(project.revision)}`; }
  function exportUrl(project, format, mode, pageIds = []) {
    const params = new URLSearchParams({ format });
    if (mode) params.set('mode', mode);
    if (pageIds.length) params.set('page_ids', pageIds.join(','));
    return `/api/comics/${encoded(project.id)}/export?${params}`;
  }
  function validateProject(value) {
    if (!value || typeof value !== 'object' || Array.isArray(value) || !Array.isArray(value.pages) || !Array.isArray(value.characters)) throw new Error('工程必须包含 pages 与 characters 数组');
    const ids = new Set();
    const id = item => { if (!item?.id || ids.has(item.id)) throw new Error('页、画格和气泡必须有唯一 ID'); ids.add(item.id); };
    for (const page of value.pages) {
      id(page);
      if (!(page.width >= 100 && page.height >= 100) || !Array.isArray(page.panels)) throw new Error('页面尺寸至少为 100，且须包含 panels 数组');
      for (const panel of page.panels) { id(panel); if (!panel.rect || !Array.isArray(panel.balloons || [])) throw new Error('画格需要 rect 和 balloons 数组'); for (const balloon of panel.balloons || []) id(balloon); }
    }
    return value;
  }
  // Saves are serialized. Acknowledgements advance revision without discarding edits made in flight.
  function createSaveQueue({ getProject, getVersion, request, onSaved }) {
    let chain = Promise.resolve();
    return { flush() {
      const run = async () => {
        while (true) {
          const version = getVersion();
          if (!getProject() || version === this.savedVersion) return;
          const snapshot = clone(getProject());
          const result = await request(`/api/comics/${encoded(snapshot.id)}`, { method: 'PUT', body: JSON.stringify(snapshot) });
          const saved = result.project || result;
          if (!Number.isFinite(saved.revision)) throw new Error('保存响应缺少 revision，请重新读取工程');
          if (getProject()?.id !== snapshot.id) return;
          getProject().revision = saved.revision;
          this.savedVersion = version;
          onSaved?.(saved, getVersion() === version);
          if (getVersion() === version) return;
        }
      };
      chain = chain.catch(() => {}).then(run);
      return chain;
    }, savedVersion: 0, reset(version = 0) { this.savedVersion = version; } };
  }
  function rectFromPoints(start, end) {
    const x = clamp(Math.min(start.x, end.x), 0, 1), y = clamp(Math.min(start.y, end.y), 0, 1);
    return { x, y, w: Math.min(1 - x, Math.abs(end.x - start.x)), h: Math.min(1 - y, Math.abs(end.y - start.y)) };
  }
  const helpers = { normalizeRect, transformRect, rectFromPoints, effectiveMode, previewUrl, exportUrl, validateProject, createSaveQueue, terminal };
  global.FicFrameComic = helpers;
  if (typeof module !== 'undefined' && module.exports) module.exports = helpers;
  if (!global.document) return;

  function boot() {
    const $ = id => document.getElementById(id);
    const state = { project: null, pageId: null, panelId: null, balloonId: null, checked: new Set(), version: 0, presets: [], busy: false, poll: null, taskSignature: '', refreshPending: false, charactersDirty: false, advancedDirty: false, epoch: 0 };
    const page = () => state.project?.pages.find(p => p.id === state.pageId);
    const panel = () => page()?.panels.find(p => p.id === state.panelId);
    const balloon = () => panel()?.balloons?.find(b => b.id === state.balloonId);
    const base = () => `/api/comics/${encoded(state.project.id)}`;
    function confirmAction(text) {
      return new Promise(resolve => {
        const dialog = $('confirmDialog'); $('confirmText').textContent = text;
        const finish = value => { dialog.close(); resolve(value); };
        $('confirmAccept').onclick = () => finish(true); $('confirmCancel').onclick = () => finish(false);
        dialog.oncancel = event => { event.preventDefault(); finish(false); }; dialog.showModal();
      });
    }
    function message(text, error = false) { $('message').hidden = !text; $('message').textContent = text; $('message').classList.toggle('error', error); }
    async function request(url, options = {}) {
      const response = await fetch(url, { ...options, headers: { ...(options.body && !(options.body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}), ...options.headers } });
      if (!response.ok) {
        let detail; try { const data = await response.json(); detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || data); } catch (_) { detail = response.statusText; }
        throw new Error(response.status === 409 ? '工程版本冲突：本地输入已保留。请复制需保留内容后重新读取工程，再合并修改。' : `请求失败 (${response.status})：${detail}`);
      }
      return response.status === 204 ? {} : response.json();
    }
    function dirty() { state.version++; $('saveStatus').textContent = '有未保存修改'; }
    const saver = createSaveQueue({ getProject: () => state.project, getVersion: () => state.version, request, onSaved(saved, current) {
      if (current) {
        for (const pg of state.project.pages) for (const p of pg.panels) {
          const fresh = saved.pages?.flatMap(item => item.panels).find(item => item.id === p.id);
          if (fresh) { p.effective_states = fresh.effective_states; p.needs_review = fresh.needs_review; }
        }
        state.project.history = saved.history || state.project.history;
        setOptions($('history'), (state.project.history || []).map((entry, i) => [String(i), entry.label || entry.title || `${i + 1} · ${entry.action || '历史快照'}`]));
        $('saveStatus').textContent = `已保存 · r${saved.revision}`;
      }
      renderPreview(); renderPages();
    } });
    function needProject() { if (!state.project) throw new Error('请先新建或打开漫画工程'); }
    function node(tag, text, className) { const n = document.createElement(tag); if (text != null) n.textContent = text; if (className) n.className = className; return n; }
    function option(value, text) { const n = node('option', text); n.value = value; return n; }
    function setOptions(element, values, selected) { element.replaceChildren(...values.map(([v, t]) => option(v, t))); element.value = selected ?? ''; }
    function modeOptions(id, value, inherit = true) { setOptions($(id), modes.filter(([v]) => inherit || v !== 'inherit'), value); }
    function field(container, label, value, update, type = 'text', config = {}) {
      const wrapper = node('label', label), input = document.createElement(type === 'textarea' ? 'textarea' : 'input');
      if (type !== 'textarea') input.type = type;
      if (type === 'checkbox') { wrapper.className = 'check'; input.checked = !!value; } else input.value = value ?? '';
      Object.assign(input, config); wrapper.append(input); container.append(wrapper);
      input.addEventListener(type === 'checkbox' ? 'change' : 'input', () => {
        if (type === 'number' && (!input.checkValidity() || input.value === '')) return;
        update(type === 'checkbox' ? input.checked : type === 'number' ? Number(input.value) : input.value); dirty();
      });
      return input;
    }
    function selectField(container, label, value, values, update) {
      const wrapper = node('label', label), select = node('select'); setOptions(select, values, value); wrapper.append(select); container.append(wrapper);
      select.onchange = () => { update(select.value); dirty(); }; return select;
    }
    function applyCharacters() {
      if (!state.charactersDirty) return;
      const list = JSON.parse($('characters').value);
      if (!Array.isArray(list) || list.some(c => !c || typeof c !== 'object' || Array.isArray(c))) throw new Error('角色 JSON 须为角色对象数组');
      for (const c of list) c.id ||= uid('char');
      if (new Set(list.map(c => c.id)).size !== list.length) throw new Error('角色 ID 不可重复');
      needProject(); state.project.characters = list; state.charactersDirty = false; dirty();
    }
    function advancedObject() { return $('advancedTarget').value === 'project' ? state.project : $('advancedTarget').value === 'page' ? page() : panel(); }
    function applyAdvanced() {
      if (!state.advancedDirty) return;
      needProject(); const target = $('advancedTarget').value, original = advancedObject();
      if (!original) throw new Error('请先选择编辑对象');
      const value = JSON.parse($('advanced').value);
      if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('JSON 必须是对象');
      const candidate = clone(state.project);
      if (target === 'project') Object.assign(candidate, value, { id: state.project.id, revision: state.project.revision });
      else {
        value.id = original.id;
        const pg = candidate.pages.find(p => p.id === state.pageId);
        if (target === 'page') candidate.pages[candidate.pages.indexOf(pg)] = value;
        else pg.panels[pg.panels.findIndex(p => p.id === state.panelId)] = value;
      }
      validateProject(candidate); state.project = candidate; state.advancedDirty = false; dirty();
    }
    async function flush() {
      needProject(); const advancedWasDirty = state.advancedDirty; applyCharacters(); applyAdvanced();
      if (advancedWasDirty) renderAll();
      const invalid = document.querySelector('.workbench input:invalid');
      if (invalid) { invalid.reportValidity(); throw new Error('请修正无效的数字设置'); }
      validateProject(state.project); await saver.flush();
    }
    async function exclusive(fn) {
      if (state.busy) return;
      state.busy = true;
      // Freeze inputs during structural operations; saves alone allow continued typing.
      const controls = [...document.querySelectorAll('.workbench button,.workbench input,.workbench select,.workbench textarea')];
      const wasDisabled = controls.map(n => n.disabled); controls.forEach(n => { n.disabled = true; });
      try { await fn(); } finally { controls.forEach((n, i) => { if (n.isConnected) n.disabled = wasDisabled[i]; }); state.busy = false; }
    }
    function bind(id, fn, event = 'click') { $(id).addEventListener(event, async e => { try { await fn(e); } catch (error) { message(error.message, true); } }); }
    function hydrate(project) {
      validateProject(project); state.project = project; state.version = 0; saver.reset(); state.charactersDirty = false; state.advancedDirty = false; state.epoch++;
      if (!project.pages.some(p => p.id === state.pageId)) state.pageId = project.pages[0]?.id || null;
      if (!page()?.panels.some(p => p.id === state.panelId)) state.panelId = page()?.panels[0]?.id || null;
      state.balloonId = panel()?.balloons?.[0]?.id || null; state.checked.clear();
      $('saveStatus').textContent = `已保存 · r${project.revision}`; state.refreshPending = false;
      if ([...$('projects').options].some(option => option.value === project.id)) $('projects').value = project.id;
      try { localStorage.setItem('ficframe.comic.id', project.id); } catch (_) { /* Storage is optional. */ }
      renderAll();
    }
    async function load(id, saveFirst = true) {
      if (saveFirst && state.project) await flush();
      const project = await request(`/api/comics/${encoded(id)}`); hydrate(project.project || project);
      state.taskSignature = ''; clearTimeout(state.poll); await pollTasks();
    }
    async function listProjects() {
      const data = await request('/api/comics');
      setOptions($('projects'), [['', '选择漫画工程'], ...(data.projects || data.comics || (Array.isArray(data) ? data : [])).map(p => [p.id, p.title || p.id])], state.project?.id);
    }
    async function createProject(sourceRunId) {
      if (state.project) await flush();
      let characters = JSON.parse($('characters').value || '[]');
      if (!Array.isArray(characters)) throw new Error('角色 JSON 必须为数组');
      const body = { title: $('title').value || '未命名漫画', source_text: $('source').value, characters };
      if (sourceRunId) body.source_run_id = sourceRunId;
      const result = await request('/api/comics', { method: 'POST', body: JSON.stringify(body) });
      if ((result.project || result).pages) hydrate(result.project || result); else await load(result.id || result.project_id, false);
      await listProjects(); await pollTasks();
    }
    async function operation(action, extra = {}) {
      await exclusive(async () => {
        await flush();
        const result = await request(`${base()}/operation`, { method: 'POST', body: JSON.stringify({ action, page_id: state.pageId, panel_id: state.panelId, ...extra }) });
        const updated = result.project || result;
        if (Array.isArray(updated.pages)) hydrate(updated); else await load(state.project.id, false);
      });
    }
    function renderPreview() {
      const pg = page(); $('paper').hidden = !pg; $('empty').hidden = !!pg;
      if (!pg) return;
      $('paper').style.aspectRatio = `${pg.width} / ${pg.height}`;
      $('previewError').hidden = true; $('preview').src = previewUrl(state.project, pg);
      $('pageLabel').textContent = `第 ${state.project.pages.indexOf(pg) + 1} 页`;
      renderOverlays();
    }
    function renderPages() {
      $('pages').replaceChildren();
      for (const [index, pg] of (state.project?.pages || []).entries()) {
        const button = node('button', null, `page-thumb${pg.id === state.pageId ? ' selected' : ''}`);
        const image = node('img'); image.src = previewUrl(state.project, pg); image.alt = `第 ${index + 1} 页缩略图`; image.loading = 'lazy';
        button.append(image, node('span', `第 ${index + 1} 页`)); button.setAttribute('aria-pressed', String(pg.id === state.pageId));
        button.onclick = () => navigate(async () => { state.pageId = pg.id; state.panelId = pg.panels[0]?.id; state.checked.clear(); renderPageSettings(); renderPreview(); renderPages(); renderPanelList(); renderPanel(); });
        $('pages').append(button);
      }
      setOptions($('movePage'), (state.project?.pages || []).map((p, i) => [p.id, `第 ${i + 1} 页`]), state.pageId);
    }
    async function navigate(fn) { try { applyCharacters(); applyAdvanced(); await fn(); } catch (error) { message(error.message, true); } }
    function setRectStyle(n, rect) { const r = normalizeRect(rect); Object.assign(n.style, { left: `${r.x * 100}%`, top: `${r.y * 100}%`, width: `${r.w * 100}%`, height: `${r.h * 100}%` }); }
    let canvasTool = 'select';
    function renderOverlays() {
      const root = $('overlays'); root.replaceChildren();
      $('paper').classList.toggle('draw-mode', canvasTool === 'draw');
      for (const [i, p] of (page()?.panels || []).entries()) {
        const n = makeOverlay(p, 'panel', p, p.id === state.panelId, `画格 ${i + 1}`); root.append(n);
        if (p.id === state.panelId) {
          const mode = effectiveMode(state.project, page(), p);
          const inner = node('div', null, 'panel-inner'), r = normalizeRect(p.rect);
          const inset = Math.min(Math.max(0, Math.round((page().gutter || 0) / 2)), (Math.min(r.w * page().width, r.h * page().height) - 1) / 2);
          Object.assign(inner.style, { position: 'absolute', inset: `${inset / (r.h * page().height) * 100}% ${inset / (r.w * page().width) * 100}%`, pointerEvents: 'none' }); n.append(inner);
          for (const b of p.balloons || []) {
            if (mode === 'clean' || b.show === false || state.project.text_settings?.[b.kind] === false) continue;
            const overlay = makeOverlay(b, 'balloon', p, b.id === state.balloonId, `${b.kind === 'dialogue' ? '对白' : b.kind === 'narration' ? '旁白' : '音效'}：${b.text || '空文字'}`);
            overlay.style.pointerEvents = 'auto'; inner.append(overlay);
          }
        }
      }
    }
    function makeOverlay(target, kind, owner, selected, label) {
      const n = node('div', null, `overlay ${kind}${selected ? ' selected' : ''}`); setRectStyle(n, target.rect);
      n.tabIndex = 0; n.setAttribute('role', 'button'); n.setAttribute('aria-label', label); n.setAttribute('aria-pressed', String(selected));
      if (kind === 'panel') {
        n.dataset.panelId = owner.id;
        const content = node('div', null, 'panel-content');
        const crop = node('img'); crop.src = $('preview').src; crop.alt = ''; crop.draggable = false;
        const r = normalizeRect(target.rect);
        Object.assign(crop.style, { width: `${100 / r.w}%`, height: `${100 / r.h}%`, left: `${-r.x / r.w * 100}%`, top: `${-r.y / r.h * 100}%` });
        content.append(crop); n.append(content);
      }
      const handle = node('span', null, 'handle'); handle.setAttribute('aria-hidden', 'true');
      n.append(handle);
      if (kind === 'panel') n.append(node('span', String(page().panels.indexOf(owner) + 1), 'overlay-label'));
      n.onkeydown = e => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); select(); }
        if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(e.key)) {
          e.preventDefault(); if (state.busy || (kind === 'panel' && owner.locks?.layout)) return;
          const step = e.shiftKey ? .02 : .005;
          target.rect = transformRect(target.rect, e.key === 'ArrowLeft' ? -step : e.key === 'ArrowRight' ? step : 0, e.key === 'ArrowUp' ? -step : e.key === 'ArrowDown' ? step : 0, e.altKey); dirty(); setRectStyle(n, target.rect);
        }
      };
      function select() {
        if (state.advancedDirty || state.charactersDirty) { message('请先应用正在编辑的 JSON，再选择画格', true); return false; }
        state.panelId = owner.id; state.balloonId = kind === 'balloon' ? target.id : owner.balloons?.[0]?.id; renderPanelList(); renderPanel(); return true;
      }
      n.addEventListener('pointerdown', e => {
        if (canvasTool === 'draw' || state.busy || e.button !== 0) return;
        e.stopPropagation(); e.preventDefault();
        if (!select()) return;
        // Keep this overlay mounted throughout pointer capture.
        rootSelection(n, owner.id, target.id, kind);
        if (owner.locks?.layout) { message('此格已锁定布局，请先解除布局锁'); return; }
        const initial = normalizeRect(target.rect), origin = { x: e.clientX, y: e.clientY }, resizing = e.target === handle;
        const bounds = (kind === 'balloon' ? n.parentElement : $('paper')).getBoundingClientRect();
        n.setPointerCapture(e.pointerId);
        let moved = false;
        const move = event => {
          const dx = (event.clientX - origin.x) / bounds.width, dy = (event.clientY - origin.y) / bounds.height;
          if (!moved && Math.hypot(event.clientX - origin.x, event.clientY - origin.y) < 3) return;
          target.rect = transformRect(initial, dx, dy, resizing); setRectStyle(n, target.rect);
          n.classList.add('dragging'); $('paper').classList.add('editing-layout'); moved = true;
        };
        const end = async event => {
          n.removeEventListener('pointermove', move); n.removeEventListener('pointerup', end); n.removeEventListener('pointercancel', end);
          if (n.hasPointerCapture(event.pointerId)) n.releasePointerCapture(event.pointerId);
          if (event.type === 'pointercancel') { target.rect = initial; moved = false; }
          if (moved) { dirty(); try { await flush(); } catch (error) { message(error.message, true); } }
          $('paper').classList.remove('editing-layout'); renderOverlays(); renderPanel();
        };
        n.addEventListener('pointermove', move); n.addEventListener('pointerup', end); n.addEventListener('pointercancel', end);
      });
      return n;
    }
    function setCanvasTool(tool) {
      canvasTool = tool;
      $('selectTool').setAttribute('aria-pressed', String(tool === 'select'));
      $('drawTool').setAttribute('aria-pressed', String(tool === 'draw'));
      $('canvasHint').textContent = tool === 'draw' ? '在纸面上拖出矩形创建画格，Esc 返回选择' : '拖动画格移动，拖动角点缩放；松手自动保存';
      renderOverlays();
    }
    bind('selectTool', () => setCanvasTool('select'));
    bind('drawTool', () => { needProject(); setCanvasTool('draw'); });
    $('overlays').addEventListener('pointerdown', e => {
      if (canvasTool !== 'draw' || state.busy || e.button !== 0 || !page()) return;
      e.preventDefault();
      const root = $('overlays'), bounds = root.getBoundingClientRect();
      const point = event => ({ x: clamp((event.clientX - bounds.left) / bounds.width, 0, 1), y: clamp((event.clientY - bounds.top) / bounds.height, 0, 1) });
      const start = point(e), draft = node('div', null, 'draw-draft'); root.append(draft); root.setPointerCapture(e.pointerId);
      let rect = rectFromPoints(start, start);
      const move = event => { rect = rectFromPoints(start, point(event)); setRectStyle(draft, rect); };
      const end = async event => {
        root.removeEventListener('pointermove', move); root.removeEventListener('pointerup', end); root.removeEventListener('pointercancel', end);
        if (root.hasPointerCapture(event.pointerId)) root.releasePointerCapture(event.pointerId);
        draft.remove();
        if (event.type === 'pointercancel' || rect.w < .025 || rect.h < .025) return;
        const created = { id: uid('panel'), description: '', characters: [], actions: '', expression: '', camera: '中景', angle: '平视', scene_id: '', time: '', source_ref: { kind: 'description', quote: '' }, positive_prompt: '', negative_prompt: '', rect, crop: { x: .5, y: .5, zoom: 1 }, lettering_mode: 'inherit', locks: {}, state_bindings: {}, effective_states: {}, needs_review: [], balloons: [], image_versions: [], current_image: null };
        page().panels.push(created); state.panelId = created.id; dirty(); setCanvasTool('select'); renderPanelList(); renderPanel();
        try { await flush(); } catch (error) { message(error.message, true); }
      };
      root.addEventListener('pointermove', move); root.addEventListener('pointerup', end); root.addEventListener('pointercancel', end);
    });
    document.addEventListener('keydown', e => { if (e.key === 'Escape') setCanvasTool('select'); });
    function rootSelection(n, ownerId, targetId, kind) {
      $('overlays').querySelectorAll('.overlay').forEach(el => el.classList.remove('selected'));
      n.classList.add('selected');
      if (kind === 'balloon') n.closest('.overlay.panel')?.classList.add('selected');
    }
    function renderPageSettings() {
      const p = state.project, pg = page();
      modeOptions('projectMode', p?.lettering_mode || 'text', false); modeOptions('pageMode', pg?.lettering_mode || 'inherit');
      $('pageWidth').value = pg?.width || ''; $('pageHeight').value = pg?.height || ''; $('gutter').value = pg?.gutter ?? '';
      $('textSettings').replaceChildren();
      for (const [key, label] of [['dialogue', '对白'], ['narration', '旁白'], ['sfx', '音效']]) field($('textSettings'), label, p?.text_settings?.[key] !== false, value => { if (!p) return; p.text_settings ||= {}; p.text_settings[key] = value; renderOverlays(); }, 'checkbox');
    }
    function renderPanelList() {
      $('panelList').replaceChildren();
      for (const [i, p] of (page()?.panels || []).entries()) {
        const row = node('div', null, `panel-row${p.id === state.panelId ? ' selected' : ''}`), check = node('input'); check.type = 'checkbox'; check.checked = state.checked.has(p.id); check.setAttribute('aria-label', `勾选第 ${i + 1} 格`);
        check.onchange = () => { if (check.checked) state.checked.add(p.id); else state.checked.delete(p.id); };
        const button = node('button', `${i + 1}  ${p.description || '未填写剧情'}`); button.onclick = () => navigate(() => { state.panelId = p.id; state.balloonId = p.balloons?.[0]?.id; renderPanelList(); renderPanel(); renderOverlays(); });
        row.append(check, button); $('panelList').append(row);
      }
    }
    function renderPanel() {
      const p = panel(); $('panelProperties').hidden = !p; $('balloonSection').hidden = !p;
      if (!p) return;
      const fields = $('panelFields'); fields.replaceChildren();
      for (const [key, label, type] of [['description', '剧情', 'textarea'], ['source_ref', '原文定位（文本或 JSON）', 'textarea'], ['actions', '动作'], ['expression', '表情'], ['camera', '镜头'], ['angle', '角度'], ['time', '时间'], ['positive_prompt', '正向提示词', 'textarea'], ['negative_prompt', '负向提示词', 'textarea']]) {
        field(fields, label, typeof p[key] === 'object' ? JSON.stringify(p[key]) : p[key], value => { if (key === 'source_ref' && /^[\[{]/.test(value.trim())) { try { p[key] = JSON.parse(value); } catch (_) { p[key] = value; } } else p[key] = value; }, type);
      }
      const chars = state.project.characters;
      setOptions($('panelCharacters'), chars.map(c => [c.id, c.name || c.id]));
      [...$('panelCharacters').options].forEach(o => { o.selected = (p.characters || []).includes(o.value); });
      setOptions($('scene'), [['', '无场景节点'], ...(state.project.scenes || []).map(s => [s.id, s.description || s.id])], p.scene_id);
      modeOptions('panelMode', p.lettering_mode || 'inherit');
      $('locks').replaceChildren();
      for (const [key, label] of [['script', '剧情'], ['state', '状态'], ['prompt', '提示词'], ['layout', '布局']]) field($('locks'), label, p.locks?.[key], value => { p.locks ||= {}; p.locks[key] = value; }, 'checkbox');
      $('bindings').replaceChildren();
      for (const c of chars.filter(c => (p.characters || []).includes(c.id))) {
        const wrapper = node('div', null, 'binding'); wrapper.append(node('strong', c.name || c.id)); $('bindings').append(wrapper);
        const binding = p.state_bindings?.[c.id] || {};
        const update = patch => { p.state_bindings ||= {}; p.state_bindings[c.id] = { state_id: '', scope: 'continue', confirmed: true, ...p.state_bindings[c.id], ...patch }; };
        selectField(wrapper, '状态节点', binding.state_id, [['', '未绑定'], ...(c.states || []).map(s => [s.id, s.label || s.id])], state_id => update({ state_id }));
        selectField(wrapper, '作用范围', binding.scope || 'continue', [['continue', '延续到后续画格'], ['panel', '仅本格']], scope => update({ scope }));
        field(wrapper, '已确认状态', binding.confirmed, confirmed => update({ confirmed }), 'checkbox');
        for (const [key, label] of [['outfit', '本格服装覆盖'], ['props', '本格道具覆盖'], ['injuries', '本格伤势覆盖']]) {
          field(wrapper, `${label}（留空继承节点）`, binding.overrides?.[key] || '', value => {
            const overrides = { ...p.state_bindings?.[c.id]?.overrides };
            if (value.trim()) overrides[key] = value; else delete overrides[key];
            update({ overrides });
          });
        }
      }
      $('effectiveStates').textContent = JSON.stringify(p.effective_states || {}, null, 2);
      $('review').replaceChildren(...(p.needs_review || []).map(v => node('li', typeof v === 'string' ? v : JSON.stringify(v))));
      rectFields($('rectFields'), p, '画格');
      $('cropFields').replaceChildren(); p.crop ||= { x: .5, y: .5, zoom: 1 };
      for (const [key, label, min, max] of [['x', '裁切中心 X', 0, 1], ['y', '裁切中心 Y', 0, 1], ['zoom', '图片缩放', 1, 20]]) field($('cropFields'), label, p.crop[key], value => { p.crop[key] = value; }, 'number', { min, max, step: .01 });
      setOptions($('imageVersion'), [['', '未选择图片'], ...(p.image_versions || []).map((v, i) => [v.id || v.path, `版本 ${i + 1} · ${v.id || v.path}`])], (p.image_versions || []).find(v => v.path === p.current_image)?.id || p.current_image);
      $('versionSnapshot').textContent = JSON.stringify((p.image_versions || []).find(v => v.path === p.current_image)?.snapshot || {}, null, 2);
      setOptions($('candidateImage'), [['', '选择候选素材'], ...(state.project.candidate_images || []).map(v => [v.path, v.title || v.path])]);
      renderBalloons();
    }
    function rectFields(container, target, label) {
      container.replaceChildren(); const r = normalizeRect(target.rect);
      for (const [key, text] of [['x', 'X'], ['y', 'Y'], ['w', '宽'], ['h', '高']]) field(container, `${label}${text}（0–1）`, r[key], value => { target.rect = normalizeRect({ ...target.rect, [key]: value }); renderOverlays(); }, 'number', { min: key === 'w' || key === 'h' ? .01 : 0, max: 1, step: .01 });
    }
    function renderBalloons() {
      const p = panel(); if (!p) return; p.balloons ||= [];
      if (!p.balloons.some(b => b.id === state.balloonId)) state.balloonId = p.balloons[0]?.id;
      setOptions($('balloons'), p.balloons.map((b, i) => [b.id, `${i + 1} · ${b.text || '空文字'}`]), state.balloonId);
      const container = $('balloonFields'); container.replaceChildren(); const b = balloon(); if (!b) return;
      selectField(container, '文字种类', b.kind || 'dialogue', [['dialogue', '对白'], ['narration', '旁白'], ['sfx', '音效']], value => { b.kind = value; renderOverlays(); });
      field(container, '说话角色', b.speaker, value => { b.speaker = value; });
      field(container, '文字内容', b.text, value => { b.text = value; }, 'textarea', { rows: 3 });
      field(container, '显示此文字', b.show !== false, value => { b.show = value; renderOverlays(); }, 'checkbox');
      selectField(container, '字体', b.font || 'noto', [['noto', 'Noto Sans SC 常规'], ['noto-bold', 'Noto Sans SC 粗体']], value => { b.font = value; });
      selectField(container, '文字方向', b.writing_mode || 'horizontal', [['horizontal', '横排'], ['vertical', '竖排']], value => { b.writing_mode = value; });
      field(container, '字号（像素）', b.font_size || 28, value => { b.font_size = value; }, 'number', { min: 8, max: 300 });
      field(container, '行距', b.line_spacing || 1.3, value => { b.line_spacing = value; }, 'number', { min: .5, max: 5, step: .1 });
      const rect = node('div', null, 'grid2'); container.append(rect); rectFields(rect, b, '气泡');
      const tail = node('div', null, 'grid2'); container.append(tail);
      for (const key of ['x', 'y']) field(tail, `尾部 ${key.toUpperCase()}（格内比例）`, b.tail?.[key] ?? .5, value => { b.tail ||= { x: .5, y: .5 }; b.tail[key] = value; }, 'number', { min: 0, max: 1, step: .01 });
    }
    function renderCharacterForms() {
      $('characterForms').replaceChildren();
      for (const c of state.project?.characters || []) {
        const wrapper = node('details'); wrapper.append(node('summary', c.name || c.id)); $('characterForms').append(wrapper);
        const sync = () => { if (!state.charactersDirty) $('characters').value = JSON.stringify(state.project.characters, null, 2); };
        field(wrapper, '身份核心（仅固定身份，不含服装道具）', c.identity_core, value => { c.identity_core = value; sync(); }, 'textarea');
        for (const s of c.states || []) {
          const group = node('fieldset'); group.append(node('legend', s.label || s.id)); wrapper.append(group);
          for (const [key, label] of [['label', '节点名称'], ['outfit', '服装'], ['props', '道具'], ['injuries', '伤势']]) field(group, label, s[key], value => { s[key] = value; sync(); });
          field(group, '节点已确认', s.confirmed, value => { s.confirmed = value; sync(); }, 'checkbox');
        }
        const add = node('button', '新增状态节点'); add.onclick = () => {
          if (state.charactersDirty) { message('请先应用角色 JSON，再编辑身份与状态', true); return; }
          c.states ||= []; c.states.push({ id: uid('state'), label: '新状态', outfit: '', props: '', injuries: '', confirmed: false }); dirty(); sync(); renderCharacterForms(); renderPanel();
        }; wrapper.append(add);
      }
    }
    function renderSceneForms() {
      $('sceneForms').replaceChildren();
      for (const scene of state.project?.scenes || []) {
        const wrapper = node('details'); wrapper.append(node('summary', scene.description || scene.id)); $('sceneForms').append(wrapper);
        field(wrapper, '场景描述', scene.description, value => {
          scene.description = value;
          setOptions($('scene'), [['', '无场景节点'], ...(state.project.scenes || []).map(s => [s.id, s.description || s.id])], panel()?.scene_id);
        }, 'textarea');
        field(wrapper, '场景参考图片路径（每行一条）', (scene.reference_images || []).join('\n'), value => { scene.reference_images = value.split(/\r?\n/).map(v => v.trim()).filter(Boolean); }, 'textarea');
      }
    }
    function renderAll() {
      renderCharacterForms(); renderSceneForms();
      setOptions($('history'), (state.project.history || []).map((entry, i) => [String(i), entry.label || entry.title || `${i + 1} · ${entry.action || '历史快照'} ${entry.created_at || entry.at || ''}`]));
      $('title').value = state.project.title; $('source').value = state.project.source_text || ''; $('characters').value = JSON.stringify(state.project.characters, null, 2);
      $('style').value = state.project.style?.id || ''; $('advanced').value = ''; renderPageSettings(); renderPages(); renderPanelList(); renderPanel(); renderPreview();
    }
    async function submitTask(kind, body) {
      await exclusive(async () => { await flush(); await request(`${base()}/${kind}-task`, { method: 'POST', body: JSON.stringify(body) }); });
      message('任务已提交，可继续查看任务进度。'); await pollTasks();
    }
    async function pollTasks() {
      clearTimeout(state.poll); if (!state.project) return;
      const id = state.project.id, epoch = state.epoch;
      try {
        const data = await request(`${base()}/tasks`); if (state.project?.id !== id || epoch !== state.epoch) return;
        const tasks = data.tasks || []; $('tasks').replaceChildren();
        for (const task of tasks) {
          const box = node('div', null, 'task'); box.append(node('strong', ({ queued: '排队中', running: '执行中', succeeded: '已完成', completed: '已完成', failed: '失败', cancelled: '已取消' })[task.status] || task.status));
          box.append(node('p', `${task.stage || task.kind || ''} ${task.message || ''}`));
          const progress = node('progress'); progress.max = 100; progress.value = clamp(Number(task.progress) || 0, 0, 100); progress.setAttribute('aria-label', '任务进度'); box.append(progress);
          if (task.error) box.append(node('p', typeof task.error === 'string' ? task.error : JSON.stringify(task.error), 'error'));
          $('tasks').append(box);
        }
        if (!tasks.length) $('tasks').append(node('p', '暂无任务', 'hint'));
        const signature = JSON.stringify(tasks.filter(t => terminal(t.status)).map(t => [t.task_id || t.id, t.status, t.updated_at]));
        if (signature !== state.taskSignature && signature !== '[]') state.refreshPending = true;
        state.taskSignature = signature;
        if (state.refreshPending && !tasks.some(t => !terminal(t.status))) {
          if (state.version !== saver.savedVersion || state.charactersDirty || state.advancedDirty || state.busy || document.activeElement?.matches('input,textarea,select') || $('overlays').querySelector(':active')) {
            message('任务已结束。当前输入已保留；保存后点击“重新读取工程”查看任务结果。');
          } else {
            const version = state.version, fresh = await request(`${base()}`);
            if (state.project?.id === id && state.epoch === epoch && state.version === version && !state.charactersDirty && !state.advancedDirty && !state.busy && !document.activeElement?.matches('input,textarea,select')) hydrate(fresh.project || fresh);
          }
        }
      } catch (error) { if (state.project?.id === id) message(`任务状态读取失败，将自动重试：${error.message}`, true); }
      finally { if (state.project?.id === id) state.poll = setTimeout(pollTasks, 1800); }
    }
    bind('save', async () => { await flush(); message('工程已保存。'); });
    bind('refreshProjects', listProjects);
    bind('projects', () => exclusive(() => $('projects').value && load($('projects').value)), 'change');
    bind('newProject', () => exclusive(async () => {
      if (state.project) await flush();
      const title = state.project ? '未命名漫画' : $('title').value || '未命名漫画';
      const result = await request('/api/comics', { method: 'POST', body: JSON.stringify({ title: title || '未命名漫画', source_text: '', characters: [] }) });
      const p = result.project || result; if (p.pages) hydrate(p); else await load(p.id || p.project_id, false); await listProjects(); await pollTasks();
    }));
    bind('importRun', () => exclusive(async () => { if (!$('runs').value) throw new Error('请选择小说工程'); await createProject($('runs').value); }));
    bind('importProject', e => exclusive(async () => {
      const file = e.target.files[0]; if (!file) return; if (state.project) await flush();
      const form = new FormData(); form.append('file', file);
      const data = await request('/api/comics/import', { method: 'POST', body: form }), p = data.project || data;
      if (p.pages) hydrate(p); else await load(p.id || p.project_id, false); await listProjects(); await pollTasks(); e.target.value = '';
    }), 'change');
    bind('sourceFile', async e => {
      const file = e.target.files[0]; if (!file) return; const id = state.project?.id, version = state.version; const text = await file.text();
      if (state.project?.id !== id || state.version !== version) throw new Error('读取期间输入已变更，请重新导入文本');
      $('source').value = text; if (state.project) { state.project.source_text = text; dirty(); } e.target.value = '';
    }, 'change');
    for (const [id, key] of [['title', 'title'], ['source', 'source_text']]) bind(id, () => { if (state.project) { state.project[key] = $(id).value; dirty(); } }, 'input');
    bind('characters', () => { state.charactersDirty = true; $('saveStatus').textContent = '角色 JSON 待应用'; }, 'input');
    bind('applyCharacters', () => { applyCharacters(); renderCharacterForms(); renderPanel(); message('角色已应用，保存后生效。'); });
    bind('style', () => exclusive(async () => { needProject(); const id = $('style').value; await flush(); const preset = state.presets.find(p => p.id === id); const result = await request(`${base()}/style`, { method: 'POST', body: JSON.stringify({ id, reference_mode: preset?.reference_mode || 'text' }) }); hydrate(result.project || result); }), 'change');
    bind('assetFile', e => exclusive(async () => {
      const file = e.target.files[0]; if (!file) return; await flush(); const form = new FormData(); form.append('file', file); form.append('role', $('assetRole').value);
      const data = await request(`${base()}/assets`, { method: 'POST', body: form });
      const link = node('a', data.path); link.href = `${base()}/assets/${String(data.path).split('/').map(encoded).join('/')}`; link.target = '_blank'; link.rel = 'noopener'; $('assetPath').replaceChildren(link); e.target.value = '';
    }), 'change');
    bind('addScene', () => {
      needProject(); state.project.scenes ||= []; const scene = { id: uid('scene'), description: '新场景', reference_images: [] };
      state.project.scenes.push(scene); dirty(); renderSceneForms(); renderPanel(); $('sceneForms').lastElementChild.open = true;
    });
    function moveBalloon(delta) {
      const p = panel(), b = balloon(); if (!p || !b) return;
      const index = p.balloons.indexOf(b), destination = clamp(index + delta, 0, p.balloons.length - 1);
      if (destination === index) return; p.balloons.splice(index, 1); p.balloons.splice(destination, 0, b); dirty(); renderBalloons(); renderOverlays();
    }
    bind('balloonUp', () => moveBalloon(-1)); bind('balloonDown', () => moveBalloon(1));
    bind('addPage', () => operation('add_page'));
    bind('deletePage', async () => { if (!page()) throw new Error('请选择页面'); if (await confirmAction('删除当前页及其全部画格？')) await operation('delete_page'); });
    bind('addPanel', () => operation('add_panel'));
    bind('deletePanel', async () => { if (!panel()) throw new Error('请选择画格'); if (await confirmAction('删除当前画格？')) await operation('delete_panel'); });
    bind('splitPanel', () => { if (!panel()) throw new Error('请选择画格'); return operation('split_panel', { direction: 'vertical' }); });
    bind('mergePanels', async () => {
      if (state.checked.size !== 2) throw new Error('请勾选两个画格进行合并');
      const [first, second] = [...state.checked]; state.panelId = first;
      await operation('merge_panels', { other_panel_id: second });
    });
    bind('pageUp', () => { if (!page()) throw new Error('请选择页面'); return operation('move_page', { index: Math.max(0, state.project.pages.indexOf(page()) - 1) }); });
    bind('pageDown', () => { if (!page()) throw new Error('请选择页面'); return operation('move_page', { index: Math.min(state.project.pages.length - 1, state.project.pages.indexOf(page()) + 1) }); });
    async function movePanel(delta, targetPage) {
      if (!panel()) throw new Error('请选择画格'); const pg = page();
      const target = state.project.pages.find(p => p.id === targetPage) || pg;
      const index = delta == null ? target.panels.length : clamp(pg.panels.indexOf(panel()) + delta, 0, pg.panels.length - 1);
      await operation('move_panel', { target_page_id: target.id, index, target_index: index });
    }
    bind('panelUp', () => movePanel(-1)); bind('panelDown', () => movePanel(1)); bind('movePanel', () => movePanel(null, $('movePage').value));
    bind('applyTemplate', () => operation('template', { template: $('template').value }));
    for (const [id, key] of [['pageWidth', 'width'], ['pageHeight', 'height'], ['gutter', 'gutter']]) bind(id, () => { if (page() && $(id).checkValidity() && $(id).value !== '') { page()[key] = Number($(id).value); dirty(); $('paper').style.aspectRatio = `${page().width} / ${page().height}`; } }, 'input');
    for (const [id, object] of [['projectMode', () => state.project], ['pageMode', page], ['panelMode', panel]]) bind(id, () => { const target = object(); if (target) { target.lettering_mode = $(id).value; dirty(); renderOverlays(); } }, 'change');
    bind('panelCharacters', () => { if (!panel()) return; panel().characters = [...$('panelCharacters').selectedOptions].map(o => o.value); dirty(); renderPanel(); }, 'change');
    bind('scene', () => { if (panel()) { panel().scene_id = $('scene').value; dirty(); } }, 'change');
    bind('imageVersion', () => { const p = panel(), version = p?.image_versions?.find(v => (v.id || v.path) === $('imageVersion').value); if (p) { p.current_image = version?.path || ''; dirty(); $('versionSnapshot').textContent = JSON.stringify(version?.snapshot || {}, null, 2); } }, 'change');
    bind('useCandidate', () => {
      const path = $('candidateImage').value; if (!panel() || !path) throw new Error('请选择画格和候选素材');
      return operation('use_candidate', { path });
    });
    bind('balloons', () => { state.balloonId = $('balloons').value; renderBalloons(); renderOverlays(); }, 'change');
    bind('addBalloon', () => { const p = panel(); if (!p) throw new Error('请先选择画格'); p.balloons ||= []; const b = { id: uid('balloon'), kind: 'dialogue', speaker: '', text: '', rect: { x: .1, y: .1, w: .5, h: .25 }, font_size: 28, line_spacing: 1.3, writing_mode: 'horizontal', tail: { x: .5, y: .5 }, show: true }; p.balloons.push(b); state.balloonId = b.id; dirty(); renderBalloons(); renderOverlays(); });
    bind('deleteBalloon', () => { const p = panel(); if (!p || !balloon()) return; p.balloons = p.balloons.filter(b => b.id !== state.balloonId); dirty(); renderBalloons(); renderOverlays(); });
    bind('advanced', () => { state.advancedDirty = true; $('saveStatus').textContent = '高级 JSON 待应用'; }, 'input');
    bind('readAdvanced', async () => { if (state.advancedDirty && !await confirmAction('覆盖尚未应用的 JSON 输入？')) return; $('advanced').value = JSON.stringify(advancedObject() || {}, null, 2); state.advancedDirty = false; });
    let advancedTarget = $('advancedTarget').value;
    bind('advancedTarget', () => {
      if (state.advancedDirty) { $('advancedTarget').value = advancedTarget; throw new Error('请先应用 JSON，再切换对象'); }
      advancedTarget = $('advancedTarget').value; $('advanced').value = JSON.stringify(advancedObject() || {}, null, 2);
    }, 'change');
    bind('applyAdvanced', () => { applyAdvanced(); renderAll(); message('JSON 已应用，请保存工程。'); });
    bind('plan', async () => { needProject(); if (!await confirmAction('自动规划将替换当前分页与未锁定内容。已锁定的剧情 / 状态 / 提示词 / 布局由服务端保护。是否继续？')) return; await submitTask('plan', { pages: Number($('planPages').value), panels_per_page: Number($('planPanels').value), instructions: $('instructions').value, use_llm: $('useLlm').checked }); });
    const selectedIds = () => state.checked.size ? [...state.checked] : panel() ? [panel().id] : [];
    bind('prompts', () => { if (!selectedIds().length) throw new Error('请先选择画格'); return submitTask('prompt', { panel_ids: selectedIds(), use_llm: $('useLlm').checked }); });
    bind('generate', () => { const mode = $('generateMode').value; if (mode === 'selected' && !selectedIds().length) throw new Error('请先选择画格'); return submitTask('generate', { panel_ids: mode === 'selected' ? selectedIds() : [], mode, size: $('size').value, retries: Number($('retries').value) }); });
    bind('restoreHistory', () => exclusive(async () => {
      needProject(); const index = Number($('history').value);
      if (!state.project.history?.[index]) throw new Error('请选择历史版本');
      if (!await confirmAction('恢复所选脚本与布局？当前图片版本将保留。')) return;
      await flush(); const result = await request(`${base()}/restore`, { method: 'POST', body: JSON.stringify({ index }) }); hydrate(result.project || result); message('脚本与布局已恢复。');
    }));
    bind('refreshTasks', pollTasks);
    bind('reload', () => exclusive(async () => { needProject(); await load(state.project.id); message('工程与任务结果已读取。'); }));
    bind('check', async () => { await flush(); const data = await request(`${base()}/check`); $('issues').replaceChildren(...(data.issues || []).map(i => node('li', typeof i === 'string' ? i : i.message || JSON.stringify(i)))); if (!data.issues?.length) $('issues').append(node('li', '未发现问题')); });
    bind('export', async () => { await flush(); const url = exportUrl(state.project, $('exportFormat').value, $('exportMode').value, $('exportCurrent').checked && page() ? [page().id] : []); const link = node('a'); link.href = url; link.download = ''; document.body.append(link); link.click(); link.remove(); });
    $('preview').onerror = () => { $('previewError').hidden = false; }; $('preview').onload = () => { $('previewError').hidden = true; };
    document.addEventListener('keydown', e => { if ((e.ctrlKey || e.metaKey) && e.key === 's') { e.preventDefault(); $('save').click(); } });
    global.addEventListener('beforeunload', e => { if (state.version !== saver.savedVersion || state.charactersDirty || state.advancedDirty) { e.preventDefault(); e.returnValue = ''; } });
    // Keep existing controls and handlers, but show one focused workspace at a time.
    const materials = $('materials'), sections = [...materials.children];
    const tabs = node('div', null, 'workspace-tabs'); tabs.setAttribute('role', 'tablist'); tabs.setAttribute('aria-label', '工作面板');
    const groups = [['工程', [0, 5, 6]], ['素材', [1, 2]], ['生成', [3, 4]]];
    groups.forEach(([label, indices], index) => {
      const tab = node('button', label); tab.setAttribute('role', 'tab'); tab.setAttribute('aria-selected', String(index === 0));
      tab.onclick = () => { sections.forEach((section, i) => { section.hidden = !indices.includes(i); }); [...tabs.children].forEach(button => button.setAttribute('aria-selected', String(button === tab))); };
      tabs.append(tab);
    });
    materials.prepend(tabs);
    for (const index of [4, 5, 6, 7]) {
      const section = sections[index]; if (!section) continue;
      const heading = section.querySelector('h2'), details = node('details'), summary = node('summary', heading?.textContent || '更多操作');
      if (heading) heading.remove(); details.append(summary); while (section.firstChild) details.append(section.firstChild); section.append(details);
    }
    tabs.children[0].click();
    $('characters').value = '[]'; renderPageSettings();
    Promise.allSettled([
      listProjects(),
      request('/api/runs').then(data => setOptions($('runs'), [['', '选择小说工程'], ...(data.runs || []).map(r => [r.run_id, `${r.run_id}（${r.shot_count || 0} 个分镜）`])])),
      request('/api/visual-presets').then(data => { state.presets = (data.presets || []).filter(p => p.type === 'style'); setOptions($('style'), [['', '不使用画风'], ...state.presets.map(p => [p.id, `${p.name || p.id} · v${p.version || 1}`])], state.project?.style?.id); })
    ]).then(async results => {
      const failed = results.filter(r => r.status === 'rejected'); if (failed.length) message(failed.map(r => r.reason.message).join('；'), true);
      let id; try { id = new URLSearchParams(global.location.search).get('id') || localStorage.getItem('ficframe.comic.id'); } catch (_) { /* No persisted selection. */ }
      if (id && !state.project) { try { await exclusive(() => load(id, false)); } catch (error) { message(error.message, true); } }
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
})(typeof window !== 'undefined' ? window : globalThis);
