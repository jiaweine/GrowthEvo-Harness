const runtimeStrictApi = !useDemo;
const RUNTIME_API_TIMEOUT_MS = 10000;
const RUNTIME_READY_TIMEOUT_MS = 5000;
let runtimeAvailability = useDemo ? 'demo' : 'checking';
let runtimeLastError = null;
let runtimeBackend = useDemo ? {mode:'demo',environment:'static'} : null;

async function runtimeFetch(url, options = {}, timeoutMs = RUNTIME_API_TIMEOUT_MS) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, {...options, signal: controller.signal});
  } catch (error) {
    if (error && error.name === 'AbortError') throw Error(`API request timed out after ${timeoutMs}ms`);
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

api = async function runtimeAwareApi(path, options = {}) {
  if (useDemo) return demoApi(path, options);
  const headers = {'Content-Type': 'application/json', ...(options.headers || {})};
  const response = await runtimeFetch(`${config.API_BASE || ''}${path}`, {
    ...options,
    headers,
    cache: 'no-store',
  });
  if (!response.ok) {
    const detail = await response.text();
    throw Error(`HTTP ${response.status}: ${detail.slice(0, 600)}`);
  }
  return await response.json();
};

function setRuntimeStatus(label, latency = null, freshness = null) {
  const status = document.querySelector('.status-right');
  if (!status) return;
  const parts = [label];
  if (latency !== null) parts.push(`Readiness ${latency} ms`);
  if (freshness) parts.push(freshness);
  while (status.firstChild) status.removeChild(status.firstChild);
  for (const text of parts) {
    const span = document.createElement('span');
    span.textContent = text;
    status.appendChild(span);
  }
}

function setAgentAvailability(online) {
  const text = document.querySelector('.online-text');
  if (text) text.textContent = online ? '在线' : 'API 不可用';
  const dot = document.querySelector('.online-dot');
  if (dot) dot.style.opacity = online ? '1' : '.35';
}

function runtimeWorkspaceLabel() {
  const meta = document.querySelector('.workspace-card .workspace-copy span');
  if (useDemo) {
    if (meta) meta.textContent = 'Demo Workspace · Synthetic Data';
    document.body.dataset.runtimeMode = 'demo';
    setRuntimeStatus('Demo · Synthetic Data', null, '非生产数据');
    setAgentAvailability(true);
    return;
  }
  if (meta) meta.textContent = 'API Workspace · Checking';
  document.body.dataset.runtimeMode = 'api';
  setRuntimeStatus('API 状态检查中');
}

async function probeRuntime() {
  if (useDemo) return;
  const started = performance.now();
  try {
    const response = await runtimeFetch(`${config.API_BASE || ''}/api/ready`, {cache: 'no-store'}, RUNTIME_READY_TIMEOUT_MS);
    const latency = Math.max(0, Math.round(performance.now() - started));
    let payload = null;
    try { payload = await response.json(); } catch (_) { payload = null; }
    if (!response.ok) {
      const mode = payload && payload.mode ? ` (${payload.mode})` : '';
      throw Error(`readiness returned HTTP ${response.status}${mode}`);
    }
    runtimeAvailability = 'ready';
    runtimeLastError = null;
    runtimeBackend = payload || {};
    const mode = payload && payload.mode ? payload.mode : 'api';
    const env = payload && payload.environment ? ` · ${payload.environment}` : '';
    const meta = document.querySelector('.workspace-card .workspace-copy span');
    if (meta) meta.textContent = mode === 'production' ? 'Production Workspace · Live API' : 'API Workspace · Reference API';
    document.body.dataset.runtimeMode = mode;
    setRuntimeStatus(`API Ready · ${mode}${env}`, latency, 'Live API');
    setAgentAvailability(true);
  } catch (error) {
    runtimeAvailability = 'unavailable';
    runtimeLastError = error;
    setRuntimeStatus('API 不可用');
    setAgentAvailability(false);
    renderApiUnavailable(error);
  }
}

function renderApiUnavailable(error) {
  runtimeAvailability = useDemo ? 'demo' : 'unavailable';
  runtimeLastError = error || runtimeLastError;
  const view = document.querySelector('#view');
  if (!view) return;
  const base = esc(config.API_BASE || 'same-origin API');
  const reason = esc(error && error.message ? error.message : 'Connection failed');
  view.innerHTML = `
    <div class="runtime-error card">
      <div class="runtime-error-icon">!</div>
      <div>
        <h1>生产 API 暂不可用</h1>
        <p>当前处于严格 API 模式，GrowthEvo 不会把 synthetic demo 数据伪装成真实生产数据。</p>
        <dl><div><dt>API</dt><dd>${base}</dd></div><div><dt>错误</dt><dd>${reason}</dd></div></dl>
        <button class="secondary" id="runtime-retry">重新连接</button>
      </div>
    </div>`;
  setRuntimeStatus('API 不可用');
  setAgentAvailability(false);
  const retry = document.querySelector('#runtime-retry');
  if (retry) retry.onclick = () => location.reload();
}

window.addEventListener('DOMContentLoaded', () => {
  runtimeWorkspaceLabel();
  void probeRuntime();
});
window.addEventListener('unhandledrejection', event => {
  if (!runtimeStrictApi) return;
  event.preventDefault();
  renderApiUnavailable(event.reason);
});
