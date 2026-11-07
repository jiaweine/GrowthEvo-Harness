const REFERENCE_FIXTURE_ROUTES=new Set();
const baseRouteRender=render;
const AGENT_PLAN_TIMEOUT_MS=30000;
const AGENT_RUN_TIMEOUT_MS=90000;
let routeRenderEpoch=0;

function markReferenceFixture(route){
  if(useDemo||!REFERENCE_FIXTURE_ROUTES.has(route))return;
  const view=$('#view');
  if(!view||view.querySelector('[data-reference-fixture]'))return;
  const note=document.createElement('div');
  note.dataset.referenceFixture='true';
  note.className='card';
  note.style.cssText='margin-bottom:10px;padding:9px 12px;border:1px solid #e2d6a6;background:#fffaf0;color:#6f5a16;font-size:10px;line-height:1.5';
  note.textContent='参考演示 · 此工作台仍包含静态参考数据，不代表生产状态。服务不可用时不会用样例数据替代。';
  view.prepend(note);
}

function renderWorkspaceFailure(error){
  if(typeof isAuthRequiredError==='function'&&isAuthRequiredError(error))renderAuthRequired(error);
  else renderApiUnavailable(error);
}

render=async function guardedRender(){
  const epoch=++routeRenderEpoch;
  const route=state.route;
  if(useDemo){
    await baseRouteRender();
    if(epoch===routeRenderEpoch)$('#view').dataset.renderedRoute=route;
    if(epoch===routeRenderEpoch&&route==='dashboard')renderAgentOsHero();
    return;
  }
  if(runtimeAvailability==='unavailable'){renderApiUnavailable(runtimeLastError);return}
  if(runtimeAvailability==='auth_required'){renderAuthRequired(runtimeLastError);return}
  if(route!=='dashboard'&&!state.dashboard){
    try{state.dashboard=await api('/api/dashboard')}
    catch(error){if(epoch===routeRenderEpoch)renderWorkspaceFailure(error);return}
    if(epoch!==routeRenderEpoch||route!==state.route)return;
  }
  try{await baseRouteRender()}
  catch(error){if(epoch===routeRenderEpoch)renderWorkspaceFailure(error);return}
  if(epoch===routeRenderEpoch&&route===state.route){
    $('#view').dataset.renderedRoute=route;
    markReferenceFixture(route);
    if(route==='dashboard')renderAgentOsHero();
  }
};

function renderAgentOsHero(){
  const view=$('#view');
  if(!view||view.querySelector('.os-hero'))return;
  const hero=document.createElement('section');
  hero.className='os-hero';
  hero.setAttribute('aria-label','智能体操作系统与递归自进化');
  hero.innerHTML='<div class="os-hero-copy"><div class="os-eyebrow"><span class="os-signal"></span> 智能增长 · 受控操作工作区</div>'
    +'<h2>从指令，到真实行动。<br><em>从执行，到持续进化。</em></h2>'
    +'<p>让 AI 在受控工作空间内观察、选择工具、执行与校验；用真实轨迹发现可改进的策略，经过独立评测再推广。</p>'
    +'<div class="os-hero-actions"><button class="os-cta" type="button" id="os-start-agent">启动智能体操作 <span>↗</span></button>'
    +'<button class="os-cta-secondary" type="button" id="os-open-evolution">查看进化中心 <span>↗</span></button></div></div>'
    +'<div class="os-flow" aria-label="执行与进化闭环">'
    +'<span class="os-flow-heading">操作闭环 <b>● 过程可追溯</b></span>'
    +'<div class="os-flow-step"><i>01</i><strong>观察</strong><span>读取真实工作区</span></div>'
    +'<div class="os-flow-step"><i>02</i><strong>行动</strong><span>执行受控工具</span></div>'
    +'<div class="os-flow-step"><i>03</i><strong>核验</strong><span>检验动作与轨迹</span></div>'
    +'<div class="os-flow-step os-flow-last"><i>↺</i><strong>改进</strong><span>回放 · 评测 · 审批</span></div>'
    +'</div>';
  view.prepend(hero);
  const start=$('#os-start-agent');if(start)start.onclick=()=>go('agent');
  const evolution=$('#os-open-evolution');if(evolution)evolution.onclick=()=>go('evolution');
}

