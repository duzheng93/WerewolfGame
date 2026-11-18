const app = document.querySelector('#app');
const GOD_ROLES = ['预言家', '女巫', '猎人', '白痴', '守卫', '丘比特'];
let hostRefreshTimer = null;

function clearHostRefresh() {
  if (hostRefreshTimer !== null) clearInterval(hostRefreshTimer);
  hostRefreshTimer = null;
}

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function hero(kicker, title, description) {
  const container = node('div', 'hero');
  container.append(node('p', 'eyebrow', kicker), node('h1', '', title), node('p', '', description));
  return container;
}

function showError(element, message) { element.textContent = message || ''; }

async function api(path, options = {}) {
  const response = await fetch(path, {
    cache: 'no-store',
    ...options,
    headers: {'Accept': 'application/json', ...(options.headers || {})},
  });
  let body;
  try { body = await response.json(); } catch { throw new Error('服务器响应异常，请稍后重试'); }
  if (!response.ok) throw new Error(body.error || '请求失败，请稍后重试');
  return body;
}

function post(path, data) {
  return api(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)});
}

function gamePath(id) { return `/api/games/${encodeURIComponent(id)}`; }
function tokenFromHash() { return new URLSearchParams(location.hash.slice(1)).get('token'); }
function gameUrl(id) { return `${location.origin}/game/${encodeURIComponent(id)}`; }
function hostUrl(id, token) { return `${location.origin}/host/${encodeURIComponent(id)}#token=${encodeURIComponent(token)}`; }
function storageGet(key) {
  try { return window.localStorage.getItem(key); } catch { return null; }
}
function storageSet(key, value) {
  try { window.localStorage.setItem(key, value); } catch { /* The URL fragment still carries the token. */ }
}

async function copy(text, button) {
  try {
    await navigator.clipboard.writeText(text);
    const previous = button.textContent;
    button.textContent = '已复制';
    setTimeout(() => { button.textContent = previous; }, 1800);
  } catch { window.prompt('请复制以下链接：', text); }
}

function summary(game) {
  const box = node('div', 'summary');
  [
    `${game.player_count} 位玩家`, `${game.wolf_count} 狼`,
    `${game.villager_count} 平民`, `${game.god_count} 神职`,
    game.white_wolf_king ? '含白狼王' : null,
  ].filter(Boolean).forEach(label => box.append(node('span', 'pill', label)));
  return box;
}

function renderCreate() {
  clearHostRefresh();
  app.replaceChildren();
  app.append(hero('THE NIGHT BEGINS', '创建一场月下对局', '设定身份牌，分享链接，让每位玩家亲自揭开自己的秘密。'));
  const layout = node('div', 'layout');
  const panel = node('section', 'panel');
  panel.innerHTML = `<h2>设定身份</h2>
    <form id="create-form">
      <div class="field-grid">
        <div class="field"><label for="player-count">玩家人数</label><input id="player-count" name="player_count" type="number" min="3" max="30" value="8" required></div>
        <div class="field"><label for="wolf-count">狼人数</label><input id="wolf-count" name="wolf_count" type="number" min="1" max="30" value="2" required></div>
        <div class="field"><label for="villager-count">平民人数</label><input id="villager-count" name="villager_count" type="number" min="0" max="30" value="3" required></div>
        <div class="field"><label for="god-count">神职人数</label><input id="god-count" name="god_count" type="number" min="0" max="6" value="3" required></div>
      </div>
      <div class="section-title"><h3>选择神职</h3><span>每种神职最多一位</span></div>
      <div class="role-options" id="god-options"></div>
      <label class="toggle"><input id="white-wolf" type="checkbox"> <span>加入白狼王 <span class="hint">· 占用一个狼人名额</span></span></label>
      <div class="actions"><button class="primary" type="submit">创建对局</button><span class="hint">身份在创建时随机洗牌</span></div>
      <p class="error" id="create-error" role="alert"></p>
    </form>`;
  const options = panel.querySelector('#god-options');
  GOD_ROLES.forEach((role, index) => {
    const label = node('label', 'role-choice');
    const input = node('input'); input.type = 'checkbox'; input.value = role; input.name = 'god_role';
    input.checked = index < 3;
    label.append(input, node('span', '', role)); options.append(label);
  });
  const rules = node('aside', 'panel rules');
  rules.innerHTML = `<h2>抽取流程</h2>
    <p><span class="rule-number">1</span>主持人设定人数与身份，创建对局。</p>
    <p><span class="rule-number">2</span>将玩家链接发给大家；每人填写昵称并抽取一张身份牌。</p>
    <p><span class="rule-number">3</span>主持人从专属页面查看昵称和身份。</p>
    <hr><p>神职每种最多一位。白狼王可选，选中时占用一个狼人名额。</p>
    <p>主持人链接含有查看全部身份的密钥，请妥善保管。</p>`;
  layout.append(panel, rules); app.append(layout);
  const form = panel.querySelector('#create-form');
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const error = panel.querySelector('#create-error'); showError(error, '');
    const button = form.querySelector('button[type="submit"]');
    const values = Object.fromEntries(new FormData(form));
    const god_roles = [...form.querySelectorAll('input[name="god_role"]:checked')].map(i => i.value);
    const data = {
      player_count: Number(values.player_count), wolf_count: Number(values.wolf_count),
      villager_count: Number(values.villager_count), god_count: Number(values.god_count),
      god_roles, white_wolf_king: panel.querySelector('#white-wolf').checked,
    };
    if (data.player_count !== data.wolf_count + data.villager_count + data.god_count) {
      showError(error, '狼人、平民和神职人数之和须等于玩家人数'); return;
    }
    if (god_roles.length !== data.god_count) {
      showError(error, '所选神职数量须与神职人数一致'); return;
    }
    button.disabled = true;
    try {
      const result = await post('/api/games', data);
      storageSet(`werewolf-host-${result.game_id}`, result.host_token);
      history.pushState({}, '', `/host/${encodeURIComponent(result.game_id)}#token=${encodeURIComponent(result.host_token)}`);
      await renderHost(result.game_id);
    } catch (e) { showError(error, e.message); button.disabled = false; }
  });
}

