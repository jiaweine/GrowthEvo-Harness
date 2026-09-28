function init(){ $('#search-icon').innerHTML=icon('search');$('#command-search-icon').innerHTML=icon('search');$('#bell-icon').innerHTML=icon('bell');
 const nav=$('#main-nav');nav.innerHTML=NAV.map(n=>`<button class="nav-item" data-route="${n[0]}"><span class="nav-icon">${icon(n[1])}</span>${n[2]}</button>`).join('');
 $('#mobile-tabs').innerHTML=MOBILE.map(n=>`<button class="mobile-tab" data-route="${n[0]}"><i>${n[1]}</i>${n[2]}</button>`).join('');$$('[data-route]').forEach(b=>b.onclick=()=>go(b.dataset.route));
 $('#mobile-menu').onclick=()=>$('#sidebar').classList.toggle('open');$('#command-open').onclick=openCommand;document.addEventListener('keydown',e=>{if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='k'){e.preventDefault();openCommand()}if(e.key==='Escape')$('#command-modal').hidden=true});
 $('#agent-form').onsubmit=e=>{e.preventDefault();const t=$('#agent-input');if(!t.value.trim())return;toast('Agent 已接收指令（Demo 模式）');t.value=''};
 renderAgent();renderAchievement();active();render();
}
function active(){$$('[data-route]').forEach(b=>b.classList.toggle('active',b.dataset.route===state.route))}
function go(route){if(route==='agent'){openAgent();return}state.route=route;location.hash=route;active();render();$('#sidebar').classList.remove('open')}
window.addEventListener('hashchange',()=>{state.route=(location.hash||'#dashboard').slice(1);active();render()});
function openAgent(){$('#agent-sidecar').classList.add('open')}
function openCommand(){$('#command-modal').hidden=false;$('#command-input').focus();$('#command-results').innerHTML=['创建一个新活动','分析新用户增长机会','查看待审批事项','打开 Agent Harness'].map(x=>`<div class="command-result">${x}</div>`).join('')}
if('serviceWorker' in navigator){window.addEventListener('load',()=>navigator.serviceWorker.register('./service-worker.js').catch(()=>{}));}