const COMMAND_ITEMS=[
  ['campaignStudio','创建一个新活动','目标 → 受众 → 证据 → 执行'],
  ['opportunities','分析新用户增长机会','发现真实增量机会'],
  ['experiments','打开实验中心','分组 · 对照 · 风险边界'],
  ['realtime','查看实时决策','决策记录 · 动作 · 执行策略'],
  ['approvals','查看待审批事项','风险 · 证据 · 身份校验'],
  ['harness','查看执行轨迹','步骤 · 工具 · 安全边界'],
  ['evolution','打开自进化中心','回放 → 验证 → 审批'],
  ['integrations','查看集成与渠道','数据 · 执行 · 内容接入'],
  ['growthOps','数据驱动增长运营','画像 · 旅程 · 实验反馈'],
  ['settings','打开工作区设置','工作区 · 策略 · 部署'],
];
const DATE_PRESETS=['最近 7 天','最近 30 天','最近 90 天'];
const CHANNEL_PRESETS=['全部渠道','应用推送','站内消息','邮件','短信','广告','微信'];
const AGENT_MODES=['执行模式','策略模式'];
let utilityMenuActions=[];
let agentModeIndex=0;
let agentRequestController=null;
let agentActiveRunId=null;

function closeUtilityMenu(){
  const pop=$('#utility-popover');
  if(pop)pop.hidden=true;
  utilityMenuActions=[];
}

function openUtilityMenu(title,items){
  const pop=$('#utility-popover');
  if(!pop)return;
  utilityMenuActions=items.map(item=>item.action||(()=>{}));
  pop.innerHTML=`<div class="utility-title">${esc(title)}</div>${items.map((item,index)=>`<button type="button" class="utility-item ${item.tone||''}" data-utility-index="${index}"><span>${esc(item.label)}</span>${item.detail?`<small>${esc(item.detail)}</small>`:''}</button>`).join('')}`;
  pop.hidden=false;
  $$('[data-utility-index]',pop).forEach(button=>{
    button.onclick=event=>{
      event.stopPropagation();
      const action=utilityMenuActions[Number(button.dataset.utilityIndex)];
      closeUtilityMenu();
      if(action)action();
    };
  });
}

function renderCommandResults(query=''){
  const normalized=query.trim().toLowerCase();
  const items=COMMAND_ITEMS.filter(item=>!normalized||item.some(value=>String(value).toLowerCase().includes(normalized)));
  const target=$('#command-results');
  if(!target)return;
  target.innerHTML=items.length?items.map(x=>`<button type="button" class="command-result" data-command-route="${x[0]}"><strong>${esc(x[1])}</strong><span>${esc(x[2])}</span></button>`).join(''):'<div class="command-empty">没有匹配的工作区入口</div>';
  $$('[data-command-route]',target).forEach(button=>button.onclick=()=>{
    $('#command-modal').hidden=true;
    go(button.dataset.commandRoute);
  });
}

function openCommand(){
  $('#command-modal').hidden=false;
  const input=$('#command-input');
  input.value='';
  renderCommandResults();
  input.focus();
}

function closeAgent(){
  const sidecar=$('#agent-sidecar');
  sidecar.classList.remove('open');
  if(window.innerWidth>1250)document.body.classList.add('agent-collapsed');
  syncBackdrop();
}

function openAgent(){
  document.body.classList.remove('agent-collapsed');
  $('#agent-sidecar').classList.add('open');
  syncBackdrop();
  const input=$('#agent-input');
  if(input&&window.innerWidth>760)input.focus();
}

function syncBackdrop(){
  const backdrop=$('#page-backdrop');
  if(!backdrop)return;
  const navOpen=window.innerWidth<=760&&$('#sidebar').classList.contains('open');
  const agentOpen=state.route!=='agent'&&window.innerWidth<=1250&&$('#agent-sidecar').classList.contains('open');
  backdrop.hidden=!(navOpen||agentOpen);
}

function appendAgentMessage(role,text){
  const target=$('#agent-body');
  if(!target)return;
  const label=role==='user'?'你':'智能体助手';
  const avatar=role==='user'?'我':'✦';
  target.insertAdjacentHTML('beforeend',`<div class="chat-row"><div class="chat-avatar ${role==='user'?'user':'agent'}">${avatar}</div><div><div class="chat-name">${label}</div><div class="bubble">${esc(text)}</div></div></div>`);
  target.scrollTop=target.scrollHeight;
}

function appendAgentPending(){
  const target=$('#agent-body');
  if(!target)return null;
  const row=document.createElement('div');
  row.className='chat-row agent-pending-row';
  row.innerHTML='<div class="chat-avatar agent">✦</div><div><div class="chat-name">智能体助手</div><div class="bubble agent-pending"><span></span>正在读取工作区并执行受控工具…</div></div>';
  target.appendChild(row);
  target.scrollTop=target.scrollHeight;
  return row;
}

