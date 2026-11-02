/* Agent OS cockpit: a real three-pane workspace, not fabricated chat history. */
/* Localized tool names are presentation-only; the server still controls permissions. */
const WORKSPACE_TOOL_LABELS={
  'workspace.read':'读取工作区',
  'page.navigate':'打开站内页面',
  'campaign.draft':'创建活动草案',
  'approval.review':'申请人工审核',
  'ui.control':'操作界面控件'
};
const WORKSPACE_EFFECT_LABELS={
  read:'只读',navigation:'站内导航',draft:'需用户授权',
  approval:'需要人工处理',ui_intent:'待浏览器确认'
};

const agentWorkspaceSessions=[{id:1,title:'当前会话',html:null}];
let agentWorkspaceActive=1;
let agentWorkspaceCounter=1;
const preWorkspaceRender=render;
const preWorkspaceGo=go;

function saveAgentWorkspaceSession(){
  const current=agentWorkspaceSessions.find(item=>item.id===agentWorkspaceActive);
  const body=document.getElementById('agent-body');
  if(current&&body)current.html=body.innerHTML;
}
function restoreAgentPortal(){
  const sidecar=document.getElementById('agent-sidecar');
  const body=document.getElementById('agent-body');
  const form=document.getElementById('agent-form');
  const achievement=document.getElementById('agent-achievement');
  if(!sidecar||!form||!body||!achievement)return;
  if(sidecar.contains(body)&&sidecar.contains(form))return;
  saveAgentWorkspaceSession();
  sidecar.insertBefore(body,achievement);
  sidecar.insertBefore(form,achievement);
  document.body.classList.remove('agent-workspace-route');
}
function agentWorkspaceThreads(){
  const container=document.getElementById('agent-workspace-threads');
  if(!container)return;
  container.innerHTML=agentWorkspaceSessions.slice().reverse().map(item=>
    '<button type="button" class="aw-thread '+(item.id===agentWorkspaceActive?'active':'')+
    '" data-aw-thread="'+item.id+'"><span class="aw-thread-icon">◈</span><span>'+
    esc(item.title)+'</span></button>').join('');
  container.querySelectorAll('[data-aw-thread]').forEach(button=>button.onclick=()=>{
    if(agentRequestController){toast('请先停止当前操作');return;}
    const id=Number(button.dataset.awThread);
    if(id===agentWorkspaceActive)return;
    saveAgentWorkspaceSession();
    const next=agentWorkspaceSessions.find(item=>item.id===id);
    if(!next)return;
    agentWorkspaceActive=id;
    if(next.html!==null)document.getElementById('agent-body').innerHTML=next.html;
    else renderAgent();
    bindWorkspaceSuggestionButtons();
    agentWorkspaceThreads();
  });
}
function bindWorkspaceSuggestionButtons(){
  document.querySelectorAll('#agent-body [data-agent-prompt]').forEach(button=>button.onclick=()=>{
    const field=document.getElementById('agent-input');
    if(field){field.value=button.dataset.agentPrompt;field.focus();}
  });
}
function newAgentWorkspaceSession(){
  if(agentRequestController){toast('请先停止当前操作');return;}
  saveAgentWorkspaceSession();
  const id=++agentWorkspaceCounter;
  agentWorkspaceSessions.push({id,title:'新会话 '+id,html:null});
  agentWorkspaceActive=id;
  renderAgent();
  agentWorkspaceThreads();
}
function recordAgentWorkspacePrompt(goal){
  if(state.route!=='agent'||!goal)return;
  const activeSession=agentWorkspaceSessions.find(item=>item.id===agentWorkspaceActive);
  if(activeSession&&activeSession.title.startsWith('新会话'))activeSession.title=goal.slice(0,28);
  else if(activeSession&&activeSession.title==='当前会话')activeSession.title=goal.slice(0,28);
  agentWorkspaceThreads();
}
async function agentWorkspaceTelemetry(){
  const target=document.getElementById('aw-telemetry');
  if(!target)return;
  if(use演示){
    target.innerHTML='<span>演示工作区</span><strong>示例数据，不执行真实 Agent 请求</strong>';
    return;
  }
  try{
    const [tools,readiness]=await Promise.all([
      api('/api/agent/tools'),api('/api/evolution/readiness')
    ]);
    if(!document.contains(target))return;
    const sections=Array.isArray(tools)?tools:[];
    document.getElementById('aw-tool-list').innerHTML=sections.map(tool=>
      '<div class="aw-capability"><span>◇</span><div><strong>'+esc(WORKSPACE_TOOL_LABELS[tool.name]||'受控操作')+
      '</strong><small>'+esc(WORKSPACE_EFFECT_LABELS[tool.effect]||'权限由服务端决定')+'</small></div></div>').join('');
    target.innerHTML='<span>真实运行记录 / 进化准备度</span><strong>'+
      esc(String(readiness.trace_count||0))+' / '+esc(String(readiness.required_trace_count||8))+
      ' 条轨迹</strong><small>候选 '+esc(String(readiness.candidate_count||0))+
      ' · 进程内数据，不代表自动晋升</small>';
  }catch(_error){
    target.textContent='运行环境尚未连接，无法读取工具和演进状态';
  }
}
async function renderAgentWorkspace(){
  const view=document.getElementById('view');
  if(!view)return;
  document.body.classList.add('agent-workspace-route');
  document.body.classList.remove('agent-collapsed');
  const existingBody=document.getElementById('agent-body');
  const existingForm=document.getElementById('agent-form');
  if(!existingBody||!existingForm)return;
  // Keep the existing composer, consent checkbox, request lifecycle and trace UI.
  view.innerHTML='<section class="aw-shell" aria-label="Agent OS Conversation Workspace">'+
    '<aside class="aw-conversations" aria-label="Agent 会话"><div class="aw-panel-title"><strong>会话记录</strong><button id="aw-new-session" type="button" aria-label="新建会话" title="新建会话">＋</button></div>'+
    '<p class="aw-muted">本次浏览器会话 · 不同步服务器历史</p><div id="agent-workspace-threads"></div>'+
    '<div class="aw-conversation-footer"><strong>当前工作区</strong><p>会话内容保存在当前页面内存中。Agent 单次请求不会自动继承其他会话历史。</p></div></aside>'+
    '<section class="aw-chat"><header class="aw-chat-head"><div class="aw-identity"><span class="aw-agent-icon">✦</span><div><strong>智能体助手</strong><small>智能体操作系统 · '+(use演示?'演示模式':'实时工作区')+'</small></div></div>'+
    '<div class="aw-head-actions"><button id="aw-mode" type="button">切换执行 / 策略</button><button id="aw-evolution" type="button">自进化中心 ↗</button></div></header>'+
    '<div class="aw-messages" id="aw-chat-mount"></div><div class="aw-composer-mount" id="aw-form-mount"></div>'+
    '<p class="aw-chat-disclaimer">仅可使用已授权的第一方操作。审批、发送和发布必须由人确认；任务失败不会显示为成功。</p></section>'+
    '<aside class="aw-participants" aria-label="能力与进化状态"><div class="aw-panel-title"><strong>任务上下文</strong></div>'+
    '<div class="aw-group"><h3>参与成员</h3><div class="aw-participant"><span class="aw-person">OP</span>你 · 工作区操作员</div>'+
    '<div class="aw-participant active"><span class="aw-agent-icon">✦</span>智能体助手 <small>'+(use演示?'演示':'受控执行')+'</small></div></div>'+
    '<div class="aw-group"><h3>第一方工具能力</h3><div id="aw-tool-list" class="aw-tool-list">'+
    (use演示?'<span class="aw-muted">演示预览 · 实际工具需连接 API</span>':'正在检查已注册工具…')+
    '</div></div><div class="aw-group"><h3>自进化</h3><div id="aw-telemetry" class="aw-telemetry">正在获取真实进化状态…</div>'+
    '<button id="aw-open-evolution" type="button" class="aw-quick">查看进化诊断 ↗</button></div>'+
    '<div class="aw-group"><h3>快捷操作</h3>'+
    '<button class="aw-quick" data-aw-prompt="读取当前增长机会，并导航到实验中心">检查增长机会</button>'+
    '<button class="aw-quick" data-aw-prompt="读取审批工作区，并带我打开审批页面">检查待审批事项</button>'+
    '<button class="aw-quick" data-aw-prompt="先读取工作区，再打开命令搜索面板">打开界面搜索</button></div></aside></section>';
  document.getElementById('aw-chat-mount').appendChild(existingBody);
  document.getElementById('aw-form-mount').appendChild(existingForm);
  const session=agentWorkspaceSessions.find(item=>item.id===agentWorkspaceActive);
  if(session?.html!==null&&existingBody.innerHTML!==session.html){
    existingBody.innerHTML=session.html;bindWorkspaceSuggestionButtons();
  }
  agentWorkspaceThreads();
  document.getElementById('aw-new-session').onclick=newAgentWorkspaceSession;
  document.getElementById('aw-mode').onclick=()=>document.getElementById('agent-mode').click();
  document.getElementById('aw-evolution').onclick=()=>go('evolution');
  document.getElementById('aw-open-evolution').onclick=()=>go('evolution');
  view.querySelectorAll('[data-aw-prompt]').forEach(button=>button.onclick=()=>{
    const field=document.getElementById('agent-input');field.value=button.dataset.awPrompt;field.focus();
  });
  if(!use演示)void agentWorkspaceTelemetry();
  else agentWorkspaceTelemetry();
}

render=async function renderWithAgentWorkspace(){
  if(state.route==='agent')return renderAgentWorkspace();
  restoreAgentPortal();
  return preWorkspaceRender();
};
go=function routeWithAgentWorkspace(route){
  if(route!=='agent')return preWorkspaceGo(route);
  state.route='agent';
  location.hash='agent';
  active();
  void render();
  document.getElementById('sidebar').classList.remove('open');
  syncBackdrop();
  window.scrollTo({top:0,behavior:'instant'});
};
