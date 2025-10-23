// static/receipts_mode_persist.js
(function () {
  const KEY = 'UI:useReceipts'; // ίδιο κλειδί με αυτό που διαβάζουν τα υπόλοιπα scripts

  function applyMode(isReceipts) {
    // 1) persist
    try {
      localStorage.setItem(KEY, isReceipts ? '1' : '0');
    } catch (_) {}

    // 2) ενημέρωσε globals / data-attrs για να το "βλέπουν" άλλα scripts
    try {
      document.body.dataset.useReceipts = isReceipts ? '1' : '0';
      window.USE_RECEIPTS = !!isReceipts;
    } catch (_) {}

    // 3) τσέκαρε/ξετσέκαρε το switch αν υπάρχει στο DOM
    const sw = document.getElementById('useReceiptsSwitch');
    if (sw) sw.checked = !!isReceipts;

    // 4) ειδοποίησε όποιον ακούει (π.χ. autosave) ότι άλλαξε
    try {
      window.dispatchEvent(
        new CustomEvent('useReceiptsChange', { detail: { value: !!isReceipts } })
      );
    } catch (_) {}
  }

  function restoreOnLoad() {
    let initial = false;
    try {
      const v = localStorage.getItem(KEY);
      if (v !== null) initial = (v === '1');
    } catch (_) {}

    applyMode(initial);

    // δέσε listener στο switch για να γράφουμε αμέσως το νέο state
    const sw = document.getElementById('useReceiptsSwitch');
    if (sw && !sw._persistBound) {
      sw._persistBound = true;
      sw.addEventListener('change', (e) => applyMode(!!e.target.checked));
    }

    // πριν από κάθε submit αποθήκευσε ξανά το state (safety)
    const form = document.getElementById('markSearchForm');
    if (form && !form._persistBound) {
      form._persistBound = true;
      form.addEventListener('submit', () => {
        const sw2 = document.getElementById('useReceiptsSwitch');
        if (sw2) {
          try { localStorage.setItem(KEY, sw2.checked ? '1' : '0'); } catch (_) {}
        }
      });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', restoreOnLoad, { once: true });
  } else {
    restoreOnLoad();
  }
})();
