function sectionNav(items,active){return `<div class="section-nav">${items.map(([r,l])=>`<button class="${r===active?'active':''}" data-go="${r}">${l}</button>`).join('')}</div>`}
const DEMO_DECISION_API_SAMPLE='POST /api/realtime/decision\n\n{\n  "entity_id": "user_28419",\n  "placement": "checkout_banner",\n  "context": {"cart_value": 198, "session_intent": "high"},\n  "candidate_action_ids": ["free_shipping", "NO_TREATMENT"]\n}';

function demoDownloadJson(filename,payload){
 const blob=new Blob([JSON.stringify(payload,null,2)+'\n'],{type:'application/json'});
 const url=URL.createObjectURL(blob);
 const link=document.createElement('a');
 link.href=url;link.download=filename;link.hidden=true;
 document.body.appendChild(link);
 link.click();
 link.remove();
 setTimeout(()=>URL.revokeObjectURL(url),0);
 document.body.dataset.lastDownload=filename;
 toast(filename+' 已导出');
}

async function demoCopyText(text,label){
 let copied=false;
 let clipboardError=null;
 if(navigator.clipboard&&window.isSecureContext){
  try{await navigator.clipboard.writeText(text);copied=true}
  catch(error){clipboardError=error}
 }
 if(!copied){
  const field=document.createElement('textarea');
  field.value=text;field.setAttribute('readonly','');field.style.position='fixed';field.style.opacity='0';
  document.body.appendChild(field);field.select();
  try{copied=Boolean(document.execCommand('copy'))}finally{field.remove()}
 }
 if(copied){
  document.body.dataset.lastCopy=label;
  toast(label+' 已复制');
 }else toast('复制失败：'+(clipboardError&&clipboardError.message?clipboardError.message:'browser denied clipboard access'));
}

function demoApprovalDecision(id,decision){
 const item=(DEMO.approvalsFull||[]).find(row=>row.id===id);
 if(!item)return;
 item.status=decision;
 item.decision_note='Demo workspace interaction';
 item.decided_at=new Date().toISOString();
 document.body.dataset.lastApproval=id+':'+decision;
 approvals();
}

function runDemoAction(button){
 const action=button.dataset.demoAction;
 if(action==='evidence-export')return demoDownloadJson('growthevo-evidence-report.json',{kind:'GrowthEvoDemoEvidenceReport',generated_at:new Date().toISOString(),opportunities:DEMO.opportunityRows,evidence:DEMO.evidence||[]});
 if(action==='trace-export')return demoDownloadJson('growthevo-trace-run-9081.json',{kind:'GrowthEvoDemoTrace',run_id:'RUN-9081',trace:DEMO.traces});
 if(action==='connector-export')return demoDownloadJson('growthevo-connector-registry.json',{kind:'GrowthEvoDemoConnectorRegistry',connectors:DEMO.connectors});
 if(action==='realtime-copy')return void demoCopyText(DEMO_DECISION_API_SAMPLE,'Decision API sample');
 if(action==='save-campaign-draft'){
  const payload={id:'CAM-842',goal:'春节前提升新用户 7 日首购增量',audience:'新用户 0–7 天未首购',budget:500000,candidate_action_ids:['NO_TREATMENT','free_shipping','coupon_10'],saved_at:new Date().toISOString()};
  sessionStorage.setItem('growthevo.demo.campaign-draft.v1',JSON.stringify(payload));
  document.body.dataset.lastDemoSave=payload.id;
  button.textContent='✓ 已保存';
  return toast('活动草案已保存到当前标签页');
 }
 if(action==='create-experiment'){
  const id='EXP-DRAFT-'+String(Date.now()).slice(-6);
  DEMO.experiments.unshift({id,name:'新实验草稿',status:'Draft',unit:'user_id',population:'—',variants:'2 arms',assignment:'50/50',metric:'待配置',guardrail:'待配置',maturity:'未开始',estimate:'—',impact:'—',uncertainty:'—'});
  document.body.dataset.lastExperimentDraft=id;
  return experiments();
 }
 if(action==='preflight'){
  const result=$('#demo-preflight-result');
  const ready=(DEMO.connectors||[]).filter(item=>item.status==='ready').length;
  const total=(DEMO.connectors||[]).length;
  if(result){result.hidden=false;result.textContent='通过 · '+DEMO.executions.length+' 项流程已检查 · '+ready+'/'+total+' 个连接器就绪 · 外部动作仍为演示';}
  document.body.dataset.lastPreflight='pass';
  return toast('预检通过');
 }
 if(action==='approval')return demoApprovalDecision(button.dataset.approvalId,button.dataset.decision);
 if(action==='failure-miner'){
  if(!(DEMO.evolution||[]).some(item=>item.id==='EV-DEMO')){
   DEMO.evolution.unshift({id:'EV-DEMO',source:'演示轨迹分析',problem:'审批前说明缺少明确的影响范围摘要。',candidate:'在申请审批前补充影响范围摘要。',metrics:[['Coverage','+100%'],['Policy Violation','0%'],['Extra latency','+0.4%'],['Cost','+$0.00']],stage:'Offline replay'});
  }
  document.body.dataset.lastFailureMiner='EV-DEMO';
  return evolution();
 }
 if(action==='reject-candidate'){
  const item=(DEMO.evolution||[]).find(row=>row.id===button.dataset.candidateId);
  if(item)item.stage='Rejected';
  document.body.dataset.lastEvolutionDecision=String(button.dataset.candidateId||'')+':rejected';
  return evolution();
 }
 if(action==='deployment-check'){
  const cfg=window.GROWTHEVO_CONFIG||{};
  const target=$('#demo-deployment-result');
  const apiBase=cfg.API_BASE?'configured':'not configured';
  const auth=cfg.AUTH&&cfg.AUTH.ENABLED?'enabled':'disabled';
  const sw='serviceWorker' in navigator?'supported':'unsupported';
  if(target){target.hidden=false;target.textContent='通过 · mode '+String(cfg.MODE||'demo')+' · API '+apiBase+' · auth '+auth+' · service worker '+sw;}
  document.body.dataset.lastDeploymentCheck='pass';
  return toast('部署检查完成');
 }
 if(action==='evidence-detail'){
  if(!useDemo)return go('evidence');
  const item=(DEMO.opportunityRows||[]).find(row=>row.segment===button.dataset.segment);
  if(typeof openUtilityMenu==='function'&&item){
   return openUtilityMenu('证据详情',[
    {label:'Tier '+item.evidence_tier+' · support '+Math.round(item.support*100)+'%',detail:item.confidence||'Evidence snapshot'},
    {label:'查看完整证据工作台',detail:item.best_action,action:()=>go('evidence')},
    {label:'查看实时决策',detail:'始终保留不触达作为备选动作',action:()=>go('realtime')},
   ]);
  }
  return go('evidence');
 }
}