async function renderHost(id) {
  clearHostRefresh();
  const token = tokenFromHash() || storageGet(`werewolf-host-${id}`);
  app.replaceChildren(hero('HOST ROOM', '主持人控制台', '只有持有主持人链接的人可以查看全部身份。'));
  const outer = node('div', 'single stack'); app.append(outer);
  if (!token) {
    const panel = node('section', 'panel');
    panel.append(node('h2', '', '缺少主持人密钥'), node('p', 'privacy-note', '请打开创建对局时保存的主持人专属链接。'));
    outer.append(panel); return;
  }
  storageSet(`werewolf-host-${id}`, token);
  const info = node('section', 'panel');
  const list = node('section', 'panel');
  outer.append(info, list);
  async function refresh() {
    try {
      const data = await api(`${gamePath(id)}/host`, {headers: {'Authorization': `Bearer ${token}`}});
      drawHost(data);
    } catch (e) {
      info.replaceChildren(node('h2', '', '无法读取对局'), node('p', 'error', e.message));
      list.replaceChildren();
    }
  }
  function drawHost(data) {
    info.replaceChildren(node('div', 'status-line', `已加入 ${data.game.joined_count} / ${data.game.player_count} 位玩家`),
      node('h2', '', '对局已创建'), summary(data.game));
    const linkSection = node('div', 'stack');
    const playerGroup = node('div');
    playerGroup.append(node('span', 'small-label', '分享给玩家的链接'), node('div', 'link-box', gameUrl(id)));
    const playerCopy = node('button', 'secondary', '复制玩家链接');
    playerCopy.type = 'button'; playerCopy.addEventListener('click', () => copy(gameUrl(id), playerCopy));
    playerGroup.append(node('div', 'actions')); playerGroup.lastChild.append(playerCopy);
    const hostGroup = node('div');
    hostGroup.append(node('span', 'small-label', '主持人专属链接 · 请勿发给玩家'), node('div', 'link-box', hostUrl(id, token)));
    const hostCopy = node('button', 'secondary', '复制主持人链接');
    hostCopy.type = 'button'; hostCopy.addEventListener('click', () => copy(hostUrl(id, token), hostCopy));
    hostGroup.append(node('div', 'actions')); hostGroup.lastChild.append(hostCopy);
    linkSection.append(playerGroup, hostGroup); info.append(linkSection);

    list.replaceChildren(node('h2', '', '玩家与身份'));
    if (!data.players.length) {
      list.append(node('div', 'empty', '还没有玩家加入。分享链接，等待第一张身份牌被揭开。'));
      return;
    }
    const wrap = node('div', 'table-wrap'); const table = node('table', 'roster');
    const head = node('thead'); const headRow = node('tr');
    ['序号', '昵称', '身份'].forEach(t => headRow.append(node('th', '', t)));
    head.append(headRow); table.append(head);
    const body = node('tbody');
    data.players.forEach((player, index) => {
      const row = node('tr');
      row.append(node('td', '', String(index + 1)), node('td', '', player.nickname), node('td', '', player.role));
      body.append(row);
    });
    table.append(body); wrap.append(table); list.append(wrap);
  }
  await refresh();
  hostRefreshTimer = setInterval(() => { if (document.visibilityState === 'visible') refresh(); }, 5000);
}

