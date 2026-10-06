const REFERENCE_FIXTURE_ROUTES=new Set(['campaigns','campaignStudio','execution','evidence','data','integrations','settings']);
const baseRouteRender=render;
const AGENT_PLAN_TIMEOUT_MS=30000;
let routeRenderEpoch=0;

function markReferenceFixture(route){
  if(useDemo||!REFERENCE_FIXTURE_ROUTES.has(route))return;
  const view=$('#view');
  if(!view||view.querySelector('[data-reference-fixture]'))return;
  const note=document.createElement('div');
  note.dataset.referenceFixture='true';
  note.className='card';
  note.style.cssText='margin-bottom:10px;padding:9px 12px;border:1px solid #e2d6a6;background:#fffaf0;color:#6f5a16;font-size:10px;line-height:1.5';
  note.textContent='Reference UI Fixture · 此工作台仍包含静态参考数据，不代表实时生产状态。真实 API 可用性与业务数据不会被 synthetic fixture 替代。';
  view.prepend(note);
}

function renderWorkspaceFailure(error){
  if(typeof isAuthRequiredError==='function'&&isAuthRequiredError(error))renderAuthRequired(error);
  else renderApiUnavailable(error);
}

render=async function guardedRender(){
  const epoch=++routeRenderEpoch;
  const route=state.route;
  if(useDemo)return baseRouteRender();
  if(runtimeAvailability==='unavailable'){renderApiUnavailable(runtimeLastError);return}
  if(runtimeAvailability==='auth_required'){renderAuthRequired(runtimeLastError);return}
  if(route!=='dashboard'&&!state.dashboard){
    try{state.dashboard=await api('/api/dashboard')}
    catch(error){if(epoch===routeRenderEpoch)renderWorkspaceFailure(error);return}
    if(epoch!==routeRenderEpoch||route!==state.route)return;
  }
  try{await baseRouteRender()}
  catch(error){if(epoch===routeRenderEpoch)renderWorkspaceFailure(error);return}
  if(epoch===routeRenderEpoch&&route===state.route)markReferenceFixture(route);
};

const COMMAND_ITEMS=[
  ['campaignStudio','创建一个新活动','Goal → Audience → Evidence → Execution'],
  ['opportunities','分析新用户增长机会','Opportunity Map · causal incrementality'],
  ['experiments','打开实验中心','Assignment / Holdout / Guardrails'],
  ['realtime','查看实时决策','Decision API / propensity / policy'],
  ['approvals','查看待审批事项','Risk / evidence / identity'],
  ['harness','打开 Agent Harness','Trace / tools / guardrails'],
  ['evolution','打开 Evolution Lab','Replay → Shadow → Canary'],
  ['integrations','查看集成与渠道','Data / execution / content connectors'],
  ['settings','打开工作区设置','Workspace / policy / deployment'],
];
const DATE_PRESETS=['最近 7 天','最近 30 天','最近 90 天'];
const CHANNEL_PRESETS=['全部渠道','App Push','站内消息','Email','短信','广告','微信'];
const AGENT_MODES=['策略模式','证据模式','执行模式'];
let utilityMenuActions=[];
let agentModeIndex=0;
let agentRequestController=null;

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
  const agentOpen=window.innerWidth<=1250&&$('#agent-sidecar').classList.contains('open');
  backdrop.hidden=!(navOpen||agentOpen);
}

function appendAgentMessage(role,text){
  const target=$('#agent-body');
  if(!target)return;
  const label=role==='user'?'你':'Growth Agent';
  const avatar=role==='user'?'李':'✦';
  target.insertAdjacentHTML('beforeend',`<div class="chat-row"><div class="chat-avatar ${role==='user'?'user':'agent'}">${avatar}</div><div><div class="chat-name">${label}</div><div class="bubble">${esc(text)}</div></div></div>`);
  target.scrollTop=target.scrollHeight;
}

