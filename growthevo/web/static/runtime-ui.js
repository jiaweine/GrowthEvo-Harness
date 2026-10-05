const runtimeStrictApi = !useDemo;
const RUNTIME_API_TIMEOUT_MS = 10000;
const RUNTIME_READY_TIMEOUT_MS = 5000;
let runtimeAvailability = useDemo ? 'demo' : 'checking';
let runtimeLastError = null;
let runtimeBackend = useDemo ? {mode:'demo',environment:'static'} : null;

async function runtimeFetch(url, options = {}, timeoutMs = RUNTIME_API_TIMEOUT_MS) {
  const controller = new AbortController();
  const upstream = options.signal;
  let timedOut = false;
  const abortFromUpstream = () => controller.abort(upstream && upstream.reason ? upstream.reason : 'upstream');
  if (upstream) {
    if (upstream.aborted) controller.abort(upstream.reason || 'upstream');
    else upstream.addEventListener('abort', abortFromUpstream, {once:true});
  }
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort('timeout');
  }, timeoutMs);
  try {
    const {signal: _ignored, ...rest} = options;
    return await fetch(url, {...rest, signal: controller.signal});
  } catch (error) {
    if (error && error.name === 'AbortError') {
      const wrapped = Error(timedOut ? `API request timed out after ${timeoutMs}ms` : 'API request cancelled');
      wrapped.name = timedOut ? 'TimeoutError' : 'AbortError';
      wrapped.code = timedOut ? 'GROWTHEVO_API_TIMEOUT' : 'GROWTHEVO_API_CANCELLED';
      throw wrapped;
    }
    throw error;
  } finally {
    clearTimeout(timer);
    if (upstream) upstream.removeEventListener('abort', abortFromUpstream);
  }
}

api = async function runtimeAwareApi(path, options = {}) {
  if (useDemo) return demoApi(path, options);
  const {timeoutMs = RUNTIME_API_TIMEOUT_MS, ...requestOptions} = options;
  const headers = new Headers(requestOptions.headers || {});
  if (!headers.has('Accept')) headers.set('Accept', 'application/json');
  // Avoid forcing application/json on GET/HEAD: doing so turns otherwise-simple
  // cross-origin reads into unnecessary CORS preflights. JSON write helpers pass
  // string bodies, so add Content-Type only when a body actually exists.
  if (typeof requestOptions.body === 'string' && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  const response = await runtimeFetch(`${config.API_BASE || ''}${path}`, {
    ...requestOptions,
    headers,
    cache: 'no-store',
  }, timeoutMs);
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

function setAgentAvailability(state, detail = '') {
  const labels = {
    ai: 'AI 已连接',
    safe: '安全模式',
    demo: 'Demo',
    checking: '检查中',
    offline: 'API 不可用',
  };
  const text = document.querySelector('.online-text');
  if (text) {
    text.textContent = labels[state] || labels.safe;
    text.title = detail || '';
  }
  const dot = document.querySelector('.online-dot');
  if (dot) {
    dot.style.opacity = state === 'offline' ? '.35' : '1';
    dot.style.background = state === 'ai' ? '#10b981' : state === 'offline' ? '#94a3b8' : '#6366f1';
  }
  document.body.dataset.agentRuntime = state;
}

function runtimeWorkspaceLabel() {
  const meta = document.querySelector('.workspace-card .workspace-copy span');
  if (useDemo) {
    if (meta) meta.textContent = 'Demo Workspace · Synthetic Data';
    document.body.dataset.runtimeMode = 'demo';
    setRuntimeStatus('Demo · Synthetic Data', null, '非生产数据');
    setAgentAvailability('demo', '静态演示不会连接外部模型');
    return;
  }
  if (meta) meta.textContent = 'API Workspace · Checking';
  document.body.dataset.runtimeMode = 'api';
  setRuntimeStatus('API 状态检查中');
  setAgentAvailability('checking');
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
    const durable = mode === 'production' && payload && payload.persistence && payload.persistence.active === true;
    const dataMode = payload && payload.data_mode ? payload.data_mode : 'reference-contract';
    const meta = document.querySelector('.workspace-card .workspace-copy span');
    if (meta) {
      meta.textContent = durable
        ? 'Production Workspace · Durable API'
        : `API Workspace · ${dataMode === 'synthetic' ? 'Synthetic' : 'Reference Contract'}`;
    }
    document.body.dataset.runtimeMode = mode;
    setRuntimeStatus(`API Ready · ${mode}${env}`, latency, durable ? 'Durable production' : `Data: ${dataMode}`);

    const llm = payload && payload.llm ? payload.llm : null;
    const agentActive = Boolean(llm && llm.agent_planning === true && llm.active === true && llm.healthy !== false);
    if (agentActive) {
      const available = Number(llm.available_routes || 0);
      const total = Number(llm.route_count || 0);
      const providers = Array.isArray(llm.providers) ? llm.providers.join(' / ') : '';
      setAgentAvailability('ai', `${available}/${total || available} routes${providers ? ` · ${providers}` : ''}`);
    } else {
      setAgentAvailability('safe', '模型未激活或暂不可用时使用 deterministic 安全规划');
    }
  } catch (error) {
    runtimeAvailability = 'unavailable';
    runtimeLastError = error;
    setRuntimeStatus('API 不可用');
    setAgentAvailability('offline');
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
        <h1>GrowthEvo API 暂不可用</h1>
        <p>当前处于严格 API 模式，GrowthEvo 不会把 synthetic demo 数据伪装成真实生产数据。</p>
        <dl><div><dt>API</dt><dd>${base}</dd></div><div><dt>错误</dt><dd>${reason}</dd></div></dl>
        <button class="secondary" id="runtime-retry">重新连接</button>
      </div>
    </div>`;
  setRuntimeStatus('API 不可用');
  setAgentAvailability('offline');
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
