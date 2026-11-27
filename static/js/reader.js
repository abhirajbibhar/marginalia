/*!
 * reader.js — EmbedPDF v2 (pinned 2.15.1) inside the Cadence shell.
 *
 * Responsibilities:
 *   1. Mount the viewer in #pdf-viewer (same-origin, session-authenticated PDF
 *      through /read/<id>/file/, Range-capable).
 *   2. Private / room annotation layers, switched from the reader bar.
 *   3. Sync engine: batched ops → /api/reading/<book>/annotations/ops/,
 *      change polling → .../changes/, presence piggybacked on the poll.
 *      Queue survives reloads via localStorage (per user + book).
 *   4. Read-only display of other users' annotations (server rewrites the PDF
 *      `readOnly`/`lockedContents` flags into imported objects).
 *
 * This module is the ONLY non-HTMX XHR surface in the app (annotation payloads
 * are structured objects). Documented in docs/COLLABORATION.md.
 *
 * Verified API surface (docs/PHASE0.md):
 *   - EmbedPDF.init({ type:'container', target, documentManager, tabBar, ... })
 *   - registry.getPlugin('annotation').provides():
 *       exportAnnotations() -> Task<[{annotation, ctx?}]>
 *       importAnnotations(items)   (echo-free: no create events)
 *       deleteAnnotation(id), updateAnnotations(patches)
 *       onAnnotationEvent({type: create|update|delete, annotation, pageIndex})
 *   - registry.getPlugin('scroll').provides():
 *       scrollToPage, onPageChange, onLayoutReady
 *   - viewer.setTheme('light'|'dark') (CustomEvent 'themechange')
 *   - replies: annotation.inReplyToId + replyType; comment text: `contents`
 */
import EmbedPDF, { PdfAnnotationSubtype } from '/static/embedpdf/embedpdf.js';

// ---------------------------------------------------------------------------
// Page config
// ---------------------------------------------------------------------------
const mount = document.getElementById('pdf-viewer');
if (mount) {
  const cfg = {
    book: Number(mount.dataset.book),
    src: mount.dataset.src,
    title: mount.dataset.title || '',
    authorName: mount.dataset.authorName || 'Reader',
    userId: Number(mount.dataset.user || 0),
    resume: Number(mount.dataset.resume || 1),
    focus: mount.dataset.focus || '',
    pollActive: Number(mount.dataset.pollActive || 3000),
    pollAlone: Number(mount.dataset.pollAlone || 10000),
    pollHidden: Number(mount.dataset.pollHidden || 30000),
  };
  startReader(cfg, mount);
}

// ---------------------------------------------------------------------------
// Subtype mapping: engine annotation type -> server whitelist
// ---------------------------------------------------------------------------
const SUBTYPE_MAP = {
  [PdfAnnotationSubtype.HIGHLIGHT]: 'markup',
  [PdfAnnotationSubtype.UNDERLINE]: 'markup',
  [PdfAnnotationSubtype.STRIKEOUT]: 'markup',
  [PdfAnnotationSubtype.SQUIGGLY]: 'markup',
  [PdfAnnotationSubtype.INK]: 'ink',
  [PdfAnnotationSubtype.SQUARE]: 'shape',
  [PdfAnnotationSubtype.CIRCLE]: 'shape',
  [PdfAnnotationSubtype.LINE]: 'shape',
  [PdfAnnotationSubtype.POLYGON]: 'shape',
  [PdfAnnotationSubtype.POLYLINE]: 'shape',
  [PdfAnnotationSubtype.FREETEXT]: 'free_text',
  [PdfAnnotationSubtype.TEXT]: 'text_note',
  [PdfAnnotationSubtype.STAMP]: 'stamp',
};

function subtypeOf(annotation) {
  return SUBTYPE_MAP[annotation.type] || 'markup';
}

// ---------------------------------------------------------------------------
// CSRF
// ---------------------------------------------------------------------------
function csrfToken() {
  return (
    document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/)?.[1] ??
    document.querySelector('[name=csrfmiddlewaretoken]')?.value ??
    ''
  );
}

