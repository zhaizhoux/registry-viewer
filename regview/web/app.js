/* regview 前端：原生 JS，无框架、无外部资源。
   所有注册表文本都通过 textContent 写入，避免键名/值数据里的 HTML 被解析。 */
(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const params = new URLSearchParams(location.search);
  const TOKEN = params.get('token') || '';

  if (!TOKEN) {
    $('no-token').hidden = false;
    return;
  }

  const NS = 'http://www.w3.org/2000/svg';
  const FOLDER_PATH = 'M3 6.5h6l2 2h10v9.5a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-10a1 1 0 0 1 1-1z';
  const ROOT_PATH = 'M12 3l8 4.5v9L12 21l-8-4.5v-9L12 3zM4 7.5l8 4.5 8-4.5M12 12v9';

  const state = {
    path: 'HKEY_CURRENT_USER',
    view: 'default',
    roots: [],
    node: null,
    nodes: new Map(),
    bookmarks: [],
    searchAbort: null,
    seq: 0,
    selectedValue: null,
  };

  // ---------- 工具 ----------

  function toast(message, isError) {
    const el = $('toast');
    el.textContent = message;
    el.className = 'toast' + (isError ? ' error' : '');
    el.hidden = false;
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => { el.hidden = true; }, 2600);
  }

  function setStatus(text, isError) {
    $('status-text').textContent = text;
    $('status-dot').className = 'status-dot' + (isError ? ' error' : '');
  }

  function icon(pathData, className) {
    const svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('class', className);
    svg.setAttribute('aria-hidden', 'true');
    const path = document.createElementNS(NS, 'path');
    path.setAttribute('d', pathData);
    svg.appendChild(path);
    return svg;
  }

  function shortPath(path) {
    const root = path.split('\\')[0];
    const found = state.roots.find((item) => item.name === root);
    const alias = found ? found.alias : root;
    const rest = path.slice(root.length);
    return alias + rest;
  }

  function kindOf(type) {
    if (type === 'REG_SZ') return 'sz';
    if (type === 'REG_EXPAND_SZ') return 'expand';
    if (type === 'REG_MULTI_SZ') return 'multi';
    if (type === 'REG_DWORD' || type === 'REG_DWORD_BIG_ENDIAN') return 'dword';
    if (type === 'REG_QWORD') return 'qword';
    if (type === 'REG_BINARY' || type === 'REG_NONE') return 'binary';
    return 'other';
  }

  function badge(type) {
    const span = document.createElement('span');
    span.className = 'type-badge';
    span.dataset.kind = kindOf(type);
    span.textContent = type;
    return span;
  }

  function cell(text, className) {
    const td = document.createElement('td');
    td.textContent = text;
    if (className) td.className = className;
    return td;
  }

  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
      toast('已复制到剪贴板');
    } catch (_) {
      const area = document.createElement('textarea');
      area.value = text;
      area.style.position = 'fixed';
      area.style.opacity = '0';
      document.body.appendChild(area);
      area.select();
      try { document.execCommand('copy'); toast('已复制到剪贴板'); }
      catch (e) { toast('复制失败，请手动选中', true); }
      area.remove();
    }
  }

  // ---------- API ----------

  function query(extra) {
    const search = new URLSearchParams(extra || {});
    if (state.view !== 'default') search.set('view', state.view);
    return search.toString();
  }

  async function api(name, extra, options) {
    const opts = options || {};
    const response = await fetch('/api/' + name + '?' + query(extra), {
      headers: { 'X-Regview-Token': TOKEN },
      signal: opts.signal,
    });
    if (!response.ok) {
      let message = 'HTTP ' + response.status;
      try {
        const body = await response.json();
        if (body && body.error && body.error.message) message = body.error.message;
      } catch (_) { /* 保持默认信息 */ }
      throw new Error(message);
    }
    return response.json();
  }

  async function apiSend(name, method, payload) {
    const response = await fetch('/api/' + name + '?' + query({}), {
      method: method,
      headers: { 'X-Regview-Token': TOKEN, 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      let message = 'HTTP ' + response.status;
      try { const body = await response.json(); message = body.error.message || message; }
      catch (_) { /* 保持默认信息 */ }
      throw new Error(message);
    }
    return response.json();
  }

  // ---------- 树 ----------

  function makeNode(path, label, isRoot) {
    const wrapper = document.createElement('div');
    wrapper.className = 'tree-node';

    const row = document.createElement('div');
    row.className = 'tree-row';
    row.setAttribute('role', 'treeitem');

    const arrow = document.createElement('span');
    arrow.className = 'tree-arrow';
    arrow.title = '展开 / 折叠';

    const glyph = icon(isRoot ? ROOT_PATH : FOLDER_PATH, 'tree-icon' + (isRoot ? ' root' : ''));
    const text = document.createElement('span');
    text.className = 'tree-label';
    text.textContent = label;

    row.append(arrow, glyph, text);
    const childrenEl = document.createElement('div');
    childrenEl.className = 'tree-children';
    childrenEl.hidden = true;
    wrapper.append(row, childrenEl);

    const entry = { path, row, arrow, childrenEl, expanded: false, loaded: false, names: [] };
    state.nodes.set(path, entry);

    arrow.addEventListener('click', (event) => {
      event.stopPropagation();
      toggleNode(entry);
    });
    row.addEventListener('click', () => loadPath(path));
    row.addEventListener('dblclick', () => toggleNode(entry));
    return wrapper;
  }

  async function loadChildren(entry) {
    if (entry.loaded || entry.busy) return;
    entry.busy = true;
    entry.arrow.classList.add('busy');
    try {
      const data = await api('children', { path: entry.path });
      entry.loaded = true;
      if (data.error) {
        const note = document.createElement('div');
        note.className = 'tree-error';
        note.textContent = data.error.message;
        entry.childrenEl.appendChild(note);
      } else {
        entry.names = data.children;
        for (const name of data.children) {
          const childPath = entry.path + '\\' + name;
          if (!state.nodes.has(childPath)) {
            entry.childrenEl.appendChild(makeNode(childPath, name, false));
          }
        }
        if (!data.children.length) {
          entry.arrow.classList.add('leaf');
          const note = document.createElement('div');
          note.className = 'tree-empty';
          note.textContent = '（无子键）';
          entry.childrenEl.appendChild(note);
        }
      }
    } catch (error) {
      const note = document.createElement('div');
      note.className = 'tree-error';
      note.textContent = error.message;
      entry.childrenEl.appendChild(note);
    } finally {
      entry.busy = false;
      entry.arrow.classList.remove('busy');
    }
  }

  async function expandNode(entry) {
    if (!entry.loaded) await loadChildren(entry);
    entry.expanded = true;
    entry.childrenEl.hidden = false;
    entry.arrow.classList.add('open');
  }

  function collapseNode(entry) {
    entry.expanded = false;
    entry.childrenEl.hidden = true;
    entry.arrow.classList.remove('open');
  }

  function toggleNode(entry) {
    if (entry.expanded) collapseNode(entry);
    else expandNode(entry).catch((error) => toast(error.message, true));
  }

  async function expandAncestors(path) {
    const parts = path.split('\\');
    let current = parts[0];
    let entry = state.nodes.get(current);
    for (let index = 1; index < parts.length && entry; index += 1) {
      await expandNode(entry);
      current += '\\' + parts[index];
      entry = state.nodes.get(current);
    }
  }

  function highlight(path) {
    state.nodes.forEach((entry, key) => {
      entry.row.classList.toggle('active', key === path);
    });
    const entry = state.nodes.get(path);
    if (entry) entry.row.scrollIntoView({ block: 'nearest' });
  }

  function buildRoots() {
    const tree = $('tree');
    tree.replaceChildren();
    state.nodes.clear();
    for (const root of state.roots) {
      const node = makeNode(root.name, root.alias, true);
      const entry = state.nodes.get(root.name);
      entry.row.title = root.name + ' · ' + root.description;
      tree.appendChild(node);
    }
    $('tree-count').textContent = state.roots.length + ' 个根键';
  }

  // ---------- 主视图 ----------

  async function loadPath(rawPath, options) {
    const target = (rawPath || '').trim();
    if (!target) return;
    const opts = options || {};
    const seq = ++state.seq;
    setStatus('正在读取 ' + target + ' …');
    try {
      const data = await api('node', { path: target });
      if (seq !== state.seq) return;
      state.node = data;
      state.path = data.path;
      $('path-input').value = data.path;
      await expandAncestors(data.path);
      if (seq !== state.seq) return;
      highlight(data.path);
      renderValues(data);
      updateSearchRoots();
      if (opts.valueName) selectValueByName(opts.valueName);
      const info = data.error
        ? data.error.message
        : shortPath(data.path) + ' · ' + data.subkeys.length + ' 子键 · ' + data.values.length + ' 值';
      setStatus(info, Boolean(data.error));
    } catch (error) {
      if (seq === state.seq) {
        setStatus('读取失败：' + error.message, true);
        toast(error.message, true);
      }
    }
  }

  function renderValues(data) {
    const errorBar = $('node-error');
    errorBar.hidden = !data.error;
    if (data.error) errorBar.textContent = data.error.message;

    $('values-title').textContent = shortPath(data.path);
    $('values-meta').textContent = data.subkeys.length + ' 子键 / ' + data.values.length + ' 值';
    state.selectedValue = null;
    $('detail').hidden = true;

    const body = $('values-body');
    body.replaceChildren();
    $('values-empty').hidden = data.values.length > 0;
    if (!data.values.length) {
      $('values-empty').textContent = data.error ? '无法读取该键' : '该键下没有值，左侧可展开子键';
    }

    for (const value of data.values) {
      const row = document.createElement('tr');
      row.dataset.name = value.name;
      const nameCell = cell(value.name || '(默认)', value.name ? '' : 'muted');
      const typeCell = document.createElement('td');
      typeCell.appendChild(badge(value.type));
      const dataCell = cell(value.display, 'mono');
      dataCell.title = value.full;
      row.append(nameCell, typeCell, dataCell, cell(String(value.size), 'muted'));
      row.addEventListener('click', () => showDetail(value, row));
      body.appendChild(row);
    }
  }

  function selectValueByName(name) {
    const label = name === '(默认)' ? '' : name;
    const rows = $('values-body').querySelectorAll('tr');
    for (const row of rows) {
      if (row.dataset.name === label) { row.click(); return; }
    }
  }

  function showDetail(value, row) {
    state.selectedValue = value;
    for (const item of $('values-body').querySelectorAll('tr')) {
      item.classList.toggle('selected', item === row);
    }
    $('detail').hidden = false;
    $('detail-name').textContent = value.name || '(默认)';
    const holder = $('detail-type');
    holder.replaceChildren(badge(value.type));
    $('detail-size').textContent = value.size + ' 字节';
    $('detail-data').textContent = value.full || '（空）';

    const expanded = $('detail-expanded');
    if (value.expanded && value.expanded !== value.full) {
      expanded.hidden = false;
      expanded.textContent = '环境变量展开后：' + value.expanded;
    } else {
      expanded.hidden = true;
    }
    const hexWrap = $('detail-hex-wrap');
    hexWrap.hidden = !value.hex;
    if (value.hex) $('detail-hex').textContent = value.hex;
  }

  function goUp() {
    if (state.node && state.node.parent) loadPath(state.node.parent);
    else toast('已经是根键', true);
  }

  function updateSearchRoots() {
    const select = $('search-root');
    const previous = select.value;
    const options = [];
    const current = document.createElement('option');
    current.value = state.path;
    current.textContent = '当前键 · ' + shortPath(state.path);
    options.push(current);
    for (const root of state.roots) {
      const option = document.createElement('option');
      option.value = root.name;
      option.textContent = root.alias + ' · ' + root.description;
      options.push(option);
    }
    select.replaceChildren(...options);
    if (previous && Array.from(select.options).some((item) => item.value === previous)) {
      select.value = previous;
    }
  }

  // ---------- 搜索 ----------

  async function runSearch() {
    const keyword = $('search-input').value.trim();
    if (!keyword) { toast('请输入搜索关键字', true); $('search-input').focus(); return; }
    if (state.searchAbort) state.searchAbort.abort();
    const controller = new AbortController();
    state.searchAbort = controller;
    $('search-panel').hidden = false;
    $('bookmark-panel').hidden = true;
    $('btn-search-stop').hidden = false;
    $('btn-search').disabled = true;
    $('search-summary').textContent = '正在扫描…';
    $('search-results').replaceChildren();

    try {
      const result = await api('search', {
        q: keyword,
        root: $('search-root').value || state.path,
        scope: $('search-scope').value,
        limit: 300,
        max_keys: 8000,
        seconds: 8,
      }, { signal: controller.signal });

      const limits = {
        results: '（命中数已达上限）', keys: '（扫描键数已达上限）',
        time: '（超出时间限制）', cancelled: '（已停止）',
      };
      $('search-summary').textContent =
        '扫描 ' + result.scanned + ' 个键 · 命中 ' + result.count + ' 条 · ' +
        result.elapsed + 's · 跳过 ' + result.errors + ' 个受限键' +
        (result.truncated ? ' ' + limits[result.truncated] : '');
      renderResults(result.results);
      setStatus('搜索完成：' + result.count + ' 条命中');
    } catch (error) {
      if (error.name === 'AbortError') {
        $('search-summary').textContent = '已停止搜索';
        setStatus('已停止搜索');
      } else {
        $('search-summary').textContent = '搜索失败：' + error.message;
        toast(error.message, true);
      }
    } finally {
      $('btn-search-stop').hidden = true;
      $('btn-search').disabled = false;
      state.searchAbort = null;
    }
  }

  function renderResults(results) {
    const list = $('search-results');
    list.replaceChildren();
    if (!results.length) {
      const note = document.createElement('div');
      note.className = 'drawer-note';
      note.textContent = '没有匹配项，试试换个关键字或扩大搜索范围';
      list.appendChild(note);
      return;
    }
    for (const item of results) {
      const box = document.createElement('div');
      box.className = 'result-item';
      const title = document.createElement('div');
      title.className = 'result-title';
      const kind = document.createElement('span');
      kind.className = 'result-kind';
      kind.textContent = item.kind === 'key' ? '键' : '值';
      const name = document.createElement('span');
      name.textContent = item.name;
      title.append(kind, name);
      if (item.type) title.appendChild(badge(item.type));
      const path = document.createElement('div');
      path.className = 'result-path';
      path.textContent = shortPath(item.path);
      box.append(title, path);
      if (item.detail && item.detail !== '子键') {
        const detail = document.createElement('div');
        detail.className = 'result-detail';
        detail.textContent = item.detail;
        box.appendChild(detail);
      }
      box.addEventListener('click', () => {
        $('search-panel').hidden = true;
        loadPath(item.path, { valueName: item.kind === 'value' ? item.name : null });
      });
      list.appendChild(box);
    }
  }

  // ---------- 导出 / 收藏 ----------

  async function exportData(format) {
    setStatus('正在导出 ' + format + ' …');
    try {
      const response = await fetch('/api/export?' + query({ path: state.path, format }), {
        headers: { 'X-Regview-Token': TOKEN },
      });
      if (!response.ok) {
        let message = 'HTTP ' + response.status;
        try { const body = await response.json(); message = body.error.message || message; }
        catch (_) { /* 保持默认信息 */ }
        throw new Error(message);
      }
      const blob = await response.blob();
      const disposition = response.headers.get('Content-Disposition') || '';
      const match = /filename="([^"]+)"/.exec(disposition);
      const link = document.createElement('a');
      link.href = URL.createObjectURL(blob);
      link.download = match ? match[1] : 'regview.' + format;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(link.href), 2000);
      const stats = response.headers.get('X-Regview-Stats');
      setStatus('已导出 ' + link.download + (stats ? ' · ' + stats : ''));
      toast('导出完成：' + link.download);
    } catch (error) {
      setStatus('导出失败：' + error.message, true);
      toast(error.message, true);
    }
  }

  async function refreshBookmarks() {
    try {
      const result = await api('bookmarks');
      state.bookmarks = result.bookmarks;
      $('bookmark-count').textContent = String(state.bookmarks.length);
      renderBookmarks();
    } catch (error) {
      toast('读取收藏夹失败：' + error.message, true);
    }
  }

  function renderBookmarks() {
    const list = $('bookmark-list');
    list.replaceChildren();
    if (!state.bookmarks.length) {
      const note = document.createElement('div');
      note.className = 'drawer-note';
      note.textContent = '还没有收藏。点击工具栏「收藏」保存常用路径。';
      list.appendChild(note);
      return;
    }
    for (const item of state.bookmarks) {
      const row = document.createElement('div');
      row.className = 'bookmark-item';
      const main = document.createElement('div');
      main.className = 'bookmark-main';
      const name = document.createElement('div');
      name.className = 'bookmark-name';
      name.textContent = item.name || item.path;
      const path = document.createElement('div');
      path.className = 'bookmark-path';
      path.textContent = shortPath(item.path);
      main.append(name, path);
      main.addEventListener('click', () => {
        $('bookmark-panel').hidden = true;
        loadPath(item.path);
      });
      const remove = document.createElement('button');
      remove.className = 'btn small';
      remove.textContent = '移除';
      remove.addEventListener('click', async () => {
        try {
          const result = await apiSend('bookmarks', 'DELETE', { path: item.path });
          state.bookmarks = result.bookmarks;
          $('bookmark-count').textContent = String(result.bookmarks.length);
          renderBookmarks();
        } catch (error) { toast(error.message, true); }
      });
      row.append(main, remove);
      list.appendChild(row);
    }
  }

  async function toggleBookmark() {
    const exists = state.bookmarks.some((item) => item.path === state.path);
    try {
      const result = await apiSend('bookmarks', exists ? 'DELETE' : 'POST', { path: state.path });
      state.bookmarks = result.bookmarks;
      $('bookmark-count').textContent = String(result.bookmarks.length);
      renderBookmarks();
      toast(exists ? '已取消收藏' : '已加入收藏夹');
    } catch (error) {
      toast(error.message, true);
    }
  }

  // ---------- 主题 / 交互绑定 ----------

  function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem('regview-theme', theme);
  }

  function bindEvents() {
    $('btn-go').addEventListener('click', () => loadPath($('path-input').value));
    $('btn-up').addEventListener('click', goUp);
    $('btn-refresh').addEventListener('click', () => loadPath(state.path));
    $('path-input').addEventListener('keydown', (event) => {
      if (event.key === 'Enter') { event.preventDefault(); loadPath($('path-input').value); }
    });

    $('view-select').addEventListener('change', (event) => {
      state.view = event.target.value;
      $('status-view').textContent = event.target.selectedOptions[0].textContent;
      loadPath(state.path);
    });
    $('btn-theme').addEventListener('click', () => {
      const current = document.documentElement.dataset.theme;
      const dark = current === 'dark' || (current === 'auto' &&
        window.matchMedia('(prefers-color-scheme: dark)').matches);
      applyTheme(dark ? 'light' : 'dark');
      toast(dark ? '已切换为浅色主题' : '已切换为深色主题');
    });

    $('btn-search').addEventListener('click', runSearch);
    $('btn-search-stop').addEventListener('click', () => {
      if (state.searchAbort) state.searchAbort.abort();
    });
    $('search-input').addEventListener('keydown', (event) => {
      if (event.key === 'Enter') { event.preventDefault(); runSearch(); }
    });
    $('btn-close-search').addEventListener('click', () => { $('search-panel').hidden = true; });

    $('btn-bookmark').addEventListener('click', toggleBookmark);
    $('btn-bookmarks').addEventListener('click', () => {
      $('bookmark-panel').hidden = !$('bookmark-panel').hidden;
      $('search-panel').hidden = true;
    });
    $('btn-close-bookmarks').addEventListener('click', () => { $('bookmark-panel').hidden = true; });

    for (const id of ['btn-export-reg', 'btn-export-json', 'btn-export-csv']) {
      $(id).addEventListener('click', (event) => exportData(event.currentTarget.dataset.format));
    }
    $('btn-copy').addEventListener('click', () => copyText(state.path));
    $('btn-copy-value').addEventListener('click', () => {
      if (state.selectedValue) copyText(state.selectedValue.full || '');
    });
    $('btn-close-detail').addEventListener('click', () => {
      $('detail').hidden = true;
      state.selectedValue = null;
      for (const row of $('values-body').querySelectorAll('tr')) row.classList.remove('selected');
    });

    document.addEventListener('keydown', (event) => {
      const key = event.key.toLowerCase();
      if ((event.ctrlKey || event.metaKey) && key === 'f') {
        event.preventDefault(); $('search-input').focus(); $('search-input').select();
      } else if ((event.ctrlKey || event.metaKey) && key === 'l') {
        event.preventDefault(); $('path-input').focus(); $('path-input').select();
      } else if (event.key === 'F5') {
        event.preventDefault(); loadPath(state.path);
      } else if (event.altKey && event.key === 'ArrowUp') {
        event.preventDefault(); goUp();
      } else if (event.key === 'Escape') {
        $('search-panel').hidden = true;
        $('bookmark-panel').hidden = true;
        $('detail').hidden = true;
      }
    });

    // 可拖动的左右分栏
    const splitter = $('splitter');
    const workspace = $('workspace');
    let dragging = false;
    splitter.addEventListener('pointerdown', (event) => {
      dragging = true;
      splitter.classList.add('dragging');
      splitter.setPointerCapture(event.pointerId);
    });
    splitter.addEventListener('pointermove', (event) => {
      if (!dragging) return;
      const left = workspace.getBoundingClientRect().left;
      const width = Math.max(200, Math.min(620, event.clientX - left));
      workspace.style.setProperty('--tree-width', width + 'px');
    });
    splitter.addEventListener('pointerup', (event) => {
      dragging = false;
      splitter.classList.remove('dragging');
      splitter.releasePointerCapture(event.pointerId);
    });
  }

  async function init() {
    bindEvents();
    applyTheme(localStorage.getItem('regview-theme') || 'auto');
    $('status-view').textContent = '默认视图';
    try {
      const health = await api('health');
      if (!health.readonly) throw new Error('后端只读标志异常');
      const roots = await api('roots');
      state.roots = roots.roots;
      buildRoots();
      await refreshBookmarks();
      await loadPath('HKEY_CURRENT_USER');
    } catch (error) {
      setStatus('后端连接失败：' + error.message, true);
      toast('后端连接失败：' + error.message, true);
    }
  }

  init();
})();