function appendAgentPending(){
  const target=$('#agent-body');
  if(!target)return null;
  const row=document.createElement('div');
  row.className='chat-row agent-pending-row';
  row.innerHTML='<div class="chat-avatar agent">✦</div><div><div class="chat-name">Growth Agent</div><div class="bubble agent-pending"><span></span>正在读取机会证据并进行 Critic 复核…</div></div>';
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
  if(value==='critic_veto')return 'Critic 未通过，已采用安全基线';
  if(value==='agent_circuit_open')return '模型保护中，已采用安全基线';
  if(value.startsWith('workspace_invalid'))return '工作区证据校验未通过，已采用安全基线';
  if(value.startsWith('llm_failure'))return '模型暂不可用，已采用安全基线';
  if(value==='no_workspace_opportunity')return '没有可用机会，已采用安全基线';
  return '已采用 deterministic 安全规划';
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
  const status=accepted?'AI + Critic 已通过':usedLLM?agentFallbackLabel(audit.reason):'Deterministic 安全规划';
  const provider=accepted&&audit.provider?[audit.provider,audit.model].filter(Boolean).join(' · '):'';
  const critic=accepted&&audit.critic_provider?[audit.critic_provider,audit.critic_model].filter(Boolean).join(' · '):'';
  const gate=result&&result.next_gate?result.next_gate:'Shadow preflight';
  const runId=result&&result.run_id?result.run_id:'proposal_ready';
  const title=strategy&&strategy.title?strategy.title:'受控增长策略草案';
  const hypothesisText=hypothesis&&hypothesis.text?hypothesis.text:'等待实验验证';
  const experimentText=experiment&&experiment.title?experiment.title:'NO_TREATMENT 对照实验';
  const estimateText=estimate&&estimate.text?estimate.text:'增量估计由工作区证据编译';
  const meta=[provider?`Proposal · ${provider}`:'',critic?`Critic · ${critic}`:'',`Next · ${gate}`].filter(Boolean);
  target.insertAdjacentHTML('beforeend',`
    <div class="chat-row agent-plan-row">
      <div class="chat-avatar agent">✦</div>
      <div>
        <div class="chat-name">Growth Agent</div>
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

function demoAgentResponse(goal){
  if(/审批|风险/.test(goal))return '我会先检查影响用户、预算、证据等级和最大风险敞口，再把高影响动作送入审批路径。';
  if(/机会|增量|人群/.test(goal))return '我会优先按 Population × Incremental Lift × Support 排序，并保留 NO_TREATMENT 作为一等候选动作。';
  if(/实验|验证|canary/i.test(goal))return '建议先定义主指标与 guardrail，再用 Holdout / Canary 收集成熟窗口内的增量证据。';
  return '已收到。我会把目标、证据、约束和执行边界放在同一条决策链里，并优先选择可验证的下一步。';
}

async function submitAgentPrompt(event){
  event.preventDefault();
  if(agentRequestController){
    agentRequestController.abort('user_cancelled');
    return;
  }
  const input=$('#agent-input');
  const goal=input.value.trim();
  if(!goal)return;
  appendAgentMessage('user',goal);
  input.value='';
  if(useDemo){
    appendAgentMessage('agent',demoAgentResponse(goal));
    toast('Growth Agent 已生成下一步建议');
    return;
  }

  const controller=new AbortController();
  agentRequestController=controller;
  setAgentBusy(true);
  const pending=appendAgentPending();
  try{
    const result=await api('/api/agent/plan',{
      method:'POST',
      body:JSON.stringify({goal,primary_metric:'incremental_profit',guardrails:[]}),
      signal:controller.signal,
      timeoutMs:AGENT_PLAN_TIMEOUT_MS,
    });
    if(pending)pending.remove();
    renderAgentPlan(result);
    const audit=result&&result.planner_audit?result.planner_audit:null;
    toast(audit&&audit.accepted?'AI 策略已通过 Critic':'安全计划已生成');
  }catch(error){
    if(pending)pending.remove();
    if(typeof isAuthRequiredError==='function'&&isAuthRequiredError(error)){
      appendAgentMessage('agent','生产登录已失效。重新登录后再继续规划；当前不会提交任何执行动作。');
      renderAuthRequired(error);
      toast('生产工作区需要重新登录');
    }else if(error&&error.name==='AbortError'){
      appendAgentMessage('agent','已停止这次规划。没有提交执行动作，也不会继续占用模型请求。');
      toast('已停止 Growth Agent');
    }else if(error&&error.name==='TimeoutError'){
      appendAgentMessage('agent','这次规划超过响应预算，已停止等待。GrowthEvo 主工作区仍可继续使用，你可以稍后重试。');
      toast('Agent 规划已超时');
      void probeRuntime();
    }else{
      appendAgentMessage('agent','这次规划没有完成。GrowthEvo 会把 Agent 故障与主工作区隔离；确认 API 状态后可直接重试。');
      toast('Agent 请求未完成');
      void probeRuntime();
    }
  }finally{
    if(agentRequestController===controller)agentRequestController=null;
    setAgentBusy(false);
  }
}

function renderAchievement(){
  const target=$('#agent-achievement');
  if(!target)return;
  target.innerHTML=`<div class="achievement-head"><strong>本周增量成果</strong><button id="achievement-evidence" type="button">查看证据 →</button></div><div class="achievement-card"><div class="achievement-main"><div class="achievement-avatar">Acme</div><div class="achievement-copy"><strong>增量收益</strong><b>+28%</b></div><div class="achievement-copy"><strong>NO_TREATMENT 节省</strong><b>31.6%</b></div></div><div class="achievement-metrics"><div><span>Evidence</span><strong>Tier A</strong></div><div><span>Support</span><strong>91%</strong></div><div><span>Canary</span><strong>5%</strong></div></div></div>`;
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

  $('#notification-open').onclick=event=>{
    event.stopPropagation();
    const dot=$('#notification-open i');
    if(dot)dot.style.display='none';
    openUtilityMenu('需要关注',[
      {label:'2 个活动待审批',detail:'查看风险与证据',action:()=>go('approvals')},
      {label:'实验结果已成熟',detail:'查看增量结果',action:()=>go('experiments')},
      {label:'渠道发送异常',detail:'查看执行状态',action:()=>go('execution')},
    ]);
  };

  $('#profile-open').onclick=event=>{
    event.stopPropagation();
    const authItems=typeof authProfileMenuItems==='function'?authProfileMenuItems():[];
    const title=typeof authProfileLabel==='function'?authProfileLabel():'李明 · 增长负责人';
    openUtilityMenu(title,[
      ...authItems,
      {label:'工作区设置',detail:'权限、预算与安全策略',action:()=>go('settings')},
      {label:'数据与集成',detail:'数据源与执行渠道',action:()=>go('integrations')},
    ]);
  };

  $('#agent-close').onclick=closeAgent;
  $('#page-backdrop').onclick=()=>{
    $('#sidebar').classList.remove('open');
    $('#agent-sidecar').classList.remove('open');
    syncBackdrop();
  };

  $('#agent-mode').onclick=()=>{
    agentModeIndex=(agentModeIndex+1)%AGENT_MODES.length;
    $('#agent-mode').textContent=`${AGENT_MODES[agentModeIndex]}⌄`;
    toast(`Growth Agent · ${AGENT_MODES[agentModeIndex]}`);
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
  $('#achievement-evidence').onclick=()=>go('evidence');

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
  const parent=parentRoute(state.route);
  $$('[data-route]').forEach(button=>button.classList.toggle('active',button.dataset.route===parent));
}
function go(route){
  if(route==='agent'){openAgent();return}
  state.route=route;
  location.hash=route;
  active();
  void render();
  $('#sidebar').classList.remove('open');
  syncBackdrop();
  window.scrollTo({top:0,behavior:'instant'});
}
window.addEventListener('hashchange',()=>{
  state.route=(location.hash||'#dashboard').slice(1);
  active();
  void render();
});

if('serviceWorker' in navigator){window.addEventListener('load',()=>navigator.serviceWorker.register('./service-worker.js').catch(()=>{}));}
document.addEventListener('DOMContentLoaded',init);