/**
 * Modal Utility Functions
 * Replaces browser alert/confirm with custom modal dialogs
 */

/**
 * Show an alert modal
 * @param {string} title - Modal title
 * @param {string} message - Modal message body
 * @param {string} buttonText - Button text (default: "OK")
 * @returns {Promise<void>}
 */
async function showModalAlert(title, message, buttonText = 'OK') {
  return new Promise((resolve) => {
    const modal = document.createElement('div');
    modal.className = 'fixed inset-0 flex items-center justify-center bg-black/40 z-[100]';
    modal.id = 'modalAlert_' + Date.now();
    
    modal.innerHTML = `
      <div class="modal-warning-panel max-w-md w-11/12">
        <div class="modal-warning-title">${escapeHtml(title)}</div>
        <div class="modal-warning-body">
          <p>${escapeHtml(message).replace(/\n/g, '<br>')}</p>
        </div>
        <div class="modal-warning-actions">
          <button type="button" class="modal-warning-btn modal-warning-btn--muted modal-alert-ok">
            ${escapeHtml(buttonText)}
          </button>
        </div>
      </div>
    `;
    
    document.body.appendChild(modal);
    
    const okBtn = modal.querySelector('.modal-alert-ok');
    okBtn.focus();
    
    okBtn.addEventListener('click', () => {
      modal.remove();
      resolve();
    });
    
    // Close on Escape
    const handleEscape = (e) => {
      if (e.key === 'Escape') {
        document.removeEventListener('keydown', handleEscape);
        modal.remove();
        resolve();
      }
    };
    document.addEventListener('keydown', handleEscape);
  });
}

/**
 * Show a confirm modal
 * @param {string} title - Modal title
 * @param {string} message - Modal message body
 * @param {string} confirmText - Confirm button text (default: "Επιβεβαίωση")
 * @param {string} cancelText - Cancel button text (default: "Άκυρο")
 * @returns {Promise<boolean>} - true if confirmed, false if cancelled
 */
async function showModalConfirm(title, message, confirmText = 'Επιβεβαίωση', cancelText = 'Άκυρο') {
  return new Promise((resolve) => {
    const modal = document.createElement('div');
    modal.className = 'fixed inset-0 flex items-center justify-center bg-black/40 z-[100]';
    modal.id = 'modalConfirm_' + Date.now();
    
    modal.innerHTML = `
      <div class="modal-warning-panel max-w-md w-11/12">
        <div class="modal-warning-title">⚠️ ${escapeHtml(title)}</div>
        <div class="modal-warning-body">
          <p>${escapeHtml(message).replace(/\n/g, '<br>')}</p>
        </div>
        <div class="modal-warning-actions">
          <button type="button" class="modal-warning-btn modal-warning-btn--muted modal-confirm-cancel">
            ${escapeHtml(cancelText)}
          </button>
          <button type="button" class="modal-warning-btn modal-warning-btn--danger modal-confirm-ok">
            ${escapeHtml(confirmText)}
          </button>
        </div>
      </div>
    `;
    
    document.body.appendChild(modal);
    
    const confirmBtn = modal.querySelector('.modal-confirm-ok');
    const cancelBtn = modal.querySelector('.modal-confirm-cancel');
    
    cancelBtn.focus();
    
    confirmBtn.addEventListener('click', () => {
      modal.remove();
      resolve(true);
    });
    
    cancelBtn.addEventListener('click', () => {
      modal.remove();
      resolve(false);
    });
    
    // Close on Escape
    const handleEscape = (e) => {
      if (e.key === 'Escape') {
        document.removeEventListener('keydown', handleEscape);
        modal.remove();
        resolve(false);
      }
    };
    document.addEventListener('keydown', handleEscape);
  });
}

/**
 * Escape HTML special characters
 * @param {string} text - Text to escape
 * @returns {string} - Escaped HTML
 */
function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

/**
 * Create a simple wrapper for existing showAlert pattern
 * If a modal with id 'id' and data-role='modal-warning' exists, use it
 * Otherwise create a new one
 */
function showWarningModal(id, title, message, confirmText = 'Επιβεβαίωση', cancelText = 'Άκυρο') {
  const existing = document.getElementById(id);
  if (existing && existing.dataset.role === 'modal-warning') {
    const titleEl = existing.querySelector('.modal-warning-title');
    const bodyEl = existing.querySelector('.modal-warning-body');
    
    if (titleEl) titleEl.textContent = title;
    if (bodyEl) bodyEl.innerHTML = `<p>${escapeHtml(message).replace(/\n/g, '<br>')}</p>`;
    
    existing.classList.remove('hidden');
    return existing;
  }
  
  return null; // Fall back to showModalConfirm if not found
}