function bindProductActions(){
 $$('[data-go]').forEach(b=>b.onclick=()=>go(b.dataset.go));
 $$('[data-toast]').forEach(b=>b.onclick=()=>toast(b.dataset.toast));
 $$('[data-demo-action]').forEach(b=>b.onclick=event=>{
  if(b.dataset.demoAction==='evidence-detail')event.stopPropagation();
  runDemoAction(b);
 });
 $$('[data-campaign-more]').forEach(b=>b.onclick=event=>{
  event.stopPropagation();
  const route=b.dataset.campaignRoute||'campaignStudio';
  const name=b.dataset.campaignMore||'Campaign';
  if(typeof openUtilityMenu!=='function')return go(route);
  openUtilityMenu(name,[
   {label:'打开工作台',detail:'查看活动与实验状态',action:()=>go(route)},
   {label:'查看证据',detail:'检查增量与支持度',action:()=>go('evidence')},
   {label:'治理与审批',detail:'查看影响范围与审批条件',action:()=>go('approvals')},
  ]);
 });
}
function money(n){return `¥${fmt(n)}`}
function evidenceBadge(t){return `<span class="evidence-dot">${esc(t)}</span>`}
function supportMeter(v){return `<div>${Math.round(v*100)}%</div><div class="support-meter"><i style="width:${Math.round(v*100)}%"></i></div>`}
const STRATEGY_NAV=[['campaigns','策略总览'],['campaignStudio','活动设计工作台'],['experiments','实验中心'],['execution','执行中心']];
const EVIDENCE_NAV=[['evidence','智能总览'],['opportunities','增长机会'],['realtime','实时决策']];
const RUNTIME_NAV=[['harness','执行轨迹'],['approvals','治理与审批'],['evolution','自进化中心']];

async function campaigns(){const d=state.dashboard||DEMO;$('#view').innerHTML=`${head('策略与执行','从增长目标、增长机会到实验、活动与执行的统一工作区。','<button class="primary" data-go="campaignStudio">＋ 新建活动</button><button class="secondary" id="talk-product">◉ 与智能体对话</button>')}${sectionNav(STRATEGY_NAV,'campaigns')}<div class="stat-strip"><div class="stat-box"><span>运行活动</span><strong>6</strong><em>4 个正在创造正增量</em></div><div class="stat-box"><span>活跃实验</span><strong>4</strong><em>1 个达到成熟窗口</em></div><div class="stat-box"><span>小流量验证</span><strong>5%</strong><em class="muted">风险敞口受控</em></div><div class="stat-box"><span>执行成功率</span><strong>99.7%</strong><em>过去 24 小时</em></div></div><div class="card table-card">${campaignsTable(d.campaigns)}</div><div class="page-grid" style="margin-top:10px"><div class="card panel span-8"><div class="panel-head"><h2>策略画布 · 新用户首购提升计划</h2>${pill('5% Canary')}</div><div class="metric-row"><div class="metric-chip"><span>主要指标</span><strong>首购增量</strong></div><div class="metric-chip"><span>对照动作</span><strong>不触达</strong></div><div class="metric-chip"><span>推荐动作</span><strong>首单免邮</strong></div><div class="metric-chip"><span>证据</span><strong>A级</strong></div><div class="metric-chip"><span>支持度</span><strong>91%</strong></div></div></div><div class="card panel span-4"><div class="panel-head"><h2>下一步</h2></div><div class="insight-item"><strong>小流量验证已达到 48 小时</strong><p>增量首购 +8.1pp，退订变化 +0.08pp，预算消耗在计划内。</p><div class="insight-actions"><button class="mini-action primary" data-go="approvals">查看扩量审批</button></div></div></div></div>`;bindProductActions();const talk=$('#talk-product');if(talk)talk.onclick=openAgent}

