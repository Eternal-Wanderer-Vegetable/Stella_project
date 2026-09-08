const PAGE_EXIT_MS = 220;

const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;

document.documentElement.classList.add("page-transition-enabled");
if (reducedMotion) {
  document.documentElement.classList.add("page-transition-reduced");
}

requestAnimationFrame(() => {
  requestAnimationFrame(() => {
    document.documentElement.classList.add("page-transition-entered");
  });
});

function isInternalPageLink(link) {
  if (link.target && link.target !== "_self") return false;
  if (link.hasAttribute("download")) return false;

  const href = link.getAttribute("href");
  if (!href || href.startsWith("#")) return false;

  const url = new URL(href, location.href);
  return url.origin === location.origin
    && url.pathname.endsWith(".html")
    && url.href !== location.href;
}

export function navigateToPage(path, { replace = false } = {}) {
  const url = new URL(path, location.href);
  const navigate = () => {
    if (replace) {
      location.replace(url.href);
    } else {
      location.assign(url.href);
    }
  };

  if (reducedMotion || document.documentElement.classList.contains("page-transition-leaving")) {
    navigate();
    return;
  }

  document.documentElement.classList.add("page-transition-leaving");
  window.setTimeout(navigate, PAGE_EXIT_MS);
}

document.addEventListener("click", (event) => {
  if (event.defaultPrevented || event.button !== 0
      || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
    return;
  }

  const link = event.target.closest("a[href]");
  if (!link || !isInternalPageLink(link)) return;

  event.preventDefault();
  navigateToPage(link.href);
}, true);

window.addEventListener("pageshow", () => {
  document.documentElement.classList.remove("page-transition-leaving");
});
