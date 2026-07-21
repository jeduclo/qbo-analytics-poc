/* demos.js — Minimal interaction for /demos pages */

(function () {
  'use strict';

  // ── Active nav link ──────────────────────────────────────────
  // Adds 'active' class to the nav link matching the current page path.
  function setActiveNavLink() {
    var currentPath = window.location.pathname;
    var navLinks    = document.querySelectorAll('.nav__links a');

    navLinks.forEach(function (link) {
      var linkPath = new URL(link.href).pathname;
      if (currentPath === linkPath ||
          (currentPath.startsWith(linkPath) && linkPath !== '/')) {
        link.classList.add('active');
      }
    });
  }

  // ── Iframe load state ────────────────────────────────────────
  // Shows a loading placeholder until the Power BI iframe loads.
  function initIframePlaceholder() {
    var iframe      = document.querySelector('.dashboard-container iframe');
    var placeholder = document.querySelector('.dashboard-placeholder');

    if (!iframe || !placeholder) return;

    iframe.addEventListener('load', function () {
      placeholder.style.display = 'none';
      iframe.style.display      = 'block';
    });
  }

  // ── Scroll-triggered fade-in ─────────────────────────────────
  // Adds 'visible' class to .fade-in elements as they enter the viewport.
  function initFadeIn() {
    if (!('IntersectionObserver' in window)) return;

    var elements = document.querySelectorAll('.fade-in');
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add('visible');
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.1 });

    elements.forEach(function (el) { observer.observe(el); });
  }

  // ── Init ─────────────────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', function () {
    setActiveNavLink();
    initIframePlaceholder();
    initFadeIn();
  });
}());