async function evidence(){const rows=DEMO.opportunityRows;$('#view').innerHTML=`${head('智能与证据','因果机会、证据等级、支持度、策略证据与在线决策统一查看。','<button class="secondary" data-demo-action="evidence-export">导出证据报告</button>')}${sectionNav(EVIDENCE_NAV,'evidence')}<div class="stat-strip"><div class="stat-box"><span>A级增长机会</span><strong>18</strong><em>覆盖 128.4 万用户</em></div><div class="stat-box"><span>不触达建议</span><strong>31.6%</strong><em>避免无效触达</em></div><div class="stat-box"><span>平均支持度</span><strong>88%</strong><em>可执行区域稳定</em></div><div class="stat-box"><span>证据更新时间</span><strong>5m</strong><em class="muted">最近一次重算</em></div></div><div class="workbench-grid"><div class="card surface-card table-scroll"><div class="surface-title"><div><h2>最高价值机会</h2><p>按预计增量价值排序，区分购买意愿与实际增量。</p></div><span class="soft-badge green">证据优先</span></div>${opportunityTable(rows.slice(0,4))}</div><div class="workbench-stack"><div class="card surface-card"><div class="surface-title"><div><h2>证据分布</h2><p>生产执行优先使用 A/B 级证据。</p></div></div><div class="evidence-row"><span>A级 · 随机实验</span><strong>42%</strong></div><div class="evidence-row"><span>B级 · 已记录策略</span><strong>31%</strong></div><div class="evidence-row"><span>C级 · 观测证据</span><strong>19%</strong></div><div class="evidence-row"><span>D级 · 预测结果</span><strong>8%</strong></div></div><div class="card surface-card"><div class="insight-item"><strong>高频浏览人群建议不触达</strong><p>自然转化较高，历史触达对部分用户产生负向增量效果。</p><div class="insight-actions"><button class="mini-action" data-go="opportunities">查看增长机会地图</button><button class="mini-action" data-go="realtime">查看在线策略</button></div></div></div></div></div>`;bindProductActions()}

function opportunityTable(rows){return `<table class="opportunity-table"><thead><tr><th>人群</th><th>人群规模</th><th>自然转化</th><th>推荐动作</th><th>增量提升</th><th>增量价值</th><th>支持度</th><th>证据</th><th></th></tr></thead><tbody>${rows.map(x=>`<tr><td class="segment-cell"><strong>${esc(x.segment)}</strong><span>${esc(x.kind)} · ${esc(x.freshness)}</span></td><td>${fmt(x.population)}</td><td>${x.natural}%</td><td>${esc(x.best_action)}</td><td class="${x.incremental_lift_pp>=0?'value-positive':'negative'}">${x.incremental_lift_pp>=0?'+':''}${x.incremental_lift_pp}pp</td><td class="value-positive">${money(x.incremental_value)}</td><td>${supportMeter(x.support)}</td><td>${evidenceBadge(x.evidence_tier)}</td><td><button class="mini-action" data-demo-action="evidence-detail" data-segment="${esc(x.segment)}">证据</button></td></tr>`).join('')}</tbody></table>`}

function opportunities(){const rows=DEMO.opportunityRows;$('#view').innerHTML=`${head('增长机会地图','结合人群规模、增量提升、成本与支持度，寻找值得验证的增长机会。','<button class="primary" data-go="campaignStudio">让智能体设计方案</button>')}${sectionNav(EVIDENCE_NAV,'opportunities')}<div class="workbench-grid"><div class="workbench-stack"><div class="card surface-card"><div class="surface-title"><div><h2>人群规模 × 增量提升</h2><p>气泡大小代表预计增量价值；不触达也是有效策略。</p></div><div class="surface-badges"><span class="soft-badge">按价值加权</span><span class="soft-badge green">支持度校验</span></div></div><div class="bubble-map"><span class="axis-label y">增量提升 ↑</span><span class="axis-label x">人群规模 →</span><div class="opp-bubble a"><div><strong>+8.4pp</strong>新用户<br>¥1.84m</div></div><div class="opp-bubble b"><div><strong>+4.7pp</strong>沉默会员</div></div><div class="opp-bubble c"><div><strong>+3.9pp</strong>到期会员</div></div><div class="opp-bubble d"><div><strong>-1.8pp</strong>不触达组</div></div></div></div><div class="card surface-card table-scroll">${opportunityTable(rows)}</div></div><div class="workbench-stack"><div class="card surface-card"><div class="surface-title"><div><h2>机会解释</h2><p>选中的人群：新用户 0–7 天未首购。</p></div>${evidenceBadge('A')}</div><div class="evidence-row"><span>自然转化率</span><strong>12.4%</strong></div><div class="evidence-row"><span>推荐动作</span><strong>首单免邮</strong></div><div class="evidence-row"><span>增量提升</span><strong class="value-positive">+8.4pp</strong></div><div class="evidence-row"><span>预计价值</span><strong>¥1,840,000</strong></div><div class="evidence-row"><span>支持度</span><strong>91%</strong></div><div class="evidence-row"><span>不确定性</span><strong>+6.8 ~ +10.1pp</strong></div></div><button class="primary" style="width:100%" data-go="campaignStudio">基于该机会创建活动</button></div></div>`;bindProductActions()}

