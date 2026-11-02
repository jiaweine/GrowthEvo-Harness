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

function liveText(value,fallback='—'){return value===null||value===undefined||value===''?fallback:productLabel(value)}
function liveNumber(value){const n=Number(value);return Number.isFinite(n)?n:null}
function liveMoney(value){const n=liveNumber(value);return n===null?'—':`¥${fmt(n)}`}
function liveBadge(value){return `<span class="soft-badge">${esc(liveText(value))}</span>`}
function emptyState(title,detail){return `<div class="card surface-card"><div class="surface-title"><div><h2>${esc(title)}</h2><p>${esc(detail)}</p></div></div></div>`}

opportunities=async function liveOpportunities(){
 if(useDemo)return fixtureOpportunitiesPage();
 const raw=await api('/api/opportunities');
 const rows=(Array.isArray(raw)?raw:[]).map(x=>({
  segment:liveText(x.segment),
  kind:'工作区机会',
  population:liveNumber(x.population)||0,
  natural:(liveNumber(x.natural_conversion)||0)*100,
  best_action:liveText(x.best_action),
  incremental_lift_pp:liveNumber(x.incremental_lift_pp)||0,
  incremental_value:liveNumber(x.incremental_value)||0,
  support:Math.max(0,Math.min(1,liveNumber(x.support)||0)),
  evidence_tier:liveText(x.evidence_tier),
  freshness:liveText(x.freshness),
 }));
 $('#view').innerHTML=`${head('增长机会地图','查看当前工作区的增长机会、增量效果与证据。','<button class="primary" data-go="campaignStudio">基于机会创建活动</button>')}${sectionNav(EVIDENCE_NAV,'opportunities')}${rows.length?`<div class="card surface-card table-scroll"><div class="surface-title"><div><h2>当前机会</h2><p>综合人群规模、增量提升、支持度和证据评估机会。</p></div><span class="soft-badge green">实时数据</span></div>${opportunityTable(rows)}</div>`:emptyState('暂无机会','当前工作区没有可展示的机会。')}`;
 bindProductActions();
};

experiments=async function liveExperiments(){
 if(useDemo)return fixtureExperimentsPage();
 const rows=await api('/api/experiments');
 const items=Array.isArray(rows)?rows:[];
 $('#view').innerHTML=`${head('实验中心','查看实验分组、主要指标、成熟度、保护指标和结果的不确定性。')}${sectionNav(STRATEGY_NAV,'experiments')}${items.length?`<div class="experiment-grid"><div class="card surface-card"><div class="surface-title"><div><h2>实验列表</h2><p>当前 API 返回的实验状态。</p></div><span class="soft-badge green">实时数据</span></div><div class="experiment-list">${items.map(x=>`<div class="experiment-card"><div class="experiment-head"><div><strong>${esc(liveText(x.name))}</strong><div class="evo-source">${esc(liveText(x.id))} · ${esc(liveText(x.assignment))}</div></div>${liveBadge(x.status)}</div><div class="experiment-meta"><div><span>主要指标</span><strong>${esc(liveText(x.primary_metric))}</strong></div><div><span>分配比例</span><strong>${esc(liveText(x.allocation))}</strong></div><div><span>成熟度</span><strong>${esc(liveText(x.maturity))}</strong></div><div><span>实验分组</span><strong>${esc(Array.isArray(x.variants)?x.variants.join(' / '):liveText(x.variants))}</strong></div></div><div class="result-box"><div><span>估计结果</span><strong class="value-positive">${esc(liveText(x.estimate))}</strong></div><div><span>不确定性</span><strong>${esc(liveText(x.ci))}</strong></div><div><span>保护指标</span><strong>${esc(Array.isArray(x.guardrails)?x.guardrails.join(', '):liveText(x.guardrails))}</strong></div></div><p style="font-size:8px;color:#7d8899;line-height:1.5">${esc(liveText(x.hypothesis))}</p></div>`).join('')}</div></div></div>`:emptyState('暂无实验','当前工作区没有实验记录。')}`;
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
  toast(`示例决策： ${result.action_id} · p=${Number(result.propensity).toFixed(3)}`);
  await realtime();
 }catch(error){toast(`决策失败： ${error&&error.message?error.message:'未知原因'}`)}finally{if(button)button.disabled=false}
}

