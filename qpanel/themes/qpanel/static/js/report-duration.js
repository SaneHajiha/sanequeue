/* Report durations are elapsed seconds, never wall-clock times. */
(() => {
  'use strict';
  function format(value) {
    if (value == null || value === '' || !Number.isFinite(Number(value)) || Number(value) < 0) return '—';
    const seconds = Math.floor(Number(value));
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor(seconds / 60) % 60;
    return hours + ':' + String(minutes).padStart(2, '0') + ':' + String(seconds % 60).padStart(2, '0');
  }
  window.SaneQueueReportDuration = format;
})();