function campaignStudio(){const steps=[['1','目标与受众','春节前提升首购增量','done'],['2','策略设计','备选动作与对照组','done'],['3','创意内容','候选创意','active'],['4','实验验证','分组与保留组',''],['5','执行准备','小流量 / 批量 / 实时',''],['6','效果证据','离线评估 / 支持度 / 风险','']];$('#view').innerHTML=`${head('活动设计工作台','从目标、受众与证据出发，完成活动设计、实验验证和执行准备。','<button class="secondary" data-demo-action="save-campaign-draft">保存草稿</button><button class="primary" data-go="approvals">提交影子验证</button>')}${sectionNav(STRATEGY_NAV,'campaignStudio')}<div class="studio-shell"><div class="card studio-rail">${steps.map(s=>`<div class="studio-step ${s[3]}"><div class="n">${s[0]}</div><div><strong>${s[1]}</strong><span>${s[2]}</span></div></div>`).join('')}</div><div class="studio-canvas"><div class="card form-section"><div class="surface-title"><div><h2>基础信息</h2><p>把增长目标整理为可审查的活动草案。</p></div><span class="soft-badge gray">草案 CAM-842</span></div><div class="form-grid"><div class="field"><label>目标</label><div class="field-value">春节前提升新用户 7 日首购增量</div></div><div class="field"><label>受众</label><div class="field-value">新用户 0–7 天未首购 · 864,210 人</div></div><div class="field"><label>预算</label><div class="field-value">¥500,000 · 预算上限</div></div><div class="field"><label>时间与渠道</label><div class="field-value">12/20 → 01/31 · 应用推送 / 站内消息</div></div></div></div><div class="card form-section"><div class="surface-title"><div><h2>策略设计</h2><p>保留不触达对照动作，并明确可以验证的业务假设。</p></div><span class="soft-badge green">A级</span></div><div class="field"><label>业务假设</label><div class="field-value multi">假设：为注册 0–7 天仍未首购、且可能受激励影响的用户提供免邮，比统一发券更有效；需要通过实验验证。</div></div><div class="form-grid" style="margin-top:10px"><div class="field"><label>备选动作</label><div class="field-value"><div class="token-row"><span class="token action">首单免邮</span><span class="token action">优惠券</span><span class="token control">不触达</span></div></div></div><div class="field"><label>保护指标</label><div class="field-value">退订 < 0.3% · 单用户 ≤ 2 次/7d · 毛利率 > 24%</div></div></div></div><div class="card form-section"><div class="surface-title"><div><h2>实验与执行</h2><p>先进行影子验证，再进行小流量测试；实际执行遵循既定审批流程。</p></div></div><div class="form-grid"><div class="field"><label>分组方式</label><div class="field-value">40% 免邮 / 30% ¥10 / 30% 不触达</div></div><div class="field"><label>主要指标</label><div class="field-value">7 日增量首购率 · 成熟窗口 7 天</div></div><div class="field"><label>执行</label><div class="field-value">批量锁定受众，按事件检查资格</div></div><div class="field"><label>安全</label><div class="field-value">预检 · 幂等校验 · 预算预留 · 紧急停止</div></div></div></div></div><div class="card evidence-panel"><div class="surface-title"><div><h2>效果证据</h2><p>是否值得执行，由证据和约束决定。</p></div>${evidenceBadge('A')}</div><div class="evidence-row"><span>预期提升</span><strong class="value-positive">+8.4pp</strong></div><div class="evidence-row"><span>预计价值</span><strong>¥1.84m</strong></div><div class="evidence-row"><span>支持度</span><strong>91%</strong></div><div class="evidence-row"><span>离线评估 / 回放</span><strong>通过</strong></div><div class="evidence-row"><span>风险</span><strong>L3 · 受限执行</strong></div><button class="primary" style="width:100%;margin-top:14px" data-go="approvals">提交审批与小流量验证</button></div></div>`;bindProductActions()}

function experiments(){const rows=DEMO.experiments;$('#view').innerHTML=`${head('实验中心','统一管理分组、曝光、指标、保留组、保护指标与证据。','<button class="primary" data-demo-action="create-experiment">＋ 创建实验</button>')}${sectionNav(STRATEGY_NAV,'experiments')}<div class="experiment-grid"><div class="card surface-card"><div class="surface-title"><div><h2>实验列表</h2><p>查看对照实验、保留组、序贯验证、小流量测试和方案对比。</p></div><span class="soft-badge green">证据优先</span></div><div class="experiment-list">${rows.map(x=>`<div class="experiment-card"><div class="experiment-head"><div><strong>${esc(x.name)}</strong><div class="evo-source">${x.id} · Assignment unit: ${x.unit}</div></div><span class="soft-badge ${x.status==='Matured'?'green':x.status.includes('Canary')?'amber':''}">${x.status}</span></div><div class="experiment-meta"><div><span>人群规模</span><strong>${x.population}</strong></div><div><span>实验分组</span><strong>${x.variants}</strong></div><div><span>分组方式</span><strong>${x.assignment}</strong></div><div><span>成熟度</span><strong>${x.maturity}</strong></div></div><div class="result-box"><div><span>增量估计</span><strong class="value-positive">${x.estimate}</strong></div><div><span>业务影响</span><strong>${x.impact}</strong></div><div><span>不确定性</span><strong>${x.uncertainty}</strong></div></div></div>`).join('')}</div></div><div class="workbench-stack"><div class="card surface-card"><div class="surface-title"><div><h2>结果解释</h2><p>观察差异与因果估计分开呈现。</p></div>${evidenceBadge('A')}</div><div class="evidence-row"><span>观测差异</span><strong>+8.7pp</strong></div><div class="evidence-row"><span>增量估计</span><strong>+8.4pp</strong></div><div class="evidence-row"><span>每增量订单成本</span><strong>¥18.4</strong></div><div class="evidence-row"><span>保护指标</span><strong class="value-positive">通过</strong></div></div><div class="card surface-card"><div class="insight-item"><strong>建议继续小流量验证</strong><p>成熟窗口尚未结束，继续收集数据可缩小不确定性。</p><div class="insight-actions"><button class="mini-action primary" data-go="approvals">查看审批</button></div></div></div></div></div>`;bindProductActions()}

