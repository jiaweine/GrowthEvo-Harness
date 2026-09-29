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
 const raw=await api('/api/v1/opportunities');
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
 const rows=await api('/api/v1/experiments');
 const items=Array.isArray(rows)?rows:[];
 $('#view').innerHTML=`${head('实验中心','服务端 Experiment contract：assignment、variants、metric、maturity、guardrail 与 uncertainty 分离。')}${sectionNav(STRATEGY_NAV,'experiments')}${items.length?`<div class="experiment-grid"><div class="card surface-card"><div class="surface-title"><div><h2>Experiments</h2><p>当前 API 返回的实验状态。</p></div><span class="soft-badge green">Live API</span></div><div class="experiment-list">${items.map(x=>`<div class="experiment-card"><div class="experiment-head"><div><strong>${esc(liveText(x.name))}</strong><div class="evo-source">${esc(liveText(x.id))} · ${esc(liveText(x.assignment))}</div></div>${liveBadge(x.status)}</div><div class="experiment-meta"><div><span>Primary metric</span><strong>${esc(liveText(x.primary_metric))}</strong></div><div><span>Allocation</span><strong>${esc(liveText(x.allocation))}</strong></div><div><span>Maturity</span><strong>${esc(liveText(x.maturity))}</strong></div><div><span>Variants</span><strong>${esc(Array.isArray(x.variants)?x.variants.join(' / '):liveText(x.variants))}</strong></div></div><div class="result-box"><div><span>Estimate</span><strong class="value-positive">${esc(liveText(x.estimate))}</strong></div><div><span>Uncertainty</span><strong>${esc(liveText(x.ci))}</strong></div><div><span>Guardrails</span><strong>${esc(Array.isArray(x.guardrails)?x.guardrails.join(', '):liveText(x.guardrails))}</strong></div></div><p style="font-size:8px;color:#7d8899;line-height:1.5">${esc(liveText(x.hypothesis))}</p></div>`).join('')}</div></div></div>`:emptyState('暂无实验','Experiment API 当前没有返回实验。')}`;
 bindProductActions();
};