realtime=async function liveRealtime(){
 if(useDemo)return fixtureRealtimePage();
 const [actions,logs]=await Promise.all([api('/api/actions'),api('/api/decisions/recent?limit=50')]);
 const registry=Array.isArray(actions)?actions:[];const recent=Array.isArray(logs)?logs:[];
 $('#view').innerHTML=`${head('实时决策','查看当前动作目录、分配概率与决策记录；示例决策仅验证操作流程。','<button class="primary" id="run-reference-decision">运行安全示例决策</button>')}${sectionNav(EVIDENCE_NAV,'realtime')}<div class="page-grid"><div class="card surface-card span-4"><div class="surface-title"><div><h2>可用动作</h2><p>始终保留“不触达”作为备选动作。</p></div><span class="soft-badge green">实时数据</span></div>${registry.map(x=>`<div class="evidence-row"><span>${esc(liveText(x.label))}<br><small>${esc(liveText(x.action_id))}</small></span><strong>${esc(liveText(x.risk_level))} · ${liveMoney(x.cost)}</strong></div>`).join('')}</div><div class="card surface-card span-8 table-scroll"><div class="surface-title"><div><h2>决策记录</h2><p>记录策略身份、实际分配概率与安全回退。</p></div></div>${recent.length?`<table class="log-table"><thead><tr><th>ID</th><th>展示位置</th><th>动作</th><th>分配概率</th><th>策略</th><th>证据</th><th>模式</th></tr></thead><tbody>${recent.map(x=>`<tr><td><code>${esc(liveText(x.decision_id))}</code></td><td>${esc(liveText(x.placement))}</td><td>${esc(liveText(x.action_id))}</td><td>${esc(liveNumber(x.propensity)===null?'—':Number(x.propensity).toFixed(4))}</td><td>${esc(liveText(x.policy_id))}</td><td>${esc(liveText(x.evidence_tier))}</td><td>${esc(liveText(x.policy_randomization))}</td></tr>`).join('')}</tbody></table>`:'<p style="font-size:10px;color:#7d8899">尚无本进程决策记录。可运行一个无外部副作用的 示例决策。</p>'}</div></div>`;
 bindProductActions();const run=$('#run-reference-decision');if(run)run.onclick=runReferenceDecision;
};

harness=async function liveHarness(){
  if(useDemo)return fixtureHarnessPage();
  const raw=await api('/api/harness/runs');
  const runs=Array.isArray(raw)?raw:[];
  const body=runs.map(run=>{
    const steps=Array.isArray(run.steps)?run.steps:[];
    const names=steps.map(step=>(AGENT_TOOL_LABELS[step.tool]||'受控操作')+'：'+(AGENT_OUTCOME_LABELS[step.outcome]||'已记录')).join(' · ');
    return '<tr><td><code>'+esc(liveText(run.run_id))+'</code></td>'
      +'<td>'+esc(AGENT_STATUS_LABELS[run.status]||'未知状态')+'</td>'
      +'<td>'+esc(liveText(run.tool_calls,0))+'</td>'
      +'<td>'+esc(liveText(run.policy_fingerprint))+'</td>'
      +'<td>'+esc(names||'没有执行工具')+'</td></tr>';
  }).join('');
  $('#view').innerHTML=head('执行轨迹','真实运行轨迹：工具、结果和演进策略指纹。记录仅保留在当前服务进程，重启后会清空。')
    +sectionNav(RUNTIME_NAV,'harness')
    +(runs.length?'<div class="card surface-card table-scroll"><table class="opportunity-table">'
      +'<thead><tr><th>运行编号</th><th>状态</th><th>工具次数</th><th>策略指纹</th><th>已执行操作</th></tr></thead>'
      +'<tbody>'+body+'</tbody></table></div>'
      :emptyState('还没有真实运行记录','在执行模式中输入目标，完成运行后这里会记录实际结果。'));
  bindProductActions();
};

function approvalActionLabel(decision){return ({approve_shadow:'批准影子验证',approve_1:'批准 1%',approve_5:'批准 5%',approve_25:'批准 25%',reject:'拒绝',return:'退回'})[decision]||decision}
async function submitApprovalDecision(id,decision){
 try{
  await api(`/api/approvals/${encodeURIComponent(id)}/decision`,{method:'POST',body:JSON.stringify({decision,note:`Reviewed from GrowthEvo Web: ${approvalActionLabel(decision)}`})});
  toast(`${id} · ${approvalActionLabel(decision)}`);await approvals();
 }catch(error){toast(`审批未提交：${error&&error.message?error.message:'未知原因'}`)}
}