function execution(){const rows=DEMO.executions;$('#view').innerHTML=`${head('执行中心','集中查看真实外部副作用、连接器、成本、失败与回滚状态。','<button class="secondary" data-demo-action="preflight">运行全局预检</button>')}${sectionNav(STRATEGY_NAV,'execution')}<div id="demo-preflight-result" class="card" hidden style="margin-bottom:10px;padding:9px 12px;font-size:9px"></div><div class="stat-strip"><div class="stat-box"><span>运行中</span><strong>7</strong><em>全部在预算内</em></div><div class="stat-box"><span>等待审批</span><strong>3</strong><em class="muted">1 个 L4</em></div><div class="stat-box"><span>失败</span><strong>1</strong><em class="muted">模拟连接器异常</em></div><div class="stat-box"><span>外部成本</span><strong>¥128k</strong><em>今日累计</em></div></div><div class="card surface-card table-scroll"><div class="surface-title"><div><h2>执行状态流程</h2><p>草案 → 预检 → 审批 → 执行 → 完成或回滚。</p></div><span class="soft-badge green">紧急停止已就绪</span></div><table class="opportunity-table"><thead><tr><th>活动</th><th>状态</th><th>受众</th><th>渠道</th><th>连接器</th><th>动作</th><th>送达</th><th>成本</th><th>审批</th></tr></thead><tbody>${rows.map(x=>`<tr><td class="segment-cell"><strong>${esc(x.name)}</strong><span>可恢复工作流</span></td><td>${esc(productLabel(x.status))}</td><td>${esc(x.audience)}</td><td>${esc(x.channel)}</td><td>${esc(x.connector)}</td><td>${esc(x.action)}</td><td>${esc(x.delivery)}</td><td>${esc(x.cost)}</td><td><code>${esc(x.approval)}</code></td></tr>`).join('')}</tbody></table></div><div class="page-grid" style="margin-top:10px"><div class="card surface-card span-8"><div class="surface-title"><div><h2>执行安全边界</h2><p>所有外部动作均须通过相同的安全校验。</p></div></div><div class="guardrail-grid">${[['Idempotency','重复请求不会重复发送'],['Dry-run / Preflight','执行前验证受众、创意与连接器'],['Budget Reservation','先冻结可用预算再发送'],['Rate Limit / Retry','连接器限速与指数退避'],['Dead Letter','失败请求进入可重放队列'],['Rollback / Kill Switch','小流量验证异常时立即停止']].map(x=>`<div class="guardrail"><strong>${x[0]} <span class="pass">✓</span></strong><span>${x[1]}</span></div>`).join('')}</div></div></div>`;bindProductActions()}