function setAgentBusy(busy){
  const form=$('#agent-form');
  const submit=$('#agent-form button[type="submit"]');
  if(form)form.classList.toggle('is-busy',busy);
  if(!submit)return;
  submit.disabled=false;
  submit.dataset.busy=busy?'true':'false';
  submit.textContent=busy?'■':'➤';
  submit.setAttribute('aria-label',busy?'停止规划':'发送');
  submit.title=busy?'停止这次规划':'发送';
}

function agentFallbackLabel(reason){
  const value=String(reason||'');
  if(value==='proposal_low_confidence')return '置信度不足，已采用安全基线';
  if(value==='critic_veto')return '审核模型未通过，已采用安全基线';
  if(value==='agent_circuit_open')return '模型保护中，已采用安全基线';
  if(value.startsWith('workspace_invalid'))return '工作区证据校验未通过，已采用安全基线';
  if(value.startsWith('llm_failure'))return '模型暂不可用，已采用安全基线';
  if(value==='no_workspace_opportunity')return '没有可用机会，已采用安全基线';
  return '已采用规则安全规划';
}

function agentItem(items,type){
  return Array.isArray(items)?items.find(item=>item&&item.type===type):null;
}

function renderAgentPlan(result){
  const target=$('#agent-body');
  if(!target)return;
  const audit=result&&result.planner_audit?result.planner_audit:null;
  const strategy=agentItem(result&&result.artifacts,'StrategyProposal');
  const experiment=agentItem(result&&result.artifacts,'ExperimentDraft');
  const hypothesis=agentItem(result&&result.claims,'HYPOTHESIS');
  const estimate=agentItem(result&&result.claims,'ESTIMATE');
  const accepted=Boolean(audit&&audit.accepted);
  const usedLLM=Boolean(audit&&audit.used_llm);
  const status=accepted?'方案与审核已通过':usedLLM?agentFallbackLabel(audit.reason):'规则安全规划';
  const provider=accepted&&audit.provider?[audit.provider,audit.model].filter(Boolean).join(' · '):'';
  const critic=accepted&&audit.critic_provider?[audit.critic_provider,audit.critic_model].filter(Boolean).join(' · '):'';
  const gate=productLabel(result&&result.next_gate?result.next_gate:'灰度前检查');
  const runId=result&&result.run_id?result.run_id:'策略建议已生成';
  const title=strategy&&strategy.title?strategy.title:'受控增长策略草案';
  const hypothesisText=hypothesis&&hypothesis.text?hypothesis.text:'等待实验验证';
  const experimentText=experiment&&experiment.title?productLabel(experiment.title):'不触达对照实验';
  const estimateText=estimate&&estimate.text?estimate.text:'增量估计由工作区证据编译';
  const meta=[provider?`方案模型 · ${provider}`:'',critic?`审核模型 · ${critic}`:'',`下一步 · ${gate}`].filter(Boolean);
  target.insertAdjacentHTML('beforeend',`
    <div class="chat-row agent-plan-row">
      <div class="chat-avatar agent">✦</div>
      <div>
        <div class="chat-name">智能体助手</div>
        <article class="agent-plan-card" data-agent-plan-status="${accepted?'ai':'safe'}">
          <div class="agent-plan-head"><div><span class="agent-plan-status">${esc(status)}</span><strong>${esc(title)}</strong></div><small>${esc(runId)}</small></div>
          <div class="agent-plan-block"><span>可证伪假设</span><p>${esc(hypothesisText)}</p></div>
          <div class="agent-plan-grid"><div><span>实验方向</span><strong>${esc(experimentText)}</strong></div><div><span>证据判断</span><strong>${esc(estimateText)}</strong></div></div>
          <div class="agent-plan-meta">${meta.map(item=>`<span>${esc(item)}</span>`).join('')}</div>
          <div class="agent-plan-actions"><button type="button" data-agent-go="opportunities">查看机会</button><button type="button" data-agent-go="approvals">查看审批边界</button></div>
        </article>
      </div>
    </div>`);
  $$('[data-agent-go]',target).forEach(button=>{
    if(button.dataset.boundAgentGo)return;
    button.dataset.boundAgentGo='true';
    button.onclick=()=>go(button.dataset.agentGo);
  });
  target.scrollTop=target.scrollHeight;
}

