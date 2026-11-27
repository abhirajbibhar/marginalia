/*!
 * cover.js — render page 1 to JPEG in the browser at upload/review time using
 * the EmbedPDF engine (verified API: registry.getPlugin('render').provides()
 * .renderPage({ pageIndex, scaleFactor }) -> Task<Blob>), then upload it to
 * /library/<id>/cover/. Falls back silently — manual cover upload remains.
 */
import EmbedPDF from '/static/embedpdf/embedpdf.js';

const mount = document.getElementById('cover-render');
if (mount) {
  void renderCover(mount);
}

async function renderCover(target) {
  const book = Number(target.dataset.book);
  const src = target.dataset.src;
  const status = document.getElementById('coverStatus');

  try {
    const viewer = EmbedPDF.init({
      type: 'container',
      target,
      documentManager: { initialDocuments: [{ documentId: `book-${book}`, src }] },
      tabBar: 'never',
      disabledCategories: ['annotation', 'redaction', 'form', 'print', 'export'],
      fontFallback: null,
      wasmUrl: '/static/embedpdf/pdfium.wasm',
      worker: true,
    });
    const registry = await viewer.registry;
    const renderApi = registry.getPlugin('render')?.provides();
    if (!renderApi?.renderPage) throw new Error('render plugin missing');

    // Wait for the first page to be document-ready, then render it.
    const blob = await new Promise((resolve, reject) => {
      renderApi.renderPage({ pageIndex: 0, scaleFactor: 1.5, imageType: 'image/jpeg' })
        .wait(resolve, reject);
    });

    const form = new FormData();
    form.append('cover', blob, 'cover.jpg');
    const csrf = document.querySelector('[name=csrfmiddlewaretoken]')?.value
      ?? (document.cookie.match(/csrftoken=([^;]+)/)?.[1] ?? '');
    const res = await fetch(`/library/${book}/cover/`, {
      method: 'POST',
      headers: { 'X-CSRFToken': csrf },
      body: form,
    });
    if (!res.ok) throw new Error(`cover upload failed (${res.status})`);
    if (status) status.textContent = 'Cover rendered from page 1.';
    viewer.destroy?.();
    target.hidden = true;
  } catch (err) {
    if (status) status.textContent = `Automatic cover failed (${String(err)}); upload one manually.`;
  }
}
