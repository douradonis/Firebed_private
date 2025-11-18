/**
 * Modern Dialog/Modal utilities for the application
 * Provides openModal, closeModal, showConfirmDialog, showAlertDialog functions
 */

/**
 * Open a modal by adding 'active' class
 * @param {string} selector - CSS selector of the modal element
 */
function openModal(selector) {
  const modal = document.querySelector(selector);
  if (modal) {
    modal.classList.add('active');
  }
}

/**
 * Close a modal by removing 'active' class
 * @param {string} selector - CSS selector of the modal element
 */
function closeModal(selector) {
  const modal = document.querySelector(selector);
  if (modal) {
    modal.classList.remove('active');
  }
}

/**
 * Show a confirmation dialog
 * @param {string} title - Dialog title
 * @param {string} message - Dialog message
 * @param {Function} onConfirm - Callback when user clicks "Confirm"
 * @param {Function} onCancel - Callback when user clicks "Cancel"
 */
function showConfirmDialog(title, message, onConfirm, onCancel) {
  // Remove existing confirmation dialog if present
  const existing = document.querySelector('.confirm-dialog-overlay');
  if (existing) {
    existing.remove();
  }

  // Create dialog structure
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay active confirm-dialog-overlay';
  overlay.innerHTML = `
    <div class="modal-panel confirm-dialog-panel">
      <div class="modal-header">
        <h2 class="modal-title">${escapeHtml(title)}</h2>
        <button class="modal-close" type="button">&times;</button>
      </div>
      <div class="modal-body">
        <p>${escapeHtml(message)}</p>
      </div>
      <div class="modal-footer">
        <button class="modal-btn modal-btn--secondary cancel-btn" type="button">Ακύρωση</button>
        <button class="modal-btn modal-btn--primary confirm-btn" type="button">Επιβεβαίωση</button>
      </div>
    </div>
  `;

  document.body.appendChild(overlay);

  const confirmBtn = overlay.querySelector('.confirm-btn');
  const cancelBtn = overlay.querySelector('.cancel-btn');
  const closeBtn = overlay.querySelector('.modal-close');

  const cleanup = () => {
    overlay.remove();
  };

  confirmBtn.addEventListener('click', () => {
    cleanup();
    if (onConfirm) onConfirm();
  });

  cancelBtn.addEventListener('click', () => {
    cleanup();
    if (onCancel) onCancel();
  });

  closeBtn.addEventListener('click', () => {
    cleanup();
    if (onCancel) onCancel();
  });

  // Close on overlay click
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) {
      cleanup();
      if (onCancel) onCancel();
    }
  });

  // Close on Escape
  const escapeHandler = (e) => {
    if (e.key === 'Escape') {
      overlay.removeEventListener('keydown', escapeHandler);
      cleanup();
      if (onCancel) onCancel();
    }
  };
  overlay.addEventListener('keydown', escapeHandler);
}

/**
 * Show an alert dialog
 * @param {string} title - Dialog title
 * @param {string} message - Dialog message
 * @param {Function} onOk - Callback when user clicks "OK"
 */
function showAlertDialog(title, message, onOk) {
  // Remove existing alert dialog if present
  const existing = document.querySelector('.alert-dialog-overlay');
  if (existing) {
    existing.remove();
  }

  // Create dialog structure
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay active alert-dialog-overlay';
  overlay.innerHTML = `
    <div class="modal-panel alert-dialog-panel">
      <div class="modal-header">
        <h2 class="modal-title">${escapeHtml(title)}</h2>
        <button class="modal-close" type="button">&times;</button>
      </div>
      <div class="modal-body">
        <p>${escapeHtml(message)}</p>
      </div>
      <div class="modal-footer">
        <button class="modal-btn modal-btn--primary ok-btn" type="button">OK</button>
      </div>
    </div>
  `;

  document.body.appendChild(overlay);

  const okBtn = overlay.querySelector('.ok-btn');
  const closeBtn = overlay.querySelector('.modal-close');

  const cleanup = () => {
    overlay.remove();
  };

  okBtn.addEventListener('click', () => {
    cleanup();
    if (onOk) onOk();
  });

  closeBtn.addEventListener('click', () => {
    cleanup();
    if (onOk) onOk();
  });

  // Close on overlay click
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) {
      cleanup();
      if (onOk) onOk();
    }
  });

  // Close on Escape
  const escapeHandler = (e) => {
    if (e.key === 'Escape') {
      overlay.removeEventListener('keydown', escapeHandler);
      cleanup();
      if (onOk) onOk();
    }
  };
  overlay.addEventListener('keydown', escapeHandler);
}

/**
 * Escape HTML special characters
 * @param {string} str - String to escape
 * @returns {string} Escaped string
 */
function escapeHtml(str) {
  if (!str) return '';
  const map = {
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#039;'
  };
  return str.replace(/[&<>"']/g, (m) => map[m]);
}

/**
 * Initialize modal close handlers (Escape key, backdrop click)
 */
function initializeModalHandlers() {
  // Handle Escape key press on all modals
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      const activeModals = document.querySelectorAll('.modal-overlay.active');
      if (activeModals.length > 0) {
        const lastModal = activeModals[activeModals.length - 1];
        lastModal.classList.remove('active');
      }
    }
  });

  // Handle backdrop clicks (click on overlay, not panel)
  document.addEventListener('click', (e) => {
    if (e.target.classList.contains('modal-overlay') && e.target.classList.contains('active')) {
      e.target.classList.remove('active');
    }
  });
}

// Initialize modal handlers when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initializeModalHandlers);
} else {
  initializeModalHandlers();
}
