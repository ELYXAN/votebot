// Gemeinsame Helfer für Wizard & Dashboard.

async function api(path, method = "GET", body = null) {
  const opts = { method, headers: {} };
  if (body !== null) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  let data = {};
  try { data = await res.json(); } catch (e) {}
  if (!res.ok) {
    throw new Error(data.error || data.detail || `HTTP ${res.status}`);
  }
  return data;
}

function getState() { return api("/api/state"); }

function $(id) { return document.getElementById(id); }

function showMsg(id, text, kind = "info") {
  const el = $(id);
  if (!el) return;
  el.className = "msg " + kind;
  el.textContent = text;
}

function copyText(id) {
  const el = $(id);
  const text = el.textContent || el.value;
  navigator.clipboard.writeText(text).then(() => {
    const old = el.dataset.old;
    if (!old) el.dataset.old = "1";
  }).catch(() => {});
}

function esc(s) {
  return (s == null ? "" : String(s)).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}
