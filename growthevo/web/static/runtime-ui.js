const runtimeStrictApi = config.MODE === 'api' || config.MODE === 'production';

api = async function runtimeAwareApi(path, options = {}) {
  if (useDemo) return demoApi(path, options);
  try {
    const response = await fetch(`${config.API_BASE || ''}${path}`, {
      headers: {'Content-Type': 'application/json', ...(options.headers || {})},
      ...options,
    });
    if (!response.ok) throw Error(await response.text());
    return await response.json();
  } catch (error) {
    if (!runtimeStrictApi && config.MODE === 'auto') {
      console.warn('API unavailable; using demo mode because MODE=auto', error);
      return demoApi(path, options);
    }
    console.error('GrowthEvo API unavailable; strict API mode will not substitute synthetic data', error);
    throw error;
  }
};

function runtimeWorkspaceLabel() {
  const meta = document.querySelector('.workspace-card .workspace-copy span');
  if (!meta) return;
  if (useDemo) {
    meta.textContent = 'Demo Workspace · Synthetic Data';
    document.body.dataset.runtimeMode = 'demo';
    return;
  }
  meta.textContent = config.MODE === 'production' ? 'Production Workspace' : 'API Workspace';
  document.body.dataset.runtimeMode = config.MODE === 'production' ? 'production' : 'api';
}

function renderApiUnavailable(error) {
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
  const retry = document.querySelector('#runtime-retry');
  if (retry) retry.onclick = () => location.reload();
}

window.addEventListener('DOMContentLoaded', runtimeWorkspaceLabel);
window.addEventListener('unhandledrejection', event => {
  if (!runtimeStrictApi) return;
  event.preventDefault();
  renderApiUnavailable(event.reason);
});
