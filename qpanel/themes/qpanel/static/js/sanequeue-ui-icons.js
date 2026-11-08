/* Navigation icon system: decorative SVG only, never changes button behavior.
 * Build from trusted static path definitions (no fetched assets, no inline HTML).
 */
(() => {
  'use strict';
  const ns = 'http://www.w3.org/2000/svg';
  const paths = {
    live: ['M3 3h7v7H3z','M14 3h7v7h-7z','M3 14h7v7H3z','M14 14h7v7h-7z'],
    queues: ['M8 6h13','M8 12h13','M8 18h13','M3 6h.01','M3 12h.01','M3 18h.01'],
    calls: ['M22 16.92v3a2 2 0 0 1-2.18 2A19.79 19.79 0 0 1 3.09 5.18 2 2 0 0 1 5.08 3h3a2 2 0 0 1 2 1.72l.4 2.81a2 2 0 0 1-.57 1.71L8.1 11.05a16 16 0 0 0 4.85 4.85l1.81-1.81a2 2 0 0 1 1.71-.57l2.81.4a2 2 0 0 1 1.72 2z'],
    waiting: ['M12 7v5l3 2','M3.05 11a9 9 0 1 0 1.84-4.95','M3 3v4h4'],
    wallboard: ['M2 4h20v14H2z','M8 22h8','M12 18v4'],
    agents: ['M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2','M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8','M22 21v-2a4 4 0 0 0-3-3.87','M16 3.13a4 4 0 0 1 0 7.75'],
    presence: ['M22 16.92v3a2 2 0 0 1-2.18 2A19.79 19.79 0 0 1 3.09 5.18 2 2 0 0 1 5.08 3h3a2 2 0 0 1 2 1.72l.4 2.81a2 2 0 0 1-.57 1.71L8.1 11.05a16 16 0 0 0 4.85 4.85l1.81-1.81a2 2 0 0 1 1.71-.57l2.81.4a2 2 0 0 1 1.72 2z','M16 7h5','M18.5 4.5v5'],
    shifts: ['M3 5h18v16H3z','M16 3v4','M8 3v4','M3 10h18','M8 14h.01','M12 14h.01','M16 14h.01'],
    directory: ['M4 19.5A2.5 2.5 0 0 1 6.5 17H20','M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z','M9 8h6','M9 12h4'],
    control: ['M4 21v-7','M4 10V3','M12 21v-9','M12 8V3','M20 21v-5','M20 12V3','M1 14h6','M9 8h6','M17 16h6'],
    alerts: ['M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9','M10 21h4'],
    audit: ['M8 6h13','M8 12h13','M8 18h13','M3 6l1 1 2-2','M3 12l1 1 2-2','M3 18l1 1 2-2'],
    policies: ['M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z','M9 12l2 2 4-4'],
    pbx: ['M2 12h4l3-8 4 16 3-8h6'],
    features: ['M12 3l1.7 5.3L19 10l-5.3 1.7L12 17l-1.7-5.3L5 10l5.3-1.7z','M20 17l.7 2.3L23 20l-2.3.7L20 23l-.7-2.3L17 20l2.3-.7z','M4 2l.6 1.4L6 4l-1.4.6L4 6l-.6-1.4L2 4l1.4-.6z'],
    users: ['M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2','M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8','M19 8v4','M17 10h4'],
    telephony: ['M3 14v-3a9 9 0 0 1 18 0v3','M3 14v4a2 2 0 0 0 2 2h3v-7H5a2 2 0 0 0-2 2z','M21 14v4a2 2 0 0 1-2 2h-3v-7h3a2 2 0 0 1 2 2z'],
    settings: ['M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6','M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-1.86 1.86-.06-.06A1.7 1.7 0 0 0 16 18.4a1.7 1.7 0 0 0-1 .94V21h-3v-1.66a1.7 1.7 0 0 0-1-.94 1.7 1.7 0 0 0-1.88.34l-.06.06-1.86-1.86.06-.06A1.7 1.7 0 0 0 7.6 15a1.7 1.7 0 0 0-.94-1H5v-3h1.66a1.7 1.7 0 0 0 .94-1 1.7 1.7 0 0 0-.34-1.88L7.2 8.06 9.06 6.2l.06.06A1.7 1.7 0 0 0 11 6.6a1.7 1.7 0 0 0 1-.94V4h3v1.66a1.7 1.7 0 0 0 1 .94 1.7 1.7 0 0 0 1.88-.34l.06-.06 1.86 1.86-.06.06A1.7 1.7 0 0 0 19.4 10a1.7 1.7 0 0 0 .94 1H22v3h-1.66a1.7 1.7 0 0 0-.94 1z']
  };
  const nav = document.getElementById('sq-primary-nav');
  if (!nav) return;
  for (const button of nav.querySelectorAll('button[data-view]')) {
    const icon = button.querySelector('span');
    const commands = paths[button.dataset.view];
    if (!icon || !commands) continue;
    const svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('width', '20');
    svg.setAttribute('height', '20');
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', 'currentColor');
    svg.setAttribute('stroke-width', '1.8');
    svg.setAttribute('stroke-linecap', 'round');
    svg.setAttribute('stroke-linejoin', 'round');
    svg.setAttribute('aria-hidden', 'true');
    svg.setAttribute('focusable', 'false');
    for (const d of commands) {
      const path = document.createElementNS(ns, 'path');
      path.setAttribute('d', d);
      svg.appendChild(path);
    }
    icon.replaceChildren(svg);
    icon.setAttribute('aria-hidden', 'true');
  }
})();
