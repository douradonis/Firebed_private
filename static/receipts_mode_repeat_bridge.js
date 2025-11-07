// static/receipts_mode_repeat_bridge.js
(function () {
  var KEY_USE_RECEIPTS = 'UI:useReceipts';       // '1' | '0'
  var KEY_REPEAT_ENABLED = 'REPEAT:enabled';     // '1' | '0'
  var KEY_REPEAT_MAPPING = 'REPEAT:mapping';     // JSON string
  var KEY_AUTO_SUBMIT   = 'UI:autoSubmit';       // optional, if you already use it elsewhere

  function boolToFlag(b){ return b ? '1' : '0'; }
  function flagToBool(v){ return v === '1' || v === 1 || v === true || v === 'true'; }

  function setUseReceiptsState(on) {
    try { localStorage.setItem(KEY_USE_RECEIPTS, boolToFlag(on)); } catch (_){}
    try {
      window.USE_RECEIPTS = !!on;
      document.body && (document.body.dataset.useReceipts = boolToFlag(on));
      var sw = document.getElementById('useReceiptsSwitch');
      if (sw) sw.checked = !!on;
      window.dispatchEvent(new CustomEvent('useReceiptsChange', { detail: { value: !!on } }));
    } catch (_){}
  }

  function setRepeatState(on, mapping) {
    try { localStorage.setItem(KEY_REPEAT_ENABLED, boolToFlag(on)); } catch (_){}
    try { localStorage.setItem(KEY_REPEAT_MAPPING, JSON.stringify(mapping || {})); } catch (_){}
    try {
      window.REPEAT_ENABLED = !!on;
      window.REPEAT_MAPPING = mapping || {};
      document.body && (document.body.dataset.repeatEnabled = boolToFlag(on));
      window.dispatchEvent(new CustomEvent('repeatStateChange', { detail: { enabled: !!on, mapping: window.REPEAT_MAPPING } }));
    } catch (_){}
  }

  function getInitialUseReceipts() {
    try {
      var usp = new URLSearchParams(location.search);
      if (usp.has('use_receipts')) {
        return usp.get('use_receipts') === '1';
      }
    } catch(_){}
    try {
      var v = localStorage.getItem(KEY_USE_RECEIPTS);
      if (v !== null) return flagToBool(v);
    } catch(_){}
    var sw = document.getElementById('useReceiptsSwitch');
    return !!(sw && sw.checked);
  }

  function getInitialRepeatFromDOMOrStorage() {
    var sw = document.getElementById('repeatEntrySwitch');
    var domVal = sw ? !!sw.checked : null;
    var stored = null;
    try {
      var v = localStorage.getItem(KEY_REPEAT_ENABLED);
      if (v !== null) stored = flagToBool(v);
    } catch(_){}
    var enabled = (domVal !== null) ? domVal : !!stored;

    var mapping = {};
    try {
      var m = localStorage.getItem(KEY_REPEAT_MAPPING);
      if (m) mapping = JSON.parse(m);
    } catch(_){}
    return { enabled: !!enabled, mapping: mapping || {} };
  }

  function hookSwitches() {
    var swRec = document.getElementById('useReceiptsSwitch');
    if (swRec && !swRec.__boundUseReceipts) {
      swRec.__boundUseReceipts = true;
      swRec.addEventListener('change', function (e) {
        setUseReceiptsState(!!e.target.checked);
      });
    }
    var swRep = document.getElementById('repeatEntrySwitch');
    if (swRep && !swRep.__boundRepeat) {
      swRep.__boundRepeat = true;
      swRep.addEventListener('change', function (e) {
        setRepeatState(!!e.target.checked, window.REPEAT_MAPPING || {});
      });
    }
  }

  function hookFormSubmit() {
    var form = document.getElementById('markSearchForm');
    if (form && !form.__boundPersist) {
      form.__boundPersist = true;
      form.addEventListener('submit', function () {
        try {
          var swRec = document.getElementById('useReceiptsSwitch');
          if (swRec) localStorage.setItem(KEY_USE_RECEIPTS, boolToFlag(!!swRec.checked));
          var swRep = document.getElementById('repeatEntrySwitch');
          if (swRep) localStorage.setItem(KEY_REPEAT_ENABLED, boolToFlag(!!swRep.checked));
          window.dispatchEvent(new Event('rc:markSubmit'));
        } catch (_){}
      });
    }
  }

  function init() {
    var useRec = getInitialUseReceipts();
    setUseReceiptsState(useRec);

    var rep = getInitialRepeatFromDOMOrStorage();
    setRepeatState(rep.enabled, rep.mapping);

    try {
      console.log('[BRIDGE] useReceipts=%s repeat=%s', useRec, rep.enabled);
    } catch (_){}

    hookSwitches();
    hookFormSubmit();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})(); 
