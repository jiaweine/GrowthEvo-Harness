const $=(s,r=document)=>r.querySelector(s),$$=(s,r=document)=>[...r.querySelectorAll(s)];
const config=window.GROWTHEVO_CONFIG||{MODE:'auto',API_BASE:''};
const isGitHubPages=location.hostname.endsWith('.github.io');
const useDemo=config.MODE==='demo'||(config.MODE==='auto'&&isGitHubPages&&!config.API_BASE);
const state={route:(location.hash||'#dashboard').slice(1),dashboard:null};
const fmt=n=>new Intl.NumberFormat('zh-CN').format(n);const esc=s=>String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[c]));
const toast=m=>{const e=$('#toast');e.textContent=m;e.classList.add('show');setTimeout(()=>e.classList.remove('show'),2200)};
const icon=(name)=>{const paths={home:'<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h14V9.5"/><path d="M9 21v-7h6v7"/>',strategy:'<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M8 4v4M16 4v4M4 10h16M8 14h3M8 17h5"/>',agent:'<path d="M12 3 14 7l4 2-4 2-2 4-2-4-4-2 4-2 2-4Z"/><path d="m18 14 .9 1.9L21 17l-2.1 1.1L18 20l-1.1-1.9L15 17l1.9-1.1L18 14Z"/>',evidence:'<path d="M12 3 4.5 7v5c0 4.7 3.1 7.6 7.5 9 4.4-1.4 7.5-4.3 7.5-9V7L12 3Z"/><path d="m9 12 2 2 4-4"/>',runtime:'<circle cx="6" cy="12" r="2"/><circle cx="18" cy="7" r="2"/><circle cx="18" cy="17" r="2"/><path d="m8 11 8-3M8 13l8 3"/>',data:'<path d="M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3Z"/><path d="M4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/>',integrations:'<path d="M8 4H5a2 2 0 0 0-2 2v3M16 4h3a2 2 0 0 1 2 2v3M8 20H5a2 2 0 0 1-2-2v-3M16 20h3a2 2 0 0 0 2-2v-3"/><rect x="8" y="8" width="8" height="8" rx="2"/>',settings:'<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.83 2.83-.06-.06a1.7 1.7 0 0 0-1.88-.34 1.7 1.7 0 0 0-1.03 1.56V21h-4v-.09A1.7 1.7 0 0 0 9 19.36a1.7 1.7 0 0 0-1.88.34l-.06.06-2.83-2.83.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-1.56-1.03H3v-4h.09A1.7 1.7 0 0 0 4.64 9a1.7 1.7 0 0 0-.34-1.88l-.06-.06 2.83-2.83.06.06A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1.03-1.56V3h4v.09A1.7 1.7 0 0 0 15 4.64a1.7 1.7 0 0 0 1.88-.34l.06-.06 2.83 2.83-.06.06A1.7 1.7 0 0 0 19.4 9c.63.24 1.04.85 1.04 1.52V10h.56v4h-.57c0 .67-.4 1.28-1.03 1.52Z"/>',search:'<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/>',bell:'<path d="M18 8a6 6 0 1 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9"/><path d="M10 21h4"/>'};return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round">${paths[name]||paths.home}</svg>`};

const NAV=[['dashboard','home','增长驾驶舱'],['campaigns','strategy','策略与执行'],['agent','agent','Growth Agent'],['evidence','evidence','智能与证据'],['harness','runtime','Agent Runtime'],['data','data','数据中心'],['integrations','integrations','集成与渠道'],['settings','settings','设置']];
const MOBILE=[['dashboard','⌂','首页'],['campaigns','▦','活动'],['agent','✦','Agent'],['harness','⌘','运行'],['settings','⚙','设置']];

const DEMO={
 kpis:[
  {id:'incremental_revenue',label:'增量收入',formatted:'¥ 2,846,320',delta:'+23.4%',suffix:'较上月',color:'#4ba2ff',spark:[18,20,19,25,29,28,35,33,39,43,41,52]},
  {id:'incremental_profit',label:'增量利润',formatted:'¥ 1,284,610',delta:'+26.1%',suffix:'',color:'#8a56f7',spark:[11,12,17,16,22,24,23,31,34,33,40,48]},
  {id:'incremental_roi',label:'Incremental ROI',formatted:'4.42x',delta:'+0.8x',suffix:'',color:'#14b88a',spark:[17,22,20,28,32,31,39,42,39,48,45,54]},
  {id:'waste_avoided',label:'无效触达节省',formatted:'¥ 843,210',delta:'+31.8%',suffix:'',color:'#f6a23b',spark:[8,9,12,11,17,18,23,22,27,31,30,39]}
 ],
 trend:[108,104,98,112,128,126,139,135,148,153,146,160,172,185,181,190,208,212,224,236,231,246,252,260,257,269,278,281,286,287,302],
 channels:[['App Push',32,'#675ef4'],['站内消息',24,'#756dff'],['Email',18,'#65a4ef'],['短信',12,'#45bed9'],['广告',9,'#20b88c'],['微信',4,'#4caec6'],['其他',1,'#9da9bc']],
 campaigns:[
  {name:'新用户首购提升计划',type:'Campaign',status:'运行中',goal:'首购率',population:128421,started_at:'12-18',expected_lift:'+12.1%'},
  {name:'沉默用户召回',type:'Experiment',status:'5% Canary',goal:'7日活跃',population:320510,started_at:'12-16',expected_lift:'+8.7%'},
  {name:'高价值用户加购',type:'Campaign',status:'运行中',goal:'加购率',population:86210,started_at:'12-12',expected_lift:'+5.3%'},
  {name:'节日礼品推荐',type:'Experiment',status:'分析中',goal:'GMV',population:520331,started_at:'12-10',expected_lift:'-1.2%'},
  {name:'会员升级激励',type:'Campaign',status:'已暂停',goal:'会员转化',population:72881,started_at:'12-08',expected_lift:'+9.4%'}
 ],
 tasks:[
  {icon:'◎',tone:'orange',title:'2 个活动待审批',sub:'预计覆盖 186,421 人，预算 ¥286,000',count:2},
  {icon:'▣',tone:'purple',title:'实验结果已出',sub:'新用户首购激励（7日）',count:3},
  {icon:'◉',tone:'green',title:'模型漂移需新训练',sub:'数据分布发生变化',count:1},
  {icon:'◷',tone:'orange',title:'渠道发送异常',sub:'短信通道失败率上升',count:1},
  {icon:'▣',tone:'purple',title:'新创意待审核',sub:'已生成 12 条 Push 文案',count:12}
 ],
 approvals:[
  {id:'apr_281',title:'新用户首购计划扩大至 25%',affected_users:186421,budget:286000,incremental_value:724000,evidence_tier:'A',max_risk:'退订 +0.08pp',uncertainty:'95% CI +5.9 ~ +10.7pp',status:'pending'},
  {id:'apr_404',title:'Creative Set #12 发布到 Email',affected_users:72881,budget:62000,incremental_value:134000,evidence_tier:'B',max_risk:'brand claim review',uncertainty:'OPE SE 0.0041',status:'pending'}
 ],
 opportunities:[
  {segment:'新用户 0–7 天未首购',population:864210,best_action:'首单免邮',incremental_lift_pp:8.4,incremental_value:1840000,support:.91,evidence_tier:'A',freshness:'3 分钟前'},
  {segment:'沉默 30–60 天会员',population:320510,best_action:'召回 Push + 商品卡',incremental_lift_pp:4.7,incremental_value:612000,support:.89,evidence_tier:'A',freshness:'7 分钟前'},
  {segment:'高意向加购未支付',population:86210,best_action:'NO_TREATMENT / 免邮',incremental_lift_pp:5.3,incremental_value:438000,support:.84,evidence_tier:'B',freshness:'2 分钟前'}
 ]
};

async function api(path,options={}){if(useDemo) return demoApi(path,options);try{const r=await fetch(`${config.API_BASE||''}${path}`,{headers:{'Content-Type':'application/json',...(options.headers||{})},...options});if(!r.ok)throw Error(await r.text());return await r.json()}catch(e){console.warn('API unavailable; using demo mode',e);return demoApi(path,options)}}
function demoApi(path,options={}){if(path.includes('/dashboard'))return Promise.resolve({...DEMO,kpis:DEMO.kpis});if(path.includes('/opportunities'))return Promise.resolve(DEMO.opportunities);if(path.includes('/campaigns'))return Promise.resolve(DEMO.campaigns);if(path.includes('/approvals'))return Promise.resolve(DEMO.approvals);if(path.includes('/harness/runs'))return Promise.resolve([{id:'run_9081',task:'Create 5% canary for dormant users',success:true,policy:'pass',evidence:'A',tool_calls:8,cost:.84,latency_ms:8240,outcome:'approval_requested'}]);if(path.includes('/agent/plan'))return Promise.resolve({run_id:'demo-run',status:'proposal_ready'});return Promise.resolve({ok:true,status:'demo'})}
