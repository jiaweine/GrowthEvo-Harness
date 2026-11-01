(() => {
  if (!new URLSearchParams(window.location.search).has('agent-api-smoke')) return;

  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const failures = [];
  const check = (condition, message) => { if (!condition) failures.push(message); };
  const waitFor = async (predicate, timeoutMs = 5000) => {
    const started = performance.now();
    while (performance.now() - started < timeoutMs) {
      if (predicate()) return true;
      await sleep(30);
    }
    return false;
  };
  const finish = () => {
    const marker = document.createElement('div');
    marker.id = 'agent-api-smoke';
    marker.textContent = failures.length ? `AGENT_API_SMOKE_FAIL: ${failures.join(' | ')}` : 'AGENT_API_SMOKE_PASS';
    document.body.appendChild(marker);
    document.body.dataset.agentApiSmoke = failures.length ? 'fail' : 'pass';
  };

  async function run() {
    const ready = await waitFor(() => runtimeAvailability === 'ready', 5000);
    check(ready, `runtime not ready: ${runtimeAvailability}`);
    check(document.body.dataset.agentRuntime === 'safe', `expected safe agent runtime, got ${document.body.dataset.agentRuntime}`);
    check(document.querySelector('.online-text').textContent.includes('安全'), 'agent status did not expose safe mode');

    document.querySelector('[data-route="agent"]').click();
    const input = document.querySelector('#agent-input');
    input.value = '查看当前工作区';
    document.querySelector('#agent-form').requestSubmit();
    const unavailable = await waitFor(() => document.querySelector('#agent-body').textContent.includes('model_unavailable'));
    check(unavailable, 'unconfigured execution must report no model and no actions');
    document.querySelector('#agent-mode').click();
    check(document.querySelector('#agent-mode').textContent.includes('策略模式'), 'failed to switch to conservative planner');
    input.value = '为新用户首购设计一个可验证的增长方案';
    document.querySelector('#agent-form').requestSubmit();
    const rendered = await waitFor(() => document.querySelector('.agent-plan-card'));
    check(rendered, 'real API agent plan card did not render');
    const cardText = document.querySelector('.agent-plan-card')?.textContent || '';
    check(cardText.includes('Deterministic 安全规划'), 'safe plan status missing');
    check(cardText.includes('新用户 7 日首购增量策略'), 'strategy title missing from live API result');
    check(cardText.includes('NO_TREATMENT vs 首单免邮'), 'experiment direction missing from live API result');
    check(cardText.includes('Shadow preflight'), 'next safety gate missing from live API result');
    check(runtimeAvailability === 'ready', 'successful agent plan changed global runtime state');

    const realApi = api;
    api = async () => { throw Error('isolated agent fixture failure'); };
    input.value = '触发一次隔离失败';
    document.querySelector('#agent-form').requestSubmit();
    const isolated = await waitFor(() => document.querySelector('#agent-body').textContent.includes('主工作区隔离'));
    check(isolated, 'agent-local failure message did not render');
    check(runtimeAvailability === 'ready', 'agent-local failure marked the whole runtime unavailable');
    check(!document.querySelector('#view').textContent.includes('GrowthEvo API 暂不可用'), 'agent-local failure replaced the main workspace');
    api = realApi;

    api = (_path, options = {}) => new Promise((resolve, reject) => {
      const signal = options.signal;
      if (!signal) {
        reject(Error('missing cancellation signal'));
        return;
      }
      const onAbort = () => {
        const error = Error('cancelled by smoke');
        error.name = 'AbortError';
        reject(error);
      };
      if (signal.aborted) onAbort();
      else signal.addEventListener('abort', onAbort, {once:true});
      void resolve;
    });
    input.value = '启动一个可取消的规划';
    document.querySelector('#agent-form').requestSubmit();
    const busy = await waitFor(() => document.querySelector('#agent-form').classList.contains('is-busy'));
    check(busy, 'agent did not enter busy state');
    const stopButton = document.querySelector('#agent-form button[type="submit"]');
    check(stopButton.getAttribute('aria-label') === '停止规划', 'busy send button did not become stop control');
    stopButton.click();
    const cancelled = await waitFor(() => document.querySelector('#agent-body').textContent.includes('已停止这次规划'));
    check(cancelled, 'agent cancellation message did not render');
    check(!document.querySelector('#agent-form').classList.contains('is-busy'), 'agent stayed busy after cancellation');
    check(runtimeAvailability === 'ready', 'user cancellation polluted global runtime state');
    api = realApi;

    finish();
  }

  window.addEventListener('DOMContentLoaded', () => {
    setTimeout(() => run().catch(error => {
      failures.push(error && error.message ? error.message : String(error));
      finish();
    }), 0);
  });
})();
