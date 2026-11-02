'use strict';
// Shared Apache-2.0 deployment viewer UI; source/asset notices accompany each distribution.
// UI preference only. Never stores deployment state or changes execution.
(()=>{
  const key='uds-deploy-theme';
  const valid=value=>value==='dark'?'dark':'light';
  function apply(value){
    const theme=valid(value);document.documentElement.dataset.theme=theme;
    document.querySelectorAll('.uds-logo-on-light').forEach(image=>{image.hidden=theme==='dark';});
    document.querySelectorAll('.uds-logo-on-dark').forEach(image=>{image.hidden=theme!=='dark';});
    const button=document.getElementById('theme-toggle');
    if(button){button.hidden=false;button.setAttribute('aria-pressed',String(theme==='dark'));button.title='Switch to '+(theme==='dark'?'light':'dark')+' mode';}
  }
  let initial='light';try{initial=valid(localStorage.getItem(key));}catch(_){/* Storage may be disabled. */}
  apply(initial); // Synchronous head script prevents a light flash on dark reload.
  document.addEventListener('DOMContentLoaded',()=>{
    apply(document.documentElement.dataset.theme);
    document.getElementById('theme-toggle').addEventListener('click',()=>{
      const next=document.documentElement.dataset.theme==='dark'?'light':'dark';apply(next);
      try{localStorage.setItem(key,next);}catch(_){/* The toggle still works without storage. */}
    });
  });
  window.addEventListener('storage',event=>{if(event.key===key||event.key===null)apply(event.newValue);});
})();