async function renderPlayer(id) {
  clearHostRefresh();
  app.replaceChildren(hero('YOUR SECRET AWAITS', '揭开你的身份', '输入昵称，抽取属于你的那一张身份牌。'));
  const outer = node('div', 'single stack'); app.append(outer);
  let game;
  try { game = await api(gamePath(id)); }
  catch (e) { outer.append(node('section', 'panel', e.message)); return; }
  const info = node('section', 'panel');
  info.append(node('div', 'status-line', `已加入 ${game.joined_count} / ${game.player_count} 位玩家`),
    node('h2', '', '本局配置'), summary(game));
  outer.append(info);
  const token = tokenFromHash() || storageGet(`werewolf-player-${id}`);
  if (token) {
    try {
      const me = await api(`${gamePath(id)}/me`, {headers: {'Authorization': `Bearer ${token}`}});
      storageSet(`werewolf-player-${id}`, token);
      showRole(outer, id, token, me);
      return;
    } catch (e) {
      const warning = node('p', 'error', `保存的身份令牌无法使用：${e.message}`);
      info.append(warning);
    }
  }
  const panel = node('section', 'panel');
  panel.innerHTML = `<h2>领取身份</h2><form id="join-form">
    <div class="field"><label for="nickname">你的昵称</label><input id="nickname" name="nickname" maxlength="24" autocomplete="nickname" placeholder="输入游戏中使用的昵称" required></div>
    <div class="actions"><button class="primary" type="submit">抽取身份</button><span class="hint">每个昵称仅可领取一次</span></div>
    <p class="error" role="alert"></p></form>`;
  outer.append(panel);
  const form = panel.querySelector('form');
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const error = form.querySelector('.error'); showError(error, '');
    const button = form.querySelector('button'); button.disabled = true;
    try {
      const result = await post(`${gamePath(id)}/join`, {nickname: form.querySelector('#nickname').value});
      storageSet(`werewolf-player-${id}`, result.player_token);
      location.hash = `token=${encodeURIComponent(result.player_token)}`;
      panel.remove(); showRole(outer, id, result.player_token, result);
      const updated = await api(gamePath(id));
      info.firstChild.textContent = `已加入 ${updated.joined_count} / ${updated.player_count} 位玩家`;
    } catch (e) { showError(error, e.message); button.disabled = false; }
  });
}

function showRole(outer, id, token, me) {
  const panel = node('section', 'panel');
  panel.append(node('p', 'eyebrow', `${me.nickname} · 你的身份`));
  const card = node('div', 'role-card');
  card.append(node('div', 'moon', '☾'), node('p', 'your-role', 'YOUR ROLE'),
    node('h2', '', me.role), node('p', '', '请保管好你的身份，等待主持人开启游戏。'));
  panel.append(card);
  const privateUrl = `${gameUrl(id)}#token=${encodeURIComponent(token)}`;
  const actions = node('div', 'actions');
  const copyButton = node('button', 'secondary', '复制我的身份链接');
  copyButton.type = 'button'; copyButton.addEventListener('click', () => copy(privateUrl, copyButton));
  actions.append(copyButton); panel.append(actions);
  panel.append(node('p', 'privacy-note', '此链接可在其他设备上恢复你的身份，请勿分享给其他玩家。'));
  outer.append(panel);
}

function renderCurrentRoute() {
  const pathParts = location.pathname.split('/').filter(Boolean);
  if (pathParts.length === 2 && pathParts[0] === 'game') renderPlayer(pathParts[1]);
  else if (pathParts.length === 2 && pathParts[0] === 'host') renderHost(pathParts[1]);
  else renderCreate();
}

window.addEventListener('popstate', renderCurrentRoute);
renderCurrentRoute();
