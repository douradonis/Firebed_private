/**
 * Mobile OCR Scanner Module
 * Handles OCR text recognition from camera feed for extracting 15-digit MARK numbers
 * Uses Tesseract.js for client-side OCR processing
 */

(function(window) {
  'use strict';

  class MobileOCRScanner {
    constructor(config) {
      this.config = config || {};
      this.worker = null;
      this.videoElement = null;
      this.processing = false;
      this.intervalId = null;
      this.onSuccess = this.config.onSuccess || function() {};
      this.onError = this.config.onError || function() {};
      this.onStatusChange = this.config.onStatusChange || function() {};
      this.scanInterval = this.config.scanInterval || 150; // ms between scans (faster for real-time)
      this.languages = this.config.languages || 'eng'; // English-only for maximum speed
      this.overlayCanvas = null;
      this.highlightTimeout = null;
      this.showOverlay = this.config.showOverlay !== false; // default true
      this.highlightDuration = this.config.highlightDuration || 800; // ms
      this.onHighlight = this.config.onHighlight || function() {};
      this.usePreprocessing = this.config.usePreprocessing !== false; // default true
      this.focusCenter = this.config.focusCenter !== false; // default true (crop to center for speed)
      this.cropFactor = this.config.cropFactor || 0.6; // use center 60% of image
    }

    /**
     * Initialize the Tesseract OCR worker
     */
    async initWorker() {
      if (this.worker) {
        return this.worker;
      }

      try {
        if (typeof Tesseract === 'undefined') {
          throw new Error('Tesseract.js library not loaded');
        }

        this.onStatusChange('Φόρτωση OCR engine...', 'info');

        this.worker = await Tesseract.createWorker(this.languages, 1, {
          logger: m => {
            if (m.status === 'recognizing text') {
              const progress = Math.round(m.progress * 100);
              if (progress % 20 === 0 && progress > 0) {
                console.log('OCR progress:', progress + '%');
              }
            }
          }
        });

        // Configure for speed and accuracy with numbers
        await this.worker.setParameters({
          tessedit_pageseg_mode: Tesseract.PSM.SINGLE_BLOCK, // PSM 6: uniform text block
          tessedit_char_whitelist: '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyzΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩαβγδεζηθικλμνξοπρστυφχψω.,:-/ ',
          preserve_interword_spaces: '0'
        });

        this.onStatusChange('OCR engine έτοιμο', 'success');
        return this.worker;
      } catch (err) {
        console.error('Failed to initialize OCR worker:', err);
        this.onStatusChange('Σφάλμα φόρτωσης OCR', 'error');
        this.onError(err);
        return null;
      }
    }

    /**
     * Extract 15-digit MARK from text
     * - Matches 15 digits that start with 400 (allows common separators)
     * - Is robust to OCR artifacts and accepts prefixes like `mark`, `μαρκ`, `Μ.Αρ.Κ.`
     */
    extractMARKFromText(text) {
      if (!text) return null;

      const original = text;

      // Regex: 15 digits allowing separators (spaces, dots, hyphens) between them
      const digitPattern = /(?:\d[\s\.\-]*){15}/g;

      // Map common Greek letters to latin equivalents for prefix normalization
      const greekToLatin = {
        'μ': 'm', 'Μ': 'm',
        'α': 'a', 'Α': 'a',
        'ρ': 'r', 'Ρ': 'r',
        'κ': 'k', 'Κ': 'k'
      };

      let match;
      while ((match = digitPattern.exec(original)) !== null) {
        const matchedRaw = match[0];
        const digitsOnly = matchedRaw.replace(/\D/g, '');

        // Must start with 400
        if (!digitsOnly.startsWith('400')) {
          continue;
        }

        // Look backwards a short distance for a possible prefix like "mark" / "μαρκ" / "Μ.Αρ.Κ."
        const lookback = 30; // chars to examine before the number
        const startIdx = Math.max(0, match.index - lookback);
        const prefix = original.substring(startIdx, match.index);

        // Normalize prefix: keep only letters, map greek letters to latin, lowercase
        let normalized = '';
        for (let ch of prefix) {
          if (/\p{Letter}/u.test(ch)) {
            normalized += (greekToLatin[ch] || ch).toLowerCase();
          }
        }

        const prefixDetected = normalized.endsWith('mark');

        return {
          mark: digitsOnly,
          prefixDetected,
          matchIndex: match.index,
          matchedRaw,
          prefix
        };
      }

      return null;
    }

    /**
     * Preprocess image for better OCR accuracy (like Android native OCR)
     */
    preprocessImage(canvas) {
      const ctx = canvas.getContext('2d');
      const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
      const data = imageData.data;

      // Convert to grayscale and apply contrast enhancement
      for (let i = 0; i < data.length; i += 4) {
        const r = data[i];
        const g = data[i + 1];
        const b = data[i + 2];
        
        // Grayscale conversion
        let gray = 0.299 * r + 0.587 * g + 0.114 * b;
        
        // Contrast enhancement (increase difference from mid-gray)
        const contrast = 1.5;
        gray = ((gray - 128) * contrast) + 128;
        gray = Math.max(0, Math.min(255, gray));
        
        data[i] = data[i + 1] = data[i + 2] = gray;
      }

      ctx.putImageData(imageData, 0, 0);
      return canvas;
    }

    /**
     * Process a single video frame for OCR
     */
    async processFrame() {
      if (this.processing || !this.videoElement || !this.worker) {
        return;
      }

      this.processing = true;

      try {
        // Create canvas to capture video frame
        const fullCanvas = document.createElement('canvas');
        const vw = this.videoElement.videoWidth;
        const vh = this.videoElement.videoHeight;
        
        if (vw === 0 || vh === 0) {
          // Video not ready yet
          this.processing = false;
          return;
        }

        // Optionally crop to center area for faster processing
        let canvas, sourceX, sourceY, sourceW, sourceH;
        if (this.focusCenter && this.cropFactor < 1.0) {
          const crop = this.cropFactor;
          sourceW = Math.floor(vw * crop);
          sourceH = Math.floor(vh * crop);
          sourceX = Math.floor((vw - sourceW) / 2);
          sourceY = Math.floor((vh - sourceH) / 2);
          
          canvas = document.createElement('canvas');
          // Reduce resolution for speed (max 800px width)
          const scale = Math.min(1.0, 800 / sourceW);
          canvas.width = Math.floor(sourceW * scale);
          canvas.height = Math.floor(sourceH * scale);
        } else {
          sourceX = 0;
          sourceY = 0;
          sourceW = vw;
          sourceH = vh;
          canvas = fullCanvas;
          // Reduce resolution for speed (max 800px width)
          const scale = Math.min(1.0, 800 / vw);
          canvas.width = Math.floor(vw * scale);
          canvas.height = Math.floor(vh * scale);
        }

        const ctx = canvas.getContext('2d');
        ctx.drawImage(this.videoElement, sourceX, sourceY, sourceW, sourceH, 0, 0, canvas.width, canvas.height);
        
        // Apply preprocessing for better OCR
        if (this.usePreprocessing) {
          this.preprocessImage(canvas);
        }

        // Run OCR on the frame
        const result = await this.worker.recognize(canvas);
        const text = result?.data?.text || '';
        const words = result?.data?.words || [];

        if (text) {
          const match = this.extractMARKFromText(text);
          if (match) {
            // Try to locate bounding box in recognized words
            let bbox = null;

            // Helper to clean a word's text to digits-only
            const cleanDigits = s => (s || '').replace(/\D/g, '');

            for (let i = 0; i < words.length && !bbox; i++) {
              let joined = '';
              for (let j = i; j < Math.min(i + 4, words.length); j++) {
                joined += words[j].text || '';
                const joinedDigits = cleanDigits(joined);
                if (joinedDigits === match.mark) {
                  // Combine bounding boxes from words i..j
                  const boxes = words.slice(i, j + 1).map(w => w.bbox || w);
                  let x0 = Math.min(...boxes.map(b => b.x0 ?? b.x0));
                  let y0 = Math.min(...boxes.map(b => b.y0 ?? b.y0));
                  let x1 = Math.max(...boxes.map(b => b.x1 ?? b.x1));
                  let y1 = Math.max(...boxes.map(b => b.y1 ?? b.y1));
                  
                  // Adjust bbox coordinates back to full video dimensions if cropped
                  if (this.focusCenter && this.cropFactor < 1.0) {
                    const scaleBack = sourceW / canvas.width;
                    x0 = (x0 * scaleBack) + sourceX;
                    y0 = (y0 * scaleBack) + sourceY;
                    x1 = (x1 * scaleBack) + sourceX;
                    y1 = (y1 * scaleBack) + sourceY;
                  } else {
                    const scaleBack = vw / canvas.width;
                    x0 *= scaleBack;
                    y0 *= scaleBack;
                    x1 *= scaleBack;
                    y1 *= scaleBack;
                  }
                  
                  bbox = { x0, y0, x1, y1 };
                  break;
                }
              }
            }

            // If overlay is enabled, draw highlight
            if (this.showOverlay && bbox && this.videoElement) {
              this._drawHighlight(bbox, vw, vh);
            }

            // Log / notify prefix detection
            if (match.prefixDetected) {
              this.onStatusChange('Εντοπίστηκε επισημασμένο MARK', 'info');
            }

            // Call onSuccess with extra metadata as third param
            this.onSuccess(match.mark, text, { prefixDetected: match.prefixDetected, bbox });
          }
        }
      } catch (err) {
        console.warn('OCR processing error:', err);
        this.onError(err);
      } finally {
        this.processing = false;
      }
    }

    /**
     * Start OCR scanning from camera
     */
    async start(cameraId) {
      try {
        // Initialize OCR worker if not already done
        if (!this.worker) {
          this.worker = await this.initWorker();
          if (!this.worker) {
            throw new Error('Failed to initialize OCR worker');
          }
        }

        // Get camera stream
        const constraints = cameraId 
          ? { video: { deviceId: { exact: cameraId }, facingMode: 'environment' } }
          : { video: { facingMode: 'environment' } };

        const stream = await navigator.mediaDevices.getUserMedia(constraints);

        // Create video element if it doesn't exist
        if (!this.videoElement) {
          this.videoElement = document.createElement('video');
          this.videoElement.setAttribute('playsinline', 'true');
          this.videoElement.style.width = '100%';
          this.videoElement.style.height = 'auto';
        }

        this.videoElement.srcObject = stream;
        await this.videoElement.play();

        // Ensure overlay canvas exists and is positioned over the video
        if (this.showOverlay) {
          this._ensureOverlay();
        }

        this.onStatusChange('OCR σάρωση ενεργή. Κατέθεσε το έγγραφο στη φωτογραφική μηχανή.', 'success');

        // Start processing frames at regular intervals
        this.intervalId = setInterval(() => {
          this.processFrame();
        }, this.scanInterval);

        return this.videoElement;
      } catch (err) {
        console.error('Failed to start OCR scanner:', err);
        this.onStatusChange('Αποτυχία εκκίνησης της κάμερας για OCR. Έλεγξε τα δικαιώματα.', 'error');
        this.onError(err);
        throw err;
      }
    }

    /**
     * Stop OCR scanning and clean up resources
     */
    async stop() {
      // Stop processing interval
      if (this.intervalId) {
        clearInterval(this.intervalId);
        this.intervalId = null;
      }

      // Stop video stream
      if (this.videoElement && this.videoElement.srcObject) {
        const tracks = this.videoElement.srcObject.getTracks();
        tracks.forEach(track => track.stop());
        this.videoElement.srcObject = null;
      }

      this.processing = false;

      // clear and remove overlay
      this._clearOverlay();
    }

    /**
     * Terminate the OCR worker
     */
    async terminate() {
      await this.stop();

      if (this.worker) {
        try {
          await this.worker.terminate();
        } catch (err) {
          console.warn('Error terminating OCR worker:', err);
        }
        this.worker = null;
      }
    }

    /**
     * Ensure overlay canvas exists and is sized/positioned over the video element
     */
    _ensureOverlay() {
      if (!this.videoElement) return;

      if (!this.overlayCanvas) {
        const c = document.createElement('canvas');
        c.style.position = 'absolute';
        c.style.pointerEvents = 'none';
        c.style.zIndex = 9999;
        c.className = 'ocr-overlay-canvas';
        document.body.appendChild(c);
        this.overlayCanvas = c;
        // updater to keep overlay positioned with the video on resize/scroll
        this._overlayUpdater = () => {
          if (!this.videoElement || !this.overlayCanvas) return;
          const r = this.videoElement.getBoundingClientRect();
          this.overlayCanvas.style.left = r.left + 'px';
          this.overlayCanvas.style.top = r.top + 'px';
          this.overlayCanvas.style.width = r.width + 'px';
          this.overlayCanvas.style.height = r.height + 'px';
          // keep canvas internal resolution in sync when possible
          if (this.overlayCanvas.width !== Math.round(r.width) || this.overlayCanvas.height !== Math.round(r.height)) {
            this.overlayCanvas.width = Math.max(1, Math.round(r.width));
            this.overlayCanvas.height = Math.max(1, Math.round(r.height));
          }
        };
        window.addEventListener('resize', this._overlayUpdater);
        window.addEventListener('scroll', this._overlayUpdater, true);
      }

      const rect = this.videoElement.getBoundingClientRect();
      this.overlayCanvas.style.left = rect.left + 'px';
      this.overlayCanvas.style.top = rect.top + 'px';
      this.overlayCanvas.width = rect.width;
      this.overlayCanvas.height = rect.height;
      this.overlayCanvas.style.width = rect.width + 'px';
      this.overlayCanvas.style.height = rect.height + 'px';
    }

    /**
     * Draw highlight box over detected bbox. bbox coordinates are in camera image space.
     * Enhanced visual feedback like Android native OCR with animated border and corner markers
     */
    _drawHighlight(bbox, imageWidth, imageHeight) {
      if (!this.overlayCanvas || !this.videoElement) return;

      // Update overlay sizing/position to follow video element
      const rect = this.videoElement.getBoundingClientRect();
      this.overlayCanvas.style.left = rect.left + 'px';
      this.overlayCanvas.style.top = rect.top + 'px';
      this.overlayCanvas.width = rect.width;
      this.overlayCanvas.height = rect.height;

      const ctx = this.overlayCanvas.getContext('2d');
      ctx.clearRect(0, 0, this.overlayCanvas.width, this.overlayCanvas.height);

      const scaleX = this.overlayCanvas.width / imageWidth;
      const scaleY = this.overlayCanvas.height / imageHeight;

      const x = bbox.x0 * scaleX;
      const y = bbox.y0 * scaleY;
      const w = (bbox.x1 - bbox.x0) * scaleX;
      const h = (bbox.y1 - bbox.y0) * scaleY;

      // Add padding around detected text
      const padding = Math.min(w, h) * 0.1;
      const drawX = Math.max(0, x - padding);
      const drawY = Math.max(0, y - padding);
      const drawW = Math.min(this.overlayCanvas.width - drawX, w + 2 * padding);
      const drawH = Math.min(this.overlayCanvas.height - drawY, h + 2 * padding);

      // Draw semi-transparent fill
      ctx.fillStyle = 'rgba(0, 255, 100, 0.15)';
      ctx.fillRect(drawX, drawY, drawW, drawH);

      // Draw vibrant border (like Android green highlight)
      ctx.strokeStyle = '#00ff00';
      ctx.lineWidth = Math.max(3, Math.min(8, (ctx.canvas.width + ctx.canvas.height) / 200));
      ctx.shadowColor = '#00ff00';
      ctx.shadowBlur = 15;
      ctx.strokeRect(drawX + 0.5, drawY + 0.5, drawW - 1, drawH - 1);
      
      // Reset shadow for corner markers
      ctx.shadowBlur = 0;
      
      // Draw corner markers (like Android camera focus)
      const cornerLength = Math.min(drawW, drawH) * 0.15;
      const cornerWidth = ctx.lineWidth + 2;
      ctx.lineWidth = cornerWidth;
      ctx.strokeStyle = '#00ff00';
      
      // Top-left corner
      ctx.beginPath();
      ctx.moveTo(drawX, drawY + cornerLength);
      ctx.lineTo(drawX, drawY);
      ctx.lineTo(drawX + cornerLength, drawY);
      ctx.stroke();
      
      // Top-right corner
      ctx.beginPath();
      ctx.moveTo(drawX + drawW - cornerLength, drawY);
      ctx.lineTo(drawX + drawW, drawY);
      ctx.lineTo(drawX + drawW, drawY + cornerLength);
      ctx.stroke();
      
      // Bottom-left corner
      ctx.beginPath();
      ctx.moveTo(drawX, drawY + drawH - cornerLength);
      ctx.lineTo(drawX, drawY + drawH);
      ctx.lineTo(drawX + cornerLength, drawY + drawH);
      ctx.stroke();
      
      // Bottom-right corner
      ctx.beginPath();
      ctx.moveTo(drawX + drawW - cornerLength, drawY + drawH);
      ctx.lineTo(drawX + drawW, drawY + drawH);
      ctx.lineTo(drawX + drawW, drawY + drawH - cornerLength);
      ctx.stroke();

      // Add "MARK DETECTED" label
      const fontSize = Math.max(12, Math.min(20, drawH * 0.25));
      ctx.font = `bold ${fontSize}px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`;
      ctx.fillStyle = '#00ff00';
      ctx.strokeStyle = '#000000';
      ctx.lineWidth = 3;
      const labelText = 'MARK ✓';
      const labelY = drawY - 10;
      
      if (labelY > fontSize) {
        ctx.strokeText(labelText, drawX, labelY);
        ctx.fillText(labelText, drawX, labelY);
      }

      // Notify listeners
      try { this.onHighlight({ bbox, x: drawX, y: drawY, w: drawW, h: drawH }); } catch (e) { /* ignore */ }

      // Clear after duration
      if (this.highlightTimeout) {
        clearTimeout(this.highlightTimeout);
      }
      this.highlightTimeout = setTimeout(() => {
        if (this.overlayCanvas) {
          const cctx = this.overlayCanvas.getContext('2d');
          cctx.clearRect(0, 0, this.overlayCanvas.width, this.overlayCanvas.height);
        }
        this.highlightTimeout = null;
      }, this.highlightDuration);
    }

    _clearOverlay() {
      if (this.highlightTimeout) {
        clearTimeout(this.highlightTimeout);
        this.highlightTimeout = null;
      }
      if (this.overlayCanvas) {
        try { this.overlayCanvas.remove(); } catch (e) { /* ignore */ }
        if (this._overlayUpdater) {
          window.removeEventListener('resize', this._overlayUpdater);
          window.removeEventListener('scroll', this._overlayUpdater, true);
          this._overlayUpdater = null;
        }
        this.overlayCanvas = null;
      }
    }

    /**
     * Check if OCR is currently scanning
     */
    isScanning() {
      return this.intervalId !== null;
    }

    /**
     * Get the video element for display
     */
    getVideoElement() {
      return this.videoElement;
    }
  }

  // Export to window
  window.MobileOCRScanner = MobileOCRScanner;

})(window);