function realtime(){const logs=DEMO.decisions;const req=`POST /api/realtime/decision\n\n{\n  "entity_id": "user_28419",\n  "placement": "checkout_banner",\n  "context": {"cart_value": 198, "session_intent": "high"},\n  "candidate_action_ids": ["free_shipping", "NO_TREATMENT"]\n}`;const res=`{\n  "decision_id": "dec_920184",\n  "action_id": "free_shipping",\n  "creative_id": "cr_281",\n  "propensity": 0.23,\n  "policy_id": "policy_growth_safe",\n  "evidence_tier": "A"\n}`;$('#view').innerHTML=`${head('实时决策','结合当前上下文与备选动作评估增量价值，并在约束范围内保留不触达。','<button class="secondary" data-demo-action="realtime-copy">复制 API 示例</button>')}${sectionNav(EVIDENCE_NAV,'realtime')}<div class="stat-strip"><div class="stat-box"><span>中位响应耗时</span><strong>41ms</strong><em>目标 < 60ms</em></div><div class="stat-box"><span>决策数量</span><strong>1.28m</strong><em>过去 24 小时</em></div><div class="stat-box"><span>不触达</span><strong>31.6%</strong><em>一等动作</em></div><div class="stat-box"><span>回退比例</span><strong>0.04%</strong><em class="muted">上下文过期 / 连接器异常</em></div></div><div class="decision-console"><div class="workbench-stack"><div class="card surface-card"><div class="surface-title"><div><h2>决策接口请求</h2><p>演示页面不会发送真实营销动作。</p></div><span class="soft-badge green">参考数据</span></div><div class="code-card">${esc(req)}</div></div><div class="card surface-card"><div class="surface-title"><div><h2>决策记录</h2><p>保留决策编号、分配概率、策略身份与证据。</p></div></div><table class="log-table"><thead><tr><th>ID</th><th>展示位置</th><th>动作</th><th>分配概率</th><th>策略</th><th>耗时</th><th>结果</th></tr></thead><tbody>${logs.map(x=>`<tr><td><code>${esc(x.id)}</code></td><td>${esc(x.placement)}</td><td>${esc(x.action)}</td><td>${esc(x.propensity)}</td><td>${esc(x.policy)}</td><td>${esc(x.latency)}ms</td><td>${esc(x.result)}</td></tr>`).join('')}</tbody></table></div></div><div class="workbench-stack"><div class="card surface-card"><div class="surface-title"><div><h2>决策路径</h2><p>上下文过期时，高风险动作会停止并等待核实。</p></div></div><div class="decision-path">${[['C','Consent','允许营销触达','PASS'],['F','Frequency','2 次额度剩余','PASS'],['B','Budget','¥50 treatment budget','PASS'],['X','Context','freshness 10s','PASS'],['E','效果证据','Tier A · support 91%','PASS'],['P','Policy','free_shipping vs NO_TREATMENT','DECIDE']].map(x=>`<div class="decision-node"><div class="icon">${x[0]}</div><div><strong>${x[1]}</strong><span>${x[2]}</span></div><b>${x[3]}</b></div>`).join('')}</div></div><div class="card surface-card"><div class="surface-title"><div><h2>返回结果</h2><p>记录实际分配概率，供后续离线评估核验。</p></div></div><div class="code-card" style="min-height:190px">${esc(res)}</div></div></div></div>`;bindProductActions()}

async function harness(){const runs=DEMO.traces;$('#view').innerHTML=`${head('执行轨迹','查看上下文、经验、工具、轨迹、评测、审批与小流量验证。','<button class="secondary" data-demo-action="trace-export">导出运行轨迹</button>')}${sectionNav(RUNTIME_NAV,'harness')}<div class="runtime-grid"><div class="card surface-card"><div class="surface-title"><div><h2>运行轨迹 · RUN-9081</h2><p>智能体、执行框架与策略使用稳定身份记录操作轨迹。</p></div><div class="surface-badges"><span class="soft-badge green">策略校验通过</span><span class="soft-badge">证据 A级</span></div></div><div class="trace-list">${runs.map(x=>`<div class="trace-row"><div class="trace-glyph">${x.glyph}</div><div class="trace-copy"><strong>${esc(x.name)}</strong><span>${esc(x.detail)}</span></div><div class="trace-time">${esc(x.latency)}</div><div class="trace-cost">${esc(x.cost)}</div></div>`).join('')}</div></div><div class="workbench-stack"><div class="card surface-card"><div class="surface-title"><div><h2>运行身份</h2><p>稳定身份与证据快照用于追溯策略变化。</p></div></div><div class="evidence-row"><span>智能体</span><strong>growth_agent</strong></div><div class="evidence-row"><span>执行框架</span><strong>growth_harness</strong></div><div class="evidence-row"><span>策略</span><strong>policy_growth_safe</strong></div><div class="evidence-row"><span>工具</span><strong>growth_tool_registry</strong></div><div class="evidence-row"><span>记忆策略</span><strong>growth_memory_policy</strong></div></div><div class="card surface-card"><div class="surface-title"><div><h2>保护规则</h2><p>分别校验输入、上下文、工具、输出和执行。</p></div></div><div class="guardrail-grid">${[['Input','Prompt Injection','pass'],['Context','Tenant / freshness','pass'],['Tool','Permission / schema','pass'],['Output','Claim grounding','pass'],['执行准备','Consent / budget','pass'],['Side Effect','Approval required','gated']].map(x=>`<div class="guardrail"><strong>${x[0]} <span class="pass">${x[2]==='pass'?'✓':'●'}</span></strong><span>${x[1]}</span></div>`).join('')}</div></div></div></div>`;bindProductActions()}

