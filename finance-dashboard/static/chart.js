/**
 * chart.js  – Shared Chart.js helpers for the Finance Dashboard.
 *
 * This file is imported by charts.html and provides:
 *  - Default Chart.js global configuration
 *  - A formatINR() helper for Indian Rupee formatting
 */

// ── Indian Rupee formatter ─────────────────────────────────────────────────
function formatINR(value) {
  if (value === null || value === undefined) return '–';
  return '₹' + Number(value).toLocaleString('en-IN', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  });
}

// ── Chart.js global defaults ───────────────────────────────────────────────
if (typeof Chart !== 'undefined') {
  Chart.defaults.font.family = "'Inter', 'ui-sans-serif', system-ui, sans-serif";
  Chart.defaults.font.size   = 12;
  Chart.defaults.color       = '#6B7280';   // gray-500

  // Disable animations for snappier rendering on low-power machines
  Chart.defaults.animation = false;
}
