/* Progress page: draw px.json (built from the public roadmap and the forge by launcher/px/build.py --public). */
(function () {
  "use strict";
  MetallicPX.mount(document.getElementById("px"), function () {
    return fetch("/progress/px.json", { cache: "no-store" }).then(function (r) {
      if (!r.ok) throw new Error("the progress data is not available (" + r.status + ")");
      return r.json();
    });
  }, { title: false });
})();
