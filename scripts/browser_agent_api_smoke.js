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
    const unavailable = await waitFor(() => Boolean(document.querySelector('#agent-body [data-agent-run-status="model_unavailable"]')));
    check(unavailable, 'unconfigured execution must report no model and no actions');
    document.querySelector('#agent-mode').click();
    check(document.querySelector('#agent-mode').textContent.includes('策略模式'), 'failed to switch to conservative planner');
    input.value = '为新用户首购设计一个可验证的增长方案';
    document.querySelector('#agent-form').requestSubmit();
    const rendered = await waitFor(() => document.querySelectorAll('.agent-plan-card').length >= 2);
    check(rendered, 'real API agent plan card did not render');
    const cards = Array.from(document.querySelectorAll('.agent-plan-card'));
    const cardText = cards[cards.length - 1]?.textContent || '';
    check(cardText.includes('规则安全规划'), 'safe plan status missing');
    check(cardText.includes('新用户 7 日首购增量策略'), 'strategy title missing from live API result');
    check(cardText.includes('不触达 对照 首单免邮'), 'experiment direction missing from live API result');
    check(cardText.includes('灰度前检查'), 'next safety gate missing from live API result');
    check(runtimeAvailability === 'ready', 'successful agent plan changed global runtime state');

    const realApi = api;
    const receiptRequests=[];
    api=async(path,options={})=>{
      if(path.endsWith('/ui-confirmation')){
        receiptRequests.push(JSON.parse(options.body));
        return {status:'ui_confirmed'};
      }
      return realApi(path,options);
    };
    await renderAgentOperation({run_id:'op_browser_contract',status:'awaiting_ui_confirmation',
      message:'等待浏览器操作',steps:[],ui_confirmation_token:'browser-fixture-token',
      ui_actions:[{step_index:0,kind:'navigate',target:'campaignStudio'},
        {step_index:1,kind:'control',target:'focus_campaign_name'}]});
    check(document.activeElement?.id==='live-campaign-name','controlled form did not retain focus');
    check(receiptRequests.length===1,'UI receipts were not sent back to the API');
    check(receiptRequests[0]?.receipts.every(item=>item.status==='confirmed'),'ordered UI operations did not verify');
    check(receiptRequests[0]?.receipts.map(item=>item.step_index).join(',')==='0,1','UI receipt step order changed');
    await confirmFirstPartyUiControls({ui_actions:[{step_index:0,kind:'control',target:'open_date_filter'}]});
    check(document.querySelector('#utility-popover .utility-title')?.textContent==='时间范围','wrong date filter menu');
    await confirmFirstPartyUiControls({ui_actions:[{step_index:0,kind:'control',target:'open_channel_filter'}]});
    check(document.querySelector('#utility-popover .utility-title')?.textContent==='渠道','wrong channel filter menu');
    closeUtilityMenu();
    await go('agent');
    check(document.querySelector('[data-agent-run-id="op_browser_contract"]')?.dataset.agentRunStatus==='ui_confirmed',
      'returning to the Agent workspace discarded the confirmed receipt');

    // Exercise the real browser -> receipt -> resume loop, not just a rendered
    // fixture card. The model continuation may start only after DOM verification.
    const continuationCalls=[];
    api=async(path,options={})=>{
      if(path.startsWith('/api/agent/runs/op_browser_resume/')){
        continuationCalls.push(path.split('/').pop());
        if(path.endsWith('/ui-confirmation')){
          check(document.getElementById('command-modal').hidden===false,'continuation preceded visible search');
          check(JSON.parse(options.body).receipts[0].status==='confirmed','continuation received an unverified action');
          return {run_id:'op_browser_resume',status:'ui_confirmed',resumable:true};
        }
        if(path.endsWith('/resume')){
          check(continuationCalls.join(',')==='ui-confirmation,resume','model resumed before recorded browser receipt');
          check(options.signal instanceof AbortSignal,'resumed request has no cancellation signal');
          return {run_id:'op_browser_resume',status:'completed',steps:[{tool:'ui.control',outcome:'ui_pending',ui_confirmation:'confirmed'}],
            message:'浏览器反馈后完成任务',ui_actions:[{step_index:0,kind:'control',target:'open_search',status:'confirmed'}]};
        }
      }
      return realApi(path,options);
    };
    const continued=await continueAgentExecution({run_id:'op_browser_resume',status:'awaiting_ui_confirmation',
      steps:[],ui_confirmation_token:'continuation-fixture-token',
      ui_actions:[{step_index:0,kind:'control',target:'open_search',status:'pending'}]},new AbortController().signal);
    check(continued.status==='completed','browser feedback did not continue the task');
    check(continuationCalls.length===2,'confirmed action was unexpectedly repeated');
    const continuedCards=document.querySelectorAll('[data-agent-run-id="op_browser_resume"]');
    check(continuedCards.length===1&&continuedCards[0].dataset.agentRunStatus==='completed','task card did not advance to completed');
    check(continuedCards[0]?.textContent.includes('浏览器已回执'),'completed step still reports pending browser verification');
    document.getElementById('command-modal').hidden=true;
    api=realApi;
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
