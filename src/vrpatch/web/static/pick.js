/**
 * PickCoords — the single coordinate authority for region picking.
 *
 * Rule (see .claude/memory/js-drag-overlay-coords.md): every coordinate,
 * whether drawn on screen or submitted to the server, is derived from ONE
 * mapping: event -> getBoundingClientRect() -> two outputs. Never mix
 * clientX/Y with offsetLeft/offsetTop, and never use intrinsic dimensions
 * (naturalWidth / videoWidth) without guarding for a not-yet-loaded element.
 *
 * Style-proof by construction:
 *  - overlay position is expressed relative to the image, then converted to
 *    the overlay's offsetParent, so padding/labels/ wrappers around the image
 *    do not shift it;
 *  - scaling between displayed CSS pixels and image pixels uses whatever the
 *    browser reports at event time, so any display width works;
 *  - every call guards against an image that is reloading (naturalWidth 0)
 *    and returns null instead of garbage — callers must no-op on null.
 *
 * Public API:
 *   PickCoords.point(imgEl, event) -> {css:{x,y}, img:{x,y}, frac:{x,y}} | null
 *       frac is the position as fractions of the image (0..1) — the only
 *       thing callers should SUBMIT, because it is independent of both the
 *       preview resolution and the on-screen size.
 *   PickCoords.rect(a, b)          -> {css:{...}, img:{...}, frac:{...}} | null
 *   PickCoords.drag(imgEl, opts)   -> starts a drag controller with
 *       onMove(rect|null), onCommit(rect) (only if > minPx), onCancel();
 *       call controller.cancel() to abort (e.g. page refresh).
 */
window.PickCoords = (function () {
  "use strict";

  // works for <img> (naturalWidth) and <video> (videoWidth, readyState)
  function loaded(el) {
    return el.tagName === "VIDEO"
      ? el.readyState >= 1
      : el.complete && el.naturalWidth > 0;
  }

  function mediaSize(el) {
    if (el.tagName === "VIDEO")
      return el.videoWidth > 0 ? { w: el.videoWidth, h: el.videoHeight } : null;
    return el.naturalWidth > 0 ? { w: el.naturalWidth, h: el.naturalHeight } : null;
  }

  // event -> coords in CSS space, image pixel space and 0..1 fractions, or null
  function point(imgEl, e) {
    if (!loaded(imgEl)) return null;
    const r = imgEl.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return null;
    const d = mediaSize(imgEl);
    if (!d) return null;
    const sx = d.w / r.width, sy = d.h / r.height;
    const cssX = e.clientX - r.left, cssY = e.clientY - r.top;
    return {
      css: { x: cssX, y: cssY },
      img: { x: cssX * sx, y: cssY * sy },
      frac: { x: cssX / r.width, y: cssY / r.height },
    };
  }

  // two points -> normalized rect in all three spaces, or null
  function rect(a, b) {
    if (!a || !b) return null;
    return {
      css: norm(a.css, b.css),
      img: norm(a.img, b.img),
      frac: norm(a.frac, b.frac),
    };
  }

  function norm(a, b) {
    return { x: Math.min(a.x, b.x), y: Math.min(a.y, b.y),
             w: Math.abs(a.x - b.x), h: Math.abs(a.y - b.y) };
  }

  // Draw `cssRect` (image-relative) onto `overlayEl`, an absolutely positioned
  // box whose offsetParent contains `imgEl`. The offset between the image's
  // top-left and the overlay's containing block is measured live, so wrappers,
  // padding and labels around the image cannot desync the box from the cursor.
  function drawOverlay(overlayEl, imgEl, cssRect) {
    if (!cssRect) { overlayEl.style.display = "none"; return; }
    const ir = imgEl.getBoundingClientRect();
    const ob = (overlayEl.offsetParent || document.body)
      .getBoundingClientRect();
    overlayEl.style.left = (cssRect.x + ir.left - ob.left) + "px";
    overlayEl.style.top = (cssRect.y + ir.top - ob.top) + "px";
    overlayEl.style.width = cssRect.w + "px";
    overlayEl.style.height = cssRect.h + "px";
    overlayEl.style.display = "block";
  }

  function drag(imgEl, opts) {
    let start = null;
    let active = false;

    imgEl.addEventListener("mousedown", (e) => {
      start = point(imgEl, e);
      if (!start) return;              // image still loading: ignore the click
      active = true;
      if (opts.onBegin) opts.onBegin();
      e.preventDefault();
    });

    imgEl.addEventListener("mousemove", (e) => {
      if (!active) return;
      const r = rect(start, point(imgEl, e));
      if (r && opts.onMove) opts.onMove(r);
    });

    window.addEventListener("mouseup", (e) => {
      if (!active) return;
      active = false;
      const r = rect(start, point(imgEl, e));
      start = null;
      if (!r) { if (opts.onCancel) opts.onCancel(); return; }
      if (r.img.w > 2 && r.img.h > 2) {      // a real drag, not a stray click
        if (opts.onCommit) opts.onCommit(r); // full rect: css+img+frac spaces
      } else {
        if (opts.onCancel) opts.onCancel();  // click without drag: no-op
      }
    });

    return {
      cancel() {                     // abort an in-flight drag (page refresh)
        active = false;
        start = null;
        if (opts.onCancel) opts.onCancel();
      },
      get active() { return active; },
    };
  }

  return { point, rect, drawOverlay, drag, loaded };
})();
