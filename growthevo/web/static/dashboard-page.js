function dashboardTrendSeries(data,metric,granularity){
  const base=(Array.isArray(data.trend)?data.trend:DEMO.trend).map(Number).filter(Number.isFinite);
  const specs={
    revenue:{label:'增量收入',unit:'万',digits:0,values:base},
    users:{label:'增量用户',unit:'百人',digits:0,values:base.map(value=>value*.55)},
    conversion:{label:'转化率',unit:'%',digits:1,values:base.map(value=>4.2+(value-100)*.012)},
    roi:{label:'ROI',unit:'x',digits:2,values:base.map(value=>2.2+(value-100)*.0075)},
  };
  const spec=specs[metric]||specs.revenue;
  if(granularity!=='week')return spec;
  const weekly=[];
  for(let index=0;index<spec.values.length;index+=7){
    const bucket=spec.values.slice(index,index+7);
    weekly.push(bucket.reduce((sum,value)=>sum+value,0)/bucket.length);
  }
  return {...spec,values:weekly};
}

function dashboardTrendMarkup(data,metric,granularity){
  const spec=dashboardTrendSeries(data,metric,granularity);
  const latest=spec.values[spec.values.length-1]||0;
  const formatted=spec.digits?latest.toFixed(spec.digits):Math.round(latest).toLocaleString('zh-CN');
  return `<div class="chart-key"><span><i class="key-dot actual"></i>${esc(spec.label)}</span><span><i class="key-dot band"></i>预测区间</span><span><i class="key-dash"></i>上期对比</span></div>${trendChart(spec.values,{unit:spec.unit,digits:spec.digits})}<div class="tooltip-card"><strong>${granularity==='week'?'本周':'当前窗口'}</strong><div class="tooltip-line"><i></i>${esc(spec.label)}　${formatted}${esc(spec.unit)}</div><div class="tooltip-line"><i></i>趋势　持续更新</div><div class="tooltip-line blue"><i></i>证据　Incrementality</div></div>`;
}

