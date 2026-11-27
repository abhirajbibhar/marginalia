/*!
 * base.js — shared behaviour for every page.
 *
 * Refactored from the Cadence template so every init accepts a root element;
 * main.js re-runs these on htmx:afterSettle for swapped fragments only. The
 * demo-only initDemoForms is removed (server-rendered forms handle submits).
 *
 * Bootstrap 6 is ESM-only: importing the bundle registers the data-attribute
 * API (data-bs-toggle="dialog" | "drawer" | "menu" …). There is no
 * window.bootstrap.
 */

import { Tooltip, Popover, Toast } from 'bootstrap'

/* Color mode — dark is switched at runtime with data-bs-theme on <html>. */
export const initColorMode = (root = document, storageKey = 'bs6-theme') => {
  const toggle = root.querySelector?.('#themeToggle') ?? document.getElementById('themeToggle')
  if (!toggle || toggle.dataset.bound) return
  toggle.dataset.bound = '1'

  const html = document.documentElement
  const stored = localStorage.getItem(storageKey)
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)')

  const apply = (mode) => {
    html.setAttribute('data-bs-theme', mode)
    toggle.setAttribute('aria-pressed', String(mode === 'dark'))
  }

  apply(stored ?? (prefersDark.matches ? 'dark' : 'light'))

  toggle.addEventListener('click', () => {
    const next = html.getAttribute('data-bs-theme') === 'dark' ? 'light' : 'dark'
    localStorage.setItem(storageKey, next)
    apply(next)
  })

  prefersDark.addEventListener('change', (e) => {
    if (!localStorage.getItem(storageKey)) apply(e.matches ? 'dark' : 'light')
  })
}

/* Close the mobile drawer after tapping an in-page link. */
export const initDrawerAutoClose = (root = document) => {
  root.querySelectorAll?.('dialog.drawer').forEach((drawer) => {
    if (drawer.dataset.bound) return
    drawer.dataset.bound = '1'
    drawer.addEventListener('click', (e) => {
      if (e.target.closest('a[href^="#"]')) drawer.close()
    })
  })
}

export const initTooltips = (root = document) => {
  root.querySelectorAll?.('[data-bs-toggle="tooltip"]')
    .forEach((el) => Tooltip.getOrCreateInstance(el))
}

export const initPopovers = (root = document) => {
  root.querySelectorAll?.('[data-bs-toggle="popover"]')
    .forEach((el) => Popover.getOrCreateInstance(el))
}

export const initYear = (root = document) => {
  root.querySelectorAll?.('[data-year]')
    .forEach((el) => { el.textContent = String(new Date().getFullYear()) })
}

/* Run the standard set scoped to a root (defaults to the whole document). */
export const initBase = (root = document) => {
  initColorMode(root)
  initDrawerAutoClose(root)
  initTooltips(root)
  initPopovers(root)
  initYear(root)
}

export const onReady = (fn) => {
  document.readyState === 'loading'
    ? document.addEventListener('DOMContentLoaded', fn)
    : fn()
}

export { Toast }
