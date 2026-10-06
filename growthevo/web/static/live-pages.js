const fixtureCampaignsPage=campaigns;
const fixtureCampaignStudioPage=campaignStudio;
const fixtureEvidencePage=evidence;
const fixtureExecutionPage=execution;
const fixtureDataCenterPage=dataCenter;
const fixtureIntegrationsPage=integrations;
const fixtureSettingsPage=settings;
const fixtureOpportunitiesPage=opportunities;
const fixtureExperimentsPage=experiments;
const fixtureRealtimePage=realtime;
const fixtureHarnessPage=harness;
const fixtureApprovalsPage=approvals;
const fixtureEvolutionPage=evolution;

function liveText(value,fallback='—'){return value===null||value===undefined||value===''?fallback:String(value)}
function liveNumber(value){const n=Number(value);return Number.isFinite(n)?n:null}
function liveMoney(value){const n=liveNumber(value);return n===null?'—':`¥${fmt(n)}`}
function livePercent(value,digits=0){const n=liveNumber(value);return n===null?'—':`${(n*100).toFixed(digits)}%`}
function liveBadge(value){return `<span class="soft-badge">${esc(liveText(value))}</span>`}
function emptyState(title,detail){return `<div class="card surface-card"><div class="surface-title"><div><h2>${esc(title)}</h2><p>${esc(detail)}</p></div></div></div>`}

opportunities=async function liveOpportunities(){
 if(useDemo)return fixtureOpportunitiesPage();
 const raw=await api('/api/opportunities');
 const rows=(Array.isArray(raw)?raw:[]).map(x=>({
  segment:liveText(x.segment),
  kind:'API opportunity',
  population:liveNumber(x.population)||0,
  natural:(liveNumber(x.natural_conversion)||0)*100,
  best_action:liveText(x.best_action),
  incremental_lift_pp:liveNumber(x.incremental_lift_pp)||0,
  incremental_value:liveNumber(x.incremental_value)||0,
  support:Math.max(0,Math.min(1,liveNumber(x.support)||0)),
  evidence_tier:liveText(x.evidence_tier),
  freshness:liveText(x.freshness),
 }));
 $('#view').innerHTML=`${head('增长机会 Opportunity Map','服务端 Opportunity API 的当前因果机会；不会用购买倾向替代增量效果。','<button class="primary" data-go="campaignStudio">基于机会创建 Campaign</button>')}${sectionNav(EVIDENCE_NAV,'opportunities')}${rows.length?`<div class="card surface-card table-scroll"><div class="surface-title"><div><h2>当前机会</h2><p>Population × Incremental Lift × Support × Evidence。</p></div><span class="soft-badge green">Live API</span></div>${opportunityTable(rows)}</div>`:emptyState('暂无机会','Opportunity API 当前没有返回可展示记录。')}`;
 bindProductActions();
};

experiments=async function liveExperiments(){
 if(useDemo)return fixtureExperimentsPage();
 const rows=await api('/api/experiments');
 const items=Array.isArray(rows)?rows:[];
 $('#view').innerHTML=`${head('实验中心','服务端 Experiment contract：assignment、variants、metric、maturity、guardrail 与 uncertainty 分离。')}${sectionNav(STRATEGY_NAV,'experiments')}${items.length?`<div class="experiment-grid"><div class="card surface-card"><div class="surface-title"><div><h2>Experiments</h2><p>当前 API 返回的实验状态。</p></div><span class="soft-badge green">Live API</span></div><div class="experiment-list">${items.map(x=>`<div class="experiment-card"><div class="experiment-head"><div><strong>${esc(liveText(x.name))}</strong><div class="evo-source">${esc(liveText(x.id))} · ${esc(liveText(x.assignment))}</div></div>${liveBadge(x.status)}</div><div class="experiment-meta"><div><span>Primary metric</span><strong>${esc(liveText(x.primary_metric))}</strong></div><div><span>Allocation</span><strong>${esc(liveText(x.allocation))}</strong></div><div><span>Maturity</span><strong>${esc(liveText(x.maturity))}</strong></div><div><span>Variants</span><strong>${esc(Array.isArray(x.variants)?x.variants.join(' / '):liveText(x.variants))}</strong></div></div><div class="result-box"><div><span>Estimate</span><strong class="value-positive">${esc(liveText(x.estimate))}</strong></div><div><span>Uncertainty</span><strong>${esc(liveText(x.ci))}</strong></div><div><span>Guardrails</span><strong>${esc(Array.isArray(x.guardrails)?x.guardrails.join(', '):liveText(x.guardrails))}</strong></div></div><p style="font-size:8px;color:#7d8899;line-height:1.5">${esc(liveText(x.hypothesis))}</p></div>`).join('')}</div></div></div>`:emptyState('暂无实验','Experiment API 当前没有返回实验。')}`;
 bindProductActions();
};