async function confirmFirstPartyUiControls(result){
  if(!useDemo&&result.run_id&&!result.ui_confirmation_token)return;
  const actions=(Array.isArray(result&&result.ui_actions)?result.ui_actions:[])
    .filter(action=>action.status!=='confirmed'&&action.status!=='failed');
  if(!actions.length)return;
  const commands={open_search:'打开搜索',open_date_filter:'打开时间筛选',
    open_channel_filter:'打开渠道筛选',focus_campaign_name:'定位活动名称'};
  const routes=new Set(['dashboard','opportunities','campaigns','campaignStudio',
    'experiments','approvals','evolution','harness','realtime','evidence','execution',
    'data','growthOps','integrations','settings']);
  const receipts=[];
  const messages=[];
  for(const action of actions){
    const command=action.target;
    let success=false;
    try{
      if(action.kind==='navigate'&&routes.has(command)){
        await go(command);
        success=state.route===command&&location.hash==='#'+command&&
          document.getElementById('view').dataset.renderedRoute===command&&
          !document.querySelector('#view .runtime-error');
      }else if(action.kind!=='control'||!Object.hasOwn(commands,command)){
        success=false;
      }else if(command==='open_search'){
        closeUtilityMenu();
        openCommand();
        success=!document.getElementById('command-modal').hidden&&
          document.activeElement===document.getElementById('command-input');
      }else if(command==='open_date_filter'||command==='open_channel_filter'){
        document.getElementById('command-modal').hidden=true;
        const id=command==='open_date_filter'?'date-filter':'channel-filter';
        document.getElementById(id).click();
        const menu=document.getElementById('utility-popover');
        const title=command==='open_date_filter'?'时间范围':'渠道';
        success=!menu.hidden&&menu.querySelector('.utility-title')?.textContent===title;
      }else if(command==='focus_campaign_name'){
        await go('campaignStudio');
        const target=await new Promise(resolve=>{
          const direct=document.getElementById('live-campaign-name');
          if(direct){resolve(direct);return;}
          const observer=new MutationObserver(()=>{
            const node=document.getElementById('live-campaign-name');
            if(node){observer.disconnect();clearTimeout(timer);resolve(node);}
          });
          observer.observe(document.getElementById('view'),{childList:true,subtree:true});
          const timer=setTimeout(()=>{observer.disconnect();resolve(null);},4000);
        });
        if(target){target.focus();success=document.activeElement===target;}
      }
    }catch(_error){success=false;}
    receipts.push({step_index:action.step_index,status:success?'confirmed':'failed'});
    messages.push((commands[command]||'打开站内页面')+'：'+(success?'浏览器已验证':'未确认界面效果'));
  }
  appendAgentMessage('agent','界面操作回执：'+messages.join('；'));
  document.body.dataset.agentLastUiConfirmation=messages.join('|');
  if(useDemo||!result.run_id||!result.ui_confirmation_token)return;
  try{
    const recorded=await api('/api/agent/runs/'+encodeURIComponent(result.run_id)+'/ui-confirmation',{
      method:'POST',body:JSON.stringify({token:result.ui_confirmation_token,receipts})
    });
    const card=document.querySelector('[data-agent-run-id="'+CSS.escape(result.run_id)+'"]');
    if(card){
      card.dataset.agentRunStatus=recorded.status;
      card.querySelector('.agent-plan-head strong').textContent=AGENT_STATUS_LABELS[recorded.status]||'已记录回执';
      card.querySelector('[data-run-message]').textContent='浏览器回执已写入服务端运行记录；此回执不代表独立评测通过。';
    }
    if(state.route==='harness')await harness();
    return recorded;
  }catch(_error){
    appendAgentMessage('agent','界面回执未写入服务端，运行仍保留待确认状态。请检查连接后重试。');
  }
}

const AGENT_STATUS_LABELS={
  running:'正在执行',interrupted:'已中断，可继续',cancelled:'已取消',
  completed:'操作已结束',needs_approval:'等待人工审批',needs_consent:'需要授权',
  blocked:'已被安全规则阻止',provider_failure:'模型服务不可用',
  tool_failure:'工具执行失败',step_limit:'达到操作步数限制',
  model_unavailable:'尚未连接可用模型',unverified:'未核验',
  ui_pending:'等待界面确认',awaiting_ui_confirmation:'等待浏览器确认',
  ui_confirmed:'界面操作已收到回执',ui_failed:'界面操作未全部完成',unknown:'未知状态'
};
const AGENT_TOOL_LABELS={
  'workspace.read':'读取工作区','page.navigate':'打开站内页面',
  'campaign.draft':'创建活动草案','approval.review':'请求人工审核',
  'ui.control':'操作界面控件'
};
const AGENT_OUTCOME_LABELS={ok:'成功',ui_pending:'等待浏览器核验',
  blocked:'已阻止',needs_approval:'等待审批',needs_consent:'等待授权',
  error:'失败',tool_failure:'工具失败'};
