const authConfig=(config&&config.AUTH)||{};
const AUTH_SESSION_KEY='growthevo.oidc.session.v1';
const AUTH_TRANSACTION_KEY='growthevo.oidc.transaction.v1';
const AUTH_TRANSACTION_MAX_AGE_MS=10*60*1000;
const AUTH_EXPIRY_SKEW_SECONDS=30;
let authSession=null;
let authInitializationError=null;

function authIsConfigured(){
  return Boolean(authConfig&&authConfig.ENABLED===true&&authConfig.AUTHORIZATION_ENDPOINT&&authConfig.TOKEN_ENDPOINT&&authConfig.CLIENT_ID);
}

function authParseJwtExpiry(token){
  const parts=String(token||'').split('.');
  if(parts.length!==3)return null;
  try{
    const normalized=parts[1].replace(/-/g,'+').replace(/_/g,'/');
    const padded=normalized+'='.repeat((4-normalized.length%4)%4);
    const payload=JSON.parse(atob(padded));
    const exp=Number(payload&&payload.exp);
    return Number.isFinite(exp)&&exp>0?exp:null;
  }catch(_){return null;}
}

function authSessionValid(session){
  if(!session||typeof session.access_token!=='string'||!session.access_token.trim())return false;
  if(session.token_type&&String(session.token_type).toLowerCase()!=='bearer')return false;
  const expiresAt=Number(session.expires_at||0);
  return !expiresAt||expiresAt>(Date.now()/1000)+AUTH_EXPIRY_SKEW_SECONDS;
}

function authRestoreSession(){
  try{
    const raw=sessionStorage.getItem(AUTH_SESSION_KEY);
    const parsed=raw?JSON.parse(raw):null;
    if(authSessionValid(parsed)){authSession=parsed;return authSession;}
  }catch(_){}
  sessionStorage.removeItem(AUTH_SESSION_KEY);
  authSession=null;
  return null;
}

function authStoreSession(payload){
  const accessToken=typeof payload.access_token==='string'?payload.access_token.trim():'';
  const tokenType=typeof payload.token_type==='string'&&payload.token_type.trim()?payload.token_type.trim():'Bearer';
  if(!accessToken||tokenType.toLowerCase()!=='bearer')throw Error('identity provider returned an invalid bearer token');
  const expiresIn=Number(payload.expires_in);
  const jwtExpiry=authParseJwtExpiry(accessToken);
  const expiresAt=Number.isFinite(expiresIn)&&expiresIn>0?Math.floor(Date.now()/1000+expiresIn):jwtExpiry;
  authSession={access_token:accessToken,token_type:'Bearer',expires_at:expiresAt||null};
  sessionStorage.setItem(AUTH_SESSION_KEY,JSON.stringify(authSession));
  syncAuthUi();
  return authSession;
}

function authClearSession(reason='cleared'){
  sessionStorage.removeItem(AUTH_SESSION_KEY);
  authSession=null;
  if(document.body)document.body.dataset.authState=reason==='unauthorized'?'required':'anonymous';
  syncAuthUi();
}

function authIsAuthenticated(){
  if(!authSessionValid(authSession))authRestoreSession();
  return authSessionValid(authSession);
}

function authAuthorizationValue(){return authIsAuthenticated()?'Bearer '+authSession.access_token:'';}
function authRedirectUri(){return location.origin+location.pathname;}

function authRandomUrlSafe(byteLength=32){
  const bytes=new Uint8Array(byteLength);
  crypto.getRandomValues(bytes);
  let binary='';
  for(const byte of bytes)binary+=String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
}

async function authPkceChallenge(verifier){
  const bytes=new TextEncoder().encode(verifier);
  const digest=await crypto.subtle.digest('SHA-256',bytes);
  let binary='';
  for(const byte of new Uint8Array(digest))binary+=String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
}

function authScrubCallbackParams(){
  const url=new URL(location.href);
  for(const key of ['code','state','error','error_description','iss','session_state'])url.searchParams.delete(key);
  const query=url.searchParams.toString();
  history.replaceState(null,'',url.pathname+(query?'?'+query:'')+(url.hash||''));
}

async function beginOidcLogin(){
  if(!authIsConfigured()){toast('当前部署尚未配置生产登录');return;}
  const verifier=authRandomUrlSafe(48);
  const stateValue=authRandomUrlSafe(24);
  const challenge=await authPkceChallenge(verifier);
  sessionStorage.setItem(AUTH_TRANSACTION_KEY,JSON.stringify({state:stateValue,verifier,created_at:Date.now(),return_hash:location.hash||'#dashboard'}));
  const target=new URL(authConfig.AUTHORIZATION_ENDPOINT);
  target.searchParams.set('response_type','code');
  target.searchParams.set('client_id',authConfig.CLIENT_ID);
  target.searchParams.set('redirect_uri',authRedirectUri());
  target.searchParams.set('scope',authConfig.SCOPE||'openid profile email');
  target.searchParams.set('state',stateValue);
  target.searchParams.set('code_challenge',challenge);
  target.searchParams.set('code_challenge_method','S256');
  if(authConfig.AUDIENCE)target.searchParams.set('audience',authConfig.AUDIENCE);
  location.assign(target.toString());
}

