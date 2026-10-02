/* Fresh on load, then privacy-checked polling; manual refresh works without JS. */
(function () {
  "use strict";
  var reading = document.getElementById("scene-reading");
  var status = document.getElementById("scene-poll-status");
  if (!reading || reading.dataset.live !== "true" || !status) return;
  var url = new URL(window.location.href);
  var page = url.searchParams.get("page");
  if (page && page !== "latest") {
    status.textContent = "Reading an earlier page. Choose Refresh latest entries to follow the scene.";
    return;
  }
  url.searchParams.set("poll", "1");
  url.searchParams.set("page", "latest");
  status.textContent = "Following live entries. Updates every 10 seconds.";

  function poll() {
    if (document.hidden) {
      window.setTimeout(poll, 10000);
      return;
    }
    fetch(url, { credentials: "same-origin", cache: "no-store" })
      .then(function (response) {
        if (response.status === 403 || response.status === 404) {
          reading.replaceChildren();
          throw new Error("This scene is no longer available. Refresh the page to check access.");
        }
        if (!response.ok || !response.headers.get("Content-Type").includes("application/json")) {
          throw new Error("Updates paused. Use Refresh latest entries to try again.");
        }
        return response.json();
      })
      .then(function (data) {
        // Let readers finish selecting text or using a focused log control.
        // Keep checking even if the scene closes while replacement is deferred.
        if (window.getSelection().toString() || reading.contains(document.activeElement)) {
          window.setTimeout(poll, 10000);
          return;
        }
        // HTML is rendered and escaped by the same template as the initial page.
        var fragment = document.createElement("div");
        fragment.innerHTML = data.html;
        var details = reading.querySelector("details");
        var nextDetails = fragment.querySelector("details");
        if (details && nextDetails) nextDetails.open = details.open;
        if (fragment.innerHTML !== reading.innerHTML) {
          var scroll = window.scrollY;
          reading.replaceChildren.apply(reading, Array.from(fragment.childNodes));
          window.scrollTo(0, scroll);
        }
        if (!data.live) {
          status.textContent = "This scene has ended. Its final entries are shown below.";
          return;
        }
        window.setTimeout(poll, 10000);
      })
      .catch(function (error) {
        status.textContent = error.message || "Updates paused. Refresh this page to try again.";
      });
  }
  window.setTimeout(poll, 10000);
}());