function agentStepOutcomeLabel(step){
  if(step.ui_confirmation==='confirmed')return '浏览器已回执';
  if(step.ui_confirmation==='failed')return '浏览器报告失败';
  return AGENT_OUTCOME_LABELS[String(step.outcome||'')]||'已记录';
}
function agentOperationMessage(status,message){
  const messages={
    awaiting_ui_confirmation:'服务端已校验操作请求，正在等待浏览器执行并报告界面结果。',
    model_unavailable:'执行模式需要连接可用模型，本次没有执行任何操作。',
    provider_failure:'模型服务暂不可用，本步骤没有执行工具。',
    tool_failure:'站内工具执行失败，请核对运行记录后再重试。',
    step_limit:'已达到本次操作步数上限，任务可能尚未完成。',
    blocked:'操作未通过服务端校验，请检查工具权限与请求参数。',
    needs_consent:'创建活动草案需要勾选明确授权。',
    needs_approval:'已提出人工审核请求，请在审批页面核对并决定。',
    unverified:'没有执行可核验的工作区操作。'
  };
  return messages[status]||message;
}
async function renderAgentOperation(result){
  const target=$('#agent-body');
  if(!target)return;
  const status=String(result&&result.status||'unknown');
  const message=String(result&&result.message||'没有返回可验证的运行结果');
  const steps=Array.isArray(result&&result.steps)?result.steps:[];
  if(result.run_id){
    const previous=target.querySelector('[data-agent-run-id="'+CSS.escape(result.run_id)+'"]');
    if(previous)previous.closest('.chat-row')?.remove();
  }
  const details=steps.map((step,index)=>{
    const label=AGENT_TOOL_LABELS[String(step.tool||'')]||'受控操作';
    const outcome=agentStepOutcomeLabel(step);
    return '<div class="agent-plan-meta"><span>'+esc(String(index+1))+'. '+esc(label)+'</span><span>'+esc(outcome)+'</span></div>';
  }).join('');
  target.insertAdjacentHTML('beforeend',
    '<div class="chat-row agent-plan-row"><div class="chat-avatar agent">✦</div><div>'
    +'<div class="chat-name">智能体助手 · 操作记录</div>'
    +'<article class="agent-plan-card" data-agent-run-id="'+esc(result.run_id||'')+'" data-agent-run-status="'+esc(status)+'"><div class="agent-plan-head"><strong>'+esc(AGENT_STATUS_LABELS[status]||'请查看操作详情')+'</strong></div>'
    +'<p data-run-message>'+esc(agentOperationMessage(status,message))+'</p>'+details
    +'<small>执行记录来自实际 API 调用；审批、发布和外部发送不会自动完成。</small>'
    +'</article></div></div>');
  target.scrollTop=target.scrollHeight;
  return await confirmFirstPartyUiControls(result);
}

async function continueAgentExecution(result,signal){
  for(let round=0;round<8;round++){
    if(signal?.aborted)throw new DOMException('Cancelled','AbortError');
    agentActiveRunId=result.run_id||null;
    const confirmation=await renderAgentOperation(result);
    if(confirmation?.status!=='ui_confirmed'||!confirmation.resumable)return confirmation||result;
    if(signal?.aborted)throw new DOMException('Cancelled','AbortError');
    result=await api('/api/agent/runs/'+encodeURIComponent(agentActiveRunId)+'/resume',{
      method:'POST',signal,timeoutMs:AGENT_RUN_TIMEOUT_MS,
      body:JSON.stringify({allow_draft_writes:Boolean($('#agent-draft-consent')?.checked)})
    });
  }
  await renderAgentOperation(result);
  return result;
}

async function resumeAgentRun(runId){
  if(agentRequestController){toast('请先停止当前任务');return;}
  const controller=new AbortController();
  agentRequestController=controller;agentActiveRunId=runId;setAgentBusy(true);
  try{
    const result=await api('/api/agent/runs/'+encodeURIComponent(runId)+'/resume',{
      method:'POST',signal:controller.signal,timeoutMs:AGENT_RUN_TIMEOUT_MS,
      body:JSON.stringify({allow_draft_writes:Boolean($('#agent-draft-consent')?.checked)})
    });
    await continueAgentExecution(result,controller.signal);
    if(state.route==='harness')await harness();
  }catch(error){
    toast(error?.status===409?'任务状态已改变，请刷新后重试':'任务暂未继续，请检查连接或模型配置');
  }finally{
    agentRequestController=null;agentActiveRunId=null;setAgentBusy(false);
  }
}

