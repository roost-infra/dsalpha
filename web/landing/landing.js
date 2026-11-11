/* Public site: small, dependency-free interactions. */
(function () {
  var nav = document.querySelector('[data-nav]');
  var toggle = document.querySelector('[data-menu-toggle]');
  var menu = document.querySelector('[data-mobile-menu]');

  var onScroll = function () {
    if (nav) nav.classList.toggle('is-scrolled', window.scrollY > 8);
  };
  window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();

  if (toggle && menu) {
    var setOpen = function (open) {
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
      toggle.setAttribute('aria-label', open ? '关闭导航' : '打开导航');
      menu.hidden = !open;
    };
    toggle.addEventListener('click', function () {
      setOpen(toggle.getAttribute('aria-expanded') !== 'true');
    });
    menu.addEventListener('click', function (event) {
      if (event.target.closest('a')) setOpen(false);
    });
    window.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') setOpen(false);
    });
  }

  // Sections and the major cards come in gently; motion is optional.
  var reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (!reduced && 'IntersectionObserver' in window) {
    var targets = document.querySelectorAll('.section__head, .feature, .step, .data-cell, .deliverable, .auto-card, .wechat-card, .trust, .faq details, .workspace__copy, .workspace__panel');
    targets.forEach(function (el, index) {
      el.classList.add('reveal');
      el.style.transitionDelay = String(Math.min(index % 6, 4) * 45) + 'ms';
    });
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-in');
          observer.unobserve(entry.target);
        }
      });
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0.05 });
    targets.forEach(function (el) { observer.observe(el); });
    // If the observer never delivers (a restored scroll position, a browser
    // that throttles it), do not leave the page looking empty.
    setTimeout(function () {
      targets.forEach(function (el) { el.classList.add('is-in'); });
    }, 1800);
  }
})();
