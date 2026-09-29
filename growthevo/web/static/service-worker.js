const CACHE='growthevo-shell-v6';
const SCOPE=new URL(self.registration.scope);
const asset=path=>new URL(path,SCOPE).toString();
const ASSETS=['./','./assets/styles.css','./assets/layout.css','./assets/dashboard.css','./assets/agent.css','./assets/product-pages.css','./assets/responsive.css','./assets/fidelity.css','./assets/data.js','./assets/runtime-ui.js','./assets/product-data.js','./assets/product-advanced-data.js','./assets/views.js','./assets/dashboard-page.js','./assets/pages.js','./assets/app.js','./assets/config.js','./assets/icon.svg','./manifest.webmanifest'].map(asset);
const SHELL=new Set(ASSETS);
const ROOT=asset('./');
function isApi(url){
  if(url.origin!==SCOPE.origin)return false;
  const base=SCOPE.pathname.endsWith('/')?SCOPE.pathname:SCOPE.pathname+'/';
  const apiRoot=`${base}api`;
  return url.pathname===apiRoot||url.pathname.startsWith(`${apiRoot}/`);
}
self.addEventListener('install',event=>event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(ASSETS)).then(()=>self.skipWaiting())));
self.addEventListener('activate',event=>event.waitUntil(Promise.all([caches.keys().then(keys=>Promise.all(keys.filter(key=>key!==CACHE).map(key=>caches.delete(key)))),self.clients.claim()])));
self.addEventListener('fetch',event=>{
  const request=event.request;
  if(request.method!=='GET')return;
  const url=new URL(request.url);
  // API traffic (including same-origin FastAPI and cross-origin configured APIs)
  // must retain true network/error semantics. Never cache it or replace it with HTML.
  if(url.origin!==SCOPE.origin||isApi(url))return;
  if(request.mode==='navigate'){
    event.respondWith(fetch(request).catch(()=>caches.match(ROOT)));
    return;
  }
  if(!SHELL.has(url.toString()))return;
  const network=fetch(request).then(response=>{
    if(response.ok){
      const copy=response.clone();
      event.waitUntil(caches.open(CACHE).then(cache=>cache.put(request,copy)).catch(()=>undefined));
    }
    return response;
  });
  event.respondWith(caches.match(request).then(hit=>{
    if(hit){event.waitUntil(network.then(()=>undefined).catch(()=>undefined));return hit}
    return network;
  }));
});
