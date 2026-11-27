/*!
 * main.js — page behaviour, HTMX-aware.
 *
 * Every init accepts a root element; on htmx:afterSettle the set re-runs for
 * the swapped fragment only, so listeners are never double-bound (guards use
 * dataset.bound) and the reader keeps its own module (reader.js).
 */

import { initBase, onReady } from './base.js'

/* Sidebar rail. Never overwrite a stored preference: if 'cadence-rail' is
   absent, pages start expanded (reader pages start collapsed — handled in
   reader.js without touching the stored value). */
const initRail = (root = document) => {
  const btn = (root.querySelector?.('#railToggle')) ?? document.getElementById('railToggle')
  const side = document.getElementById('side')
  if (!btn || !side || btn.dataset.bound) return
  btn.dataset.bound = '1'

  const apply = (on) => {
    document.body.classList.toggle('is-rail', on)
    btn.setAttribute('aria-pressed', String(on))
    btn.setAttribute('aria-label', on ? 'Expand sidebar' : 'Collapse sidebar')
  }
  apply(localStorage.getItem('cadence-rail') === '1')

  btn.addEventListener('click', () => {
    const on = !document.body.classList.contains('is-rail')
    localStorage.setItem('cadence-rail', on ? '1' : '0')
    apply(on)
  })
}

/* Type-to-filter over a table — matches the row's whole text. */
const initFilter = (root = document) => {
  root.querySelectorAll?.('[data-filter]').forEach((input) => {
    if (input.dataset.bound) return
    input.dataset.bound = '1'
    const table = document.querySelector(input.dataset.filter)
    const count = document.querySelector('[data-filter-count]')
    if (!table) return
    const rows = [...table.querySelectorAll('tbody tr')]
    input.addEventListener('input', () => {
      const q = input.value.trim().toLowerCase()
      let shown = 0
      rows.forEach((r) => {
        const hit = !q || r.textContent.toLowerCase().includes(q)
        r.hidden = !hit
        if (hit) shown += 1
      })
      if (count) count.textContent = shown
    })
  })
}

const initPage = (root) => {
  initBase(root)
  initRail(root)
  initFilter(root)
}

onReady(() => initPage(document))

/* Re-init only the swapped fragment after HTMX settles. */
document.addEventListener('htmx:afterSettle', (e) => {
  initPage(e.detail?.target ?? document)
})