function demoAgentResponse(goal){
  if(/审批|风险/.test(goal))return '演示建议：先检查受众影响、预算、证据和风险，再将高影响动作送入人工审批。';
  if(/机会|增量|人群/.test(goal))return '演示建议：结合人群规模、增量效果与证据支持度审视机会，同时保留“不触达”选项。';
  if(/实验|验证|灰度/.test(goal))return '演示建议：先明确主要指标和风险边界，再通过对照实验收集结果。';
  return '演示建议：把目标、证据、约束和下一步操作放在同一工作流中。';
}
function demoNavigationTarget(goal){
  // Explicit user-directed preview navigation only; not model inference.
  if(!/(打开|导航到|带我进入|进入)/.test(goal))return null;
  if(/自进化|演进/.test(goal))return 'evolution';
  if(/审批/.test(goal))return 'approvals';
  if(/实验/.test(goal))return 'experiments';
  if(/活动|草案/.test(goal))return 'campaignStudio';
  if(/机会/.test(goal))return 'opportunities';
  return null;
}

async function submitAgentPrompt(event){
  event.preventDefault();
  if(agentRequestController){
    agentRequestController.abort('user_cancelled');
    if(agentActiveRunId)void api('/api/agent/runs/'+encodeURIComponent(agentActiveRunId)+'/cancel',{method:'POST'}).catch(()=>{});
    return;
  }
  const input=$('#agent-input');
  const goal=input.value.trim();
  if(!goal)return;
  if(typeof recordAgentWorkspacePrompt==='function')recordAgentWorkspacePrompt(goal);
  appendAgentMessage('user',goal);
  input.value='';
  if(useDemo){
    const route=demoNavigationTarget(goal);
    appendAgentMessage('agent',demoAgentResponse(goal)+(route?' 正在打开对应的演示页面；这只是本地导航，并非 AI 模型执行。':''));
    if(route){go(route);toast('已打开演示页面（未调用模型）');}
    else toast('演示建议已生成（未调用模型）');
    return;
  }

  const controller=new AbortController();
  agentRequestController=controller;
  setAgentBusy(true);
  const pending=appendAgentPending();
  try{
    const strategyMode=agentModeIndex===1;
    const draftPermission=agentModeIndex===0&&Boolean($('#agent-draft-consent')&&$('#agent-draft-consent').checked);
    let result=await api(strategyMode?'/api/agent/plan':'/api/agent/run',{
      method:'POST',
      body:JSON.stringify(strategyMode
        ? {goal,primary_metric:'incremental_profit',guardrails:[]}
        : {goal,allow_draft_writes:draftPermission}),
      signal:controller.signal,
      timeoutMs:strategyMode?AGENT_PLAN_TIMEOUT_MS:AGENT_RUN_TIMEOUT_MS,
    });
    if(pending)pending.remove();
    if(strategyMode){
      renderAgentPlan(result);
      const audit=result&&result.planner_audit?result.planner_audit:null;
      toast(audit&&audit.accepted?'智能策略已通过审核':'安全计划已生成');
    }else{
      result=await continueAgentExecution(result,controller.signal);
      void renderAchievement();
      toast(result.status==='completed'?'智能体操作已返回结果':'智能体操作停止：'+(AGENT_STATUS_LABELS[result.status]||'请查看详情'));
    }
  }catch(error){
    if(pending)pending.remove();
    if(typeof isAuthRequiredError==='function'&&isAuthRequiredError(error)){
      appendAgentMessage('agent','生产登录已失效。重新登录后再继续规划；当前不会提交任何执行动作。');
      renderAuthRequired(error);
      toast('生产工作区需要重新登录');
    }else if(error&&error.name==='AbortError'){
      appendAgentMessage('agent','已停止这次规划的等待。服务端可能已执行部分操作，请到执行轨迹核对结果后再重试。');
      toast('已停止智能体操作');
    }else if(error&&error.name==='TimeoutError'){
      appendAgentMessage('agent','这次规划超过响应预算，已停止等待。GrowthEvo 主工作区仍可继续使用，你可以稍后重试。');
      toast('智能体规划已超时');
      void probeRuntime();
    }else{
      appendAgentMessage('agent','这次规划没有完成。GrowthEvo 会将智能体故障与主工作区隔离；确认 API 状态后可直接重试。');
      toast('智能体请求未完成');
      void probeRuntime();
    }
  }finally{
    if(agentRequestController===controller)agentRequestController=null;
    agentActiveRunId=null;
    setAgentBusy(false);
  }
}