async function runReferenceDecision(){
 const button=$('#run-reference-decision');if(button)button.disabled=true;
 try{
  const suffix=`${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const result=await api('/api/decide',{
   method:'POST',
   headers:{'Idempotency-Key':`ui-reference-${suffix}`},
   body:JSON.stringify({
    entity_id:`ui_reference_${suffix}`,
    placement:'decision_console',
    context:{cart_value:198,session_intent:'high',new_user:true},
    candidate_action_ids:['NO_TREATMENT','free_shipping'],
    consent_state:true,
    frequency_remaining:2,
    budget_remaining:50,
    context_freshness_seconds:5,
   }),
  });
  toast(`Reference decision: ${result.action_id} · p=${Number(result.propensity).toFixed(3)}`);
  await realtime();
 }catch(error){toast(`Decision failed: ${error&&error.message?error.message:'unknown error'}`)}finally{if(button)button.disabled=false}
}

realtime=async function liveRealtime(){
 if(useDemo)return fixtureRealtimePage();
 const [actions,logs]=await Promise.all([api('/api/actions'),api('/api/decisions/recent?limit=50')]);
 const registry=Array.isArray(actions)?actions:[];const recent=Array.isArray(logs)?logs:[];
 $('#view').innerHTML=`${head('实时决策','当前 Reference Decision API 的真实 registry、propensity 与 Decision Log。它验证决策契约，不宣称因果最优。','<button class="primary" id="run-reference-decision">运行安全示例决策</button>')}${sectionNav(EVIDENCE_NAV,'realtime')}<div class="page-grid"><div class="card surface-card span-4"><div class="surface-title"><div><h2>Action Registry</h2><p>NO_TREATMENT 始终是一等动作。</p></div><span class="soft-badge green">Live API</span></div>${registry.map(x=>`<div class="evidence-row"><span>${esc(liveText(x.label))}<br><small>${esc(liveText(x.action_id))}</small></span><strong>${esc(liveText(x.risk_level))} · ${liveMoney(x.cost)}</strong></div>`).join('')}</div><div class="card surface-card span-8 table-scroll"><div class="surface-title"><div><h2>Decision Log</h2><p>记录 policy identity、真实 assignment propensity 与 guardrail fallback。</p></div></div>${recent.length?`<table class="log-table"><thead><tr><th>ID</th><th>Placement</th><th>Action</th><th>Propensity</th><th>Policy</th><th>Evidence</th><th>Mode</th></tr></thead><tbody>${recent.map(x=>`<tr><td><code>${esc(liveText(x.decision_id))}</code></td><td>${esc(liveText(x.placement))}</td><td>${esc(liveText(x.action_id))}</td><td>${esc(liveNumber(x.propensity)===null?'—':Number(x.propensity).toFixed(4))}</td><td>${esc(liveText(x.policy_id))}</td><td>${esc(liveText(x.evidence_tier))}</td><td>${esc(liveText(x.policy_randomization))}</td></tr>`).join('')}</tbody></table>`:'<p style="font-size:10px;color:#7d8899">尚无本进程决策记录。可运行一个无外部副作用的 reference decision。</p>'}</div></div>`;
 bindProductActions();const run=$('#run-reference-decision');if(run)run.onclick=runReferenceDecision;
};

harness=async function liveHarness(){
 if(useDemo)return fixtureHarnessPage();
 const rows=await api('/api/harness/runs');const items=Array.isArray(rows)?rows:[];
 $('#view').innerHTML=`${head('Agent Runtime','服务端 Harness Run API：身份、工具调用、策略结果、证据与成本可审计。')}${sectionNav(RUNTIME_NAV,'harness')}${items.length?`<div class="card surface-card table-scroll"><div class="surface-title"><div><h2>Harness Runs</h2><p>当前 reference run history。</p></div><span class="soft-badge green">Live API</span></div><table class="opportunity-table"><thead><tr><th>Run</th><th>Task</th><th>Agent</th><th>Harness</th><th>Policy</th><th>Evidence</th><th>Tools</th><th>Latency</th><th>Outcome</th></tr></thead><tbody>${items.map(x=>`<tr><td><code>${esc(liveText(x.id))}</code></td><td>${esc(liveText(x.task))}</td><td>${esc(liveText(x.agent_id))}</td><td>${esc(liveText(x.harness_id))}</td><td>${esc(liveText(x.policy))}</td><td>${esc(liveText(x.evidence))}</td><td>${esc(liveText(x.tool_calls))}</td><td>${esc(liveText(x.latency_ms))} ms</td><td>${esc(liveText(x.outcome))}</td></tr>`).join('')}</tbody></table></div>`:emptyState('暂无 Harness Run','Harness API 当前没有返回 run。')}`;
 bindProductActions();
};

function approvalActionLabel(decision){return ({approve_shadow:'批准 Shadow',approve_1:'批准 1%',approve_5:'批准 5%',approve_25:'批准 25%',reject:'拒绝',return:'退回'})[decision]||decision}
async function submitApprovalDecision(id,decision){
 try{
  await api(`/api/approvals/${encodeURIComponent(id)}/decision`,{method:'POST',body:JSON.stringify({decision,note:`Reviewed from GrowthEvo Web: ${approvalActionLabel(decision)}`})});
  toast(`${id} · ${approvalActionLabel(decision)}`);await approvals();
 }catch(error){toast(`审批未提交：${error&&error.message?error.message:'unknown error'}`)}
}

approvals=async function liveApprovals(){
 if(useDemo)return fixtureApprovalsPage();
 const rows=await api('/api/approvals');const items=Array.isArray(rows)?rows:[];
 $('#view').innerHTML=`${head('治理与审批','当前服务端审批状态。已完成的审批不能被不同的二次决策覆盖。')}${sectionNav(RUNTIME_NAV,'approvals')}${items.length?`<div class="approval-list">${items.map(x=>{const pending=x.status==='pending';return `<div class="card approval-wide"><div class="approval-summary"><div class="approval-name"><strong>${esc(liveText(x.title))}</strong><p>${esc(liveText(x.id))} · ${esc(liveText(x.campaign))}</p></div><div class="approval-kv"><span>影响用户</span><strong>${esc(liveText(x.affected_users))}</strong></div><div class="approval-kv"><span>预算</span><strong>${liveMoney(x.budget)}</strong></div><div class="approval-kv"><span>最大风险</span><strong>${esc(liveText(x.max_risk))}</strong></div><div class="approval-kv"><span>预计增量价值</span><strong class="value-positive">${liveMoney(x.incremental_value)}</strong></div></div><div class="change-box"><strong>Evidence：</strong> Tier ${esc(liveText(x.evidence_tier))}　·　<strong>不确定性：</strong> ${esc(liveText(x.uncertainty))}　·　<strong>状态：</strong> ${esc(liveText(x.status))}</div><div class="version-row"><span class="version-pill">Agent ${esc(liveText(x.agent_id))}</span><span class="version-pill">Harness ${esc(liveText(x.harness_id))}</span><span class="version-pill">Policy ${esc(liveText(x.policy_id))}</span></div>${pending?`<div class="approval-buttons"><button data-approval="${esc(x.id)}" data-decision="return">退回</button><button class="danger" data-approval="${esc(x.id)}" data-decision="reject">拒绝</button><button data-approval="${esc(x.id)}" data-decision="approve_shadow">Shadow</button><button data-approval="${esc(x.id)}" data-decision="approve_1">1%</button><button class="canary" data-approval="${esc(x.id)}" data-decision="approve_5">5%</button></div>`:'<div class="surface-badges"><span class="soft-badge green">Finalized · server state</span></div>'}</div>`}).join('')}</div>`:emptyState('暂无待审批记录','Approval API 当前没有返回记录。')}`;
 bindProductActions();$$('[data-approval][data-decision]').forEach(button=>button.onclick=()=>submitApprovalDecision(button.dataset.approval,button.dataset.decision));
};

evolution=async function liveEvolution(){
 if(useDemo)return fixtureEvolutionPage();
 const rows=await api('/api/evolution/candidates');const items=Array.isArray(rows)?rows:[];
 $('#view').innerHTML=`${head('Evolution Lab','服务端 Evolution candidates：候选改进必须沿 Replay → Eval → Shadow → Canary → Promote 边界演进。')}${sectionNav(RUNTIME_NAV,'evolution')}${items.length?`<div class="evolution-list">${items.map(x=>`<div class="card evo-card"><div class="evo-head"><div><strong>${esc(liveText(x.id))}</strong><div class="evo-source">Source runs: ${esc(liveText(x.source_runs))}</div></div>${liveBadge(x.status)}</div><div class="evo-problem"><strong>问题</strong><br>${esc(liveText(x.problem))}<br><br><strong>候选改进</strong><br>${esc(liveText(x.candidate))}</div><div class="eval-grid">${Object.entries(x.offline_replay||{}).map(([key,value])=>`<div class="eval-cell"><span>${esc(key)}</span><strong>${esc(liveText(value))}</strong></div>`).join('')}</div><div class="promotion-line"><div class="promotion-stage done">Offline Replay</div><span class="promotion-arrow">→</span><div class="promotion-stage done">Eval</div><span class="promotion-arrow">→</span><div class="promotion-stage ${x.shadow==='PASS'?'done':''}">Shadow</div><span class="promotion-arrow">→</span><div class="promotion-stage active">Canary Gate</div><span class="promotion-arrow">→</span><div class="promotion-stage">Promote</div></div></div>`).join('')}</div>`:emptyState('暂无进化候选','Evolution API 当前没有返回 candidate。')}`;
 bindProductActions();
};


campaigns=async function liveCampaigns(){
 if(useDemo)return fixtureCampaignsPage();
 const raw=await api('/api/campaigns');
 const items=Array.isArray(raw)?raw:[];
 const drafts=items.filter(item=>String(item.status||'').toLowerCase()==='draft').length;
 const nonDraft=items.length-drafts;
 const summary='<div class="stat-strip">'
  +'<div class="stat-box"><span>Campaign records</span><strong>'+items.length+'</strong><em>Live API</em></div>'
  +'<div class="stat-box"><span>Draft</span><strong>'+drafts+'</strong><em>等待证据与审批</em></div>'
  +'<div class="stat-box"><span>Non-draft</span><strong>'+nonDraft+'</strong><em>服务端当前状态</em></div>'
  +'<div class="stat-box"><span>Source</span><strong>Server</strong><em>不使用浏览器 fixture</em></div>'
  +'</div>';
 const content=items.length
  ?'<div class="card table-card"><div class="surface-title"><div><h2>Campaign Registry</h2><p>当前 API 返回的 Campaign 列表。</p></div><span class="soft-badge green">Live API</span></div>'+campaignsTable(items)+'</div>'
  :emptyState('暂无 Campaign','当前 API 尚未创建 Campaign。');
 $('#view').innerHTML=head('策略与执行','服务端 Campaign state：草稿、目标、候选动作与持久化状态来自当前 API。','<button class="primary" data-go="campaignStudio">＋ 新建 Campaign Draft</button>')
  +sectionNav(STRATEGY_NAV,'campaigns')+summary+content;
 bindProductActions();
};

campaignStudio=async function liveCampaignStudio(){
 if(useDemo)return fixtureCampaignStudioPage();
 const rawActions=await api('/api/actions');
 const actions=Array.isArray(rawActions)?rawActions:[];
 const actionInputs=actions.map(item=>{
  const actionId=liveText(item.action_id);
  const control=actionId==='NO_TREATMENT';
  const checked=control||actionId==='free_shipping';
  return '<label class="token '+(control?'control':'action')+'" style="cursor:pointer">'
   +'<input type="checkbox" data-live-campaign-action value="'+esc(actionId)+'" '+(checked?'checked ':'')+(control?'disabled':'')+'/> '
   +esc(liveText(item.label,actionId))+'</label>';
 }).join('');
 $('#view').innerHTML=head('Campaign Studio','创建真实服务端 Campaign Draft。此步骤只写入草稿，不产生外部营销副作用。')
  +sectionNav(STRATEGY_NAV,'campaignStudio')
  +'<form id="live-campaign-form" class="studio-shell">'
  +'<div class="studio-canvas">'
  +'<div class="card form-section"><div class="surface-title"><div><h2>Campaign Draft</h2><p>字段直接匹配 /api/campaigns/draft contract。</p></div><span class="soft-badge green">Live API</span></div>'
  +'<div class="form-grid">'
  +'<div class="field"><label for="live-campaign-name">Name</label><input id="live-campaign-name" class="field-value" style="width:100%;box-sizing:border-box" required minlength="2" maxlength="200" value="新用户增量计划"/></div>'
  +'<div class="field"><label for="live-campaign-budget">Budget</label><input id="live-campaign-budget" class="field-value" style="width:100%;box-sizing:border-box" required type="number" min="0" step="1" value="500000"/></div>'
  +'<div class="field"><label for="live-campaign-goal">Goal</label><textarea id="live-campaign-goal" class="field-value multi" style="width:100%;box-sizing:border-box" required minlength="3" maxlength="1000">提高新用户 7 日首购真实增量</textarea></div>'
  +'<div class="field"><label for="live-campaign-audience">Audience</label><textarea id="live-campaign-audience" class="field-value multi" style="width:100%;box-sizing:border-box" required minlength="2" maxlength="500">新用户 0–7 天未首购</textarea></div>'
  +'</div></div>'
  +'<div class="card form-section"><div class="surface-title"><div><h2>Candidate Actions</h2><p>NO_TREATMENT 固定保留；其它动作来自服务端 Action Registry。</p></div></div><div class="token-row">'+(actionInputs||'<span class="soft-badge">No server actions</span>')+'</div></div>'
  +'</div>'
  +'<div class="card evidence-panel"><div class="surface-title"><div><h2>Write Boundary</h2><p>提交只创建 Draft，不执行外部 side effect。</p></div><span class="soft-badge green">Draft only</span></div>'
  +'<div class="evidence-row"><span>Endpoint</span><strong>/api/campaigns/draft</strong></div>'
  +'<div class="evidence-row"><span>NO_TREATMENT</span><strong>Required</strong></div>'
  +'<div class="evidence-row"><span>External execution</span><strong>Disabled</strong></div>'
  +'<button id="live-campaign-submit" class="primary" type="submit" style="width:100%;margin-top:14px">创建 Campaign Draft</button></div>'
  +'</form>';
 bindProductActions();
 const form=$('#live-campaign-form');
 if(form)form.onsubmit=async event=>{
  event.preventDefault();
  const submit=$('#live-campaign-submit');
  if(submit)submit.disabled=true;
  try{
   const selected=Array.from(document.querySelectorAll('[data-live-campaign-action]:checked')).map(input=>input.value).filter(Boolean);
   const candidateIds=[...new Set(['NO_TREATMENT',...selected])];
   const created=await api('/api/campaigns/draft',{
    method:'POST',
    body:JSON.stringify({
     name:$('#live-campaign-name').value.trim(),
     goal:$('#live-campaign-goal').value.trim(),
     audience:$('#live-campaign-audience').value.trim(),
     budget:Number($('#live-campaign-budget').value),
     candidate_action_ids:candidateIds,
    }),
   });
   document.body.dataset.lastCampaignDraft=liveText(created&&created.id,'created');
   state.dashboard=null;
   toast('Campaign Draft '+liveText(created&&created.id)+' 已创建');
   go('campaigns');
  }catch(error){
   toast('Campaign Draft 创建失败：'+(error&&error.message?error.message:'unknown error'));
  }finally{
   if(submit)submit.disabled=false;
  }
 };
};

evidence=async function liveEvidence(){
 if(useDemo)return fixtureEvidencePage();
 const raw=await api('/api/evidence');
 const items=Array.isArray(raw)?raw:[];
 const cards=items.map(item=>{
  const metrics=(Array.isArray(item.metrics)?item.metrics:[]).map(metric=>'<div><span>'+esc(liveText(metric.label))+'</span><strong>'+esc(liveText(metric.value))+'</strong></div>').join('');
  return '<article class="experiment-card"><div class="experiment-head"><div><strong>'+esc(liveText(item.name))+'</strong><div class="evo-source">'+esc(liveText(item.id))+' · '+esc(liveText(item.kind))+'</div></div><span class="soft-badge green">'+esc(liveText(item.winner))+'</span></div>'
   +'<div class="result-box">'+metrics+'</div><p style="font-size:8px;color:#7d8899;word-break:break-all">commit · '+esc(liveText(item.commit))+'</p></article>';
 }).join('');
 $('#view').innerHTML=head('智能与证据','服务端锁定证据集合；结果、候选与 commit 身份从 API 读取。')
  +sectionNav(EVIDENCE_NAV,'evidence')
  +(items.length?'<div class="card surface-card"><div class="surface-title"><div><h2>Locked Evidence</h2><p>当前 API 暴露的可审计证据摘要。</p></div><span class="soft-badge green">Live API</span></div><div class="experiment-list">'+cards+'</div></div>':emptyState('暂无锁定证据','Evidence API 当前没有返回证据集合。'));
 bindProductActions();
};

execution=async function liveExecution(){
 if(useDemo)return fixtureExecutionPage();
 const values=await Promise.all([api('/api/system/runtime'),api('/api/campaigns'),api('/api/approvals')]);
 const runtime=values[0]||{};
 const campaigns=Array.isArray(values[1])?values[1]:[];
 const approvals=Array.isArray(values[2])?values[2]:[];
 const pending=approvals.filter(item=>String(item.status||'pending')==='pending').length;
 const sideEffects=Boolean(runtime.side_effects_enabled);
 const summary='<div class="stat-strip">'
  +'<div class="stat-box"><span>Execution mode</span><strong>'+esc(liveText(runtime.execution_mode))+'</strong><em>Live runtime</em></div>'
  +'<div class="stat-box"><span>External side effects</span><strong>'+(sideEffects?'Enabled':'Disabled')+'</strong><em>'+(sideEffects?'受控执行已启用':'不会发送外部动作')+'</em></div>'
  +'<div class="stat-box"><span>Campaign records</span><strong>'+campaigns.length+'</strong><em>服务端状态</em></div>'
  +'<div class="stat-box"><span>Pending approvals</span><strong>'+pending+'</strong><em>治理边界</em></div>'
  +'</div>';
 const boundary='<div class="card surface-card"><div class="surface-title"><div><h2>Execution Boundary</h2><p>'
  +(sideEffects?'外部执行已启用，仍受 approval / policy gate 约束。':'当前部署明确为 reference-only；Campaign 与审批可写，但不会产生外部营销副作用。')
  +'</p></div><span class="soft-badge '+(sideEffects?'green':'amber')+'">'+(sideEffects?'Side effects enabled':'Reference only')+'</span></div></div>';
 $('#view').innerHTML=head('执行中心','读取当前服务端执行边界；没有启用的外部 side effect 不会被伪装成 Running。')
  +sectionNav(STRATEGY_NAV,'execution')+summary+boundary
  +(campaigns.length?'<div class="card table-card" style="margin-top:10px">'+campaignsTable(campaigns)+'</div>':'');
 bindProductActions();
};

dataCenter=async function liveDataCenter(){
 if(useDemo)return fixtureDataCenterPage();
 const values=await Promise.all([api('/api/system/runtime'),api('/api/decisions/recent?limit=20')]);
 const runtime=values[0]||{};
 const rows=Array.isArray(values[1])?values[1]:[];
 const persistence=runtime.persistence||{};
 const body=rows.map(item=>'<tr><td><code>'+esc(liveText(item.decision_id))+'</code></td><td>'+esc(liveText(item.placement))+'</td><td>'+esc(liveText(item.action_id))+'</td><td>'+esc(liveNumber(item.propensity)===null?'—':Number(item.propensity).toFixed(4))+'</td><td>'+esc(liveText(item.policy_id))+'</td><td>'+esc(liveText(item.evidence_tier))+'</td></tr>').join('');
 $('#view').innerHTML=head('数据中心','当前运行时的数据边界、持久化后端与最近 Decision Log。')
  +'<div class="stat-strip">'
  +'<div class="stat-box"><span>Data mode</span><strong>'+esc(liveText(runtime.data_mode))+'</strong><em>Live runtime</em></div>'
  +'<div class="stat-box"><span>Persistence</span><strong>'+esc(liveText(persistence.backend))+'</strong><em>'+(persistence.active?'active':'inactive')+'</em></div>'
  +'<div class="stat-box"><span>Recent decisions</span><strong>'+rows.length+'</strong><em>最多 20 条</em></div>'
  +'<div class="stat-box"><span>Environment</span><strong>'+esc(liveText(runtime.environment))+'</strong><em>'+esc(liveText(runtime.mode))+'</em></div>'
  +'</div>'
  +'<div class="card surface-card table-scroll"><div class="surface-title"><div><h2>Recent Decision Log</h2><p>来自 /api/decisions/recent，不使用浏览器 fixture。</p></div><span class="soft-badge green">Live API</span></div>'
  +(rows.length?'<table class="log-table"><thead><tr><th>ID</th><th>Placement</th><th>Action</th><th>Propensity</th><th>Policy</th><th>Evidence</th></tr></thead><tbody>'+body+'</tbody></table>':'<p style="font-size:10px;color:#7d8899">当前服务端尚无决策记录。</p>')
  +'</div>';
 bindProductActions();
};

integrations=async function liveIntegrations(){
 if(useDemo)return fixtureIntegrationsPage();
 const raw=await api('/api/system/connectors');
 const items=Array.isArray(raw)?raw:[];
 const cards=items.map(item=>'<div class="connector"><div class="connector-logo">'+esc(liveText(item.id).slice(0,2).toUpperCase())+'</div><div><strong>'+esc(liveText(item.label))+'</strong><span>'+esc(liveText(item.id))+' · '+esc(liveText(item.state))+'</span></div><i style="background:'+(item.state==='connected'?'#0db17d':item.state==='error'?'#d64545':'#c7ced9')+'"></i></div>').join('');
 $('#view').innerHTML=head('集成与渠道','当前服务端 Connector Registry 与真实激活状态。')
  +'<div class="card surface-card"><div class="surface-title"><div><h2>Runtime Connector Registry</h2><p>状态来自 /api/system/connectors。</p></div><span class="soft-badge green">Live API</span></div><div class="connector-grid">'+cards+'</div></div>';
 bindProductActions();
};

settings=async function liveSettings(){
 if(useDemo)return fixtureSettingsPage();
 const runtime=await api('/api/system/runtime');
 const persistence=runtime&&runtime.persistence?runtime.persistence:{};
 const authentication=runtime&&runtime.authentication?runtime.authentication:{};
 const llm=runtime&&runtime.llm?runtime.llm:{};
 $('#view').innerHTML=head('设置','当前 Workspace 的公开安全运行配置；不展示密钥、token 或私有端点。')
  +'<div class="workbench-grid">'
  +'<div class="card surface-card"><div class="surface-title"><div><h2>Runtime Configuration</h2><p>来自 /api/system/runtime。</p></div><span class="soft-badge green">Live API</span></div>'
  +'<div class="evidence-row"><span>Mode</span><strong>'+esc(liveText(runtime&&runtime.mode))+'</strong></div>'
  +'<div class="evidence-row"><span>Environment</span><strong>'+esc(liveText(runtime&&runtime.environment))+'</strong></div>'
  +'<div class="evidence-row"><span>Ready</span><strong>'+(runtime&&runtime.ready?'Yes':'No')+'</strong></div>'
  +'<div class="evidence-row"><span>Execution</span><strong>'+esc(liveText(runtime&&runtime.execution_mode))+'</strong></div>'
  +'<div class="evidence-row"><span>Side effects</span><strong>'+(runtime&&runtime.side_effects_enabled?'Enabled':'Disabled')+'</strong></div></div>'
  +'<div class="card surface-card"><div class="surface-title"><div><h2>Boundaries</h2><p>只显示公开安全状态。</p></div></div>'
  +'<div class="evidence-row"><span>Persistence</span><strong>'+esc(liveText(persistence.backend))+' · '+(persistence.active?'active':'inactive')+'</strong></div>'
  +'<div class="evidence-row"><span>Authentication</span><strong>'+esc(liveText(authentication.backend))+' · '+(authentication.active?'active':'inactive')+'</strong></div>'
  +'<div class="evidence-row"><span>LLM routes</span><strong>'+esc(liveText(llm.available_routes,0))+' / '+esc(liveText(llm.route_count,0))+'</strong></div>'
  +'<div class="evidence-row"><span>Agent planning</span><strong>'+(llm.agent_planning?'active':'safe fallback')+'</strong></div></div>'
  +'</div>';
 bindProductActions();
};
