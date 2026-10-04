(() => {
  if (!new URLSearchParams(window.location.search).has('interaction-smoke')) return;

  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const failures = [];
  const check = (condition, message) => { if (!condition) failures.push(message); };
  const click = selector => {
    const element = document.querySelector(selector);
    check(Boolean(element), `missing ${selector}`);
    if (element) element.click();
    return element;
  };
  const finish = () => {
    const marker = document.createElement('div');
    marker.id = 'interaction-smoke';
    marker.textContent = failures.length ? `INTERACTION_SMOKE_FAIL: ${failures.join(' | ')}` : 'INTERACTION_SMOKE_PASS';
    document.body.appendChild(marker);
    document.body.dataset.interactionSmoke = failures.length ? 'fail' : 'pass';
  };

  async function run() {
    await sleep(180);

    click('#sidebar-collapse');
    check(document.body.classList.contains('sidebar-collapsed'), 'sidebar did not collapse');
    click('#sidebar-collapse');
    check(!document.body.classList.contains('sidebar-collapsed'), 'sidebar did not expand');

    click('#date-filter');
    check(!document.querySelector('#utility-popover').hidden, 'date menu did not open');
    click('#utility-popover [data-utility-index="0"]');
    check(document.querySelector('#date-filter-label').textContent.includes('7'), 'date filter did not change');

    click('#channel-filter');
    click('#utility-popover [data-utility-index="1"]');
    check(document.querySelector('#channel-filter-label').textContent === 'App Push', 'channel filter did not change');

    click('#notification-open');
    check(document.querySelector('#utility-popover').textContent.includes('待审批'), 'notification menu missing content');
    document.querySelector('#utility-popover').hidden = true;

    click('#command-open');
    const commandInput = document.querySelector('#command-input');
    commandInput.value = '审批';
    commandInput.dispatchEvent(new Event('input', {bubbles: true}));
    check(document.querySelectorAll('[data-command-route]').length >= 1, 'command search did not filter');
    click('[data-command-route="approvals"]');
    await sleep(80);
    check(location.hash === '#approvals', 'command result did not navigate');

    click('[data-route="dashboard"]');
    await sleep(80);
    click('[data-dashboard-metric="roi"]');
    check(document.querySelector('[data-dashboard-metric="roi"]').classList.contains('active'), 'trend metric did not switch');
    click('#trend-granularity');
    check(document.querySelector('#trend-granularity').textContent.includes('周'), 'trend granularity did not switch');

    click('[data-dashboard-filter="Experiment"]');
    check(document.querySelectorAll('#dashboard-strategies tbody tr').length >= 1, 'dashboard list filter returned no rows');
    check([...document.querySelectorAll('#dashboard-strategies tbody tr')].every(row => row.textContent.includes('Experiment')), 'dashboard filter kept wrong row types');

    click('#dashboard-strategies .action-view');
    await sleep(60);
    check(location.hash === '#experiments', 'row action did not open experiment workspace');

    click('[data-route="dashboard"]');
    await sleep(80);
    click('.quick-card[data-go="opportunities"]');
    await sleep(60);
    check(location.hash === '#opportunities', 'quick action did not navigate');

    click('[data-route="agent"]');
    click('#agent-close');
    check(document.body.classList.contains('agent-collapsed'), 'agent did not close on desktop');
    click('[data-route="agent"]');
    check(!document.body.classList.contains('agent-collapsed'), 'agent did not reopen');

    const agentInput = document.querySelector('#agent-input');
    agentInput.value = '帮我分析增长机会';
    document.querySelector('#agent-form').requestSubmit();
    await sleep(40);
    check(document.querySelector('#agent-body').textContent.includes('帮我分析增长机会'), 'agent did not render user message');
    check(document.querySelector('#agent-body').textContent.includes('Population'), 'agent did not render demo response');

    const beforeMode = document.querySelector('#agent-mode').textContent;
    click('#agent-mode');
    check(document.querySelector('#agent-mode').textContent !== beforeMode, 'agent mode did not change');

    click('#product-intro');
    check(!document.querySelector('#intro-modal').hidden, 'product intro did not open');
    click('#intro-close');
    check(document.querySelector('#intro-modal').hidden, 'product intro did not close');

    check(document.querySelector('#agent-achievement').textContent.includes('本周增量成果'), 'agent achievement did not render');
    finish();
  }

  window.addEventListener('DOMContentLoaded', () => {
    setTimeout(() => run().catch(error => {
      failures.push(error && error.message ? error.message : String(error));
      finish();
    }), 0);
  });
})();
