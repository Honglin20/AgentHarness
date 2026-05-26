"use strict";
/*
 * ATTENTION: An "eval-source-map" devtool has been used.
 * This devtool is neither made for production nor for readable output files.
 * It uses "eval()" calls to create a separate source file with attached SourceMaps in the browser devtools.
 * If you are trying to read the output file, select a different devtool (https://webpack.js.org/configuration/devtool/)
 * or disable the default devtool with "devtool: false".
 * If you are looking for production-ready output files, see mode: "production" (https://webpack.js.org/configuration/mode/).
 */
exports.id = "vendor-chunks/unist-util-remove-position";
exports.ids = ["vendor-chunks/unist-util-remove-position"];
exports.modules = {

/***/ "(ssr)/./node_modules/unist-util-remove-position/lib/index.js":
/*!**************************************************************!*\
  !*** ./node_modules/unist-util-remove-position/lib/index.js ***!
  \**************************************************************/
/***/ ((__unused_webpack___webpack_module__, __webpack_exports__, __webpack_require__) => {

eval("__webpack_require__.r(__webpack_exports__);\n/* harmony export */ __webpack_require__.d(__webpack_exports__, {\n/* harmony export */   removePosition: () => (/* binding */ removePosition)\n/* harmony export */ });\n/* harmony import */ var unist_util_visit__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(/*! unist-util-visit */ \"(ssr)/./node_modules/unist-util-visit/lib/index.js\");\n/**\n * @typedef {import('unist').Node} Node\n */\n\n/**\n * @typedef Options\n *   Configuration.\n * @property {boolean | null | undefined} [force=false]\n *   Whether to use `delete` to remove `position` fields.\n *\n *   The default is to set them to `undefined`.\n */\n\n\n\n/**\n * Remove the `position` field from a tree.\n *\n * @param {Node} tree\n *   Tree to clean.\n * @param {Options | null | undefined} [options={force: false}]\n *   Configuration (default: `{force: false}`).\n * @returns {undefined}\n *   Nothing.\n */\nfunction removePosition(tree, options) {\n  const config = options || {}\n  const force = config.force || false\n\n  ;(0,unist_util_visit__WEBPACK_IMPORTED_MODULE_0__.visit)(tree, remove)\n\n  /**\n   * @param {Node} node\n   */\n  function remove(node) {\n    if (force) {\n      delete node.position\n    } else {\n      node.position = undefined\n    }\n  }\n}\n//# sourceURL=[module]\n//# sourceMappingURL=data:application/json;charset=utf-8;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoiKHNzcikvLi9ub2RlX21vZHVsZXMvdW5pc3QtdXRpbC1yZW1vdmUtcG9zaXRpb24vbGliL2luZGV4LmpzIiwibWFwcGluZ3MiOiI7Ozs7O0FBQUE7QUFDQSxhQUFhLHNCQUFzQjtBQUNuQzs7QUFFQTtBQUNBO0FBQ0E7QUFDQSxjQUFjLDRCQUE0QjtBQUMxQztBQUNBO0FBQ0E7QUFDQTs7QUFFc0M7O0FBRXRDO0FBQ0E7QUFDQTtBQUNBLFdBQVcsTUFBTTtBQUNqQjtBQUNBLFdBQVcsNEJBQTRCLFVBQVUsYUFBYTtBQUM5RCwrQkFBK0IsYUFBYTtBQUM1QyxhQUFhO0FBQ2I7QUFDQTtBQUNPO0FBQ1A7QUFDQTs7QUFFQSxFQUFFLHdEQUFLOztBQUVQO0FBQ0EsYUFBYSxNQUFNO0FBQ25CO0FBQ0E7QUFDQTtBQUNBO0FBQ0EsTUFBTTtBQUNOO0FBQ0E7QUFDQTtBQUNBIiwic291cmNlcyI6WyJ3ZWJwYWNrOi8vYWdlbnQtaGFybmVzcy1mcm9udGVuZC8uL25vZGVfbW9kdWxlcy91bmlzdC11dGlsLXJlbW92ZS1wb3NpdGlvbi9saWIvaW5kZXguanM/OWRlZiJdLCJzb3VyY2VzQ29udGVudCI6WyIvKipcbiAqIEB0eXBlZGVmIHtpbXBvcnQoJ3VuaXN0JykuTm9kZX0gTm9kZVxuICovXG5cbi8qKlxuICogQHR5cGVkZWYgT3B0aW9uc1xuICogICBDb25maWd1cmF0aW9uLlxuICogQHByb3BlcnR5IHtib29sZWFuIHwgbnVsbCB8IHVuZGVmaW5lZH0gW2ZvcmNlPWZhbHNlXVxuICogICBXaGV0aGVyIHRvIHVzZSBgZGVsZXRlYCB0byByZW1vdmUgYHBvc2l0aW9uYCBmaWVsZHMuXG4gKlxuICogICBUaGUgZGVmYXVsdCBpcyB0byBzZXQgdGhlbSB0byBgdW5kZWZpbmVkYC5cbiAqL1xuXG5pbXBvcnQge3Zpc2l0fSBmcm9tICd1bmlzdC11dGlsLXZpc2l0J1xuXG4vKipcbiAqIFJlbW92ZSB0aGUgYHBvc2l0aW9uYCBmaWVsZCBmcm9tIGEgdHJlZS5cbiAqXG4gKiBAcGFyYW0ge05vZGV9IHRyZWVcbiAqICAgVHJlZSB0byBjbGVhbi5cbiAqIEBwYXJhbSB7T3B0aW9ucyB8IG51bGwgfCB1bmRlZmluZWR9IFtvcHRpb25zPXtmb3JjZTogZmFsc2V9XVxuICogICBDb25maWd1cmF0aW9uIChkZWZhdWx0OiBge2ZvcmNlOiBmYWxzZX1gKS5cbiAqIEByZXR1cm5zIHt1bmRlZmluZWR9XG4gKiAgIE5vdGhpbmcuXG4gKi9cbmV4cG9ydCBmdW5jdGlvbiByZW1vdmVQb3NpdGlvbih0cmVlLCBvcHRpb25zKSB7XG4gIGNvbnN0IGNvbmZpZyA9IG9wdGlvbnMgfHwge31cbiAgY29uc3QgZm9yY2UgPSBjb25maWcuZm9yY2UgfHwgZmFsc2VcblxuICB2aXNpdCh0cmVlLCByZW1vdmUpXG5cbiAgLyoqXG4gICAqIEBwYXJhbSB7Tm9kZX0gbm9kZVxuICAgKi9cbiAgZnVuY3Rpb24gcmVtb3ZlKG5vZGUpIHtcbiAgICBpZiAoZm9yY2UpIHtcbiAgICAgIGRlbGV0ZSBub2RlLnBvc2l0aW9uXG4gICAgfSBlbHNlIHtcbiAgICAgIG5vZGUucG9zaXRpb24gPSB1bmRlZmluZWRcbiAgICB9XG4gIH1cbn1cbiJdLCJuYW1lcyI6W10sInNvdXJjZVJvb3QiOiIifQ==\n//# sourceURL=webpack-internal:///(ssr)/./node_modules/unist-util-remove-position/lib/index.js\n");

/***/ })

};
;