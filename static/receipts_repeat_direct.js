/* receipts_repeat_direct.js — Bypass summary modal for receipts when repeat is ON */
(function(){
  if (window.__rc_direct_bypass__) return;
  window.__rc_direct_bypass__ = true;

  function $id(id){ return document.getElementById(id); }
  function lsGet(k,d){ try{const v=localStorage.getItem(k);return v==null?d:v;}catch(_){return d;} }
  function lsSet(k,v){ try{localStorage.setItem(k,v);}catch(_){ } }
  function ssGet(k){ try{return sessionStorage.getItem(k);}catch(_){return null;} }
  function ssSet(k,v){ try{sessionStorage.setItem(k,v);}catch(_){ } }
  function ssDel(k){ try{sessionStorage.removeItem(k);}catch(_){ } }
  function onceKey(mark){ return 'rc-direct:' + String(mark||'').trim(); }
  function isReceipts(){ try{var sw=$id('useReceiptsSwitch'); if(sw) return !!sw.checked;}catch(_){}
                         return lsGet('UI:useReceipts','0')==='1'; }
  function isRepeat(){   try{var rs=$id('repeatEntrySwitch'); if(rs) return !!rs.checked;}catch(_){}
                         return lsGet('REPEAT:enabled','0')==='1'; }
  function parseSummary(){
    var el=$id('summaryJsonInput');
    if(!el || !el.value || el.value==='{}' || el.value==='null') return null;
    try{ return JSON.parse(el.value); }catch(_){ return null; }
  }
  function isReceiptSummary(s){
    if(!s||typeof s!=='object') return false;
    if(s.is_receipt===true) return true;
    var t=String(s.type_name||s.type||'').toLowerCase();
    if(t.includes('απόδει') || t.includes('receipt')) return true;
    var ui=String(s.ui_hint||'').toLowerCase();
    if(ui.includes('λήφθηκε')&&ui.includes('αποδεί')) return true;
    return false;
  }
  function hasLines(s){ try{ return Array.isArray(s.lines)&&s.lines.length>0; }catch(_){ return false; } }
  function normalizeReceipt(s){
    try{
      s.is_receipt=true;
      s.category=s.category||'αποδειξακια';
      s.characteristic=s.characteristic||'αποδειξακια';
      if(!Array.isArray(s.lines)) s.lines=[];
      s.lines=s.lines.map(function(l){ l=l||{}; l.category='αποδειξακια'; return l; });
    }catch(_){}
    return s;
  }
  function submitViaForm(s){
    var form=$id('saveSummaryForm');
    var input=$id('summaryJsonInput');
    if(form && input){
      input.value=JSON.stringify(s);
      if(typeof form.requestSubmit==='function') form.requestSubmit(); else form.submit();
      return true;
    }
    return false;
  }
  function submitViaFetch(s){
    try{
      return fetch('/save_summary',{
        method:'POST',
        headers:{'content-type':'application/x-www-form-urlencoded'},
        body:'summary_json='+encodeURIComponent(JSON.stringify(s)),
        credentials:'same-origin'
      }).then(function(r){ if(!r.ok) throw new Error('save failed'); return r.text(); });
    }catch(e){ return Promise.reject(e); }
  }
  function afterSubmit(mark){
    lsSet('UI:useReceipts','1');
    ssDel(onceKey(mark));
    try{
      var url=location.pathname+'?use_receipts=1';
      location.replace(url);
    }catch(_){ location.reload(); }
  }
  var trying=false;
  function tryDirect(){
    if(trying) return;
    if(!isReceipts()||!isRepeat()) return;

    var s=parseSummary();
    if(!s||!isReceiptSummary(s)||!hasLines(s)) return;

    var mark=String(s.mark||s.MARK||'').trim();
    if(!mark) return;
    var k=onceKey(mark);
    if(ssGet(k)) return;
    ssSet(k,'1');
    trying=true;

    s=normalizeReceipt(s);
    if(submitViaForm(s)){
      setTimeout(function(){ afterSubmit(mark); }, 50);
    }else{
      submitViaFetch(s).then(function(){ afterSubmit(mark); })
        .catch(function(){ trying=false; ssDel(k); });
    }
  }

  function patchOpenModal(){
    var old = window.openModal;
    window.openModal = function(id){
      if(id==='summaryModal' && isReceipts() && isRepeat()){
        tryDirect();
        return;
      }
      if(typeof old==='function') return old.apply(this, arguments);
    };
  }

  document.addEventListener('DOMContentLoaded', function(){
    try{
      if(lsGet('UI:useReceipts','0')==='1'){
        var sw=$id('useReceiptsSwitch');
        if(sw && !sw.checked){ sw.checked=true; try{ sw.dispatchEvent(new Event('change',{bubbles:true})); }catch(_){ } }
      }
    }catch(_){}

    tryDirect();
    setTimeout(tryDirect, 0);
    setTimeout(tryDirect, 250);
    setTimeout(tryDirect, 750);

    var el=$id('summaryJsonInput');
    if(el){
      var prev=el.value;
      setInterval(function(){
        if(el.value!==prev){ prev=el.value; tryDirect(); }
      }, 200);
    }

    var r1=$id('useReceiptsSwitch'), r2=$id('repeatEntrySwitch');
    if(r1) r1.addEventListener('change', function(){ if(this.checked) setTimeout(tryDirect,10); });
    if(r2) r2.addEventListener('change', function(){ if(this.checked) setTimeout(tryDirect,10); });

    patchOpenModal();
  });
})();