async function authExchangeCode(code,transaction){
  const body=new URLSearchParams({grant_type:'authorization_code',code,client_id:authConfig.CLIENT_ID,redirect_uri:authRedirectUri(),code_verifier:transaction.verifier});
  const response=await fetch(authConfig.TOKEN_ENDPOINT,{method:'POST',headers:{'Accept':'application/json','Content-Type':'application/x-www-form-urlencoded'},body:body.toString(),cache:'no-store',credentials:'omit',referrerPolicy:'no-referrer'});
  if(!response.ok)throw Error('identity provider token exchange failed with HTTP '+response.status);
  return authStoreSession(await response.json());
}

async function initializeAuthSession(){
  authRestoreSession();
  if(!authIsConfigured()){syncAuthUi();return authSession;}
  const params=new URLSearchParams(location.search);
  const providerError=params.get('error');
  const code=params.get('code');
  if(providerError){sessionStorage.removeItem(AUTH_TRANSACTION_KEY);authScrubCallbackParams();throw Error(params.get('error_description')||providerError);}
  if(!code){syncAuthUi();return authSession;}
  let transaction=null;
  try{transaction=JSON.parse(sessionStorage.getItem(AUTH_TRANSACTION_KEY)||'null')}catch(_){}
  sessionStorage.removeItem(AUTH_TRANSACTION_KEY);
  const returnedState=params.get('state')||'';
  if(!transaction||typeof transaction.verifier!=='string'||typeof transaction.state!=='string'||transaction.state!==returnedState||Date.now()-Number(transaction.created_at||0)>AUTH_TRANSACTION_MAX_AGE_MS){
    authScrubCallbackParams();
    throw Error('identity login state validation failed');
  }
  try{
    await authExchangeCode(code,transaction);
    const returnHash=typeof transaction.return_hash==='string'&&transaction.return_hash.startsWith('#')?transaction.return_hash:'#dashboard';
    const url=new URL(location.href);
    for(const key of ['code','state','error','error_description','iss','session_state'])url.searchParams.delete(key);
    const query=url.searchParams.toString();
    history.replaceState(null,'',url.pathname+(query?'?'+query:'')+returnHash);
    return authSession;
  }catch(error){authScrubCallbackParams();throw error;}
}

function authProfileLabel(){
  if(useDemo)return '李明 · 增长负责人';
  if(authIsAuthenticated())return '生产工作区 · 已认证';
  return authIsConfigured()?'生产工作区 · 需要登录':'生产工作区 · 登录未配置';
}

function authProfileMenuItems(){
  if(useDemo)return [];
  if(authIsAuthenticated())return [{label:'退出生产工作区',detail:'清除当前标签页的登录会话',action:()=>{authClearSession('logout');state.dashboard=null;location.reload();}}];
  if(authIsConfigured())return [{label:'登录生产工作区',detail:'使用组织身份安全登录',action:()=>{void beginOidcLogin()}}];
  return [{label:'生产登录未配置',detail:'部署方需要配置组织登录入口',action:()=>toast('生产登录尚未配置')}];
}

function syncAuthUi(){
  if(!document.body)return;
  const stateValue=useDemo?'demo':authIsAuthenticated()?'authenticated':authIsConfigured()?'anonymous':'unconfigured';
  document.body.dataset.authState=stateValue;
  const profile=document.querySelector('#profile-open');
  if(profile){
    profile.textContent=stateValue==='authenticated'?'✓':'L';
    profile.title=authProfileLabel();
    profile.setAttribute('aria-label',stateValue==='authenticated'?'打开已认证账户菜单':'打开账户菜单');
  }
  const userCopy=document.querySelector('.user-card .workspace-copy');
  if(userCopy&&!useDemo){
    const strong=userCopy.querySelector('strong');
    const span=userCopy.querySelector('span');
    if(strong)strong.textContent=stateValue==='authenticated'?'已认证用户':'生产工作区';
    if(span)span.textContent=stateValue==='authenticated'?'组织身份已验证':'需要组织登录';
  }
}

const authReadyPromise=initializeAuthSession().catch(error=>{authInitializationError=error;authClearSession('unauthorized');syncAuthUi();return null;});
window.addEventListener('DOMContentLoaded',()=>{void authReadyPromise.finally(syncAuthUi)});