async function renderAchievement(){
  const target=$('#agent-achievement');
  if(!target)return;
  // Report observations from the configured runtime, not promotional
  // uplift numbers or a fixture masquerading as production evidence.
  const isDemo=useDemo;
  target.innerHTML='<div class="achievement-head"><strong>执行与演进观测</strong><button id="achievement-evidence" type="button">证据中心 →</button></div>'
    +'<div class="achievement-card"><div class="achievement-main"><div class="achievement-avatar">OS</div>'
    +'<div class="achievement-copy"><strong>运行记录</strong><b id="agent-run-count">—</b></div>'
    +'<div class="achievement-copy"><strong>改进候选</strong><b id="agent-evo-count">—</b></div></div>'
    +'<div class="achievement-metrics"><div><span>执行模式</span><strong>'+ (isDemo?'演示':'实时 API') +'</strong></div>'
    +'<div><span>校验状态</span><strong>受控工具</strong></div>'
    +'<div><span>演进推广</span><strong>需审批</strong></div></div></div>';
  const evidence=$('#achievement-evidence');
  if(evidence)evidence.onclick=()=>go('evidence');
  if(isDemo){$('#agent-run-count').textContent='样例';$('#agent-evo-count').textContent='样例';return;}
  try{
    const [runs,candidates]=await Promise.all([api('/api/harness/runs'),api('/api/evolution/candidates')]);
    if(!document.contains(target))return;
    $('#agent-run-count').textContent=Array.isArray(runs)?String(runs.length):'—';
    $('#agent-evo-count').textContent=Array.isArray(candidates)?String(candidates.length):'—';
  }catch(_error){
    // Telemetry is advisory; never replace the main workspace when unavailable.
  }
}

function openProductIntro(){
  closeUtilityMenu();
  $('#intro-modal').hidden=false;
}

function bindShellInteractions(){
  $('#sidebar-collapse').onclick=()=>{
    if(window.innerWidth<=760){
      $('#sidebar').classList.remove('open');
      syncBackdrop();
      return;
    }
    const collapsed=document.body.classList.toggle('sidebar-collapsed');
    const button=$('#sidebar-collapse');
    button.setAttribute('aria-expanded',String(!collapsed));
    button.setAttribute('aria-label',collapsed?'展开侧栏':'收起侧栏');
    button.innerHTML=collapsed?'<span>›</span><em>展开</em>':'<span>‹</span> 收起';
  };

  $('#mobile-menu').onclick=()=>{
    $('#sidebar').classList.toggle('open');
    syncBackdrop();
  };

  $('#date-filter').onclick=event=>{
    event.stopPropagation();
    openUtilityMenu('时间范围',DATE_PRESETS.map(label=>({label,detail:label===$('#date-filter-label').textContent?'当前':'' ,action:()=>{
      $('#date-filter-label').textContent=label;
      document.body.dataset.dateRange=label;
      toast(`时间范围 · ${label}`);
    }})));
  };

  $('#channel-filter').onclick=event=>{
    event.stopPropagation();
    openUtilityMenu('渠道',CHANNEL_PRESETS.map(label=>({label,detail:label===$('#channel-filter-label').textContent?'当前':'',action:()=>{
      $('#channel-filter-label').textContent=label;
      document.body.dataset.channel=label;
      toast(`渠道 · ${label}`);
    }})));
  };

  $('#notification-open').onclick=async event=>{
    event.stopPropagation();
    const dot=$('#notification-open i');
    if(dot)dot.style.display='none';
    if(!useDemo){
      try{
        const records=await api('/api/approvals');
        const pending=(Array.isArray(records)?records:[]).filter(item=>item.status==='pending').length;
        openUtilityMenu('需要关注',[
          {label:pending?'有 '+pending+' 项待审批':'暂无待审批事项',detail:'来自当前工作区',action:()=>go('approvals')}
        ]);
      }catch(_error){toast('暂时无法读取待办事项，请检查工作区连接');}
      return;
    }
    openUtilityMenu('需要关注',[
      {label:'2 个活动待审批',detail:'查看风险与证据',action:()=>go('approvals')},
      {label:'实验结果已成熟',detail:'查看增量结果',action:()=>go('experiments')},
      {label:'渠道发送异常',detail:'查看执行状态',action:()=>go('execution')},
    ]);
  };

  $('#profile-open').onclick=event=>{
    event.stopPropagation();
    const authItems=typeof authProfileMenuItems==='function'?authProfileMenuItems():[];
    const title=typeof authProfileLabel==='function'?authProfileLabel():'工作区操作员';
    openUtilityMenu(title,[
      ...authItems,
      {label:'工作区设置',detail:'权限、预算与安全策略',action:()=>go('settings')},
      {label:'数据与集成',detail:'数据源与执行渠道',action:()=>go('integrations')},
    ]);
  };

  $('#agent-close').onclick=()=>{if(state.route==='agent')go('dashboard');else closeAgent()};
  $('#page-backdrop').onclick=()=>{
    $('#sidebar').classList.remove('open');
    $('#agent-sidecar').classList.remove('open');
    syncBackdrop();
  };

  $('#agent-mode').onclick=()=>{
    agentModeIndex=(agentModeIndex+1)%AGENT_MODES.length;
    $('#agent-mode').textContent=`${AGENT_MODES[agentModeIndex]}⌄`;
    toast(`智能体助手 · ${AGENT_MODES[agentModeIndex]}`);
  };

  $('#agent-attach').onclick=()=>$('#agent-file-input').click();
  $('#agent-file-input').onchange=event=>{
    const file=event.target.files&&event.target.files[0];
    if(!file)return;
    appendAgentMessage('agent',`已选择附件：${file.name}。文件仅保留在当前浏览器选择中，本轮规划不会自动上传附件内容。`);
    toast(`已选择 ${file.name}`);
    event.target.value='';
  };

  $('#agent-voice').onclick=()=>{
    const SpeechRecognition=window.SpeechRecognition||window.webkitSpeechRecognition;
    if(!SpeechRecognition){toast('当前浏览器不支持语音输入');return}
    const recognition=new SpeechRecognition();
    recognition.lang='zh-CN';
    recognition.interimResults=false;
    recognition.onresult=event=>{
      const text=event.results?.[0]?.[0]?.transcript||'';
      if(text)$('#agent-input').value=text;
    };
    recognition.onerror=()=>toast('语音输入未完成');
    recognition.start();
    toast('正在听取语音…');
  };

  $('#product-intro').onclick=openProductIntro;
  $('#intro-close').onclick=()=>$('#intro-modal').hidden=true;
  $('#intro-evidence').onclick=()=>{$('#intro-modal').hidden=true;go('evidence')};
  $('#intro-campaign').onclick=()=>{$('#intro-modal').hidden=true;go('campaignStudio')};
  // The evidence link is rebound whenever live observability is refreshed.

  $('#command-input').addEventListener('input',event=>renderCommandResults(event.target.value));
  $('#command-modal').addEventListener('click',event=>{if(event.target===$('#command-modal'))$('#command-modal').hidden=true});
  $('#intro-modal').addEventListener('click',event=>{if(event.target===$('#intro-modal'))$('#intro-modal').hidden=true});
  document.addEventListener('click',event=>{if(!event.target.closest('#utility-popover'))closeUtilityMenu()});
  window.addEventListener('resize',syncBackdrop);
}