approvals=async function liveApprovals(){
 if(useDemo)return fixtureApprovalsPage();
 const rows=await api('/api/approvals');const items=Array.isArray(rows)?rows:[];
 $('#view').innerHTML=`${head('治理与审批','当前服务端审批状态。已完成的审批不能被不同的二次决策覆盖。')}${sectionNav(RUNTIME_NAV,'approvals')}${items.length?`<div class="approval-list">${items.map(x=>{const pending=x.status==='pending';return `<div class="card approval-wide"><div class="approval-summary"><div class="approval-name"><strong>${esc(liveText(x.title))}</strong><p>${esc(liveText(x.id))} · ${esc(liveText(x.campaign))}</p></div><div class="approval-kv"><span>影响用户</span><strong>${esc(liveText(x.affected_users))}</strong></div><div class="approval-kv"><span>预算</span><strong>${liveMoney(x.budget)}</strong></div><div class="approval-kv"><span>最大风险</span><strong>${esc(liveText(x.max_risk))}</strong></div><div class="approval-kv"><span>预计增量价值</span><strong class="value-positive">${liveMoney(x.incremental_value)}</strong></div></div><div class="change-box"><strong>证据：</strong> 等级 ${esc(liveText(x.evidence_tier))}　·　<strong>不确定性：</strong> ${esc(liveText(x.uncertainty))}　·　<strong>状态：</strong> ${esc(liveText(x.status))}</div><div class="version-row"><span class="version-pill">Agent ${esc(liveText(x.agent_id))}</span><span class="version-pill">Harness ${esc(liveText(x.harness_id))}</span><span class="version-pill">Policy ${esc(liveText(x.policy_id))}</span></div>${pending?`<div class="approval-buttons"><button data-approval="${esc(x.id)}" data-decision="return">退回</button><button class="danger" data-approval="${esc(x.id)}" data-decision="reject">拒绝</button><button data-approval="${esc(x.id)}" data-decision="approve_shadow">影子验证</button><button data-approval="${esc(x.id)}" data-decision="approve_1">1%</button><button class="canary" data-approval="${esc(x.id)}" data-decision="approve_5">5%</button></div>`:'<div class="surface-badges"><span class="soft-badge green">已处理 · 服务端状态</span></div>'}</div>`}).join('')}</div>`:emptyState('暂无待审批记录','当前工作区没有待审批记录。')}`;
 bindProductActions();$$('[data-approval][data-decision]').forEach(button=>button.onclick=()=>submitApprovalDecision(button.dataset.approval,button.dataset.decision));
};

