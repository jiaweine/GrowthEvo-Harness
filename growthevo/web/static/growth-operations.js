/* PostgreSQL-backed growth operations workspace; never silently uses UI fixtures. */
const previousGrowthRouteRender = render;

const growthOptions = items => items.map(x=>'<option value="'+esc(x.customer_id)+'">'+esc(x.customer_id)+'</option>').join('');
const growthMetric = (label,value) => '<div class="stat-box"><span>'+esc(label)+'</span><strong>'+esc(value)+'</strong></div>';
const growthRows = (items,fields) => items.length
  ? '<table class="opportunity-table"><thead><tr>'+fields.map(f=>'<th>'+esc(f[1])+'</th>').join('')+'</tr></thead><tbody>'
    + items.map(row=>'<tr>'+fields.map(f=>'<td>'+esc(f[2]?f[2](row):row[f[0]]??'—')+'</td>').join('')+'</tr>').join('')+'</tbody></table>'
  : '<p>暂无记录，等待接入真实数据。</p>';

async function growthOperationsPage(){
  if(useDemo){
    $('#view').innerHTML=head('数据驱动增长运营','此静态演示不模拟数据库读写。请启动 PostgreSQL + API 模式，真实操作才会持久化。')
      +'<div class="card surface-card"><p>用户画像、旅程、素材、优惠、曝光与实验报表的演示数据仅在 API 模式写入 PostgreSQL。</p></div>';
    return;
  }
  const [overview,customers,segments,journeys,experiments,deliveries,offers,creatives] = await Promise.all([
    api('/api/growth/overview'),api('/api/growth/customers'),
    api('/api/growth/segments'),api('/api/growth/journeys'),
    api('/api/growth/experiments'),api('/api/growth/deliveries'),
    api('/api/growth/offers'),api('/api/growth/creatives')
  ]);
  const reports=await Promise.all(experiments.slice(0,8).map(x=>api('/api/growth/experiments/'+encodeURIComponent(x.experiment_id)+'/report')));
  const count=overview.counts;
  const origin=overview.data_origin==='synthetic_and_observed'?'包含数据库演示样例 · 非真实客户效果':'已存储业务记录';
  const customerChoices=growthOptions(customers);
  const exposureChoices=experiments.map(x=>'<option value="'+esc(x.experiment_id)+'">'+esc(x.name)+'</option>').join('');
  $('#view').innerHTML=head('数据驱动增长运营','用户画像、动态人群、事件旅程、素材优惠、实验曝光与业务反馈来自同一 PostgreSQL 工作空间。')
    +'<div class="card surface-card"><strong>'+esc(origin)+'</strong><p>数据库：PostgreSQL。外部渠道发送：未连接；任务仅创建待投递记录，不能证明已发送。实验展示观测差异，不声称已验证因果提升。</p></div>'
    +'<div class="stat-strip">'
    +growthMetric('用户',count.customers)+growthMetric('事件',count.events)+growthMetric('曝光',count.exposures)
    +growthMetric('旅程',count.journeys)+growthMetric('投递记录',count.deliveries)+'</div>'
    +'<div class="page-grid">'
    +'<div class="card surface-card span-8 table-scroll"><div class="surface-title"><div><h2>客户画像与授权</h2><p>客户属性、营销授权和动态人群使用数据库记录。</p></div></div>'
    +growthRows(customers.slice(0,40),[['customer_id','客户编号'],['attributes','属性',x=>JSON.stringify(x.attributes)],['consent','已授权',x=>x.consent?'是':'否'],['synthetic','数据来源',x=>x.synthetic?'演示':'业务']])+'</div>'
    +'<div class="card surface-card span-4"><div class="surface-title"><div><h2>动态人群</h2></div></div>'
    +segments.map(s=>'<div class="evidence-row"><span>'+esc(s.name)+'</span><strong>'+esc(JSON.stringify(s.equals))+'</strong></div>').join('')+'</div>'
    +'<div class="card surface-card span-8"><div class="surface-title"><div><h2>事件驱动旅程</h2><p>用户事件触发持久化待办；处理队列不等于发送到外部渠道。</p></div></div>'
    +growthRows(journeys,[['name','名称'],['trigger_event','触发事件'],['active','启用',x=>x.active?'是':'否'],['steps','步骤',x=>x.steps.length]])+'</div>'
    +'<div class="card surface-card span-4"><div class="surface-title"><div><h2>安全演示操作</h2></div></div>'
    +'<div class="field"><label for="growth-customer">客户</label><select id="growth-customer">'+customerChoices+'</select></div>'
    +'<div class="field"><label for="growth-event-name">事件名</label><input id="growth-event-name" value="signup" maxlength="80" /></div>'
    +'<button class="secondary" id="growth-record-event" type="button">记录事件并触发旅程</button>'
    +'<button class="secondary" id="growth-process" type="button">处理到期任务（不发送）</button>'
    +'<div class="field"><label for="growth-experiment">实验</label><select id="growth-experiment">'+exposureChoices+'</select></div>'
    +'<button class="secondary" id="growth-expose" type="button">记录一次显式曝光</button>'
    +'<p id="growth-action-result" role="status"></p></div>'
    +'<div class="card surface-card span-8 table-scroll"><div class="surface-title"><div><h2>实验与曝光反馈</h2><p>分组稳定、曝光需显式记录；转化率是观测结果，并非因果提升证明。</p></div></div>'
    +reports.map(report=>'<h3>'+esc(experiments.find(x=>x.experiment_id===report.experiment_id)?.name||report.experiment_id)+'</h3>'
      +growthRows(report.results,[['variant','分组'],['exposed_customers','曝光人数'],['converted_customers','转化人数'],
        ['conversion_rate','转化率',x=>x.conversion_rate===null?'—':(100*x.conversion_rate).toFixed(1)+'%'],
        ['observed_difference_pp','相对对照观测差（百分点）']])).join('')+'</div>'
    +'<div class="card surface-card span-4"><div class="surface-title"><div><h2>素材与优惠</h2></div></div>'
    +creatives.map(c=>'<div class="evidence-row"><span>'+esc(c.title)+'</span><strong>'+esc(c.channel)+'</strong></div>').join('')
    +offers.map(o=>'<div class="evidence-row"><span>'+esc(o.name)+'</span><strong>'+esc(o.amount)+'</strong></div>').join('')+'</div>'
    +'<div class="card surface-card span-12 table-scroll"><div class="surface-title"><div><h2>渠道任务与回执</h2><p>simulated 仅表示模拟任务，queued 表示尚未交给外部提供商。只有独立渠道回执可说明实际送达状态。</p></div></div>'
    +growthRows(deliveries.slice(0,40),[['delivery_id','任务编号'],['channel','渠道'],['customer_id','客户'],['status','状态'],
      ['synthetic','数据来源',x=>x.synthetic?'模拟':'业务']])+'</div></div>';
  const runAction=async (button,request)=>{
    button.disabled=true;
    const message=$('#growth-action-result');
    try{
      const result=await request();
      if(message)message.textContent='已写入数据库：'+JSON.stringify(result).slice(0,180);
      toast('操作已写入数据库');
      await growthOperationsPage();
    }catch(error){if(message)message.textContent='操作失败：'+(error?.message||'未知原因')}
    finally{button.disabled=false}
  };
  $('#growth-record-event').onclick=e=>runAction(e.currentTarget,()=>{
    const name=$('#growth-event-name').value.trim();
    return api('/api/growth/events',{method:'POST',body:JSON.stringify({
      event_id:'ui_event_'+Date.now()+'_'+Math.random().toString(16).slice(2,8),
      customer_id:$('#growth-customer').value,name
    })});
  });
  $('#growth-process').onclick=e=>runAction(e.currentTarget,()=>
    api('/api/growth/journeys/process',{method:'POST',body:JSON.stringify({limit:50})}));
  $('#growth-expose').onclick=e=>runAction(e.currentTarget,()=>
    api('/api/growth/experiments/'+encodeURIComponent($('#growth-experiment').value)+'/exposures',{
      method:'POST',body:JSON.stringify({
        customer_id:$('#growth-customer').value,
        request_id:'ui_exposure_'+Date.now()+'_'+Math.random().toString(16).slice(2,8),
        surface:'growth_workspace'
      })
    }));
}
render=function growthOperationsRoute(){
  if(state.route==='growthOps')return growthOperationsPage();
  return previousGrowthRouteRender();
};
