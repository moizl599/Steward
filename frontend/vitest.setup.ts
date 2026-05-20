import "@testing-library/jest-dom/vitest";

// Polyfill DOM APIs missing in jsdom that Radix UI primitives reach for.
// Without these, `Select`/`DropdownMenu`/etc. crash with
//   "target.hasPointerCapture is not a function".
if (typeof HTMLElement !== "undefined") {
  if (!HTMLElement.prototype.hasPointerCapture) {
    HTMLElement.prototype.hasPointerCapture = function () {
      return false;
    };
  }
  if (!HTMLElement.prototype.releasePointerCapture) {
    HTMLElement.prototype.releasePointerCapture = function () {};
  }
  if (!HTMLElement.prototype.setPointerCapture) {
    HTMLElement.prototype.setPointerCapture = function () {};
  }
  if (!HTMLElement.prototype.scrollIntoView) {
    HTMLElement.prototype.scrollIntoView = function () {};
  }
}