const EVOLUTION_STATUS_LABELS={
  requires_independent_eval:'等待独立评测',
  evaluating:'独立评测中',
  awaiting_shadow_canary:'等待灰度验证与人工批准',
  rejected_by_eval:'评测未通过',
  stale_evaluation:'候选证据已过期',
  promoted:'已批准采用'
};
const EVOLUTION_REASON_LABELS={
  'Repeated real operator step-limit failures':'多次真实任务达到操作步数上限',
  'Frequent first-read pattern among model-finished runs (task success unverified)':'已结束任务呈现稳定的优先读取模式（尚未验证任务成功率）'
};
function evolutionCandidateSummary(item){
  const proposal=item.proposal||{};
  const step=Number(proposal.step_budget);
  const preference=String(proposal.preferred_first_read||'none');
  const preferenceNames={none:'无',opportunities:'增长机会',evidence:'证据中心',campaigns:'活动'};
  return '操作步数 '+(Number.isFinite(step)?step:'—')+' · 优先读取 '+(preferenceNames[preference]||'其他受控模块');
}
evolution=async function liveEvolution(){
  if(useDemo)return fixtureEvolutionPage();
  const [raw,policy,readiness]=await Promise.all([
    api('/api/evolution/candidates'),api('/api/evolution/policy'),api('/api/evolution/readiness')
  ]);
  const items=Array.isArray(raw)?raw:[];
  const traceCount=Number(readiness.trace_count)||0;
  const policyCard='<div class="card surface-card evo-policy-card"><div class="surface-title"><div>'
    +'<h2>当前操作策略</h2><p>改进从真实智能体操作中产生；未经过独立评测、灰度验证和人工批准，绝不会自动采用。</p></div>'
    +'<span class="soft-badge">进程内状态</span></div>'
    +'<div class="evo-policy-facts"><div><span>当前策略有效轨迹</span><strong>'+traceCount+' / '+(Number(readiness.required_trace_count)||8)+'</strong></div>'
    +'<div><span>待评测候选</span><strong>'+items.filter(x=>x.status==='requires_independent_eval').length+'</strong></div>'
    +'<div><span>已采用候选</span><strong>'+items.filter(x=>x.status==='promoted').length+'</strong></div></div>'
    +'<p class="evo-policy-note">当前步数预算：'+esc(liveText(policy.step_budget))
    +' · 策略指纹：<code>'+esc(liveText(policy.fingerprint))+'</code></p></div>';
  const cards=items.map(item=>'<article class="card evo-card">'
    +'<div class="evo-head"><div><strong>改进候选 · '+esc(liveText(item.id))+'</strong>'
    +'<p class="evo-source">参考实际轨迹 '+esc(liveText(item.source_count))+' 条</p></div>'
    +'<span class="soft-badge">'+esc(EVOLUTION_STATUS_LABELS[item.status]||'等待人工核实')+'</span></div>'
    +'<div class="evo-problem"><strong>为什么建议改进？</strong><p>'+esc(EVOLUTION_REASON_LABELS[item.reason]||liveText(item.reason))+'</p>'
    +'<strong>建议调整</strong><p>'+esc(evolutionCandidateSummary(item))+'</p>'
    +'<strong>验证状态</strong><p>'+(item.evaluation
      ?'已完成离线工具与路由契约评测。页面实际操作、线上效果和灰度验证仍须另外核验。'
      :'尚未完成独立评测，没有经过验证的性能提升。')+'</p></div>'
    +(item.evaluation?'<div class="eval-grid">'
      +'<div class="eval-cell"><span>基线任务通过率</span><strong>'+Math.round(item.evaluation.baseline_success*100)+'%</strong></div>'
      +'<div class="eval-cell"><span>候选任务通过率</span><strong>'+Math.round(item.evaluation.candidate_success*100)+'%</strong></div>'
      +'<div class="eval-cell"><span>独立任务数</span><strong>'+esc(item.evaluation.sample_size)+'</strong></div>'
      +'<div class="eval-cell"><span>候选规则违反率</span><strong>'+Math.round(item.evaluation.candidate_violations*100)+'%</strong></div>'
      +'</div><p class="evo-policy-note">离线证据：<code>'+esc(item.evaluation.evidence_id)+'</code></p>':'')
    +'<div class="evo-path"><span class="done">真实运行</span><b>→</b><span class="done">提出候选</span><b>→</b>'
    +'<span'+(item.evaluation?' class="done"':'')+'>独立评测</span><b>→</b><span>灰度与审批</span><b>→</b><span>采用</span></div>'
    +(item.status==='requires_independent_eval'?'<div class="evo-action-row"><button class="secondary" type="button" data-evaluate-candidate="'+esc(item.id)+'" '
      +(readiness.evaluation_available&&item.parent===policy.fingerprint?'':'disabled')+'>运行独立离线评测</button></div>':'')
    +'</article>').join('');
  const action='<div class="card surface-card evo-analyze">'
    +'<div class="surface-title"><div><h2>从真实运行中发现改进</h2>'
    +'<p>仅分析当前策略的实际记录，重复运行编号不计数。数据不足时不会填入样例候选。</p>'
    +'</div></div><div class="evo-action-row"><button class="primary" id="evolution-analyze" type="button">分析真实运行轨迹</button>'
    +'<button class="secondary" data-go="harness" type="button">查看运行记录</button>'
    +'<button class="secondary" id="evolution-refresh" type="button">刷新验证进度</button></div>'
    +'<p class="evo-policy-note">'+(readiness.evaluation_available
      ?'独立离线评测已配置 · '+esc(readiness.evaluation_suite)+'。评测使用锁定快照，可能需要数分钟。'
      :'独立评测未配置。需由部署者接入锁定的离线任务集后才能运行；当前不会生成评测成绩。')+'</p>'
    +'<p id="evolution-analysis-result" class="evo-policy-note" role="status" aria-live="polite">候选发现和已配置的独立评测可在此发起；采用策略仍需灰度验证和人工批准。</p></div>';
  $('#view').innerHTML=head('自进化中心','查看智能体的真实运行、改进候选与验证进展。')
    +sectionNav(RUNTIME_NAV,'evolution')+policyCard+action
    +(items.length?'<div class="evolution-list">'+cards+'</div>'
      :emptyState('尚无真实改进候选','需要积累足够的智能体执行轨迹，并发现可改进的模式。'));
  bindProductActions();
  $('#evolution-refresh').onclick=()=>evolution();
  $$('[data-evaluate-candidate]').forEach(button=>button.onclick=async()=>{
    button.disabled=true;
    button.textContent='独立离线评测中…';
    try{
      await api('/api/evolution/candidates/'+encodeURIComponent(button.dataset.evaluateCandidate)+'/evaluate',{
        method:'POST',timeoutMs:330000
      });
      if(state.route==='evolution')await evolution();
      toast('离线评测已记录，尚未采用候选策略');
    }catch(error){
      if(state.route==='evolution')await evolution();
      toast(error?.status===503?'评测未完成，请检查配置或稍后重试':'评测请求未完成，请刷新候选状态');
    }
  });
  const trigger=$('#evolution-analyze');
  if(trigger)trigger.onclick=async()=>{
    trigger.disabled=true;
    const result=$('#evolution-analysis-result');
    if(result)result.textContent='正在检查本进程真实运行记录…';
    try{
      const analyzed=await api('/api/evolution/analyze',{method:'POST'});
      if(state.route!=='evolution')return;
      const message=analyzed.candidate_created
        ?'已从 '+analyzed.trace_count+' 条真实运行中发现候选 '+analyzed.candidate_id+'，等待独立评测。'
        :'本进程目前只有 '+analyzed.trace_count+' 条实际运行记录，或尚无可确认的改进模式；未创建虚假候选。';
      if(result)result.textContent=message;
      if(analyzed.candidate_created){await evolution();toast('已创建待评测的真实改进候选');}
    }catch(error){
      if(result)result.textContent='分析失败，未创建候选。请检查连接或登录状态。';
      toast('分析未完成');
    }finally{if(document.contains(trigger))trigger.disabled=false;}
  };
};

