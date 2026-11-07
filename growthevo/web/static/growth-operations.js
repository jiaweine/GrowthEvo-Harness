/* Nightfall growth workbench: one API-backed, tenant-scoped source of truth. */
const growthTabs = [
  ['overview','运营概览'],['customers','客户与人群'],
  ['experiments','实验与决策'],['journeys','旅程与投递'],['assets','素材与优惠']
];
const growthState = {
  tab:'overview',pages:{},notice:'',profile:null,segmentPreview:null,
  report:null,evidence:null,decision:null,selectedExperiment:null
};
let growthSnapshot=null;

function growthId(prefix){
  return prefix+'_'+Date.now()+'_'+Math.random().toString(16).slice(2,10);
}
function growthValue(value){
  if(value===null||value===undefined||value==='')return '—';
  if(typeof value==='object')return JSON.stringify(value);
  return String(value);
}
function growthMetric(label,value){
  return '<div class="stat-box"><span>'+esc(label)+'</span><strong>'+esc(growthValue(value))+'</strong></div>';
}
function growthCard(title,description,body,extraClass=''){
  return '<div class="card surface-card '+extraClass+'"><div class="surface-title"><div><h2>'+esc(title)+'</h2>'
    +(description?'<p>'+esc(description)+'</p>':'')+'</div></div>'+body+'</div>';
}
function growthOptions(rows,key,label=key,empty='请选择'){
  return '<option value="">'+esc(empty)+'</option>'+rows.map(row=>
    '<option value="'+esc(row[key])+'">'+esc(growthValue(row[label]))+'</option>'
  ).join('');
}
function growthTable(name,rows,columns){
  if(!rows.length)return '<p>暂无记录。数据不存在时不填入演示数值。</p>';
  const perPage=20;
  const pages=Math.max(1,Math.ceil(rows.length/perPage));
  const current=Math.min(Math.max(0,growthState.pages[name]||0),pages-1);
  growthState.pages[name]=current;
  const visible=rows.slice(current*perPage,(current+1)*perPage);
  const heading='<thead><tr>'+columns.map(column=>'<th>'+esc(column[1])+'</th>').join('')+'</tr></thead>';
  const body='<tbody>'+visible.map(row=>'<tr>'+columns.map(column=>{
    const value=column[2]?column[2](row):row[column[0]];
    return '<td>'+esc(growthValue(value))+'</td>';
  }).join('')+'</tr>').join('')+'</tbody>';
  return '<div class="table-scroll"><table class="opportunity-table">'+heading+body+'</table></div>'
    +'<div style="display:flex;gap:8px;align-items:center;justify-content:flex-end;flex-wrap:wrap;margin-top:10px">'
    +'<span class="muted">共 '+rows.length+' 条 · 第 '+(current+1)+' / '+pages+' 页</span>'
    +'<button type="button" class="secondary" data-growth-page="'+esc(name)+'" data-direction="-1" '+(current===0?'disabled':'')+'>上一页</button>'
    +'<button type="button" class="secondary" data-growth-page="'+esc(name)+'" data-direction="1" '+(current===pages-1?'disabled':'')+'>下一页</button></div>';
}
function growthFormValue(form,key){
  const control=form.elements.namedItem(key);
  return control?control.value.trim():'';
}
function growthForm(name,inner,submit='保存到数据库'){
  return '<form data-growth-form="'+name+'" style="margin-top:12px">'
    +'<div class="form-grid">'+inner+'</div>'
    +'<button type="submit" class="secondary" style="margin-top:12px">'+esc(submit)+'</button></form>';
}
function growthField(label,name,options={}){
  const type=options.type||'text';
  const attrs=' name="'+name+'" id="growth-'+name+'" '
    +(options.required===false?'':'required ')
    +(options.min!==undefined?'min="'+options.min+'" ':'')
    +(options.max!==undefined?'max="'+options.max+'" ':'')
    +(options.maxlength?'maxlength="'+options.maxlength+'" ':'');
  const input=options.select
    ?'<select '+attrs+'>'+options.select+'</select>'
    :'<input '+attrs+'type="'+type+'" placeholder="'+esc(options.placeholder||'')+'" value="'+esc(options.value||'')+'"/>';
  return '<div class="field"><label for="growth-'+name+'">'+esc(label)+'</label>'+input+'</div>';
}
function growthFormNotice(){
  return '<p id="growth-operation-notice" role="status" aria-live="polite" style="margin:8px 0">'+esc(growthState.notice)+'</p>';
}
function growthSourceLabel(row){return row.synthetic?'演示记录':'业务记录';}
function growthStatus(status){
  const map={queued:'待提交',simulated:'模拟',submitted:'已提交网关',delivered:'已送达',
    failed:'失败',bounced:'退信',suppressed:'已抑制',pending:'待执行',dispatched:'已处理',
    sending:'提交中',uncertain:'网关状态待核对',accepted:'网关接受'};
  return map[status]||growthValue(status);
}
function growthOverview(data){
  const count=data.overview.counts;
  const summary='<div class="stat-strip">'
    +growthMetric('客户',count.customers)+growthMetric('事件',count.events)
    +growthMetric('实验曝光',count.exposures)+growthMetric('旅程',count.journeys)
    +growthMetric('待办及投递',data.jobs.length+' / '+count.deliveries)+'</div>';
  const statement=data.overview.data_origin==='synthetic_and_observed'
    ?'包含持久化演示样本。所有演示记录单独标记，不代表真实客户转化。'
    :'当前工作空间只展示数据库业务记录；无记录时保持空状态。';
  return summary+growthCard('数据来源与执行边界',statement,
    '<div class="evidence-row"><span>存储</span><strong>PostgreSQL</strong></div>'
    +'<div class="evidence-row"><span>个体化策略</span><strong>观测学习 · 非 CATE 上线模型</strong></div>'
    +'<div class="evidence-row"><span>渠道提交</span><strong>生产权限 + 可信 HTTPS 网关</strong></div>'
    +'<p>Worker 仅生成待投递记录。网关接受不等于送达；离线评估不等于因果证明。</p>',
    'span-8')
    +growthCard('最新行为事件','来源和发生时间均来自数据库。',
      growthTable('events',data.events,[['occurred_at','发生时间'],['customer_id','客户'],
        ['name','事件'],['synthetic','来源',growthSourceLabel]]),'span-12')
    +growthCard('当前任务','查看待执行、已处理和受抑制状态。',
      growthTable('jobs',data.jobs,[['job_id','任务'],['customer_id','客户'],
        ['status','状态',r=>growthStatus(r.status)],['due_at','计划时间']]),'span-12');
}
function growthCustomers(data){
  const c=data.customers;
  const newCustomer=growthForm('customer',
    growthField('客户编号','new_customer_id',{placeholder:'customer_alpha',maxlength:80})
    +growthField('属性名','new_customer_key',{placeholder:'lifecycle',maxlength:80})
    +growthField('属性值','new_customer_value',{placeholder:'new',maxlength:150})
    +'<div class="field"><label><input type="checkbox" name="new_customer_consent"> 已取得营销授权</label></div>',
    '创建客户');
  const customerSelect=growthField('查看客户画像','profile_customer_id',{
    select:growthOptions(c,'customer_id')
  });
  const profile=growthState.profile;
  const profileDetail=profile
    ?growthCard('客户 · '+profile.customer.customer_id,
      '可核对动态人群、事件、实验分组及投递记录。',
      '<div class="evidence-row"><span>营销授权</span><strong>'+(profile.customer.consent?'已授权':'未授权')+'</strong></div>'
      +'<div class="evidence-row"><span>属性</span><strong>'+esc(JSON.stringify(profile.customer.attributes))+'</strong></div>'
      +'<div class="evidence-row"><span>匹配人群</span><strong>'+esc(profile.segments.join('、')||'无')+'</strong></div>'
      +'<div class="evidence-row"><span>行为 / 实验 / 投递</span><strong>'+profile.events.length+' / '+profile.experiments.length+' / '+profile.deliveries.length+'</strong></div>'
      +growthForm('consent','<div class="field"><label><input type="checkbox" name="consent" '+(profile.customer.consent?'checked':'')+'> 允许营销触达</label></div>','保存授权状态'),
      'span-12')
    :'';
  const segmentFields=growthField('人群编号','new_segment_id',{placeholder:'segment_recent'})
    +growthField('人群名称','new_segment_name',{placeholder:'近期注册用户'})
    +growthField('属性条件名','new_segment_key',{placeholder:'lifecycle'})
    +growthField('属性条件值','new_segment_value',{placeholder:'new'});
  const segmentList=growthTable('segments',data.segments,
    [['segment_id','人群编号'],['name','名称'],['equals','匹配条件']]);
  const preview=growthState.segmentPreview;
  const previewDetail=preview
    ?'<p role="status">匹配 '+preview.size+' 位客户：'+esc(preview.customer_ids.slice(0,20).join('、'))
     +(preview.size>20?' 等':'')+'</p>'
    :'';
  return growthCard('客户画像与授权','新建客户与更新授权都写入当前身份的 PostgreSQL 工作区。',
      newCustomer
      +'<div class="field" style="margin-top:12px"><label for="growth-profile_customer_id">客户详情</label>'
      +'<select id="growth-profile_customer_id">'+growthOptions(c,'customer_id')+'</select></div>'
      +'<button class="secondary" type="button" id="growth-open-profile" '+(!c.length?'disabled':'')+'>查看完整画像</button>',
      'span-8')
    +growthCard('客户列表','最多显示每页 20 位，支持翻页。',
      growthTable('customers',c,[['customer_id','客户'],['consent','授权',x=>x.consent?'已授权':'未授权'],
        ['attributes','属性'],['synthetic','来源',growthSourceLabel]]),'span-12')
    +profileDetail
    +growthCard('动态人群','按客户属性动态匹配，不保存过期名单。',
      growthForm('segment',segmentFields,'创建人群')
      +segmentList
      +'<div class="field"><label for="growth-preview-segment">预览人群</label>'
      +'<select id="growth-preview-segment">'+growthOptions(data.segments,'segment_id','name')+'</select></div>'
      +'<button class="secondary" type="button" id="growth-preview-segment-button" '+(!data.segments.length?'disabled':'')+'>查看匹配客户</button>'
      +previewDetail,'span-12');
}
function growthExperiments(data){
  const customerChoices=growthOptions(data.customers,'customer_id');
  const experimentChoices=growthOptions(data.experiments,'experiment_id','name');
  const expFields=growthField('实验编号','new_experiment_id',{placeholder:'experiment_checkout'})
    +growthField('实验名称','new_experiment_name',{placeholder:'首购触达验证'})
    +growthField('目标事件','new_experiment_metric',{value:'purchase'})
    +growthField('对照组名称','new_experiment_control',{value:'holdout'})
    +growthField('处理组名称','new_experiment_treatment',{value:'treatment'})
    +growthField('对照组权重（%）','new_experiment_weight',{type:'number',min:1,max:99,value:50})
    +growthField('转化观察窗口（天）','new_experiment_days',{type:'number',min:1,max:90,value:7});
  const report=growthState.report;
  const result=report
    ?'<div class="evidence-row"><span>样本比例检查</span><strong>'
       +esc(report.srm.status==='warning'?'异常：需要排查':report.srm.status==='pass'?'未发现异常':'证据不足')
       +'</strong></div>'
      +'<p>观察窗口 '+esc(report.window_days)+' 天 · 已曝光 '+esc(report.srm.exposed_total)
       +' 人 · 未成熟样本不进入成熟转化率。此报告不声称因果增量。</p>'
      +growthTable('report',report.results,[['variant','分组'],['exposed_customers','曝光'],
        ['pending_customers','观察中'],['matured_customers','成熟'],
        ['matured_conversion_rate','成熟转化率',x=>x.matured_conversion_rate===null?'—':(x.matured_conversion_rate*100).toFixed(1)+'%'],
        ['matured_wilson_95','95% Wilson 区间',x=>x.matured_wilson_95?x.matured_wilson_95.map(v=>(v*100).toFixed(1)+'%').join(' ～ '):'—'],
        ['observed_difference_pp','对照差异（pp）']])
    :'请选择实验获取报告。';
  const decision=growthState.decision;
  const decisionBox=decision
    ?growthCard('最近一次已记录决策','这不是实际曝光，也不是已发送消息。',
      '<div class="evidence-row"><span>选择动作</span><strong>'+esc(decision.action_id)+'</strong></div>'
      +'<div class="evidence-row"><span>实际概率</span><strong>'+Number(decision.propensity).toFixed(4)+'</strong></div>'
      +growthTable('probabilities',Object.entries(decision.action_distribution).map(([action,probability])=>({action,probability})),
        [['action','候选动作'],['probability','分配概率',r=>(r.probability*100).toFixed(2)+'%']])
      +'<button type="button" class="secondary" id="growth-confirm-exposure" '+(decision.exposure_confirmed?'disabled':'')+'>确认此决策已实际展示</button>',
      'span-12')
    :'';
  const evidence=growthState.evidence;
  const evidenceBox=evidence
    ?growthCard('离线评估结果','仅用于风险诊断；不会自动部署到线上。',
      '<div class="evidence-row"><span>状态</span><strong>'+esc(evidence.status)+'</strong></div>'
      +'<div class="evidence-row"><span>成熟分析单位</span><strong>'+evidence.matured_units+'</strong></div>'
      +'<div class="evidence-row"><span>实际目标动作样本</span><strong>'+evidence.observed_target_units+'</strong></div>'
      +'<div class="evidence-row"><span>尚未成熟 / 不支持</span><strong>'+evidence.immature_units+' / '+evidence.unsupported_units+'</strong></div>'
      +(evidence.estimate
        ?'<div class="evidence-row"><span>IPS 描述性估计</span><strong>'+Number(evidence.estimate.ips_conversion_rate).toFixed(4)+'</strong></div>'
        +'<div class="evidence-row"><span>标准误 / 有效样本量</span><strong>'
        +Number(evidence.estimate.ips_standard_error).toFixed(4)+' / '+Number(evidence.estimate.effective_sample_size).toFixed(1)+'</strong></div>'
        +'<div class="evidence-row"><span>支持覆盖率</span><strong>'+(100*evidence.estimate.support_coverage).toFixed(1)+'%</strong></div>'
        :'<p>样本或支持不足时不展示虚构估计。</p>')
      +'<p>因果结论：否 · 自动晋升：禁止</p>',
      'span-12')
    :'';
  return growthCard('实验设计','创建固定分组与转化观察窗口；实验创建不等于已产生曝光。',
      growthForm('experiment',expFields,'创建实验'),'span-8')
    +growthCard('实验列表','持续读取 PostgreSQL 中的实验定义。',
      growthTable('experiments',data.experiments,
        [['experiment_id','实验'],['name','名称'],['metric_event','目标事件'],['window_days','观察天数']]),
      'span-12')
    +growthCard('曝光与成熟反馈','曝光是独立事件；对照组不能由普通按钮点击替代。',
      growthForm('experiment-exposure',
        growthField('实验','exposure_experiment',{select:experimentChoices})
        +growthField('已展示的客户','exposure_customer',{select:customerChoices})
        +growthField('展示位置','exposure_surface',{value:'growth_workspace'}),'记录真实曝光')
      +'<div class="field"><label for="growth-report-id">实验报告</label><select id="growth-report-id">'
      +experimentChoices+'</select></div><button class="secondary" id="growth-get-report" type="button" '+(!data.experiments.length?'disabled':'')+'>查看成熟结果与 SRM</button>'
      +result,'span-12')
    +growthCard('个体化决策','可配置预算与频控；不触达保留为正式动作。',
      growthForm('personalization',
        growthField('客户','personalization_customer',{select:customerChoices})
        +growthField('候选动作','personalization_action',{
          select:'<option value="free_shipping">首单免邮</option><option value="coupon_10">优惠券</option><option value="push_reminder">推送提醒</option><option value="email_guide">邮件引导</option>'
        })
        +growthField('剩余频控额度','personalization_frequency',{type:'number',min:0,max:100,value:1})
        +growthField('可用动作预算','personalization_budget',{type:'number',min:0,max:1000000,value:100}),
        '生成决策（不发送）')
      +'<div class="stat-strip">'+growthMetric('决策',data.personalization.decisions)
      +growthMetric('已确认曝光',data.personalization.confirmed_exposures)+'</div>'
      +growthTable('decisions',data.personalization.recent_decisions,
        [['request_id','请求'],['customer_id','客户'],['action_id','动作'],
          ['propensity','记录概率',r=>Number(r.propensity).toFixed(4)],
          ['exposure_confirmed','确认曝光',r=>r.exposure_confirmed?'是':'否']]),'span-12')
    +decisionBox
    +growthCard('离线策略证据','复用既有 OPE。不同数据来源严格分离，证据不足不输出效果结论。',
      growthForm('offline-evidence',
        growthField('目标动作','ope_action',{
          select:'<option value="NO_TREATMENT">不触达</option><option value="free_shipping">首单免邮</option><option value="coupon_10">优惠券</option><option value="push_reminder">推送提醒</option><option value="email_guide">邮件引导</option>'
        })
        +growthField('分析来源','ope_source',{
          select:'<option value="observed">业务记录</option><option value="synthetic">演示记录（仅验证环境）</option>'
        }),'读取离线证据')
      +evidenceBox,'span-12');
}
function growthJourneys(data){
  const journeyChoices=data.journeys;
  const creativeChoices=growthOptions(data.creatives,'creative_id','title','先在素材页面创建素材');
  const offers='<option value="">不使用优惠</option>'+data.offers.map(o=>
    '<option value="'+esc(o.offer_id)+'">'+esc(o.name)+'</option>').join('');
  const segmentOptions='<option value="">不限人群</option>'+data.segments.map(s=>
    '<option value="'+esc(s.segment_id)+'">'+esc(s.name)+'</option>').join('');
  const creation=growthForm('journey',
    growthField('旅程编号','new_journey_id',{placeholder:'journey_welcome'})
    +growthField('旅程名称','new_journey_name',{placeholder:'新客引导'})
    +growthField('触发事件','new_journey_trigger',{value:'signup'})
    +growthField('动态人群','new_journey_segment',{select:segmentOptions,required:false})
    +growthField('选择素材','new_journey_creative',{select:creativeChoices})
    +growthField('优惠','new_journey_offer',{select:offers,required:false})
    +growthField('延迟秒数','new_journey_delay',{type:'number',min:0,max:2592000,value:0}),
    '创建单步旅程（默认暂停）');
  const journeyControls=journeyChoices.length
    ?journeyChoices.map(j=>'<div class="evidence-row"><span>'+esc(j.name)+' · '+esc(j.trigger_event)
      +'</span><strong>'+(j.active?'运行中':'已停止')+'</strong>'
      +'<button class="secondary" type="button" data-growth-journey="'+esc(j.journey_id)
      +'" data-journey-command="'+(j.active?'stop':'activate')+'">'+(j.active?'停止':'激活')+'</button></div>').join('')
    :'<p>暂无旅程。请先创建素材，再建立旅程。</p>';
  return growthCard('旅程编排','从事件进入、资格复核到受控渠道准备。需要多步编排可继续使用完整 API。',
      creation,'span-8')
    +growthCard('旅程控制','激活后才会处理新事件；停止会抑制未提交的触达。',
      journeyControls,'span-12')
    +growthCard('到期任务','只创建待投递意图，不向外部服务发送。',
      '<button class="secondary" type="button" id="growth-process-due">处理最多 50 条到期任务</button>'
      +growthTable('jobs',data.jobs,
        [['job_id','任务'],['journey_id','旅程'],['status','状态',r=>growthStatus(r.status)],
          ['due_at','到期时间']]),'span-12')
    +growthCard('投递与回执','状态来自数据库；渠道提交需要单独的生产权限，不从前端直接发送。',
      growthTable('deliveries',data.deliveries,
        [['delivery_id','记录'],['customer_id','客户'],['channel','渠道'],
          ['status','状态',r=>growthStatus(r.status)],['dispatch_state','提交状态',r=>growthStatus(r.dispatch_state)],
          ['provider_event_id','渠道回执'],['synthetic','来源',growthSourceLabel]]),'span-12');
}
function growthAssets(data){
  const creatives=growthTable('creatives',data.creatives,
    [['creative_id','素材'],['title','标题'],['channel','渠道'],['synthetic','来源',growthSourceLabel]]);
  const offers=growthTable('offers',data.offers,
    [['offer_id','优惠'],['name','名称'],['amount','金额'],['max_redemptions','最大核销次数']]);
  return growthCard('素材管理','内容只是可复用的候选；创建素材不会触发外部营销。',
      growthForm('creative',growthField('素材编号','new_creative_id',{placeholder:'creative_welcome'})
        +growthField('渠道','new_creative_channel',{
          select:'<option value="email">邮件</option><option value="push">推送</option><option value="sms">短信</option><option value="in_app">站内</option>'
        })
        +growthField('标题','new_creative_title',{placeholder:'欢迎加入'})
        +growthField('内容','new_creative_body',{placeholder:'感谢你的加入'}),'创建素材')
      +creatives,'span-12')
    +growthCard('优惠目录','优惠创建不代表已核销，也不会自动计入预算扣减。',
      growthForm('offer',
        growthField('优惠编号','new_offer_id',{placeholder:'offer_welcome'})
        +growthField('名称','new_offer_name',{placeholder:'新客优惠'})
        +growthField('金额','new_offer_amount',{type:'number',min:0,max:1000000,value:10})
        +growthField('最大核销量','new_offer_redemptions',{type:'number',min:1,max:10000000,value:100}),'创建优惠')
      +offers,'span-12');
}
function growthRender(){
  if(!growthSnapshot)return;
  const data=growthSnapshot;
  const origin=data.overview.data_origin==='synthetic_and_observed'?'含数据库演示样本':'数据库业务记录';
  const nav='<div role="tablist" aria-label="增长运营工作台" style="display:flex;gap:8px;flex-wrap:wrap;margin:12px 0">'
    +growthTabs.map(([key,label])=>'<button type="button" role="tab" aria-selected="'+(growthState.tab===key)
      +'" data-growth-tab="'+key+'" class="'+(growthState.tab===key?'primary':'secondary')+'">'
      +esc(label)+'</button>').join('')+'</div>';
  const content=growthState.tab==='overview'?growthOverview(data)
    :growthState.tab==='customers'?growthCustomers(data)
    :growthState.tab==='experiments'?growthExperiments(data)
    :growthState.tab==='journeys'?growthJourneys(data):growthAssets(data);
  $('#view').innerHTML=head('数据驱动增长运营',
    '客户、决策、实验、旅程与反馈共用当前身份的 PostgreSQL 记录。')
    +'<div class="card surface-card" style="margin-bottom:10px"><strong>'+esc(origin)
    +'</strong><p>可用数据与权限以当前环境为准。营销投递须由可信网关独立授权。</p>'
    +'<button type="button" class="secondary" id="growth-refresh">刷新数据库</button></div>'
    +nav+growthFormNotice()
    +'<div class="page-grid" role="tabpanel">'+content+'</div>';
  growthBind();
}
async function growthRun(button,action,success='操作已保存'){
  if(button)button.disabled=true;
  try{
    await action();
    growthState.notice=success;
    await growthOperationsPage();
  }catch(error){
    const text='操作未完成：'+(error&&error.message?error.message:'请检查权限和网络');
    growthState.notice=text;
    const notice=$('#growth-operation-notice');
    if(notice)notice.textContent=text;
    toast('操作未完成');
  }finally{if(button&&button.isConnected)button.disabled=false;}
}
function growthPost(path,body){
  return api(path,{method:'POST',body:JSON.stringify(body)});
}
function growthBind(){
  $$('[data-growth-tab]').forEach(button=>button.onclick=()=>growthOpenTab(button.dataset.growthTab));
  $$('[data-growth-page]').forEach(button=>button.onclick=()=>{
    const key=button.dataset.growthPage;
    growthState.pages[key]=(growthState.pages[key]||0)+Number(button.dataset.direction);
    growthRender();
  });
  const refresh=$('#growth-refresh');
  if(refresh)refresh.onclick=()=>growthRun(refresh,()=>growthOperationsPage(),'工作空间已刷新');
  $$('form[data-growth-form]').forEach(form=>form.onsubmit=event=>{
    event.preventDefault();
    const value=name=>growthFormValue(form,name);
    const checkbox=name=>form.elements.namedItem(name)?.checked===true;
    const named=form.dataset.growthForm;
    const customer=dataId=>dataId||null;
    let operation;
    if(named==='customer')operation=()=>growthPost('/api/growth/customers',{
      customer_id:value('new_customer_id'),
      attributes:{[value('new_customer_key')]:value('new_customer_value')},
      consent:checkbox('new_customer_consent')
    });
    else if(named==='consent')operation=()=>growthPost(
      '/api/growth/customers/'+encodeURIComponent(growthState.profile.customer.customer_id)+'/update',
      {consent:checkbox('consent')}).then(async()=>{
        growthState.profile=await api('/api/growth/customers/'+encodeURIComponent(growthState.profile.customer.customer_id));
      });
    else if(named==='segment')operation=()=>growthPost('/api/growth/segments',{
      segment_id:value('new_segment_id'),name:value('new_segment_name'),
      equals:{[value('new_segment_key')]:value('new_segment_value')}
    });
    else if(named==='experiment')operation=()=>growthPost('/api/growth/experiments',{
      experiment_id:value('new_experiment_id'),name:value('new_experiment_name'),
      metric_event:value('new_experiment_metric'),control:value('new_experiment_control'),
      variants:[{key:value('new_experiment_control'),weight:Number(value('new_experiment_weight'))},
        {key:value('new_experiment_treatment'),weight:100-Number(value('new_experiment_weight'))}],
      window_days:Number(value('new_experiment_days'))
    });
    else if(named==='experiment-exposure')operation=()=>growthPost(
      '/api/growth/experiments/'+encodeURIComponent(value('exposure_experiment'))+'/exposures',{
        customer_id:value('exposure_customer'),request_id:growthId('ui_exposure'),
        surface:value('exposure_surface')
      });
    else if(named==='personalization')operation=async()=>{
      const result=await growthPost('/api/growth/personalization/decide',{
        customer_id:value('personalization_customer'),request_id:growthId('ui_personalization'),
        placement:'growth_workspace',candidate_action_ids:['NO_TREATMENT',value('personalization_action')],
        consent_state:true,frequency_remaining:Number(value('personalization_frequency')),
        budget_remaining:Number(value('personalization_budget'))
      });
      growthState.decision=result;
    };
    else if(named==='offline-evidence')operation=async()=>{
      const query='?target_action_id='+encodeURIComponent(value('ope_action'))
        +'&synthetic='+(value('ope_source')==='synthetic');
      growthState.evidence=await api('/api/growth/personalization/offline-evidence'+query);
    };
    else if(named==='journey')operation=()=>{
      const creative=growthSnapshot.creatives.find(x=>x.creative_id===value('new_journey_creative'));
      if(!creative)throw Error('请先选择有效素材');
      return growthPost('/api/growth/journeys',{
        journey_id:value('new_journey_id'),name:value('new_journey_name'),
        trigger_event:value('new_journey_trigger'),
        segment_id:value('new_journey_segment')||null,
        steps:[{channel:creative.channel,creative_id:creative.creative_id,
          offer_id:value('new_journey_offer')||null,delay_seconds:Number(value('new_journey_delay'))}]
      });
    };
    else if(named==='creative')operation=()=>growthPost('/api/growth/creatives',{
      creative_id:value('new_creative_id'),channel:value('new_creative_channel'),
      title:value('new_creative_title'),body:value('new_creative_body')
    });
    else if(named==='offer')operation=()=>growthPost('/api/growth/offers',{
      offer_id:value('new_offer_id'),name:value('new_offer_name'),
      amount:Number(value('new_offer_amount')),max_redemptions:Number(value('new_offer_redemptions'))
    });
    if(operation)void growthRun(form.querySelector('[type=submit]'),operation);
  });
  const profile=$('#growth-open-profile');
  if(profile)profile.onclick=()=>growthRun(profile,async()=>{
    const id=$('#growth-profile_customer_id').value;
    if(!id)throw Error('请选择客户');
    growthState.profile=await api('/api/growth/customers/'+encodeURIComponent(id));
  },'客户画像已更新');
  const segment=$('#growth-preview-segment-button');
  if(segment)segment.onclick=()=>growthRun(segment,async()=>{
    const id=$('#growth-preview-segment').value;
    if(!id)throw Error('请选择人群');
    growthState.segmentPreview=await api('/api/growth/segments/'+encodeURIComponent(id)+'/preview');
  },'人群匹配已更新');
  const report=$('#growth-get-report');
  if(report)report.onclick=()=>growthRun(report,async()=>{
    const id=$('#growth-report-id').value;
    if(!id)throw Error('请选择实验');
    growthState.selectedExperiment=id;
    growthState.report=await api('/api/growth/experiments/'+encodeURIComponent(id)+'/report');
  },'实验报告已更新');
  const confirmation=$('#growth-confirm-exposure');
  if(confirmation)confirmation.onclick=()=>growthRun(confirmation,async()=>{
    if(!growthState.decision)throw Error('请先请求一次决策');
    await growthPost('/api/growth/personalization/'+encodeURIComponent(growthState.decision.request_id)
      +'/exposure',{surface:growthState.decision.placement});
    growthState.decision.exposure_confirmed=true;
  },'实际展示已确认');
  const process=$('#growth-process-due');
  if(process)process.onclick=()=>growthRun(process,()=>growthPost('/api/growth/journeys/process',{limit:50}),
    '到期任务已处理；未调用外部发送');
  $$('[data-growth-journey]').forEach(button=>button.onclick=()=>growthRun(button,()=>{
    const id=encodeURIComponent(button.dataset.growthJourney);
    return growthPost('/api/growth/journeys/'+id+'/'+button.dataset.journeyCommand,{});
  },'旅程状态已更新'));
}
async function growthOperationsPage(){
  if(useDemo){
    $('#view').innerHTML=head('数据驱动增长运营','当前为静态演示，真实数据操作需要 PostgreSQL 和 API 模式。')
      +'<div class="card surface-card"><h2>在同一个工作空间完成增长闭环</h2>'
      +'<p>客户与授权 → 动态人群 → 实验与决策 → 旅程与回执 → 离线证据。</p>'
      +'<p>本页面不模拟数据库写入，也不展示虚构转化或投递成果。</p></div>';
    return;
  }
  const endpoints=['overview','customers','segments','events','experiments','journeys',
    'journeys/jobs','deliveries','offers','creatives','personalization/metrics'];
  const payloads=await Promise.all(endpoints.map(path=>api('/api/growth/'+path)));
  growthSnapshot=Object.fromEntries(endpoints.map((key,index)=>[
    key==='journeys/jobs'?'jobs':key==='personalization/metrics'?'personalization':key,payloads[index]
  ]));
  growthRender();
}
async function growthOpenTab(tab){
  if(!growthTabs.some(item=>item[0]===tab))return;
  growthState.tab=tab;
  if(state.route==='growthOps'&&growthSnapshot)growthRender();
  else if(state.route!=='growthOps')go('growthOps');
}
