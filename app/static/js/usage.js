/* Usage visuals: filled traffic, KPI sparklines, sector donut, user-flow. */
(function () {
    var node = document.getElementById("usage-data");
    if (!node) return;
    var data;
    try {
        data = JSON.parse(node.textContent || "{}") || {};
    } catch (_) {
        return;
    }

    var root = getComputedStyle(document.documentElement);
    function token(name, fallback) {
        return (root.getPropertyValue(name) || "").trim() || fallback;
    }
    var usersColor = token("--use-line", "#106ecc");
    var viewsColor = token("--use-line-2", "#12b5cb");
    var grid = token("--use-grid", "#e5e7eb");
    var axis = token("--use-axis", "#999999");
    var font = "11px " + token("--use-chart-font", "system-ui, sans-serif");
    var palette = [
        token("--use-1", "#106ecc"),
        token("--use-2", "#0d9488"),
        token("--use-3", "#d97706"),
        token("--use-4", "#7c3aed"),
        token("--use-5", "#e11d48"),
        token("--use-6", "#16a34a"),
        token("--use-7", "#0891b2"),
        token("--use-8", "#475569")
    ];

    function withAlpha(colour, alpha) {
        var hex = (colour || "").trim();
        if (hex.charAt(0) !== "#") return hex;
        if (hex.length === 4) {
            hex = "#" + hex[1] + hex[1] + hex[2] + hex[2] + hex[3] + hex[3];
        }
        var parsed = parseInt(hex.slice(1), 16);
        if (isNaN(parsed)) return colour;
        var r = (parsed >> 16) & 255;
        var g = (parsed >> 8) & 255;
        var b = parsed & 255;
        return "rgba(" + r + "," + g + "," + b + "," + alpha + ")";
    }

    function seriesValues(rows) {
        var xs = [];
        var ys = [];
        (rows || []).forEach(function (p) {
            xs.push((p.ts || 0) / 1000);
            ys.push(p.value || 0);
        });
        return [xs, ys];
    }

    function formatAxisTime(seconds, spanSec) {
        var d = new Date(seconds * 1000);
        if (spanSec <= 36 * 3600) {
            return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
        }
        return d.toLocaleDateString([], { month: "short", day: "numeric" });
    }

    function areaFill(u, colour) {
        var gradient = u.ctx.createLinearGradient(0, u.bbox.top, 0, u.bbox.top + u.bbox.height);
        gradient.addColorStop(0, withAlpha(colour, 0.28));
        gradient.addColorStop(1, withAlpha(colour, 0.02));
        return gradient;
    }

    function drawTraffic() {
        if (typeof uPlot === "undefined") return;
        var el = document.getElementById("usage-traffic");
        if (!el) return;
        var body = el.querySelector(".use-chart-body");
        if (!body) return;
        var views = seriesValues(data.views);
        var users = seriesValues(data.users);
        if (!views[0].length) return;

        var xs = views[0];
        var usersY = users[1].length === xs.length ? users[1] : views[1].map(function () { return 0; });
        var spanSec = xs.length > 1 ? xs[xs.length - 1] - xs[0] : 0;

        var chart = new uPlot(
            {
                width: Math.max(160, body.clientWidth),
                height: Math.max(180, body.clientHeight || 280),
                padding: [8, 28, 0, 0],
                cursor: { y: false },
                legend: { show: false },
                scales: { x: { time: true } },
                axes: [
                    {
                        stroke: axis,
                        grid: { stroke: grid },
                        ticks: { stroke: grid, size: 4 },
                        font: font,
                        space: spanSec > 36 * 3600 ? 84 : 64,
                        size: 36,
                        values: function (_u, splits) {
                            return splits.map(function (s) {
                                return formatAxisTime(s, spanSec);
                            });
                        }
                    },
                    {
                        stroke: axis,
                        grid: { stroke: grid },
                        ticks: { stroke: grid },
                        font: font,
                        size: 44
                    }
                ],
                series: [
                    {},
                    {
                        label: "Users",
                        stroke: usersColor,
                        width: 2,
                        fill: function (u) { return areaFill(u, usersColor); },
                        points: { show: false }
                    },
                    {
                        label: "Views",
                        stroke: viewsColor,
                        width: 2,
                        points: { show: false }
                    }
                ]
            },
            [xs, usersY, views[1]],
            body
        );

        if (typeof ResizeObserver !== "undefined") {
            new ResizeObserver(function () {
                chart.setSize({
                    width: Math.max(160, body.clientWidth),
                    height: Math.max(180, body.clientHeight || 280)
                });
            }).observe(body);
        }
    }

    function sparkline(el, values, colour) {
        if (!el || !values || !values.length) return;
        var w = Math.max(80, el.clientWidth || 120);
        var h = Math.max(24, el.clientHeight || 36);
        var max = Math.max.apply(null, values.concat([1]));
        var min = Math.min.apply(null, values);
        var span = Math.max(1, max - min);
        var pts = values.map(function (v, i) {
            var x = values.length === 1 ? w / 2 : (i / (values.length - 1)) * w;
            var y = h - 2 - ((v - min) / span) * (h - 4);
            return x.toFixed(1) + "," + y.toFixed(1);
        });
        var last = values[values.length - 1];
        var lastX = values.length === 1 ? w / 2 : w;
        var lastY = h - 2 - ((last - min) / span) * (h - 4);
        el.innerHTML =
            '<svg viewBox="0 0 ' + w + " " + h + '" width="100%" height="100%" preserveAspectRatio="none">' +
            '<polyline fill="none" stroke="' + colour + '" stroke-width="1.6" points="' + pts.join(" ") + '"/>' +
            '<circle cx="' + lastX.toFixed(1) + '" cy="' + lastY.toFixed(1) + '" r="2.2" fill="' + colour + '"/>' +
            "</svg>";
    }

    function drawSparks() {
        document.querySelectorAll("[data-spark]").forEach(function (el) {
            var key = el.getAttribute("data-spark");
            var rows = key === "users" ? data.users : data.views;
            var values = (rows || []).map(function (p) { return p.value || 0; });
            sparkline(el, values, key === "users" ? usersColor : viewsColor);
        });
    }

    function polar(cx, cy, r, angle) {
        return [cx + r * Math.cos(angle), cy + r * Math.sin(angle)];
    }

    function arcPath(cx, cy, r, a0, a1) {
        var start = polar(cx, cy, r, a0);
        var end = polar(cx, cy, r, a1);
        var large = a1 - a0 > Math.PI ? 1 : 0;
        return "M " + cx + " " + cy + " L " + start[0] + " " + start[1] +
            " A " + r + " " + r + " 0 " + large + " 1 " + end[0] + " " + end[1] + " Z";
    }

    function drawDonut() {
        var el = document.getElementById("usage-donut");
        if (!el) return;
        var items = (data.sectors || []).slice(0, 8);
        var total = items.reduce(function (sum, row) { return sum + (row.count || 0); }, 0);
        if (!total) return;
        var cx = 70;
        var cy = 70;
        var r = 62;
        var angle = -Math.PI / 2;
        var parts = items.map(function (row, i) {
            var slice = (row.count / total) * Math.PI * 2;
            var a0 = angle;
            var a1 = angle + Math.max(slice, 0.02);
            angle = a1;
            return '<path d="' + arcPath(cx, cy, r, a0, a1) + '" fill="' + palette[i % palette.length] + '"/>';
        });
        el.innerHTML =
            '<svg viewBox="0 0 140 140" width="140" height="140">' +
            parts.join("") +
            '<circle cx="70" cy="70" r="36" fill="rgb(245,245,245)"/>' +
            "</svg>";
    }

    function fmt(n) {
        return Number(n || 0).toLocaleString();
    }

    function escapeHtml(text) {
        return String(text)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    function countFor(rows, label) {
        var found = (rows || []).find(function (row) { return row.label === label; });
        return found ? (found.count || 0) : 0;
    }

    function topRows(rows, limit) {
        var sorted = (rows || []).slice().sort(function (a, b) { return (b.count || 0) - (a.count || 0); });
        if (sorted.length <= limit) return sorted;
        var head = sorted.slice(0, limit - 1);
        var rest = sorted.slice(limit - 1).reduce(function (sum, row) { return sum + (row.count || 0); }, 0);
        if (rest) head.push({ label: "Other", count: rest, other: true });
        return head;
    }

    function flowColumn(title, rows, kind) {
        var max = Math.max.apply(null, rows.map(function (row) { return row.count || 0; }).concat([1]));
        var items = rows.map(function (row) {
            var special = row.special || row.other;
            var bar = Math.max(4, Math.round(100 * (row.count || 0) / max));
            var fillClass = kind === "next" ? "use-flow-fill is-next" : "use-flow-fill";
            var nameClass = special ? "use-flow-name is-special" : "use-flow-name";
            var inner =
                '<span class="' + nameClass + '">' + escapeHtml(row.label) + "</span>" +
                '<span class="use-flow-n">' + fmt(row.count) + "</span>" +
                '<div class="use-flow-track"><div class="' + fillClass + '" style="width:' + bar + '%"></div></div>';
            if (special) {
                return '<div class="use-flow-row">' + inner + "</div>";
            }
            return (
                '<button type="button" class="use-flow-row" data-page="' + escapeHtml(row.id || row.label) + '">' +
                inner +
                "</button>"
            );
        }).join("");
        return (
            '<div>' +
            '<div class="use-flow-col-label">' + title + "</div>" +
            (items || '<div class="use-flow-empty">None</div>') +
            "</div>"
        );
    }

    function selectPage(page) {
        var current = String(page || "");
        document.querySelectorAll(".use-page-row").forEach(function (btn) {
            var on = btn.getAttribute("data-page") === current;
            btn.classList.toggle("is-active", on);
            btn.setAttribute("aria-pressed", on ? "true" : "false");
        });
        var caption = document.getElementById("usage-flow-caption");
        if (caption) {
            caption.textContent = current
                ? "How people reach " + current + " and where they go next"
                : "Where people came from, and where they went next";
        }
        drawFlow(current);
    }

    function drawFlow(page) {
        var el = document.getElementById("usage-flow");
        if (!el) return;
        var selected = page || ((data.pages || [])[0] || {}).label;
        if (!selected) {
            el.innerHTML = '<div class="use-flow-empty">No page selected</div>';
            return;
        }

        var inbound = [];
        var outbound = [];
        (data.transitions || []).forEach(function (link) {
            if (link.to === selected) inbound.push({ label: link.frm, id: link.frm, count: link.count });
            if (link.frm === selected) outbound.push({ label: link.to, id: link.to, count: link.count });
        });
        var started = countFor(data.entries, selected);
        var stopped = countFor(data.exits, selected);
        if (started) inbound.push({ label: "Started here", count: started, special: true });
        if (stopped) outbound.push({ label: "Stopped here", count: stopped, special: true });

        inbound = topRows(inbound, 6);
        outbound = topRows(outbound, 6);

        var views = countFor(data.pages, selected);
        el.innerHTML =
            '<div class="use-flow-board">' +
            flowColumn("Came from", inbound, "from") +
            '<div class="use-flow-center">' +
            '<div class="use-flow-focus">' + escapeHtml(selected) + "</div>" +
            '<span class="use-flow-focus-meta">' + fmt(views) + " views</span>" +
            "</div>" +
            flowColumn("Went next", outbound, "next") +
            "</div>";
    }

    function bindPages() {
        var root = document.getElementById("usage-pages");
        if (root) {
            root.addEventListener("click", function (ev) {
                var btn = ev.target.closest("[data-page]");
                if (btn) selectPage(btn.getAttribute("data-page"));
            });
        }
        var flow = document.getElementById("usage-flow");
        if (flow) {
            flow.addEventListener("click", function (ev) {
                var btn = ev.target.closest("button[data-page]");
                if (btn) selectPage(btn.getAttribute("data-page"));
            });
        }
        var first = document.querySelector(".use-page-row[data-page]");
        selectPage(first ? first.getAttribute("data-page") : "");
    }

    function mixHex(a, b, t) {
        function ch(hex, i) {
            return parseInt(hex.slice(i, i + 2), 16);
        }
        var aa = a.replace("#", "");
        var bb = b.replace("#", "");
        if (aa.length === 3) aa = aa[0] + aa[0] + aa[1] + aa[1] + aa[2] + aa[2];
        if (bb.length === 3) bb = bb[0] + bb[0] + bb[1] + bb[1] + bb[2] + bb[2];
        var r = Math.round(ch(aa, 0) + (ch(bb, 0) - ch(aa, 0)) * t);
        var g = Math.round(ch(aa, 2) + (ch(bb, 2) - ch(aa, 2)) * t);
        var bl = Math.round(ch(aa, 4) + (ch(bb, 4) - ch(aa, 4)) * t);
        return "rgb(" + r + "," + g + "," + bl + ")";
    }

    function drawMap() {
        var el = document.getElementById("usage-map");
        if (!el) return;
        var src = el.getAttribute("data-src");
        if (!src) return;
        var rows = data.countries || [];
        var byCode = {};
        var max = 1;
        rows.forEach(function (row) {
            var code = String(row.label || "").toUpperCase();
            byCode[code] = row;
            if ((row.count || 0) > max) max = row.count;
        });
        var empty = token("--use-map-empty", "#e4e4e4");
        var tip = document.getElementById("usage-map-tip");
        var back = document.getElementById("usage-map-back");

        fetch(src)
            .then(function (res) { return res.ok ? res.json() : null; })
            .then(function (world) {
                if (!world || !world.c) return;
                var worldW = world.w || 1400;
                var worldH = world.h || 700;
                var worldBox = [0, 0, worldW, worldH];
                var selectedId = "";
                var anim = 0;

                var parts = world.c.map(function (country) {
                    var row = byCode[country.id];
                    var count = row ? row.count || 0 : 0;
                    var t = count ? 0.2 + Math.sqrt(count / max) * 0.8 : 0;
                    var fill = count ? mixHex("#c5daf0", usersColor, t) : empty;
                    return (
                        '<path fill-rule="evenodd" data-id="' + escapeHtml(country.id) +
                        '" data-name="' + escapeHtml(country.n || country.id) +
                        '" d="' + country.d + '" fill="' + fill + '"' +
                        (count ? ' class="is-hot"' : "") + "></path>"
                    );
                });
                var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
                svg.setAttribute("viewBox", worldBox.join(" "));
                svg.setAttribute("role", "img");
                svg.setAttribute("aria-label", "Visitors by country");
                var lakes = world.l
                    ? '<path class="use-map-water" d="' + world.l + '"></path>'
                    : "";
                svg.innerHTML = parts.join("") + lakes;
                el.insertBefore(svg, el.firstChild);

                function parseBox() {
                    return (svg.getAttribute("viewBox") || "").split(/[\s,]+/).map(Number);
                }

                function largestBox(path) {
                    var d = path.getAttribute("d") || "";
                    var parts = d.split(/(?=[Mm])/);
                    var best = null;
                    var bestArea = 0;
                    parts.forEach(function (part) {
                        if (!part) return;
                        var probe = document.createElementNS("http://www.w3.org/2000/svg", "path");
                        probe.setAttribute("d", part);
                        svg.appendChild(probe);
                        var box = probe.getBBox();
                        svg.removeChild(probe);
                        var area = box.width * box.height;
                        if (area > bestArea) {
                            best = box;
                            bestArea = area;
                        }
                    });
                    return best || path.getBBox();
                }

                function fitCountry(path) {
                    var box = largestBox(path);
                    if (!box.width && !box.height) return worldBox;
                    var padX = Math.max(box.width * 0.28, 4);
                    var padY = Math.max(box.height * 0.28, 4);
                    var w = box.width + padX * 2;
                    var h = box.height + padY * 2;
                    var aspect = worldW / worldH;
                    if (w / h < aspect) w = h * aspect;
                    else h = w / aspect;
                    w = Math.min(w, worldW);
                    h = Math.min(h, worldH);
                    return [
                        box.x + box.width / 2 - w / 2,
                        box.y + box.height / 2 - h / 2,
                        w,
                        h
                    ];
                }

                function setBox(to, animate) {
                    var from = parseBox();
                    if (!animate) {
                        svg.setAttribute("viewBox", to.join(" "));
                        return;
                    }
                    var start = performance.now();
                    var token = ++anim;
                    function tick(now) {
                        if (token !== anim) return;
                        var t = Math.min(1, (now - start) / 420);
                        var e = 1 - (1 - t) * (1 - t);
                        svg.setAttribute(
                            "viewBox",
                            from.map(function (v, i) { return v + (to[i] - v) * e; }).join(" ")
                        );
                        if (t < 1) requestAnimationFrame(tick);
                    }
                    requestAnimationFrame(tick);
                }

                function prefersReduce() {
                    return window.matchMedia &&
                        window.matchMedia("(prefers-reduced-motion: reduce)").matches;
                }

                function markSelected(id) {
                    selectedId = id || "";
                    svg.querySelectorAll("path[data-id]").forEach(function (path) {
                        path.classList.toggle("is-selected", path.getAttribute("data-id") === selectedId);
                    });
                    if (back) back.hidden = !selectedId;
                    var focused = selectedId
                        ? svg.querySelector('path[data-id="' + selectedId + '"]')
                        : null;
                    svg.setAttribute(
                        "aria-label",
                        focused
                            ? "Visitors in " + (focused.getAttribute("data-name") || selectedId)
                            : "Visitors by country"
                    );
                }

                function zoomTo(path) {
                    var id = path.getAttribute("data-id");
                    if (!id) return;
                    if (id === selectedId) {
                        zoomOut();
                        return;
                    }
                    markSelected(id);
                    setBox(fitCountry(path), !prefersReduce());
                }

                function zoomOut() {
                    markSelected("");
                    setBox(worldBox, !prefersReduce());
                }

                function hideTip() {
                    if (tip) tip.hidden = true;
                }

                svg.addEventListener("click", function (ev) {
                    var path = ev.target.closest("path");
                    if (!path || !path.getAttribute("data-id")) return;
                    hideTip();
                    zoomTo(path);
                });
                if (back) {
                    back.addEventListener("click", function () {
                        hideTip();
                        zoomOut();
                    });
                }

                svg.addEventListener("mouseover", function (ev) {
                    var path = ev.target.closest("path");
                    if (!path || !tip || !path.getAttribute("data-id")) return;
                    var row = byCode[path.getAttribute("data-id")];
                    var name = path.getAttribute("data-name") || path.getAttribute("data-id");
                    var count = row ? row.count || 0 : 0;
                    var share = row ? row.share : 0;
                    tip.hidden = false;
                    tip.textContent = count
                        ? name + " · " + fmt(count) + (share ? " (" + share + "%)" : "")
                        : name;
                });
                svg.addEventListener("mousemove", function (ev) {
                    if (!tip || tip.hidden) return;
                    var rect = el.getBoundingClientRect();
                    var x = ev.clientX - rect.left + 12;
                    var y = ev.clientY - rect.top + 12;
                    if (x + tip.offsetWidth > rect.width - 8) x = ev.clientX - rect.left - tip.offsetWidth - 8;
                    if (y + tip.offsetHeight > rect.height - 8) y = ev.clientY - rect.top - tip.offsetHeight - 8;
                    tip.style.left = Math.max(0, x) + "px";
                    tip.style.top = Math.max(0, y) + "px";
                });
                svg.addEventListener("mouseleave", hideTip);
            })
            .catch(function () { /* ranked list still shows */ });
    }

    drawTraffic();
    drawSparks();
    drawDonut();
    bindPages();
    drawMap();
})();

