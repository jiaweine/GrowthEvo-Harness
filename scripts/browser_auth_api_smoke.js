(() => {
  if (!new URLSearchParams(window.location.search).has('auth-api-smoke')) return;
  const TOKEN='browser-smoke-token';
  const SESSION_KEY='growthevo.oidc.session.v1';
  sessionStorage.setItem(SESSION_KEY,JSON.stringify({access_token:TOKEN,token_type:'Bearer',expires_at:null}));
  const nativeFetch=window.fetch.bind(window);
  window.__authSmokeSawBearer=false;
  window.fetch=async (input,init={})=>{
    const url=typeof input==='string'?input:input.url;
    const headers=new Headers(input instanceof Request?input.headers:init.headers||{});
    if(url.includes('/api/')&&headers.get('Authorization')==='Bearer '+TOKEN)window.__authSmokeSawBearer=true;
    if(url.includes('/api/auth-smoke-401'))return new Response(JSON.stringify({detail:'valid bearer token required'}),{status:401,headers:{'Content-Type':'application/json'}});
    return nativeFetch(input,init);
  };
  const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  const failures=[];
  const check=(condition,message)=>{if(!condition)failures.push(message)};
  const waitFor=async(predicate,timeoutMs=5000)=>{const started=performance.now();while(performance.now()-started<timeoutMs){if(predicate())return true;await sleep(30);}return false;};
  const finish=()=>{const marker=document.createElement('div');marker.id='auth-api-smoke';marker.textContent=failures.length?'AUTH_API_SMOKE_FAIL: '+failures.join(' | '):'AUTH_API_SMOKE_PASS';document.body.appendChild(marker);document.body.dataset.authApiSmoke=failures.length?'fail':'pass';};
  window.addEventListener('DOMContentLoaded',()=>{
    setTimeout(()=>void (async()=>{
      await authReadyPromise;
      check(authIsConfigured(),'browser auth config is not enabled');
      check(authIsAuthenticated(),'sessionStorage bearer session was not restored');
      check(document.body.dataset.authState==='authenticated','unexpected auth UI state: '+document.body.dataset.authState);
      const ready=await waitFor(()=>runtimeAvailability==='ready',5000);
      check(ready,'runtime not ready before auth request: '+runtimeAvailability);
      await api('/api/dashboard');
      check(window.__authSmokeSawBearer,'runtime API request did not include Bearer token');
      let authError=null;
      try{await api('/api/auth-smoke-401')}catch(error){authError=error}
      check(Boolean(authError),'synthetic 401 did not reject');
      check(authError&&authError.code==='GROWTHEVO_AUTH_REQUIRED','unexpected 401 error code: '+(authError&&authError.code));
      check(!authIsAuthenticated(),'401 did not clear the stale bearer session');
      renderAuthRequired(authError);
      check(runtimeAvailability==='auth_required','401 did not move runtime into auth_required: '+runtimeAvailability);
      check(Boolean(document.querySelector('#runtime-login')),'auth-required UI did not expose a login action');
      check(!document.querySelector('#view').textContent.includes('GrowthEvo API 暂不可用'),'auth expiry was misreported as API outage');
      finish();
    })().catch(error=>{failures.push(error&&error.message?error.message:String(error));finish();}),0);
  });
})();
