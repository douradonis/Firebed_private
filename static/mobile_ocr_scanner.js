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
      this.scanInterval = this.config.scanInterval || 2000; // ms between scans
      this.languages = this.config.languages || 'ell+eng'; // Greek + English
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
     * Looks for patterns of 15 consecutive digits
     */
    extractMARKFromText(text) {
      if (!text) return null;

      // Remove common OCR artifacts and spaces
      const cleaned = text.replace(/[\s\-_]/g, '');
      
      // Look for 15 consecutive digits
      const matches = cleaned.match(/\d{15}/g);
      
      if (matches && matches.length > 0) {
        return matches[0]; // Return first match
      }

      return null;
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
        const canvas = document.createElement('canvas');
        canvas.width = this.videoElement.videoWidth;
        canvas.height = this.videoElement.videoHeight;

        if (canvas.width === 0 || canvas.height === 0) {
          // Video not ready yet
          this.processing = false;
          return;
        }

        const ctx = canvas.getContext('2d');
        ctx.drawImage(this.videoElement, 0, 0);

        // Run OCR on the frame
        const { data: { text } } = await this.worker.recognize(canvas);

        if (text) {
          const mark = this.extractMARKFromText(text);
          if (mark) {
            this.onSuccess(mark, text);
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