campaigns=async function liveCampaigns(){
 if(useDemo)return fixtureCampaignsPage();
 const raw=await api('/api/campaigns');
 const items=Array.isArray(raw)?raw:[];
 const drafts=items.filter(item=>String(item.status||'').toLowerCase()==='draft').length;
 const nonDraft=items.length-drafts;
 const summary='<div class="stat-strip">'
  +'<div class="stat-box"><span>活动总数</span><strong>'+items.length+'</strong><em>实时接口</em></div>'
  +'<div class="stat-box"><span>草案</span><strong>'+drafts+'</strong><em>等待证据与审批</em></div>'
  +'<div class="stat-box"><span>非草案</span><strong>'+nonDraft+'</strong><em>服务端当前状态</em></div>'
  +'<div class="stat-box"><span>数据来源</span><strong>服务端</strong><em>不使用浏览器样例数据</em></div>'
  +'</div>';
 const content=items.length
  ?'<div class="card table-card"><div class="surface-title"><div><h2>活动列表</h2><p>当前工作区的活动列表。</p></div><span class="soft-badge green">实时数据</span></div>'+campaignsTable(items)+'</div>'
  :emptyState('暂无活动','当前 API 尚未创建活动。');
 $('#view').innerHTML=head('策略与执行','服务端 活动状态：草稿、目标、候选动作与持久化状态来自当前 API。','<button class="primary" data-go="campaignStudio">＋ 新建 活动草案</button>')
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
 $('#view').innerHTML=head('活动设计工作台','创建真实服务端 活动草案。此步骤只写入草稿，不产生外部营销动作。')
  +sectionNav(STRATEGY_NAV,'campaignStudio')
  +'<form id="live-campaign-form" class="studio-shell">'
  +'<div class="studio-canvas">'
  +'<div class="card form-section"><div class="surface-title"><div><h2>活动草案</h2><p>填写目标、受众和预算，提交后保存为活动草案。</p></div><span class="soft-badge green">实时数据</span></div>'
  +'<div class="form-grid">'
  +'<div class="field"><label for="live-campaign-name">活动名称</label><input id="live-campaign-name" class="field-value" style="width:100%;box-sizing:border-box" required minlength="2" maxlength="200" value="新用户增量计划"/></div>'
  +'<div class="field"><label for="live-campaign-budget">预算</label><input id="live-campaign-budget" class="field-value" style="width:100%;box-sizing:border-box" required type="number" min="0" step="1" value="500000"/></div>'
  +'<div class="field"><label for="live-campaign-goal">目标</label><textarea id="live-campaign-goal" class="field-value multi" style="width:100%;box-sizing:border-box" required minlength="3" maxlength="1000">提高新用户 7 日首购真实增量</textarea></div>'
  +'<div class="field"><label for="live-campaign-audience">受众</label><textarea id="live-campaign-audience" class="field-value multi" style="width:100%;box-sizing:border-box" required minlength="2" maxlength="500">新用户 0–7 天未首购</textarea></div>'
  +'</div></div>'
  +'<div class="card form-section"><div class="surface-title"><div><h2>备选动作</h2><p>固定保留“不触达”对照动作，其他选项以当前工作区授权为准。</p></div></div><div class="token-row">'+(actionInputs||'<span class="soft-badge">没有可用动作</span>')+'</div></div>'
  +'</div>'
  +'<div class="card evidence-panel"><div class="surface-title"><div><h2>写入权限</h2><p>提交只创建草案，不会向外部发送。</p></div><span class="soft-badge green">仅保存草案</span></div>'
  +'<div class="evidence-row"><span>接口</span><strong>/api/campaigns/draft</strong></div>'
  +'<div class="evidence-row"><span>不触达对照</span><strong>必须保留</strong></div>'
  +'<div class="evidence-row"><span>外部执行</span><strong>未启用</strong></div>'
  +'<button id="live-campaign-submit" class="primary" type="submit" style="width:100%;margin-top:14px">创建活动草案</button></div>'
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
   toast('活动草案 '+liveText(created&&created.id)+' 已创建');
   go('campaigns');
  }catch(error){
   toast('活动草案创建失败：'+(error&&error.message?error.message:'未知原因'));
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
   +'<div class="result-box">'+metrics+'</div><p style="font-size:8px;color:#7d8899;word-break:break-all">提交 · '+esc(liveText(item.commit))+'</p></article>';
 }).join('');
 $('#view').innerHTML=head('智能与证据','查看已锁定的证据、候选方案与对应提交。')
  +sectionNav(EVIDENCE_NAV,'evidence')
  +(items.length?'<div class="card surface-card"><div class="surface-title"><div><h2>已锁定证据</h2><p>当前 API 暴露的可审计证据摘要。</p></div><span class="soft-badge green">实时数据</span></div><div class="experiment-list">'+cards+'</div></div>':emptyState('暂无锁定证据','当前工作区没有可展示的证据。'));
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
  +'<div class="stat-box"><span>执行模式</span><strong>'+esc(liveText(runtime.execution_mode))+'</strong><em>当前运行状态</em></div>'
  +'<div class="stat-box"><span>外部执行动作</span><strong>'+(sideEffects?'已启用':'未启用')+'</strong><em>'+(sideEffects?'受控执行已启用':'不会发送外部动作')+'</em></div>'
  +'<div class="stat-box"><span>活动总数</span><strong>'+campaigns.length+'</strong><em>服务端状态</em></div>'
  +'<div class="stat-box"><span>待审批事项</span><strong>'+pending+'</strong><em>治理边界</em></div>'
  +'</div>';
 const boundary='<div class="card surface-card"><div class="surface-title"><div><h2>执行边界</h2><p>'
  +(sideEffects?'外部执行已启用，仍受审批和策略校验约束。':'当前部署仅支持本地验证；活动与审批可写，但不会产生外部营销动作。')
  +'</p></div><span class="soft-badge '+(sideEffects?'green':'amber')+'">'+(sideEffects?'外部动作已启用':'仅本地验证')+'</span></div></div>';
 $('#view').innerHTML=head('执行中心','读取当前服务端执行边界；未启用外部动作时，不会显示为正在执行。')
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
 $('#view').innerHTML=head('数据中心','当前运行时的数据边界、持久化后端与最近决策记录。')
  +'<div class="stat-strip">'
  +'<div class="stat-box"><span>数据模式</span><strong>'+esc(liveText(runtime.data_mode))+'</strong><em>当前运行状态</em></div>'
  +'<div class="stat-box"><span>持久化</span><strong>'+esc(liveText(persistence.backend))+'</strong><em>'+(persistence.active?'已激活':'未激活')+'</em></div>'
  +'<div class="stat-box"><span>近期决策</span><strong>'+rows.length+'</strong><em>最多 20 条</em></div>'
  +'<div class="stat-box"><span>环境</span><strong>'+esc(liveText(runtime.environment))+'</strong><em>'+esc(liveText(runtime.mode))+'</em></div>'
  +'</div>'
  +'<div class="card surface-card table-scroll"><div class="surface-title"><div><h2>近期决策记录</h2><p>来自 /api/decisions/recent，不使用浏览器样例数据。</p></div><span class="soft-badge green">实时数据</span></div>'
  +(rows.length?'<table class="log-table"><thead><tr><th>ID</th><th>展示位置</th><th>动作</th><th>分配概率</th><th>策略</th><th>证据</th></tr></thead><tbody>'+body+'</tbody></table>':'<p style="font-size:10px;color:#7d8899">当前服务端尚无决策记录。</p>')
  +'</div>';
 bindProductActions();
};