function approvals(){const rows=DEMO.approvalsFull;$('#view').innerHTML=`${head('治理与审批','审批围绕风险敞口、证据、不确定性和实际变化，而不是只显示“同意/拒绝”。','<button class="secondary" data-go="settings">查看策略</button>')}${sectionNav(RUNTIME_NAV,'approvals')}<div class="workbench-grid"><div class="approval-list">${rows.map(x=>`<div class="card approval-wide"><div class="approval-summary"><div class="approval-name"><div style="display:flex;gap:6px;align-items:center"><strong>${esc(x.title)}</strong><span class="soft-badge ${x.level==='L4'?'red':'amber'}">${esc(x.level)}</span></div><p>${esc(x.id)} · ${esc(x.desc)}</p></div><div class="approval-kv"><span>影响用户</span><strong>${esc(x.users)}</strong></div><div class="approval-kv"><span>预算</span><strong>${esc(x.budget)}</strong></div><div class="approval-kv"><span>最大风险敞口</span><strong>${esc(x.risk)}</strong></div><div class="approval-kv"><span>预计增量价值</span><strong class="value-positive">${esc(x.value)}</strong></div></div><div class="change-box"><strong>变化点：</strong> ${esc(x.change)}<br><strong>不确定性：</strong> ${esc(x.uncertainty)}　·　<strong>证据：</strong> 等级 ${esc(x.evidence)}</div><div class="version-row"><span class="version-pill">Agent ${esc(x.agent)}</span><span class="version-pill">Harness ${esc(x.harness)}</span><span class="version-pill">Policy ${esc(x.policy)}</span><span class="version-pill">Channel ${esc(x.channel)}</span></div>${x.status&&x.status!=='pending'?`<div class="approval-buttons"><span class="soft-badge green">已决定 · ${esc(productLabel(x.status))}</span><small>${esc(x.decided_at||'Demo session')}</small></div>`:`<div class="approval-buttons"><button data-demo-action="approval" data-approval-id="${esc(x.id)}" data-decision="return">退回修改</button><button class="danger" data-demo-action="approval" data-approval-id="${esc(x.id)}" data-decision="reject">拒绝</button><button data-demo-action="approval" data-approval-id="${esc(x.id)}" data-decision="approve_shadow">批准影子验证</button><button data-demo-action="approval" data-approval-id="${esc(x.id)}" data-decision="approve_1">批准 1%</button><button class="canary" data-demo-action="approval" data-approval-id="${esc(x.id)}" data-decision="approve_5">批准 5% 小流量</button></div>`}</div>`).join('')}</div><div class="workbench-stack"><div class="card surface-card"><div class="surface-title"><div><h2>风险分级</h2><p>爆炸半径越大，审批越严格。</p></div></div><div class="risk-ladder">${[['L0','Read Only','自动'],['L1','Draft','自动'],['L2','Internal Write','策略决定'],['L3','Limited Execution','审批/预授权'],['L4','Large Blast Radius','双审批']].map(x=>`<div class="risk-level"><b>${x[0]}</b><div><strong>${x[1]}</strong><span>工作区治理</span></div><em>${x[2]}</em></div>`).join('')}</div></div></div></div>`;bindProductActions()}

const DEMO_EVOLUTION_STAGES={Rejected:'已拒绝',Shadow:'灰度观察中',Canary:'小流量验证中',Promoted:'已批准采用',Replay:'离线回放',Pending:'等待验证','Canary ready':'等待小流量验证','Offline replay':'离线回放'};
function evolution(){const rows=DEMO.evolution;$('#view').innerHTML=`${head('自进化中心 · 演示','当前是样例演示。可预览候选的工作流程，但不会把它当作真实的自进化结果。','<button class="secondary" data-demo-action="failure-miner">生成演示候选</button>')}${sectionNav(RUNTIME_NAV,'evolution')}<div class="card surface-card"><div class="surface-title"><div><h2>演示预览 · 非真实运行</h2><p>以下候选和指标均为界面样例。要查看实际候选，请连接模型，在执行模式中积累真实运行记录，再使用自进化分析功能。</p></div><span class="soft-badge">演示数据</span></div><button class="secondary" type="button" data-go="agent">前往智能体操作系统</button></div><div class="evolution-list">${rows.map((x,i)=>`<div class="card evo-card"><div class="evo-head"><div><strong>改进候选 · ${esc(x.id)}</strong><div class="evo-source">来源：${esc(x.source)}</div></div><span class="soft-badge ${i===0?'green':i===1?'amber':''}">${esc(DEMO_EVOLUTION_STAGES[x.stage]||'等待验证')}</span></div><div class="evo-problem"><strong>问题</strong><br>${esc(x.problem)}<br><br><strong>候选改进</strong><br>${esc(x.candidate)}</div><div class="eval-grid">${x.metrics.map(m=>`<div class="eval-cell"><span>${esc(productLabel(m[0]))}</span><strong>${esc(productLabel(m[1]))}</strong></div>`).join('')}</div><div class="promotion-line"><div class="promotion-stage done">离线回放</div><span class="promotion-arrow">→</span><div class="promotion-stage ${i<2?'done':''}">独立评测</div><span class="promotion-arrow">→</span><div class="promotion-stage ${i===0?'done':i===1?'active':''}">灰度观察</div><span class="promotion-arrow">→</span><div class="promotion-stage ${i===0?'active':''}">小流量验证</div><span class="promotion-arrow">→</span><div class="promotion-stage">批准采用</div></div>${i===0?'<div class="approval-buttons"><button data-demo-action="reject-candidate" data-candidate-id="'+esc(x.id)+'">拒绝样例</button><button class="canary" data-go="approvals">查看审批流程</button></div>':''}</div>`).join('')}</div>`;bindProductActions()}