// ---------------------------------------------------------------------------
// Sync chip
// ---------------------------------------------------------------------------
function makeChip(el) {
  return {
    set(state, text) {
      el.dataset.state = state;
      el.textContent = text;
    },
    saved() { this.set('saved', 'Saved'); },
    syncing() { this.set('syncing', 'Syncing…'); },
    offline(n) { this.set('offline', `Offline (${n} pending)`); },
  };
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------
async function startReader(cfg, target) {
  const chip = makeChip(document.getElementById('syncChip'));
  const avatarsEl = document.getElementById('presenceAvatars');

  // -- rail: reader pages start collapsed ONLY when the user never chose. --
  if (localStorage.getItem('cadence-rail') === null) {
    document.body.classList.add('is-rail');
    document.getElementById('railToggle')?.setAttribute('aria-pressed', 'true');
  }

  // -- viewer ---------------------------------------------------------------
  const themeMode = document.documentElement.getAttribute('data-bs-theme') === 'dark'
    ? 'dark' : 'light';

  const viewer = EmbedPDF.init({
    type: 'container',
    target,
    documentManager: {
      initialDocuments: [{ documentId: `book-${cfg.book}`, src: cfg.src }],
    },
    tabBar: 'never',
    // Keep: annotation tools, comments panel with replies, in-book search.
    // Disable: redaction, forms, signing, open-file/tabs.
    disabledCategories: [
      'redaction', 'redaction-area', 'redaction-text', 'redaction-apply', 'redaction-clear',
      'form', 'form-textfield', 'form-checkbox', 'form-radio', 'form-select', 'form-listbox',
      'form-fill-mode',
      'document-open',
      'signatures', 'signatures.signing',
    ],
    annotations: {
      annotationAuthor: cfg.authorName,
      selectAfterCreate: true,
    },
    theme: { preference: themeMode },
    fontFallback: null,        // vendor everything locally
    wasmUrl: '/static/embedpdf/pdfium.wasm',
  });

  const registry = await viewer.registry;
  const annotationApi = registry.getPlugin('annotation')?.provides();
  const scrollApi = registry.getPlugin('scroll')?.provides();
  if (!annotationApi || !scrollApi) {
    chip.offline(0);
    return;
  }

  // -- layer state ----------------------------------------------------------
  let activeLayer = 'none';            // 'none' = private, or room id as string
  let applyingRemote = false;          // echo guard (update/delete emit events)
  let cursor = 0;
  const revisions = new Map();         // uid -> server revision
  const pending = [];                  // in-memory op queue
  const backupKey = `marginalia-pending:${cfg.userId}:${cfg.book}`;

  // localStorage backup: replay what never reached the server.
  try {
    const saved = JSON.parse(localStorage.getItem(backupKey) || '[]');
    if (Array.isArray(saved)) pending.push(...saved);
  } catch { /* corrupted backup: drop it */ }

  const persistQueue = () => {
    try { localStorage.setItem(backupKey, JSON.stringify(pending.slice(-500))); }
    catch { /* storage full: memory queue still works */ }
  };

  // -- sync chip bookkeeping -------------------------------------------------
  let flushing = false;
  const refreshChip = () => {
    if (flushing) chip.syncing();
    else if (!navigator.onLine) chip.offline(pending.length);
    else if (pending.length) chip.syncing();
    else chip.saved();
  };

  // -- op queue --------------------------------------------------------------
  function queueOp(op) {
    pending.push(op);
    persistQueue();
    refreshChip();
    scheduleFlush();
  }

  let flushTimer = null;
  function scheduleFlush() {
    if (flushTimer) return;
    flushTimer = window.setTimeout(() => {
      flushTimer = null;
      void flush();
    }, 750); // batch window: 500–1000 ms
  }

  async function flush() {
    if (flushing || !pending.length) return;
    flushing = true;
    refreshChip();
    const batch = pending.splice(0, 50); // server cap: 50 ops/request
    persistQueue();
    try {
      const res = await fetch(`/api/reading/${cfg.book}/annotations/ops/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken(),
        },
        body: JSON.stringify({ room: activeLayer, client_id: cfg.userId, ops: batch }),
        keepalive: true,
      });
      if (!res.ok) throw new Error(`ops ${res.status}`);
      const data = await res.json();
      for (const conflict of data.conflicts || []) {
        revisions.set(conflict.uid, conflict.revision ?? revisions.get(conflict.uid) ?? 1);
        if (conflict.payload && !conflict.deleted) {
          applyingRemote = true;
          try { annotationApi.importAnnotations([toItem(conflict)]); }
          finally { applyingRemote = false; }
        }
      }
      for (const uid of data.applied || []) {
        const sent = batch.find((b) => b.uid === uid);
        if (sent?.op !== 'delete') {
          revisions.set(uid, (revisions.get(uid) ?? 0) + 1);
        }
      }
    } catch {
      // Offline / server error: put the batch back and show the state.
      pending.unshift(...batch);
      persistQueue();
      chip.offline(pending.length);
    } finally {
      flushing = false;
      refreshChip();
    }
  }

  // -- annotation events -> ops ----------------------------------------------
  annotationApi.onAnnotationEvent((event) => {
    if (applyingRemote) return; // never echo remote application back
    const a = event.annotation;
    if (!a) return;
    const uid = String(a.id);
    if (event.type === 'create') {
      revisions.set(uid, revisions.get(uid) ?? 1);
      queueOp({
        op: 'create', uid, base_rev: 0,
        subtype: subtypeOf(a), page_index: event.pageIndex ?? a.pageIndex ?? 0,
        parent_uid: a.inReplyToId ? String(a.inReplyToId) : '',
        text: a.contents || '',
        payload: payloadFor(a),
      });
    } else if (event.type === 'update') {
      queueOp({
        op: 'update', uid, base_rev: revisions.get(uid) ?? 1,
        subtype: subtypeOf(a), page_index: event.pageIndex ?? a.pageIndex ?? 0,
        parent_uid: a.inReplyToId ? String(a.inReplyToId) : '',
        text: a.contents || '',
        payload: payloadFor(a),
      });
    } else if (event.type === 'delete') {
      queueOp({ op: 'delete', uid, base_rev: revisions.get(uid) ?? 1 });
    }
  });

  function payloadFor(a) {
    const payload = JSON.parse(JSON.stringify(a));
    delete payload.author; // server sets author from the session
    return payload;
  }

  function toItem(publicAnnotation) {
    const item = { annotation: publicAnnotation.payload };
    if (publicAnnotation.payload && publicAnnotation.payload._ctx_b64) {
      item.ctx = { data: b64ToBuffer(publicAnnotation.payload._ctx_b64) };
    }
    return item;
  }

  function b64ToBuffer(b64) {
    const bin = atob(b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i += 1) bytes[i] = bin.charCodeAt(i);
    return bytes.buffer;
  }

  // -- layer load -------------------------------------------------------------
  async function loadLayer(layer) {
    activeLayer = layer;
    chip.syncing();
    const res = await fetch(
      `/api/reading/${cfg.book}/annotations/?room=${encodeURIComponent(layer)}`,
      { headers: { 'X-CSRFToken': csrfToken() } },
    );
    if (!res.ok) { chip.offline(pending.length); return; }
    const data = await res.json();
    cursor = data.cursor || 0;
    applyingRemote = true;
    try {
      await annotationApi.deleteAllAnnotations?.();
      const items = (data.annotations || []).map((an) => {
        revisions.set(an.uid, an.revision);
        return toItem(an);
      });
      if (items.length) annotationApi.importAnnotations(items);
    } finally {
      applyingRemote = false;
    }
    renderParticipants(data.participants || []);
    chip.saved();
  }

  // -- presence ---------------------------------------------------------------
  function renderParticipants(participants) {
    if (!avatarsEl) return;
    avatarsEl.innerHTML = '';
    for (const p of participants.slice(0, 8)) {
      const span = document.createElement('span');
      span.className = 'avatar avatar-sm';
      span.title = p.page ? `${p.name} · p. ${p.page}` : p.name;
      const initials = document.createElement('span');
      initials.className = 'avatar-initials';
      initials.textContent = (p.name || '?').slice(0, 2).toUpperCase();
      span.appendChild(initials);
      avatarsEl.appendChild(span);
    }
  }

  // -- change polling ----------------------------------------------------------
  let pollTimer = null;
  let pollFailures = 0;

  function pollInterval() {
    if (document.visibilityState === 'hidden') return cfg.pollHidden;
    const others = (avatarsEl?.childElementCount || 1) > 1;
    return others ? cfg.pollActive : cfg.pollAlone;
  }

  async function pollOnce() {
    try {
      const res = await fetch(
        `/api/reading/${cfg.book}/annotations/changes/?room=${encodeURIComponent(activeLayer)}`
        + `&after=${cursor}&page=${currentPage()}`,
        { headers: { 'X-CSRFToken': csrfToken() } },
      );
      if (!res.ok) throw new Error(`changes ${res.status}`);
      const data = await res.json();
      pollFailures = 0;
      if (data.reset) {
        await loadLayer(activeLayer); // full resync after compaction
      } else {
        cursor = data.cursor ?? cursor;
        applyingRemote = true;
        try {
          for (const change of data.changes || []) {
            if (change.op === 'delete') {
              annotationApi.deleteAnnotation(change.uid, `book-${cfg.book}`);
            } else if (change.annotation) {
              revisions.set(change.annotation.uid, change.annotation.revision);
              annotationApi.importAnnotations([toItem(change.annotation)]);
            }
          }
        } finally {
          applyingRemote = false;
        }
      }
      renderParticipants(data.participants || []);
    } catch {
      pollFailures += 1;
      if (!navigator.onLine) chip.offline(pending.length);
    } finally {
      const backoff = Math.min(cfg.pollHidden, pollInterval() * 2 ** Math.min(pollFailures, 5));
      pollTimer = window.setTimeout(() => void pollOnce(), pollFailures ? backoff : pollInterval());
    }
  }

  // -- resume + focus ----------------------------------------------------------
  scrollApi.onLayoutReady(() => {
    if (cfg.resume > 1) scrollApi.scrollToPage(cfg.resume - 1);
  });

  scrollApi.onPageChange(({ page }) => {
    saveProgress(page + 1);
  });

  function currentPage() {
    try {
      return (scrollApi.getMetrics?.().currentPage ?? 0) + 1;
    } catch {
      return cfg.resume;
    }
  }

  let progressTimer = null;
  function saveProgress(page) {
    if (progressTimer) clearTimeout(progressTimer);
    progressTimer = window.setTimeout(() => {
      const body = new URLSearchParams({ page: String(page) });
      fetch(`/read/${cfg.book}/progress/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'X-CSRFToken': csrfToken() },
        body,
        keepalive: true,
      }).catch(() => {});
    }, 1500);
  }

  // -- bookmark button ----------------------------------------------------------
  const bookmarkBtn = document.getElementById('bookmarkBtn');
  bookmarkBtn?.addEventListener('click', () => {
    const page = currentPage();
    const body = new URLSearchParams({ page: String(page) });
    fetch(`/read/${cfg.book}/bookmark/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'X-CSRFToken': csrfToken() },
      body,
    }).then(() => {
      bookmarkBtn.title = `Bookmarked p. ${page}`;
    }).catch(() => {});
  });

  // -- layer switch buttons -------------------------------------------------------
  document.querySelectorAll('.layer-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      const layer = btn.dataset.layer === 'room' ? btn.dataset.room : 'none';
      document.querySelectorAll('.layer-btn').forEach((b) => b.classList.remove('is-active'));
      btn.classList.add('is-active');
      void flush().then(() => loadLayer(layer));
    });
  });

  // -- theme push -------------------------------------------------------------------
  new MutationObserver(() => {
    const mode = document.documentElement.getAttribute('data-bs-theme') === 'dark'
      ? 'dark' : 'light';
    viewer.setTheme?.(mode);
  }).observe(document.documentElement, { attributes: true, attributeFilter: ['data-bs-theme'] });

  // -- resize on rail toggle ---------------------------------------------------------
  if (window.ResizeObserver) {
    new ResizeObserver(() => {
      // The viewport/scroll plugins re-measure on container resize; poking the
      // registry keeps the layout correct after the sidebar rail toggles.
      scrollApi.getMetrics?.();
    }).observe(target);
  }

  // -- lifecycle ------------------------------------------------------------------------
  window.addEventListener('pagehide', () => {
    void flush();
    viewer.destroy?.();
  });
  document.addEventListener('htmx:beforeCleanupElement', (e) => {
    if (e.detail?.elt?.contains?.(target)) viewer.destroy?.();
  });
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') void flush();
    else void pollOnce(); // immediate catch-up on return
  });
  window.addEventListener('online', () => {
    chip.syncing();
    void flush().then(() => pollOnce());
  });

  // -- boot -------------------------------------------------------------------------------
  const initialRoom = new URLSearchParams(window.location.search).get('room');
  await loadLayer(initialRoom && /^\d+$/.test(initialRoom) ? initialRoom : 'none');
  if (initialRoom) {
    document.querySelectorAll('.layer-btn').forEach((b) => {
      b.classList.toggle('is-active', b.dataset.room === initialRoom);
    });
  }
  if (cfg.focus) {
    // Select the annotation we deep-linked to once layers are in place.
    window.setTimeout(() => {
      applyingRemote = true;
      try {
        const sel = annotationApi.getAnnotation?.(cfg.focus);
        if (sel) annotationApi.setSelection?.([sel.ref]);
      } finally {
        applyingRemote = false;
      }
    }, 800);
  }
  if (pending.length) await flush();
  void pollOnce();
}
