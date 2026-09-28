function init(){ $('#search-icon').innerHTML=icon('search');$('#command-search-icon').innerHTML=icon('search');$('#bell-icon').innerHTML=icon('bell');
 const nav=$('#main-nav');nav.innerHTML=NAV.map(n=>`<button class="nav-item" data-route="${n[0]}"><span class="nav-icon">${icon(n[1])}</span>${n[2]}</button>`).join('');
 $('#mobile-tabs').innerHTML=MOBILE.map(n=>`<button class="mobile-tab" data-route="${n[0]}"><i>${n[1]}</i>${n[2]}</button>`).join('');$$('[data-route]').forEach(b=>b.onclick=()=>go(b.dataset.route));
 $('#mobile-menu').onclick=()=>$('#sidebar').classList.toggle('open');$('#command-open').onclick=openCommand;document.addEventListener('keydown',e=>{if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='k'){e.preventDefault();openCommand()}if(e.key==='Escape')$('#command-modal').hidden=true});
 $('#agent-form').onsubmit=e=>{e.preventDefault();const t=$('#agent-input');if(!t.value.trim())return;toast('Agent 已接收指令（Demo 模式）');t.value=''};
 renderAgent();renderAchievement();active();render();
}
function parentRoute(route){return (typeof ROUTE_PARENT!=='undefined'&&ROUTE_PARENT[route])||route}
function active(){const parent=parentRoute(state.route);$$('[data-route]').forEach(b=>b.classList.toggle('active',b.dataset.route===parent))}
function go(route){if(route==='agent'){openAgent();return}state.route=route;location.hash=route;active();render();$('#sidebar').classList.remove('open');window.scrollTo({top:0,behavior:'instant'})}
window.addEventListener('hashchange',()=>{state.route=(location.hash||'#dashboard').slice(1);active();render()});
function openAgent(){$('#agent-sidecar').classList.add('open')}
function openCommand(){const items=[['campaignStudio','创建一个新活动','Goal → Audience → Evidence → Execution'],['opportunities','分析新用户增长机会','Opportunity Map · causal incrementality'],['experiments','打开实验中心','Assignment / Holdout / Guardrails'],['realtime','查看实时决策','Decision API / propensity / policy'],['approvals','查看待审批事项','Risk / evidence / versions'],['harness','打开 Agent Harness','Trace / tools / guardrails'],['evolution','打开 Evolution Lab','Replay → Shadow → Canary']];$('#command-modal').hidden=false;$('#command-input').focus();$('#command-results').innerHTML=items.map(x=>`<div class="command-result" data-command-route="${x[0]}"><strong>${x[1]}</strong><div style="font-size:8px;color:#8b95a5;margin-top:2px">${x[2]}</div></div>`).join('');$$('[data-command-route]').forEach(x=>x.onclick=()=>{$('#command-modal').hidden=true;go(x.dataset.commandRoute)})}
if('serviceWorker' in navigator){window.addEventListener('load',()=>navigator.serviceWorker.register('./service-worker.js').catch(()=>{}));}
document.addEventListener('DOMContentLoaded',init);