function dataCenter(){$('#view').innerHTML=`${head('数据中心','统一查看数据仓库、实时事件、决策、曝光、结果与证据。')}<div class="stat-strip"><div class="stat-box"><span>数据仓库更新时间</span><strong>5m</strong><em>正常</em></div><div class="stat-box"><span>事件延迟</span><strong>1.8s</strong><em>正常</em></div><div class="stat-box"><span>决策记录</span><strong>1.28m</strong><em>24h</em></div><div class="stat-box"><span>证据快照</span><strong>428</strong><em class="muted">不可修改</em></div></div><div class="card surface-card"><div class="surface-title"><div><h2>统一数据工作区</h2><p>区分长期资料、历史证据与会话实时上下文，保留可追溯的决策记录。</p></div></div><div class="data-plane">${[['WH','Warehouse','长期用户、订单、活动与成本记录','5 分钟内更新'],['EV','Event Stream','点击、浏览、购物车、实时触发','延迟 1.8 秒'],['FT','Feature Service','低延迟服务上下文与数据时效','中位耗时 48 毫秒'],['DL','Decision Log','动作、分配概率、策略与上下文引用','每日 128 万条'],['EX','Exposure Store','真实曝光与分组身份','关联率 99.99%'],['OU','Outcome Store','收入、转化、留存、退订、投诉','7 天成熟窗口'],['ED','Evidence Store','锁定的离线评估、实验与支持度快照','428 个快照'],['OB','Object Storage','报告、创意素材、产出文件与运行轨迹','本地演示']].map(x=>`<div class="data-node"><div class="data-icon">${x[0]}</div><strong>${x[1]}</strong><p>${x[2]}</p><footer>● ${x[3]}</footer></div>`).join('')}</div></div>`}

function integrations(){const rows=DEMO.connectors;$('#view').innerHTML=`${head('集成与渠道','从演示连接开始，按需要接入企业系统，并保持一致的权限与审批要求。','<button class="secondary" data-demo-action="connector-export">导出连接器目录</button>')}<div class="card surface-card"><div class="surface-title"><div><h2>连接器列表</h2><p>数据、执行、内容和智能体工具均按权限接入。</p></div><span class="soft-badge green">仅 GitHub 安全演示</span></div><div class="connector-grid">${rows.map(x=>`<div class="connector"><div class="connector-logo">${esc(x.logo)}</div><div><strong>${esc(x.name)}</strong><span>${esc(x.detail)}</span></div><i style="background:${x.status==='ready'?'#0db17d':'#c7ced9'}"></i></div>`).join('')}</div></div>`;bindProductActions()}

function settings(){$('#view').innerHTML=`${head('设置','管理工作区、环境、权限、预算、渠道与安全策略。')}<div class="workbench-grid"><div class="card surface-card"><div class="surface-title"><div><h2>工作区策略</h2><p>默认按最小权限运行，外部动作需要明确授权。</p></div></div><div class="evidence-row"><span>环境</span><strong>GitHub 演示 / 独立生产部署</strong></div><div class="evidence-row"><span>默认外部风险</span><strong>L3 需人工审批</strong></div><div class="evidence-row"><span>预算上限</span><strong>已启用</strong></div><div class="evidence-row"><span>不触达</span><strong>必须保留在备选动作中</strong></div><div class="evidence-row"><span>证据校验</span><strong>优先使用 A/B 级证据</strong></div><div class="evidence-row"><span>审计保留期</span><strong>不可变快照</strong></div></div><div class="card surface-card"><div class="surface-title"><div><h2>部署状态</h2><p>当前不需要任何企业凭据。</p></div><span class="soft-badge green">就绪状态</span></div><div class="evidence-row"><span>静态站点构建</span><strong>GitHub Actions</strong></div><div class="evidence-row"><span>服务地址</span><strong>演示数据</strong></div><div class="evidence-row"><span>后续接入</span><strong>GROWTHEVO_API_BASE</strong></div><button class="mini-action" style="width:100%;margin-top:10px" data-demo-action="deployment-check">运行部署检查</button><div id="demo-deployment-result" hidden style="margin-top:8px;font-size:8px;line-height:1.5;color:#667085"></div></div></div>`;bindProductActions()}

function render(){if(state.route==='dashboard')return dashboard();if(state.route==='campaigns')return campaigns();if(state.route==='campaignStudio')return campaignStudio();if(state.route==='experiments')return experiments();if(state.route==='execution')return execution();if(state.route==='evidence')return evidence();if(state.route==='opportunities')return opportunities();if(state.route==='realtime')return realtime();if(state.route==='harness')return harness();if(state.route==='approvals')return approvals();if(state.route==='evolution')return evolution();if(state.route==='data')return dataCenter();if(state.route==='integrations')return integrations();if(state.route==='settings')return settings();return dashboard()}
function renderAgent(){
  const body=$('#agent-body');
  if(!body)return;
  const mode=useDemo?'演示工作区':'真实工作区 · 工具操作';
  body.innerHTML='<div class="agent-onboarding"><div class="agent-onboarding-eyebrow"><span class="os-signal"></span> 智能体操作系统</div>'
    +'<h3>你设定目标。<br><span>我负责推进任务。</span></h3>'
    +'<p>读取工作区、调用受控工具、检验实际结果。高风险操作保持人工审批。</p>'
    +'<div class="agent-onboarding-label">建议任务 / '+esc(mode)+'</div>'
    +'<div class="agent-task-list"><button type="button" data-agent-prompt="读取当前增长机会，并导航到实验中心">分析增长机会 <span>↗</span></button>'
    +'<button type="button" data-agent-prompt="检查待审批事项，带我进入审批界面">检查审批边界 <span>↗</span></button>'
    +'<button type="button" data-agent-prompt="检查智能体的最近运行轨迹和自进化候选">检查演进状态 <span>↗</span></button></div></div>';
  document.querySelectorAll('#agent-body [data-agent-prompt]').forEach(button=>button.onclick=()=>{
    const input=$('#agent-input');
    if(input){input.value=button.dataset.agentPrompt;input.focus();}
  });
}
