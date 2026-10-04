const REFERENCE_FIXTURE_ROUTES=new Set(['campaigns','campaignStudio','execution','evidence','data','integrations','settings']);
const baseRouteRender=render;
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

render=async function guardedRender(){
  const epoch=++routeRenderEpoch;
  const route=state.route;
  if(useDemo)return baseRouteRender();
  if(runtimeAvailability==='unavailable'){renderApiUnavailable(runtimeLastError);return}
  if(route!=='dashboard'&&!state.dashboard){
    try{state.dashboard=await api('/api/dashboard')}
    catch(error){if(epoch===routeRenderEpoch)renderApiUnavailable(error);return}
    if(epoch!==routeRenderEpoch||route!==state.route)return;
  }
  try{await baseRouteRender()}
  catch(error){if(epoch===routeRenderEpoch)renderApiUnavailable(error);return}
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

function demoAgentResponse(goal){
  if(/审批|风险/.test(goal))return '我会先检查影响用户、预算、证据等级和最大风险敞口，再把高影响动作送入审批路径。';
  if(/机会|增量|人群/.test(goal))return '我会优先按 Population × Incremental Lift × Support 排序，并保留 NO_TREATMENT 作为一等候选动作。';
  if(/实验|验证|canary/i.test(goal))return '建议先定义主指标与 guardrail，再用 Holdout / Canary 收集成熟窗口内的增量证据。';
  return '已收到。我会把目标、证据、约束和执行边界放在同一条决策链里，并优先选择可验证的下一步。';
}

async function submitAgentPrompt(event){
  event.preventDefault();
  const input=$('#agent-input');
  const goal=input.value.trim();
  if(!goal)return;
  const submit=$('#agent-form button[type="submit"]');
  if(submit)submit.disabled=true;
  appendAgentMessage('user',goal);
  input.value='';
  if(useDemo){
    appendAgentMessage('agent',demoAgentResponse(goal));
    toast('Growth Agent 已生成下一步建议');
    if(submit)submit.disabled=false;
    return;
  }
  try{
    const result=await api('/api/agent/plan',{method:'POST',body:JSON.stringify({goal,primary_metric:'incremental_profit',guardrails:[]})});
    appendAgentMessage('agent',`计划已生成：${result.run_id||'proposal_ready'}。请在审批与证据工作区继续确认执行边界。`);
    toast(`Agent Plan 已生成 · ${result.run_id||'proposal_ready'}`);
  }catch(error){
    renderApiUnavailable(error);
  }finally{
    if(submit)submit.disabled=false;
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
    openUtilityMenu('李明 · 增长负责人',[
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
    appendAgentMessage('agent',`已选择附件：${file.name}`);
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
