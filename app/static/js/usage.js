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

    function shorten(path) {
        var text = String(path || "/");
        if (text.length <= 22) return text;
        return "…" + text.slice(-21);
    }

    function drawFlow() {
        var el = document.getElementById("usage-flow");
        if (!el) return;
        var links = (data.transitions || []).slice(0, 14);
        if (!links.length) return;
        var left = [];
        var right = [];
        var leftCount = {};
        var rightCount = {};
        links.forEach(function (link) {
            leftCount[link.frm] = (leftCount[link.frm] || 0) + link.count;
            rightCount[link.to] = (rightCount[link.to] || 0) + link.count;
        });
        Object.keys(leftCount).forEach(function (k) { left.push({ label: k, count: leftCount[k] }); });
        Object.keys(rightCount).forEach(function (k) { right.push({ label: k, count: rightCount[k] }); });
        left.sort(function (a, b) { return b.count - a.count; });
        right.sort(function (a, b) { return b.count - a.count; });
        left = left.slice(0, 7);
        right = right.slice(0, 7);
        var leftIndex = {};
        var rightIndex = {};
        left.forEach(function (n, i) { leftIndex[n.label] = i; });
        right.forEach(function (n, i) { rightIndex[n.label] = i; });

        var w = Math.max(280, el.clientWidth || 320);
        var h = Math.max(220, el.clientHeight || 320);
        var rowH = Math.min(36, (h - 16) / Math.max(left.length, right.length, 1));
        var maxL = Math.max.apply(null, left.map(function (n) { return n.count; }).concat([1]));
        var maxR = Math.max.apply(null, right.map(function (n) { return n.count; }).concat([1]));
        var maxLink = Math.max.apply(null, links.map(function (n) { return n.count; }).concat([1]));

        function yFor(list, i) {
            var used = list.length * rowH;
            var top = (h - used) / 2;
            return top + i * rowH + rowH / 2;
        }

        var paths = [];
        links.forEach(function (link) {
            if (!(link.frm in leftIndex) || !(link.to in rightIndex)) return;
            var y1 = yFor(left, leftIndex[link.frm]);
            var y2 = yFor(right, rightIndex[link.to]);
            var x1 = 118;
            var x2 = w - 118;
            var mid = (x1 + x2) / 2;
            var width = 1.5 + (link.count / maxLink) * 10;
            var opacity = 0.18 + (link.count / maxLink) * 0.45;
            paths.push(
                '<path d="M ' + x1 + " " + y1 + " C " + mid + " " + y1 + ", " + mid + " " + y2 + ", " + x2 + " " + y2 +
                '" fill="none" stroke="' + usersColor + '" stroke-width="' + width.toFixed(1) +
                '" opacity="' + opacity.toFixed(2) + '"/>'
            );
        });

        function nodes(list, x, align, maxC) {
            return list.map(function (n, i) {
                var y = yFor(list, i);
                var bar = 8 + (n.count / maxC) * 28;
                var rectX = align === "left" ? x - 4 - bar : x + 4;
                var textX = align === "left" ? x - 8 - bar : x + 8 + bar;
                var anchor = align === "left" ? "end" : "start";
                return (
                    '<rect x="' + rectX + '" y="' + (y - 5) + '" width="' + bar + '" height="10" rx="2" fill="' + usersColor + '"/>' +
                    '<text class="use-flow-label" text-anchor="' + anchor + '" x="' + textX + '" y="' + (y + 3) + '">' +
                    escapeXml(shorten(n.label)) + "</text>"
                );
            }).join("");
        }

        el.innerHTML =
            '<svg viewBox="0 0 ' + w + " " + h + '" width="100%" height="100%">' +
            paths.join("") +
            nodes(left, 110, "left", maxL) +
            nodes(right, w - 110, "right", maxR) +
            "</svg>";
    }

    function escapeXml(text) {
        return String(text)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    drawTraffic();
    drawSparks();
    drawDonut();
    drawFlow();
})();