integrations=async function liveIntegrations(){
 if(useDemo)return fixtureIntegrationsPage();
 const raw=await api('/api/system/connectors');
 const items=Array.isArray(raw)?raw:[];
 const cards=items.map(item=>'<div class="connector"><div class="connector-logo">'+esc(liveText(item.id).slice(0,2).toUpperCase())+'</div><div><strong>'+esc(liveText(item.label))+'</strong><span>'+esc(liveText(item.id))+' · '+esc(liveText(item.state))+'</span></div><i style="background:'+(item.state==='connected'?'#0db17d':item.state==='error'?'#d64545':'#c7ced9')+'"></i></div>').join('');
 $('#view').innerHTML=head('集成与渠道','查看已注册连接器与实际连接状态。')
  +'<div class="card surface-card"><div class="surface-title"><div><h2>运行连接器</h2><p>状态来自 /api/system/connectors。</p></div><span class="soft-badge green">实时数据</span></div><div class="connector-grid">'+cards+'</div></div>';
 bindProductActions();
};

settings=async function liveSettings(){
 if(useDemo)return fixtureSettingsPage();
 const runtime=await api('/api/system/runtime');
 const persistence=runtime&&runtime.persistence?runtime.persistence:{};
 const authentication=runtime&&runtime.authentication?runtime.authentication:{};
 const llm=runtime&&runtime.llm?runtime.llm:{};
 $('#view').innerHTML=head('设置','查看工作区公开运行配置与安全状态。')
  +'<div class="workbench-grid">'
  +'<div class="card surface-card"><div class="surface-title"><div><h2>运行配置</h2><p>来自 /api/system/runtime。</p></div><span class="soft-badge green">实时数据</span></div>'
  +'<div class="evidence-row"><span>模式</span><strong>'+esc(liveText(runtime&&runtime.mode))+'</strong></div>'
  +'<div class="evidence-row"><span>环境</span><strong>'+esc(liveText(runtime&&runtime.environment))+'</strong></div>'
  +'<div class="evidence-row"><span>就绪状态</span><strong>'+(runtime&&runtime.ready?'是':'否')+'</strong></div>'
  +'<div class="evidence-row"><span>执行</span><strong>'+esc(liveText(runtime&&runtime.execution_mode))+'</strong></div>'
  +'<div class="evidence-row"><span>外部执行动作</span><strong>'+(runtime&&runtime.side_effects_enabled?'已启用':'未启用')+'</strong></div></div>'
  +'<div class="card surface-card"><div class="surface-title"><div><h2>安全边界</h2><p>只显示公开安全状态。</p></div></div>'
  +'<div class="evidence-row"><span>持久化</span><strong>'+esc(liveText(persistence.backend))+' · '+(persistence.active?'已激活':'未激活')+'</strong></div>'
  +'<div class="evidence-row"><span>身份验证</span><strong>'+esc(liveText(authentication.backend))+' · '+(authentication.active?'已激活':'未激活')+'</strong></div>'
  +'<div class="evidence-row"><span>模型路由</span><strong>'+esc(liveText(llm.available_routes,0))+' / '+esc(liveText(llm.route_count,0))+'</strong></div>'
  +'<div class="evidence-row"><span>智能体规划</span><strong>'+(llm.agent_planning?'已激活':'安全回退')+'</strong></div></div>'
  +'</div>';
 bindProductActions();
};
