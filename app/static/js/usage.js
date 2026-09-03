/* Usage dashboard: fetch the lake after the shell paints, then draw. */
(function () {
    var page = document.getElementById("usage-page");
    var body = document.getElementById("usage-body");
    if (!page || !body) return;

    var data = {};
    var trafficChart = null;
    var fetchGen = 0;
    var mapGen = 0;

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

    function destroyTraffic() {
        if (trafficChart) {
            trafficChart.destroy();
            trafficChart = null;
        }
    }

    function drawTraffic() {
        destroyTraffic();
        if (typeof uPlot === "undefined") return;
        var el = document.getElementById("usage-traffic");
        if (!el) return;
        var chartBody = el.querySelector(".use-chart-body");
        if (!chartBody) return;
        var views = seriesValues(data.views);
        var users = seriesValues(data.users);
        if (!views[0].length) return;

        var xs = views[0];
        var usersY = users[1].length === xs.length ? users[1] : views[1].map(function () { return 0; });
        var spanSec = xs.length > 1 ? xs[xs.length - 1] - xs[0] : 0;

        trafficChart = new uPlot(
            {
                width: Math.max(160, chartBody.clientWidth),
                height: Math.max(180, chartBody.clientHeight || 280),
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
            chartBody
        );

        if (typeof ResizeObserver !== "undefined") {
            new ResizeObserver(function () {
                if (!trafficChart) return;
                trafficChart.setSize({
                    width: Math.max(160, chartBody.clientWidth),
                    height: Math.max(180, chartBody.clientHeight || 280)
                });
            }).observe(chartBody);
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
            "<div>" +
            '<div class="use-flow-col-label">' + title + "</div>" +
            (items || '<div class="use-flow-empty">None</div>') +
            "</div>"
        );
    }

    function selectPage(pageName) {
        var current = String(pageName || "");
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

    function drawFlow(pageName) {
        var el = document.getElementById("usage-flow");
        if (!el) return;
        var selected = pageName || ((data.pages || [])[0] || {}).label;
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
        var first = document.querySelector(".use-page-row[data-page]");
        selectPage(first ? first.getAttribute("data-page") : "");
    }

    body.addEventListener("click", function (ev) {
        var pageBtn = ev.target.closest(".use-page-row[data-page], .use-flow-row[data-page]");
        if (!pageBtn || !body.contains(pageBtn)) return;
        selectPage(pageBtn.getAttribute("data-page"));
    });

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
        var src = el.getAttribute("data-src") || page.getAttribute("data-map-src");
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
        var thisMap = ++mapGen;

        fetch(src)
            .then(function (res) { return res.ok ? res.json() : null; })
            .then(function (world) {
                if (thisMap !== mapGen) return;
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
                    var pieces = d.split(/(?=[Mm])/);
                    var best = null;
                    var bestArea = 0;
                    pieces.forEach(function (part) {
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
                    var tokenId = ++anim;
                    function tick(now) {
                        if (tokenId !== anim) return;
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

                function countryLabel(id) {
                    if (!id) return "";
                    var path = svg.querySelector('path[data-id="' + id + '"]');
                    return (path && path.getAttribute("data-name")) || id;
                }

                function citiesIn(country) {
                    var rows = data.cities || [];
                    if (!country) return rows.slice(0, 20);
                    return rows.filter(function (row) {
                        return String(row.country || "").toUpperCase() === country;
                    });
                }

                function paintCityBars(country) {
                    var title = document.getElementById("usage-cities-title");
                    var body = document.getElementById("usage-cities-body");
                    var mapTitle = document.getElementById("usage-map-title");
                    var name = countryLabel(country);
                    if (title) title.textContent = country ? "Cities in " + name : "Cities";
                    if (mapTitle) mapTitle.textContent = country ? name : "Countries";
                    if (!body) return;
                    var rows = citiesIn(country);
                    if (!rows.length) {
                        body.innerHTML = country
                            ? '<div class="use-flow-empty">No city breakdown for ' +
                              escapeHtml(name) + "</div>"
                            : '<div class="use-flow-empty">No city data</div>';
                        return;
                    }
                    var peak = Math.max.apply(
                        null,
                        rows.map(function (row) { return row.count || 0; }).concat([1])
                    );
                    body.innerHTML = barList(
                        rows.map(function (row) {
                            return {
                                label: country ? row.label : (row.display || row.label),
                                count: row.count,
                                share: row.share,
                                bar: Math.round((1000 * (row.count || 0)) / peak) / 10
                            };
                        }),
                        false
                    );
                }

                function clearCityMarks() {
                    var group = svg.querySelector(".use-map-cities");
                    if (group) group.remove();
                }

                function drawCityMarks(country, box) {
                    clearCityMarks();
                    if (!country) return;
                    var rows = citiesIn(country).filter(function (row) {
                        return row.x != null && row.y != null;
                    });
                    if (!rows.length) return;
                    var max = Math.max.apply(
                        null,
                        rows.map(function (row) { return row.count || 0; }).concat([1])
                    );
                    var viewW = box[2];
                    var ns = "http://www.w3.org/2000/svg";
                    var group = document.createElementNS(ns, "g");
                    group.setAttribute("class", "use-map-cities");
                    var ranked = rows.slice().sort(function (a, b) {
                        return (b.count || 0) - (a.count || 0);
                    });
                    var labeled = {};
                    ranked.slice(0, ranked.length <= 8 ? ranked.length : 6).forEach(function (row) {
                        labeled[row.label] = true;
                    });
                    ranked.slice().reverse().forEach(function (row) {
                        var t = Math.sqrt((row.count || 0) / max);
                        var r = viewW * (0.006 + t * 0.01);
                        var circle = document.createElementNS(ns, "circle");
                        circle.setAttribute("class", "use-map-city");
                        circle.setAttribute("cx", row.x);
                        circle.setAttribute("cy", row.y);
                        circle.setAttribute("r", r.toFixed(2));
                        circle.setAttribute("data-name", row.label);
                        circle.setAttribute("data-count", String(row.count || 0));
                        circle.setAttribute("data-share", String(row.share || 0));
                        group.appendChild(circle);
                        if (!labeled[row.label]) return;
                        var onRight = row.x < box[0] + box[2] * 0.62;
                        var gap = r + viewW * 0.01;
                        var text = document.createElementNS(ns, "text");
                        text.setAttribute("class", "use-map-city-label");
                        text.setAttribute("x", (row.x + (onRight ? gap : -gap)).toFixed(1));
                        text.setAttribute("y", row.y.toFixed(1));
                        text.setAttribute("text-anchor", onRight ? "start" : "end");
                        text.setAttribute("font-size", Math.max(1.2, viewW * 0.022).toFixed(2));
                        text.setAttribute("dominant-baseline", "middle");
                        text.textContent = row.label;
                        group.appendChild(text);
                    });
                    svg.appendChild(group);
                }

                function markSelected(id) {
                    selectedId = id || "";
                    el.classList.toggle("is-zoomed", !!selectedId);
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
                    var box = fitCountry(path);
                    markSelected(id);
                    setBox(box, !prefersReduce());
                    drawCityMarks(id, box);
                    paintCityBars(id);
                }

                function zoomOut() {
                    markSelected("");
                    setBox(worldBox, !prefersReduce());
                    clearCityMarks();
                    paintCityBars("");
                }

                function hideTip() {
                    if (tip) tip.hidden = true;
                }

                svg.addEventListener("click", function (ev) {
                    if (ev.target.closest(".use-map-city, .use-map-city-label")) return;
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
                    if (!tip) return;
                    var city = ev.target.closest(".use-map-city");
                    if (city) {
                        var cityCount = Number(city.getAttribute("data-count") || 0);
                        var cityShare = city.getAttribute("data-share");
                        var cityName = city.getAttribute("data-name") || "";
                        tip.hidden = false;
                        tip.textContent = cityCount
                            ? cityName + " · " + fmt(cityCount) +
                              (cityShare && cityShare !== "0" ? " (" + cityShare + "%)" : "")
                            : cityName;
                        return;
                    }
                    var path = ev.target.closest("path");
                    if (!path || !path.getAttribute("data-id")) return;
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

    function barList(rows, showFlag) {
        return (
            '<div class="use-bars">' +
            (rows || []).map(function (row) {
                var label = row.display || row.label || "";
                var flag = showFlag && row.flag
                    ? '<span class="use-flag">' + row.flag + "</span>"
                    : "";
                return (
                    '<div class="use-bar-row">' +
                    '<div class="use-bar-top">' +
                    '<span class="use-bar-label">' + flag + escapeHtml(label) + "</span>" +
                    '<span class="use-bar-meta"><strong>' + fmt(row.count) + "</strong>" +
                    "<span>" + escapeHtml(row.share) + "%</span></span>" +
                    "</div>" +
                    '<div class="use-bar-track"><div class="use-bar-fill" style="width: ' +
                    (row.bar || 0) + '%"></div></div>' +
                    "</div>"
                );
            }).join("") +
            "</div>"
        );
    }

    function renderEmpty() {
        var hasKey = page.getAttribute("data-has-key") === "1";
        var snippet = page.getAttribute("data-snippet") || "";
        var settings = page.getAttribute("data-settings") || "/settings/usage";
        var extra;
        if (hasKey) {
            extra =
                "<p>Add this snippet to your product. Pageviews arrive here; errors still go through the Sentry DSN.</p>" +
                "<pre><code>&lt;script defer src=\"" + escapeHtml(snippet) +
                "\" data-key=\"YOUR_SITE_KEY\"&gt;&lt;/script&gt;</code></pre>";
        } else {
            extra =
                "<p>Create a site key under <a href=\"" + escapeHtml(settings) +
                "\">Settings › Usage</a>, then add the snippet to your product.</p>";
        }
        body.innerHTML =
            '<div class="use-empty">' +
            '<i class="ph ph-chart-line-up"></i>' +
            "<p>No usage events in this range.</p>" +
            extra +
            "</div>";
    }

    function renderMessage(text) {
        body.innerHTML =
            '<div class="use-empty">' +
            '<i class="ph ph-chart-line-up"></i>' +
            "<p>" + escapeHtml(text) + "</p>" +
            "</div>";
    }

    function pageRowsHtml(rows) {
        return (rows || []).slice(0, 12).map(function (row) {
            var users = row.users
                ? "<span>" + fmt(row.users) + " users</span>"
                : "";
            return (
                '<button type="button" class="use-page-row" data-page="' +
                escapeHtml(row.label) + '" aria-pressed="false">' +
                '<div class="use-bar-top">' +
                '<span class="use-bar-label">' + escapeHtml(row.label) + "</span>" +
                '<span class="use-bar-meta"><strong>' + fmt(row.count) + "</strong>" +
                users + "</span></div>" +
                '<div class="use-bar-track"><div class="use-bar-fill" style="width: ' +
                (row.bar || 0) + '%"></div></div>' +
                "</button>"
            );
        }).join("");
    }

    function gatesHtml(rows) {
        return (rows || []).map(function (row) {
            return (
                '<div class="use-gate-row">' +
                '<span class="use-gate-label" title="' + escapeHtml(row.label) + '">' +
                escapeHtml(row.label) + "</span>" +
                '<div class="use-gate-metric"><span class="use-gate-n">' + fmt(row.entries) +
                '</span><div class="use-bar-track"><div class="use-bar-fill use-fill-start" style="width: ' +
                (row.entry_bar || 0) + '%"></div></div></div>' +
                '<div class="use-gate-metric"><span class="use-gate-n">' + fmt(row.exits) +
                '</span><div class="use-bar-track"><div class="use-bar-fill use-fill-stop" style="width: ' +
                (row.exit_bar || 0) + '%"></div></div></div>' +
                "</div>"
            );
        }).join("");
    }

    function journeysHtml(rows) {
        return (
            '<ol class="use-journeys">' +
            (rows || []).map(function (row) {
                var steps = (row.steps || []).map(function (step, i, all) {
                    var node = step === "…"
                        ? '<span class="use-journey-more">…</span>'
                        : '<span class="use-journey-step">' + escapeHtml(step) + "</span>";
                    var arrow = i < all.length - 1
                        ? '<span class="use-journey-arrow" aria-hidden="true">→</span>'
                        : "";
                    return node + arrow;
                }).join("");
                return (
                    '<li class="use-journey">' +
                    '<span class="use-journey-count">' + fmt(row.count) + "</span>" +
                    '<div class="use-journey-body">' +
                    '<div class="use-journey-fill" style="width: ' + (row.bar || 0) + '%"></div>' +
                    '<div class="use-journey-steps">' + steps + "</div>" +
                    "</div></li>"
                );
            }).join("") +
            "</ol>"
        );
    }

    function renderDashboard() {
        destroyTraffic();
        mapGen += 1;

        var pps = data.pages_per_session_display
            ? escapeHtml(data.pages_per_session_display) + " per session"
            : "—";
        var bounceValue = data.bounce_display ? escapeHtml(data.bounce_display) : "—";
        var html = "";

        html +=
            '<div class="use-kpis">' +
            '<div class="use-kpi"><div class="use-kpi-head"><span class="use-kpi-label">' +
            '<i class="ph ph-users"></i> Users</span></div>' +
            '<span class="use-kpi-value">' + fmt(data.uniques) + "</span>" +
            '<span class="use-kpi-sub">' + fmt(data.sessions) + " sessions</span>" +
            '<div class="use-spark" data-spark="users"></div></div>' +
            '<div class="use-kpi"><div class="use-kpi-head"><span class="use-kpi-label">' +
            '<i class="ph ph-eye"></i> Views</span></div>' +
            '<span class="use-kpi-value">' + fmt(data.pageviews) + "</span>" +
            '<span class="use-kpi-sub">' + pps + "</span>" +
            '<div class="use-spark" data-spark="views"></div></div>' +
            '<div class="use-kpi"><div class="use-kpi-head"><span class="use-kpi-label">' +
            '<i class="ph ph-timer"></i> Avg. session</span></div>' +
            '<span class="use-kpi-value">' + escapeHtml(data.avg_session_display || "—") + "</span>" +
            '<span class="use-kpi-sub">First to last beacon</span></div>' +
            '<div class="use-kpi use-kpi-bounce"><div class="use-kpi-head"><span class="use-kpi-label">' +
            '<i class="ph ph-arrow-u-up-left"></i> Bounce rate</span></div>' +
            '<div class="use-bounce"><div class="use-ring" style="--pct: ' + (data.bounce_pct || 0) +
            '"></div><div><span class="use-kpi-value">' + bounceValue + "</span>" +
            '<span class="use-kpi-sub">' + fmt(data.bounced) + " of " + fmt(data.sessions) +
            " sessions</span></div></div></div></div>";

        html +=
            '<section class="use-chart" id="usage-traffic">' +
            '<div class="use-chart-head"><h2>Traffic</h2>' +
            '<div class="use-legend">' +
            '<span class="use-legend-item"><i class="use-swatch use-swatch-users"></i> Users</span>' +
            '<span class="use-legend-item"><i class="use-swatch use-swatch-views"></i> Views</span>' +
            "</div></div><div class=\"use-chart-body\"></div></section>";

        if ((data.pages || []).length) {
            html +=
                '<div class="use-grid use-grid-main">' +
                '<section class="use-panel"><h2>Pages</h2>' +
                '<p class="use-panel-lead">Select a page to see how people reach it</p>' +
                '<div class="use-pages" id="usage-pages">' + pageRowsHtml(data.pages) + "</div></section>" +
                '<section class="use-panel use-panel-flow"><h2>User flow</h2>' +
                '<p class="use-panel-lead" id="usage-flow-caption">Where people came from, and where they went next</p>' +
                '<div class="use-flow" id="usage-flow"></div></section></div>';
        }

        html += '<div class="use-grid">';
        if ((data.sectors || []).length) {
            html +=
                '<section class="use-panel"><h2>Sectors</h2><div class="use-split">' +
                '<div class="use-donut" id="usage-donut"></div>' +
                barList(data.sectors.slice(0, 8), false) +
                "</div></section>";
        }
        if ((data.events || []).length) {
            html += '<section class="use-panel"><h2>Events</h2>' + barList(data.events, false) + "</section>";
        } else if ((data.routes || []).length) {
            html += '<section class="use-panel"><h2>Routes</h2>' + barList(data.routes.slice(0, 8), false) + "</section>";
        }
        html += "</div>";

        if ((data.gates || []).length) {
            html +=
                '<section class="use-panel use-panel-wide"><h2>Where they start and stop</h2>' +
                '<div class="use-gates-legend">' +
                '<span class="use-legend-item"><i class="use-swatch use-swatch-start"></i> Start</span>' +
                '<span class="use-legend-item"><i class="use-swatch use-swatch-stop"></i> Stop</span>' +
                "</div><div class=\"use-gates\"><div class=\"use-gate-head\"><span>Page</span>" +
                "<span>Start</span><span>Stop</span></div>" +
                gatesHtml(data.gates) +
                "</div></section>";
        }

        if ((data.journeys || []).length) {
            html +=
                '<section class="use-panel use-panel-wide"><h2>Journeys</h2>' +
                journeysHtml(data.journeys) +
                "</section>";
        }

        if (data.has_geo) {
            if ((data.countries || []).length) {
                html +=
                    '<section class="use-panel use-panel-wide use-panel-map"><h2 id="usage-map-title">Countries</h2>' +
                    '<div class="use-map" id="usage-map" data-src="' +
                    escapeHtml(page.getAttribute("data-map-src") || "") +
                    '"><button type="button" class="use-map-back" id="usage-map-back" hidden>World</button>' +
                    '<div class="use-map-tip" id="usage-map-tip" hidden></div></div>' +
                    '<div class="use-map-legend" aria-hidden="true"><span>Fewer</span>' +
                    '<span class="use-map-scale"><i data-level="0"></i><i data-level="1"></i>' +
                    '<i data-level="2"></i><i data-level="3"></i></span><span>More</span></div></section>';
            }
            html += '<div class="use-grid">';
            if ((data.countries || []).length) {
                html += '<section class="use-panel"><h2>By country</h2>' + barList(data.countries, true) + "</section>";
            }
            if ((data.cities || []).length) {
                html +=
                    '<section class="use-panel" id="usage-cities-panel">' +
                    '<h2 id="usage-cities-title">Cities</h2>' +
                    '<div id="usage-cities-body">' +
                    barList(data.cities.slice(0, 20), false) +
                    "</div></section>";
            }
            html += "</div>";
            var dataset = data.geo_dataset
                ? " · City Lite " + escapeHtml(data.geo_dataset)
                : "";
            html +=
                '<p class="use-credit">IP Geolocation by <a href="https://db-ip.com">DB-IP</a> (CC BY 4.0)' +
                dataset +
                ' · Map and city locations from <a href="https://www.naturalearthdata.com/">Natural Earth</a></p>';
        }

        if ((data.events || []).length && (data.routes || []).length) {
            html +=
                '<section class="use-panel use-panel-wide"><h2>Routes</h2>' +
                barList(data.routes.slice(0, 12), false) +
                "</section>";
        }

        body.innerHTML = html;
        drawTraffic();
        drawSparks();
        drawDonut();
        bindPages();
        drawMap();
    }

    function rangeFromUrl() {
        try {
            return new URL(window.location.href).searchParams.get("range") || "";
        } catch (_) {
            return "";
        }
    }

    function setActiveRange(rangeKey) {
        page.setAttribute("data-range", rangeKey);
        page.querySelectorAll(".use-ranges a").forEach(function (link) {
            link.classList.toggle("is-active", link.getAttribute("data-range") === rangeKey);
        });
    }

    function load(rangeKey, options) {
        var opts = options || {};
        var range = rangeKey || page.getAttribute("data-range") || "7d";
        setActiveRange(range);
        if (!opts.skipHistory) {
            try {
                var url = new URL(window.location.href);
                url.searchParams.set("range", range);
                history[opts.replace ? "replaceState" : "pushState"]({ range: range }, "", url.toString());
            } catch (_) { /* ignore */ }
        }

        var gen = ++fetchGen;
        fetch(brokeAppUrl("/api/usage?range=" + encodeURIComponent(range)), {
            credentials: "same-origin",
            headers: { Accept: "application/json" }
        })
            .then(function (res) {
                if (!res.ok) throw new Error("load failed");
                return res.json();
            })
            .then(function (payload) {
                if (gen !== fetchGen) return;
                data = payload || {};
                if (!data.has_events) {
                    destroyTraffic();
                    renderEmpty();
                    return;
                }
                renderDashboard();
            })
            .catch(function () {
                if (gen !== fetchGen) return;
                destroyTraffic();
                renderMessage("Could not load usage.");
            });
    }

    var ranges = page.querySelector(".use-ranges");
    if (ranges) {
        ranges.addEventListener("click", function (ev) {
            var link = ev.target.closest("a[data-range]");
            if (!link) return;
            ev.preventDefault();
            var next = link.getAttribute("data-range");
            if (next === page.getAttribute("data-range") && data.has_events) return;
            renderMessage("Loading usage…");
            load(next);
        });
    }

    window.addEventListener("popstate", function () {
        var range = rangeFromUrl() || page.getAttribute("data-range") || "7d";
        renderMessage("Loading usage…");
        load(range, { skipHistory: true });
    });

    load(rangeFromUrl() || page.getAttribute("data-range") || "7d", { replace: true });
})();