function init(){
  $('#search-icon').innerHTML=icon('search');
  $('#command-search-icon').innerHTML=icon('search');
  $('#bell-icon').innerHTML=icon('bell');
  const nav=$('#main-nav');
  nav.innerHTML=NAV.map(n=>`<button class="nav-item" type="button" data-route="${n[0]}"><span class="nav-icon">${icon(n[1])}</span>${esc(n[2])}</button>`).join('');
  $('#mobile-tabs').innerHTML=MOBILE.map(n=>`<button class="mobile-tab" type="button" data-route="${n[0]}"><i>${esc(n[1])}</i>${esc(n[2])}</button>`).join('');
  $$('[data-route]').forEach(button=>button.onclick=()=>go(button.dataset.route));
  $('#command-open').onclick=openCommand;
  document.addEventListener('keydown',event=>{
    if((event.metaKey||event.ctrlKey)&&event.key.toLowerCase()==='k'){
      event.preventDefault();
      openCommand();
    }
    if(event.key==='Escape'){
      $('#command-modal').hidden=true;
      $('#intro-modal').hidden=true;
      closeUtilityMenu();
      if(window.innerWidth<=1250&&$('#agent-sidecar').classList.contains('open'))closeAgent();
      $('#sidebar').classList.remove('open');
      syncBackdrop();
    }
  });
  $('#agent-form').onsubmit=submitAgentPrompt;
  renderAgent();
  renderAchievement();
  bindShellInteractions();
  active();
  void render();
}

function parentRoute(route){return (typeof ROUTE_PARENT!=='undefined'&&ROUTE_PARENT[route])||route}
function active(){
  // Dedicated top-level entries must not be shadowed by their legacy parent.
  const parent=NAV.some(item=>item[0]===state.route)?state.route:parentRoute(state.route);
  $$('[data-route]').forEach(button=>button.classList.toggle('active',button.dataset.route===parent));
}
function go(route){
  if(route==='agent'){openAgent();return}
  state.route=route;
  location.hash=route;
  active();
  const rendering=render();
  $('#sidebar').classList.remove('open');
  syncBackdrop();
  window.scrollTo({top:0,behavior:'instant'});
  return rendering;
}
window.addEventListener('hashchange',()=>{
  const route=(location.hash||'#dashboard').slice(1);
  if(state.route===route)return;
  state.route=route;
  active();
  void render();
});

if('serviceWorker' in navigator){window.addEventListener('load',()=>navigator.serviceWorker.register('./service-worker.js').catch(()=>{}));}
document.addEventListener('DOMContentLoaded',init);
