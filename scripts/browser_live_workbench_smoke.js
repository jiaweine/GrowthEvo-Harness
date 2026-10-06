(() => {
  if (!new URLSearchParams(window.location.search).has('live-workbench-smoke')) return;

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
  const visit = async (name, marker) => {
    go(name);
    const rendered = await waitFor(() =>
      location.hash === '#' + name &&
      document.querySelector('#view') &&
      document.querySelector('#view').textContent.includes(marker)
    );
    check(rendered, name + ' did not render marker ' + marker);
    check(!document.querySelector('#view [data-reference-fixture]'), name + ' rendered Reference UI Fixture');
  };
  const finish = () => {
    const marker = document.createElement('div');
    marker.id = 'live-workbench-smoke';
    marker.textContent = failures.length
      ? 'LIVE_WORKBENCH_SMOKE_FAIL: ' + failures.join(' | ')
      : 'LIVE_WORKBENCH_SMOKE_PASS';
    document.body.appendChild(marker);
    document.body.dataset.liveWorkbenchSmoke = failures.length ? 'fail' : 'pass';
  };

  window.addEventListener('DOMContentLoaded', () => {
    setTimeout(() => void (async () => {
      const ready = await waitFor(() => runtimeAvailability === 'ready');
      check(ready, 'runtime not ready: ' + runtimeAvailability);

      await visit('campaigns', 'Campaign Registry');
      await visit('evidence', 'Locked Evidence');
      await visit('execution', 'Execution Boundary');
      await visit('data', 'Recent Decision Log');
      await visit('integrations', 'Runtime Connector Registry');
      await visit('settings', 'Runtime Configuration');
      await visit('campaignStudio', 'Campaign Draft');

      const form = document.querySelector('#live-campaign-form');
      check(Boolean(form), 'live campaign form missing');
      if (form) {
        document.querySelector('#live-campaign-name').value = 'Browser Live Draft';
        document.querySelector('#live-campaign-goal').value = '验证真实 Campaign Draft 写入';
        document.querySelector('#live-campaign-audience').value = 'browser smoke audience';
        document.querySelector('#live-campaign-budget').value = '12345';
        form.requestSubmit();

        const created = await waitFor(() =>
          Boolean(document.body.dataset.lastCampaignDraft) &&
          location.hash === '#campaigns' &&
          document.querySelector('#view') &&
          document.querySelector('#view').textContent.includes('Browser Live Draft')
        );
        check(created, 'campaign draft was not created and re-rendered from API');

        const serverRows = await api('/api/campaigns');
        check(
          Array.isArray(serverRows) && serverRows.some(item => item && item.name === 'Browser Live Draft'),
          'campaign draft missing from server API'
        );
      }

      finish();
    })().catch(error => {
      failures.push(error && error.message ? error.message : String(error));
      finish();
    }), 0);
  });
})();
