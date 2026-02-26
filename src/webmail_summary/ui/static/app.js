/**
 * Webmail Summary - Global Frontend Utility Functions
 */

/**
 * Escapes HTML special characters in a string.
 */
function escapeHtml(s) {
  return String(s || '')
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/**
 * Parses and formats a summary string (raw text or JSON) into HTML.
 */
function formatSummary(raw) {
  if (!raw) return '';
  let s = String(raw).trim();
  if (!s) return '';

  // Completely strip all '**' markers
  s = s.replace(/\*\*/g, '');

  if (s.startsWith("```")) {
    s = s.replace(/^```[a-zA-Z0-9_-]*\s*/, "").replace(/\s*```$/, "").trim();
  }

  try {
    if ((s.startsWith("{") && s.endsWith("}")) || (s.startsWith("[") && s.endsWith("]"))) {
      const parsed = JSON.parse(s);
      if (Array.isArray(parsed)) {
        s = parsed.join('\n');
      } else if (parsed.summary) {
        s = Array.isArray(parsed.summary) ? parsed.summary.join('\n') : String(parsed.summary);
      }
    }
  } catch (e) {}

  const textLines = s.replace(/\r\n?/g, "\n").split("\n");
  const html = [];

  textLines.forEach(rawLine => {
    const line = rawLine.trim();
    if (!line) return;

    // Support for multiple points in one line separated by " - "
    const parts = line.split(/\s+-\s+(?=[A-Za-z0-9가-힣\[])/g);
    
    parts.forEach(p => {
      let t = p.trim();
      if (!t) return;

      // Clean leading bullet artifacts
      t = t.replace(/^([\s\-\•·\*]+)/, '');
      if (!t || t.length < 2) return;

      // Handle Markdown-style headers
      if (/^#{1,6}\s*/.test(t)) {
        const heading = t.replace(/^#{1,6}\s*/, '').trim();
        if (heading) {
          html.push(`<h3 class="summary-h3">${escapeHtml(heading)}</h3>`);
        }
        return;
      }

      // Handle "Label: Content" bolding
      let safe = escapeHtml(t);
      if (safe.includes(':')) {
        const splitIdx = safe.indexOf(':');
        const title = safe.substring(0, splitIdx).trim();
        const content = safe.substring(splitIdx + 1).trim();
        if (title && content) {
          html.push(`<div class="summary-item">• <b class="summary-item-bold">${title}:</b> ${content}</div>`);
        } else {
          html.push(`<div class="summary-item">• ${safe}</div>`);
        }
      } else {
        html.push(`<div class="summary-item">• ${safe}</div>`);
      }
    });
  });

  return html.join('');
}

/**
 * Applies formatting to elements matching a selector that have a data-raw attribute.
 */
function applyFormatting(selector = '.summary-content') {
  document.querySelectorAll(selector).forEach(el => {
    const raw = el.getAttribute('data-raw');
    if (raw) {
      el.innerHTML = formatSummary(raw);
    }
  });
}