async function runReferenceDecision(){
 const button=$('#run-reference-decision');if(button)button.disabled=true;
 try{
  const suffix=`${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const result=await api('/api/v1/decide',{
   method:'POST',
   headers:{'Idempotency-Key':`ui-reference-${suffix}`},
   body:JSON.stringify({
    entity_id:`ui_reference_${suffix}`,
    placement:'decision_console',
    context:{cart_value:198,session_intent:'high',new_user:true},
    candidate_action_ids:['NO_TREATMENT','free_shipping_v3'],
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
 const [actions,logs]=await Promise.all([api('/api/v1/actions'),api('/api/v1/decisions/recent?limit=50')]);
 const registry=Array.isArray(actions)?actions:[];const recent=Array.isArray(logs)?logs:[];
 $('#view').innerHTML=`${head('实时决策','当前 Reference Decision API 的真实 registry、propensity 与 Decision Log。它验证决策契约，不宣称因果最优。','<button class="primary" id="run-reference-decision">运行安全示例决策</button>')}${sectionNav(EVIDENCE_NAV,'realtime')}<div class="page-grid"><div class="card surface-card span-4"><div class="surface-title"><div><h2>Action Registry</h2><p>NO_TREATMENT 始终是一等动作。</p></div><span class="soft-badge green">Live API</span></div>${registry.map(x=>`<div class="evidence-row"><span>${esc(liveText(x.label))}<br><small>${esc(liveText(x.action_id))}</small></span><strong>${esc(liveText(x.risk_level))} · ${liveMoney(x.cost)}</strong></div>`).join('')}</div><div class="card surface-card span-8 table-scroll"><div class="surface-title"><div><h2>Decision Log</h2><p>记录 policy version、真实 assignment propensity 与 guardrail fallback。</p></div></div>${recent.length?`<table class="log-table"><thead><tr><th>ID</th><th>Placement</th><th>Action</th><th>Propensity</th><th>Policy</th><th>Evidence</th><th>Mode</th></tr></thead><tbody>${recent.map(x=>`<tr><td><code>${esc(liveText(x.decision_id))}</code></td><td>${esc(liveText(x.placement))}</td><td>${esc(liveText(x.action_id))}</td><td>${esc(liveNumber(x.propensity)===null?'—':Number(x.propensity).toFixed(4))}</td><td>${esc(liveText(x.policy_version))}</td><td>${esc(liveText(x.evidence_tier))}</td><td>${esc(liveText(x.policy_randomization))}</td></tr>`).join('')}</tbody></table>`:'<p style="font-size:10px;color:#7d8899">尚无本进程决策记录。可运行一个无外部副作用的 reference decision。</p>'}</div></div>`;
 bindProductActions();const run=$('#run-reference-decision');if(run)run.onclick=runReferenceDecision;
};

harness=async function liveHarness(){
 if(useDemo)return fixtureHarnessPage();
 const rows=await api('/api/v1/harness/runs');const items=Array.isArray(rows)?rows:[];
 $('#view').innerHTML=`${head('Agent Runtime','服务端 Harness Run API：版本、工具调用、策略结果、证据与成本可审计。')}${sectionNav(RUNTIME_NAV,'harness')}${items.length?`<div class="card surface-card table-scroll"><div class="surface-title"><div><h2>Harness Runs</h2><p>当前 reference run history。</p></div><span class="soft-badge green">Live API</span></div><table class="opportunity-table"><thead><tr><th>Run</th><th>Task</th><th>Agent</th><th>Harness</th><th>Policy</th><th>Evidence</th><th>Tools</th><th>Latency</th><th>Outcome</th></tr></thead><tbody>${items.map(x=>`<tr><td><code>${esc(liveText(x.id))}</code></td><td>${esc(liveText(x.task))}</td><td>${esc(liveText(x.agent_version))}</td><td>${esc(liveText(x.harness_version))}</td><td>${esc(liveText(x.policy))}</td><td>${esc(liveText(x.evidence))}</td><td>${esc(liveText(x.tool_calls))}</td><td>${esc(liveText(x.latency_ms))} ms</td><td>${esc(liveText(x.outcome))}</td></tr>`).join('')}</tbody></table></div>`:emptyState('暂无 Harness Run','Harness API 当前没有返回 run。')}`;
 bindProductActions();
};

function approvalActionLabel(decision){return ({approve_shadow:'批准 Shadow',approve_1:'批准 1%',approve_5:'批准 5%',approve_25:'批准 25%',reject:'拒绝',return:'退回'})[decision]||decision}
async function submitApprovalDecision(id,decision){
 try{
  await api(`/api/v1/approvals/${encodeURIComponent(id)}/decision`,{method:'POST',body:JSON.stringify({decision,note:`Reviewed from GrowthEvo Web: ${approvalActionLabel(decision)}`})});
  toast(`${id} · ${approvalActionLabel(decision)}`);await approvals();
 }catch(error){toast(`审批未提交：${error&&error.message?error.message:'unknown error'}`)}
}

approvals=async function liveApprovals(){
 if(useDemo)return fixtureApprovalsPage();
 const rows=await api('/api/v1/approvals');const items=Array.isArray(rows)?rows:[];
 $('#view').innerHTML=`${head('治理与审批','当前服务端审批状态。已完成的审批不能被不同的二次决策覆盖。')}${sectionNav(RUNTIME_NAV,'approvals')}${items.length?`<div class="approval-list">${items.map(x=>{const pending=x.status==='pending';return `<div class="card approval-wide"><div class="approval-summary"><div class="approval-name"><strong>${esc(liveText(x.title))}</strong><p>${esc(liveText(x.id))} · ${esc(liveText(x.campaign))}</p></div><div class="approval-kv"><span>影响用户</span><strong>${esc(liveText(x.affected_users))}</strong></div><div class="approval-kv"><span>预算</span><strong>${liveMoney(x.budget)}</strong></div><div class="approval-kv"><span>最大风险</span><strong>${esc(liveText(x.max_risk))}</strong></div><div class="approval-kv"><span>预计增量价值</span><strong class="value-positive">${liveMoney(x.incremental_value)}</strong></div></div><div class="change-box"><strong>Evidence：</strong> Tier ${esc(liveText(x.evidence_tier))}　·　<strong>不确定性：</strong> ${esc(liveText(x.uncertainty))}　·　<strong>状态：</strong> ${esc(liveText(x.status))}</div><div class="version-row"><span class="version-pill">Agent ${esc(liveText(x.agent_version))}</span><span class="version-pill">Harness ${esc(liveText(x.harness_version))}</span><span class="version-pill">Policy ${esc(liveText(x.policy_version))}</span></div>${pending?`<div class="approval-buttons"><button data-approval="${esc(x.id)}" data-decision="return">退回</button><button class="danger" data-approval="${esc(x.id)}" data-decision="reject">拒绝</button><button data-approval="${esc(x.id)}" data-decision="approve_shadow">Shadow</button><button data-approval="${esc(x.id)}" data-decision="approve_1">1%</button><button class="canary" data-approval="${esc(x.id)}" data-decision="approve_5">5%</button></div>`:'<div class="surface-badges"><span class="soft-badge green">Finalized · server state</span></div>'}</div>`}).join('')}</div>`:emptyState('暂无待审批记录','Approval API 当前没有返回记录。')}`;
 bindProductActions();$$('[data-approval][data-decision]').forEach(button=>button.onclick=()=>submitApprovalDecision(button.dataset.approval,button.dataset.decision));
};

evolution=async function liveEvolution(){
 if(useDemo)return fixtureEvolutionPage();
 const rows=await api('/api/v1/evolution/candidates');const items=Array.isArray(rows)?rows:[];
 $('#view').innerHTML=`${head('Evolution Lab','服务端 Evolution candidates：候选改进必须沿 Replay → Eval → Shadow → Canary → Promote 边界演进。')}${sectionNav(RUNTIME_NAV,'evolution')}${items.length?`<div class="evolution-list">${items.map(x=>`<div class="card evo-card"><div class="evo-head"><div><strong>${esc(liveText(x.id))}</strong><div class="evo-source">Source runs: ${esc(liveText(x.source_runs))}</div></div>${liveBadge(x.status)}</div><div class="evo-problem"><strong>问题</strong><br>${esc(liveText(x.problem))}<br><br><strong>候选改进</strong><br>${esc(liveText(x.candidate))}</div><div class="eval-grid">${Object.entries(x.offline_replay||{}).map(([key,value])=>`<div class="eval-cell"><span>${esc(key)}</span><strong>${esc(liveText(value))}</strong></div>`).join('')}</div><div class="promotion-line"><div class="promotion-stage done">Offline Replay</div><span class="promotion-arrow">→</span><div class="promotion-stage done">Eval</div><span class="promotion-arrow">→</span><div class="promotion-stage ${x.shadow==='PASS'?'done':''}">Shadow</div><span class="promotion-arrow">→</span><div class="promotion-stage active">Canary Gate</div><span class="promotion-arrow">→</span><div class="promotion-stage">Promote</div></div></div>`).join('')}</div>`:emptyState('暂无进化候选','Evolution API 当前没有返回 candidate。')}`;
 bindProductActions();
};