async function dashboard(){
  const data=await api('/api/dashboard');
  state.dashboard=data;
  const kpis=Array.isArray(data.kpis)?data.kpis:[];
  const channels=Array.isArray(data.channels)?data.channels:DEMO.channels;
  const tasks=Array.isArray(data.tasks)?data.tasks:DEMO.tasks;
  const campaigns=Array.isArray(data.campaigns)?data.campaigns:DEMO.campaigns;
  const taskRoutes=['approvals','experiments','evolution','execution','campaignStudio'];
  const quickActions=[
    ['＋','red','创建一个新活动','从目标到执行，AI 全程辅助','campaignStudio'],
    ['▥','blue','分析增长机会','基于真实因果效果','opportunities'],
    ['◇','purple','生成创意内容','从策略证据进入 Campaign Studio','campaignStudio'],
    ['⌘','cyan','接入新的数据源','连接数据仓库或业务系统','integrations'],
  ];

  $('#view').innerHTML=`${head('早上好，李明','今天有 3 个关键事项需要关注。系统正在为你优化 12 个活动，预期带来 +28% 的增量收益。','<button class="primary" id="new-c" type="button">＋ 新建活动</button><button class="secondary" id="talk" type="button">◉ 与 Agent 对话</button><button class="more-btn" id="dashboard-more" type="button" aria-label="更多驾驶舱操作">•••</button>')}
  <div class="kpi-grid">${kpis.map((k,index)=>`<div class="card kpi"><div class="kpi-label">${esc(k.label)}</div><div class="kpi-value">${esc(k.formatted)}</div><div class="kpi-delta">↑ ${esc(k.delta)}<span>${esc(k.suffix||'')}</span></div>${spark(k.spark||DEMO.kpis[index]?.spark||[1,2,3],safeColor(k.color,DEMO.kpis[index]?.color||'#5361f0'))}</div>`).join('')}</div>
  <div class="dashboard-grid">
    <div class="card panel">
      <div class="panel-head"><h2>增量效果趋势</h2><button class="select-mini" id="trend-granularity" type="button">按天⌄</button></div>
      <div class="chart-tabs"><button class="active" type="button" data-dashboard-metric="revenue">增量收入</button><button type="button" data-dashboard-metric="users">增量用户</button><button type="button" data-dashboard-metric="conversion">转化率</button><button type="button" data-dashboard-metric="roi">ROI</button></div>
      <div class="trend-wrap" id="trend-chart-area"></div>
    </div>
    <div class="card panel">
      <div class="panel-head"><h2>渠道贡献</h2><button id="channel-details" type="button">查看详情 →</button></div>
      <div class="donut-layout"><div class="donut"><div class="donut-label">¥ 2,846 万<span>增量收入</span></div></div><div class="legend">${channels.map((channel,index)=>{const item=Array.isArray(channel)?channel:[channel.name,channel.share,DEMO.channels[index]?.[2]||'#9da9bc'];const color=safeColor(item[2],'#9da9bc');return `<div class="legend-row"><span class="legend-dot" style="background:${color}"></span><span>${esc(item[0])}</span><strong>${esc(item[1])}%</strong></div>`}).join('')}</div></div>
    </div>
  </div>
  <div class="lower-grid">
    <div class="card table-card">
      <div class="table-toolbar"><div class="panel-head" style="margin:0"><h2>当前运行的策略与实验</h2></div><button class="panel-link" id="all-c" type="button">查看全部 →</button></div>
      <div class="table-toolbar" style="padding-top:7px;padding-bottom:6px"><div class="table-tabs"><button class="active" type="button" data-dashboard-filter="all">全部(${campaigns.length})</button><button type="button" data-dashboard-filter="Campaign">Campaign (${campaigns.filter(item=>item.type==='Campaign').length})</button><button type="button" data-dashboard-filter="Experiment">Experiment (${campaigns.filter(item=>item.type==='Experiment').length})</button><button type="button" data-go="realtime">实时决策 →</button></div></div>
      <div id="dashboard-strategies">${campaignsTable(campaigns)}</div>
    </div>
    <div class="card panel">
      <div class="panel-head"><h2>待处理事项</h2><button id="all-a" type="button">查看全部 →</button></div>
      <div class="tasks">${tasks.map((task,index)=>{const tone=['orange','purple','green'].includes(task.tone)?task.tone:'';const route=taskRoutes[index]||'harness';return `<button class="task-row" type="button" data-go="${route}"><div class="task-icon ${tone}">${esc(task.icon)}</div><div class="task-copy"><strong>${esc(task.title)}</strong><span>${esc(task.sub)}</span></div><span class="badge-count">${esc(task.count)}</span></button>`}).join('')}</div>
    </div>
  </div>
  <div class="card quick-panel"><div class="panel-head"><h2>快速开始</h2></div><div class="quick-grid">${quickActions.map(action=>`<button class="quick-card" type="button" data-go="${action[4]}"><div class="quick-icon ${action[1]}">${action[0]}</div><div><strong>${action[2]}</strong><span>${action[3]}</span></div></button>`).join('')}</div></div>`;

  let metric='revenue';
  let granularity='day';
  const renderTrend=()=>{$('#trend-chart-area').innerHTML=dashboardTrendMarkup(data,metric,granularity)};
  renderTrend();

  $$('[data-dashboard-metric]').forEach(button=>button.onclick=()=>{
    metric=button.dataset.dashboardMetric;
    $$('[data-dashboard-metric]').forEach(item=>item.classList.toggle('active',item===button));
    renderTrend();
  });
  $('#trend-granularity').onclick=()=>{
    granularity=granularity==='day'?'week':'day';
    $('#trend-granularity').textContent=granularity==='day'?'按天⌄':'按周⌄';
    renderTrend();
  };
  $$('[data-dashboard-filter]').forEach(button=>button.onclick=()=>{
    $$('[data-dashboard-filter]').forEach(item=>item.classList.toggle('active',item===button));
    const filter=button.dataset.dashboardFilter;
    const rows=filter==='all'?campaigns:campaigns.filter(item=>item.type===filter);
    $('#dashboard-strategies').innerHTML=rows.length?campaignsTable(rows):'<div class="dashboard-empty">当前筛选下暂无运行项</div>';
    bindProductActions();
  });

  $('#talk').onclick=openAgent;
  $('#new-c').onclick=()=>go('campaignStudio');
  $('#all-c').onclick=()=>go('campaigns');
  $('#all-a').onclick=()=>go('approvals');
  $('#channel-details').onclick=()=>go('evidence');
  $('#dashboard-more').onclick=event=>{
    event.stopPropagation();
    openUtilityMenu('驾驶舱操作',[
      {label:'查看增长证据',detail:'Evidence / Support / Incrementality',action:()=>go('evidence')},
      {label:'打开数据中心',detail:'Warehouse / Decision / Outcome',action:()=>go('data')},
      {label:'工作区设置',detail:'预算、权限与安全策略',action:()=>go('settings')},
    ]);
  };
  bindProductActions();
}
