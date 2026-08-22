/* Broke usage beacon. Served as /usage.js. No bundler, no dependencies.
   Site key is data-key on the script tag. sendBeacon cannot set Authorization,
   so the key travels in the JSON body as text/plain. */
(function () {
    try {
        if (typeof navigator === "undefined" || typeof document === "undefined") return;
        if (navigator.webdriver) return;
        var dnt = navigator.doNotTrack || window.doNotTrack;
        if (dnt === "1" || dnt === "yes") return;

        var script = document.currentScript;
        if (!script || !script.src) return;
        var key = script.getAttribute("data-key");
        if (!key) return;

        var ingest = script.src.replace(/\/usage\.js(?:\?.*)?$/i, "/ingest/usage");
        var IDLE_MS = 30 * 60 * 1000;
        var VID = "broke_vid";
        var SID = "broke_sid";
        var SAT = "broke_sat";

        function rid() {
            var bytes = new Uint8Array(18);
            crypto.getRandomValues(bytes);
            var bin = "";
            for (var i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
            return btoa(bin).replace(/[^A-Za-z0-9_-]/g, "").slice(0, 24);
        }

        function visitorId() {
            try {
                var existing = localStorage.getItem(VID);
                if (existing && existing.length >= 8) return existing;
                var created = rid();
                localStorage.setItem(VID, created);
                return created;
            } catch (_) {
                return rid();
            }
        }

        function sessionId() {
            try {
                var now = Date.now();
                var last = parseInt(sessionStorage.getItem(SAT) || "0", 10) || 0;
                var sid = sessionStorage.getItem(SID);
                if (!sid || now - last > IDLE_MS) {
                    sid = rid();
                    sessionStorage.setItem(SID, sid);
                }
                sessionStorage.setItem(SAT, String(now));
                return sid;
            } catch (_) {
                return rid();
            }
        }

        var queue = [];
        var flushTimer = null;

        function enqueue(kind, extra) {
            var event = {
                kind: kind,
                path: location.pathname || "/",
                ts: Date.now()
            };
            if (document.referrer) event.ref = document.referrer;
            if (extra && extra.name) event.name = extra.name;
            queue.push(event);
            if (queue.length >= 8) {
                flush();
                return;
            }
            if (!flushTimer) {
                flushTimer = setTimeout(function () {
                    flushTimer = null;
                    flush();
                }, 2000);
            }
        }

        function flush() {
            if (!queue.length) return;
            var body = JSON.stringify({
                k: key,
                vid: visitorId(),
                sid: sessionId(),
                e: queue.splice(0, queue.length)
            });
            var blob = new Blob([body], { type: "text/plain" });
            if (navigator.sendBeacon) {
                navigator.sendBeacon(ingest, blob);
                return;
            }
            try {
                fetch(ingest, {
                    method: "POST",
                    body: body,
                    headers: { "Content-Type": "text/plain" },
                    keepalive: true,
                    mode: "cors",
                    credentials: "omit"
                });
            } catch (_) { /* ingest is best-effort */ }
        }

        function pageview() {
            enqueue("pageview");
        }

        function track(name) {
            if (!name || typeof name !== "string") return;
            enqueue("event", { name: name.slice(0, 64) });
        }

        var lastPath = location.pathname;
        pageview();

        var history = window.history;
        if (history && history.pushState) {
            var originalPush = history.pushState;
            var originalReplace = history.replaceState;
            history.pushState = function () {
                originalPush.apply(this, arguments);
                if (location.pathname !== lastPath) {
                    lastPath = location.pathname;
                    pageview();
                }
            };
            history.replaceState = function () {
                originalReplace.apply(this, arguments);
                if (location.pathname !== lastPath) {
                    lastPath = location.pathname;
                    pageview();
                }
            };
            window.addEventListener("popstate", function () {
                if (location.pathname !== lastPath) {
                    lastPath = location.pathname;
                    pageview();
                }
            });
        }

        document.addEventListener("visibilitychange", function () {
            if (document.visibilityState === "hidden") flush();
        });
        window.addEventListener("pagehide", flush);

        window.BrokeUsage = { track: track };
    } catch (_) { /* never throw into the host page */ }
})();
