// mkdocs-puml inlines each diagram as a raw <svg> in the page, so browsers offer no native
// "save image"/"open image in new tab" (those only apply to <img src="...">). A corner hint
// button (see addOpenHint below) serializes the <svg> into its own image/svg+xml document in a
// new tab instead -- since that tab's whole document *is* the image (not HTML with an inline
// svg), the browser treats it like any other image: native zoom, right-click "Save image as" all
// work there.
//
// PlantUML embeds its own metadata as XML processing instructions (e.g. <?plantuml-src ...?>).
// Parsed inline in an HTML (not XML) page, the browser silently turns those into "bogus comment"
// nodes -- and PlantUML's encoding alphabet uses "-" as a substitution character, so that payload
// often contains a literal "--", which real XML comments forbid. Re-serializing that bogus comment
// into a standalone SVG document (parsed strictly as XML) then fails with "not well-formed". These
// comments are just round-tripping metadata, not rendering, so drop them before serializing.
function stripCommentNodes(node) {
  const clone = node.cloneNode(true);
  const walker = document.createTreeWalker(clone, NodeFilter.SHOW_COMMENT);
  const comments = [];
  let current;
  while ((current = walker.nextNode())) comments.push(current);
  comments.forEach((comment) => comment.parentNode.removeChild(comment));
  return clone;
}

function openDiagramInNewTab(svg) {
  const svgString = new XMLSerializer().serializeToString(stripCommentNodes(svg));
  const blob = new Blob([svgString], { type: "image/svg+xml" });
  const url = URL.createObjectURL(blob);
  window.open(url, "_blank");
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

// Four-corner "expand" glyph -- a generic, widely-used fullscreen affordance shape, not tied to
// any particular icon library/license.
const EXPAND_ICON = `
<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"
     stroke-linecap="round" stroke-linejoin="round">
  <path d="M8 3H5a2 2 0 0 0-2 2v3"/>
  <path d="M21 8V5a2 2 0 0 0-2-2h-3"/>
  <path d="M3 16v3a2 2 0 0 0 2 2h3"/>
  <path d="M16 21h3a2 2 0 0 0 2-2v-3"/>
</svg>`;

function addOpenHint(container, svg) {
  const hint = document.createElement("button");
  hint.type = "button";
  hint.className = "diagram-open-hint";
  hint.title = "Click to open full-size in a new tab";
  hint.setAttribute("aria-label", "Click to open full-size in a new tab");
  hint.innerHTML = EXPAND_ICON;
  hint.addEventListener("click", (event) => {
    event.stopPropagation();
    openDiagramInNewTab(svg);
  });
  container.appendChild(hint);
}

function wireDiagramHints() {
  document.querySelectorAll(".puml").forEach((container) => {
    const svg = container.querySelector("svg");
    if (!svg || container.querySelector(".diagram-open-hint")) return;

    addOpenHint(container, svg);
  });
}

// mkdocs-material replaces page content via instant-navigation (document$) instead of full
// reloads, so a plain DOMContentLoaded listener would only ever fire once and miss every diagram
// on pages navigated to afterward.
if (typeof document$ !== "undefined" && document$.subscribe) {
  document$.subscribe(wireDiagramHints);
} else {
  document.addEventListener("DOMContentLoaded", wireDiagramHints);
}
