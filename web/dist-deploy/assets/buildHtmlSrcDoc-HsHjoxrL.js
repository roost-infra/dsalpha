var e=[`--color-bg-page`,`--color-bg-card`,`--color-bg-elevated`,`--color-bg-input`,`--color-bg-surface`,`--color-bg-hover`,`--color-bg-subtle`,`--color-border-muted`,`--color-border-default`,`--color-border-elevated`,`--color-border-subtle`,`--color-text-primary`,`--color-text-secondary`,`--color-text-tertiary`,`--color-text-quaternary`,`--color-text-muted`,`--color-accent-primary`,`--color-accent-soft`,`--color-profit`,`--color-profit-soft`,`--color-loss`,`--color-loss-soft`,`--color-warning`,`--color-info`,`--color-success`],t=`
body > :first-child {
  background: transparent !important;
  border: none !important;
  border-radius: 0 !important;
  box-shadow: none !important;
  margin: 0 auto !important;
}`,n=`
::-webkit-scrollbar { width: 12px; height: 12px; }
::-webkit-scrollbar-track { background: transparent; margin: 4px; }
::-webkit-scrollbar-thumb { background-color: var(--color-border-elevated); background-clip: padding-box; border: 3px solid transparent; border-radius: 6px; }
::-webkit-scrollbar-thumb:hover { background-color: var(--color-text-tertiary); }`,r=/-webkit-scrollbar/i,i=`
body {
  max-width: 768px;
  margin-left: auto;
  margin-right: auto;
}
body > :first-child {
  margin-left: auto !important;
  margin-right: auto !important;
}`;function a(e){let t=/^rgba\((\d+), (\d+), (\d+), ([\d.]+)\)$/.exec(e);if(!t)return null;let n=e=>Math.min(255,Math.max(0,e)).toString(16).padStart(2,`0`);return`#${n(+t[1])}${n(+t[2])}${n(+t[3])}${n(Math.round(t[4]*255))}`}function o(e,t){if(!t)return e;t.fillStyle=`#000000`,t.fillStyle=e;let n=t.fillStyle;return t.fillStyle=`#ffffff`,t.fillStyle=e,typeof n!=`string`||n!==t.fillStyle?e:n.startsWith(`#`)?n:a(n)??e}function s(t=document.documentElement){let n=getComputedStyle(t),r=document.createElement(`canvas`).getContext(`2d`),i=e.map(e=>{let t=n.getPropertyValue(e).trim();return t?`${e}: ${o(t,r)};`:``}).filter(Boolean).join(`
  `),a=n.colorScheme;return a&&a!==`normal`?`color-scheme: ${a};\n  ${i}`:i}var c={"widget-inline":{bodyOverflow:`overflow-x: auto; overflow-y: hidden;`,layout:t},"widget-fullscreen":{bodyOverflow:`overflow: auto; height: 100%;`,layout:i}};function l(e,{html:t,data:i}){let a=s(),o=i&&Object.keys(i).length>0?`<script>window.__WIDGET_DATA__ = ${JSON.stringify(i).replace(/<\//g,`<\\/`)};<\/script>\n`:``;return`<!DOCTYPE html><html><head>
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net https://unpkg.com https://esm.sh; style-src 'unsafe-inline'; img-src data: blob:; font-src https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; connect-src https://cdnjs.cloudflare.com https://cdn.jsdelivr.net https://unpkg.com https://esm.sh;">
<style>
:root {
  ${a}
}
*, *::before, *::after { box-sizing: border-box; }
body { margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; color: var(--color-text-primary); background: transparent; ${c[e].bodyOverflow} }
${c[e].layout}\n${r.test(t)?``:n}
</style>
<script>
(function(){
  var _p=JSON.parse;
  JSON.parse=function(t,r){
    if(typeof t==='string'&&(t.indexOf('NaN')!==-1||t.indexOf('Infinity')!==-1)){
      var inString=false;
      t=t.replace(/\\\\[\\s\\S]|"|(?<!\\w)(?:NaN|-?Infinity)\\b/g,function(token){
        if(token==='"'){inString=!inString;return token;}
        return inString||token.charAt(0)==='\\\\'?token:'null';
      });
    }
    return _p.call(this,t,r);
  };
  var shown={},count=0,rendering=false;
  function showError(msg){
    if(rendering||shown[msg])return;
    shown[msg]=1;
    if(++count>5)return;
    rendering=true;
    msg=String(msg).slice(0,500);
    var root=document.body||document.documentElement;
    var d=document.createElement('div');
    d.style.cssText='margin:12px;padding:14px 16px;background:var(--color-bg-card);border:0.5px solid var(--color-border-muted);border-radius:10px;display:flex;align-items:center;gap:12px;';
    var dot=document.createElement('span');
    dot.style.cssText='flex-shrink:0;width:6px;height:6px;border-radius:50%;background:var(--color-loss);';
    var mid=document.createElement('div');
    mid.style.cssText='flex:1;min-width:0;';
    var detail=document.createElement('div');
    detail.style.cssText='font:13px/1.4 ui-monospace,SFMono-Regular,monospace;color:var(--color-text-muted);white-space:pre-wrap;word-break:break-word;';
    detail.textContent=msg;
    mid.appendChild(detail);
    var b=document.createElement('button');
    b.textContent='Fix';
    b.style.cssText='flex-shrink:0;padding:6px 14px;border-radius:8px;border:0.5px solid var(--color-border-default);background:var(--color-bg-elevated);color:var(--color-text-primary);font:500 13px/1 -apple-system,sans-serif;cursor:pointer;transition:background 0.15s;';
    b.onmouseover=function(){b.style.background='var(--color-bg-hover)';};
    b.onmouseout=function(){b.style.background='var(--color-bg-elevated)';};
    b.onclick=function(){window.sendPrompt('The widget threw an error: '+msg+'. Please fix the widget code and call ShowWidget again.');b.textContent='Sent';b.disabled=true;b.style.opacity='0.4';b.style.cursor='default';};
    d.appendChild(dot);d.appendChild(mid);d.appendChild(b);
    root.appendChild(d);
    parent.postMessage({type:'widget:resize',height:root.scrollHeight},'*');
    rendering=false;
  }
  window.onerror=function(_,__,___,____,e){showError(e&&e.message||String(_));};
  window.addEventListener('unhandledrejection',function(e){showError(e.reason&&e.reason.message||String(e.reason));});
  document.addEventListener('click',function(e){
    if(e.defaultPrevented)return;
    var a=e.target&&e.target.closest?e.target.closest('a[href]'):null;
    if(!a)return;
    var href=a.getAttribute('href')||'';
    if(href.charAt(0)==='#')return;
    if(!/^https?:/i.test(a.href)){e.preventDefault();return;}
    if(a.host===location.host)return;
    e.preventDefault();
    window.open(a.href,'_blank','noopener,noreferrer');
  });
})();
<\/script>
${o}<script>
window.sendPrompt = function(text) {
  parent.postMessage({ type: 'widget:sendPrompt', text: String(text) }, '*');
};
(function() {
  var lastH = 0;
  var pending = 0;
  function reportHeight() {
    if (!document.body) return;
    var h = document.body.scrollHeight;
    if (h !== window.innerHeight) h += window.innerHeight - document.documentElement.clientHeight;
    if (h > 0 && Math.abs(h - lastH) > 2) {
      lastH = h;
      parent.postMessage({ type: 'widget:resize', height: h }, '*');
    }
  }
  function debouncedReport() {
    if (pending) return;
    pending = requestAnimationFrame(function() {
      pending = 0;
      reportHeight();
    });
  }
  document.addEventListener('DOMContentLoaded', function() {
    var mo = new MutationObserver(debouncedReport);
    mo.observe(document.body, { childList: true, subtree: true });
    if (typeof ResizeObserver === 'function') {
      new ResizeObserver(debouncedReport).observe(document.body);
    }
    reportHeight();
  });
  var checks = [100, 300, 800, 2000, 5000];
  checks.forEach(function(ms) { setTimeout(reportHeight, ms); });
  // A container width change is a pure reflow — no DOM mutation — so the
  // observers above never see it; track the viewport and body box directly.
  window.addEventListener('resize', debouncedReport);
  window.addEventListener('message', function(e) {
    if (e.data && e.data.type === 'widget:themeUpdate' && e.data.css) {
      var style = document.querySelector('style');
      if (style) {
        style.textContent = style.textContent.replace(
          /:root\\s*\\{[^}]*\\}/,
          ':root {\\n  ' + e.data.css + '\\n}'
        );
        try { window.dispatchEvent(new Event('themechange')); } catch (err) {}
      }
    }
  });
})();
<\/script>
</head><body>${t}</body></html>`}export{s as n,l as t};