'use strict';
// Opt-in development preview only. Normal watcher pages never load this file.
(()=>{
  const revision=document.body.dataset.uiRevision;
  if(!revision)return;
  const endpoint=new URL('api/ui-revision',document.currentScript.src);
  const badge=document.createElement('span');badge.className='dev-preview-badge';
  badge.textContent='Auto-refresh preview';badge.title='UI edits reload this page; deployments are unaffected.';
  document.querySelector('.topbar').append(badge);
  let checking=false;
  async function check(){
    if(checking||document.hidden)return;
    checking=true;
    try{
      const response=await fetch(endpoint,{cache:'no-store'});
      if(response.ok&&(await response.json()).revision!==revision){
        badge.textContent='Updating preview…';location.reload();
      }
    }catch(_){/* A development server restart must not affect the deployment. */}
    finally{checking=false;}
  }
  setInterval(check,1000);
  document.addEventListener('visibilitychange',check);
})();
