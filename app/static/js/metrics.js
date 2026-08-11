/* Charts for the Servers pages, built on the vendored uPlot (app/static/js/vendor).

   uPlot draws to canvas, so it cannot inherit :root variables the way markup does.
   Colours are read out of the stylesheet once at startup instead, which keeps the
   theme in metrics.css rather than duplicated here. */

window.BrokeMetrics = (function () {
    var REFRESH_MS = 30000;
    var theme = null;

    var PALETTE_SIZE = 8;

    function readTheme() {
        if (theme) return theme;
        var root = getComputedStyle(document.documentElement);
        function value(name, fallback) {
            return (root.getPropertyValue(name) || '').trim() || fallback;
        }

        // A chart can now hold a histogram's quantiles or one line per disk, so colours
        // come from a palette. Defaults keep a single-line chart looking as it always did.
        var fallbacks = [
            '#106ecc', '#e8710a', '#0f9d58', '#a142f4',
            '#d93025', '#12b5cb', '#f9ab00', '#7b8794'
        ];
        var palette = [];
        for (var i = 0; i < PALETTE_SIZE; i++) {
            palette.push(value('--met-line-' + (i + 1), fallbacks[i]));
        }

        theme = {
            line: value('--met-line', '#106ecc'),
            fill: value('--met-line-fill', 'rgba(16, 110, 204, 0.12)'),
            grid: value('--met-grid', '#e5e7eb'),
            axis: value('--met-axis', '#999999'),
            font: '11px ' + value('--met-chart-font', 'system-ui, sans-serif'),
            palette: palette
        };
        return theme;
    }

    function formatValue(value, unit) {
        if (value == null || isNaN(value)) return '—';
        if (unit === 'bytes') return formatBytes(value);
        if (unit === 'bytes/s') return formatBytes(value) + '/s';
        if (unit === '%') return value.toFixed(1) + '%';
        if (unit === 'seconds') return formatDuration(value);
        if (Number.isInteger(value)) return value.toLocaleString();
        if (Math.abs(value) >= 1000) return Math.round(value).toLocaleString();
        if (Math.abs(value) >= 10) return value.toFixed(1);
        return value.toFixed(2);
    }

    /* Latency histograms are recorded in seconds but usually live in the milliseconds,
       where "0.00s" would throw away the whole reading. */
    function formatDuration(value) {
        var n = Math.abs(value);
        if (n === 0) return '0';
        if (n < 0.001) return (value * 1000000).toFixed(0) + 'µs';
        if (n < 1) return (value * 1000).toFixed(n < 0.01 ? 1 : 0) + 'ms';
        if (n < 60) return value.toFixed(2) + 's';
        return (value / 60).toFixed(1) + 'm';
    }

    /* Axis ticks land on round numbers, so drop the decimal a reading would want:
       "0%" and "25%" rather than "0.0%" and "25.0%". */
    function formatTick(value, unit) {
        if (unit === '%' && Number.isInteger(value)) return value + '%';
        return formatValue(value, unit);
    }

    function formatBytes(value) {
        var units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
        var index = 0;
        var n = Math.abs(value);
        while (n >= 1024 && index < units.length - 1) {
            n /= 1024;
            index++;
        }
        return (value < 0 ? '-' : '') + n.toFixed(n >= 10 || index === 0 ? 0 : 1) + ' ' + units[index];
    }

    // uPlot renders its legend inside the element it is given, so a chart that shows one
    // has to hand back the room for it or the tile overflows.
    var LEGEND_HEIGHT = 22;

    function canvasSize(body, multi) {
        var reserved = multi ? LEGEND_HEIGHT : 0;
        return {
            width: Math.max(120, body.clientWidth),
            height: Math.max(90, body.clientHeight - reserved)
        };
    }

    function buildOptions(options, body, labels, onCursor) {
        var t = readTheme();
        var multi = labels.length > 1;
        var size = canvasSize(body, multi);

        var series = [{}];
        labels.forEach(function (label, index) {
            var colour = multi ? t.palette[index % t.palette.length] : t.line;
            series.push({
                label: label,
                stroke: colour,
                width: 2,
                // A fill under every line would turn a multi-line chart into mud, so only
                // a chart drawing one thing keeps the shaded area.
                fill: multi ? undefined : t.fill,
                points: { show: false },
                value: function (u, v, sidx) {
                    // Away from the cursor uPlot has no value to report. The latest
                    // reading is more use than a dash, and matches what the header shows
                    // on a chart with a single line.
                    if (v == null) v = lastValue(u.data[sidx] || []);
                    return formatValue(v, options.unit);
                }
            });
        });

        return {
            width: size.width,
            height: size.height,
            // Right padding leaves room for the final x-axis label, which otherwise gets
            // clipped by the plot edge.
            padding: [10, 26, 0, 0],
            // One line keeps the single reading in the header; several need naming, and
            // uPlot's own legend gives each a value at the cursor for free.
            legend: { show: multi, live: multi },
            cursor: {
                y: false,
                drag: { x: true, y: false },
                points: { size: 7, width: 1.5, stroke: '#ffffff' }
            },
            scales: {
                x: { time: true },
                // Percentages keep a fixed 0-100 axis so hosts stay comparable at a glance.
                y: options.unit === '%' ? { range: [0, 100] } : { range: yRange }
            },
            axes: [
                {
                    stroke: t.axis,
                    font: t.font,
                    grid: { show: false },
                    ticks: { stroke: t.grid, size: 4 }
                },
                {
                    stroke: t.axis,
                    font: t.font,
                    size: 58,
                    grid: { stroke: t.grid, width: 1 },
                    ticks: { show: false },
                    values: function (u, splits) {
                        return splits.map(function (v) { return formatTick(v, options.unit); });
                    }
                }
            ],
            series: series,
            hooks: { setCursor: [onCursor] }
        };
    }

    /* Keep a zero baseline when the data sits near it, so a small wobble does not get
       magnified into a dramatic-looking spike. */
    function yRange(u, min, max) {
        if (min == null || max == null) return [0, 1];
        if (min === max) {
            if (min === 0) return [0, 1];
            var flat = Math.abs(min) * 0.1;
            return [min - flat, max + flat];
        }
        if (min > 0 && min < max - min) min = 0;
        return [min, max + (max - min) * 0.1];
    }

    function renderEmpty(container, message) {
        destroyChart(container);
        var body = container.querySelector('[data-role="canvas"]');
        if (body) body.innerHTML = '<div class="met-chart-empty">' + message + '</div>';
        var current = container.querySelector('[data-role="current"]');
        if (current) current.textContent = '—';
    }

    function destroyChart(container) {
        if (container._uplot) {
            container._uplot.destroy();
            container._uplot = null;
        }
        if (container._resizeObserver) {
            container._resizeObserver.disconnect();
            container._resizeObserver = null;
        }
    }

    /* uPlot wants one shared x axis with every series aligned to it, but the lines in a
       chart rarely agree on their timestamps: a rate has no value for its first bucket,
       and a quantile is undefined for any bucket where nothing was observed. Gaps become
       nulls, which uPlot draws as a break in the line rather than a bogus join. */
    function alignSeries(lines) {
        var stamps = {};
        lines.forEach(function (line) {
            (line.points || []).forEach(function (p) { stamps[p.ts] = true; });
        });

        var xs = Object.keys(stamps).map(Number).sort(function (a, b) { return a - b; });
        var index = {};
        xs.forEach(function (ts, i) { index[ts] = i; });

        var columns = lines.map(function (line) {
            var column = new Array(xs.length).fill(null);
            (line.points || []).forEach(function (p) { column[index[p.ts]] = p.value; });
            return column;
        });

        // uPlot's time scale works in seconds; the API reports milliseconds.
        return [xs.map(function (ts) { return ts / 1000; })].concat(columns);
    }

    function lastValue(column) {
        for (var i = column.length - 1; i >= 0; i--) {
            if (column[i] != null) return column[i];
        }
        return null;
    }

    function draw(container, payload, options) {
        var body = container.querySelector('[data-role="canvas"]');
        var currentLabel = container.querySelector('[data-role="current"]');
        var lines = (payload.series || []).filter(function (line) {
            return (line.points || []).length;
        });

        if (!lines.length) {
            renderEmpty(container, 'No data in this range.');
            return;
        }

        var labels = lines.map(function (line, i) { return line.label || ('series ' + (i + 1)); });
        var data = alignSeries(lines);
        var multi = lines.length > 1;

        function showCurrent(idx) {
            if (!currentLabel) return;
            // With several lines the legend names each value, so a single number in the
            // header would be ambiguous about which line it belongs to.
            if (multi) {
                currentLabel.textContent = '';
                return;
            }
            var value = idx == null ? lastValue(data[1]) : data[1][idx];
            currentLabel.textContent = formatValue(value, options.unit);
        }

        // The explorer reuses one panel for whichever field you click, and a family can
        // gain or lose a line between refreshes, so a chart whose shape changed needs
        // rebuilding rather than just new data: the unit and the series list are baked
        // into the options.
        var key = [
            options.measurement, options.field, options.tags || '',
            options.unit, options.kind || '', labels.join(',')
        ].join('|');
        if (container._uplot && container._seriesKey !== key) destroyChart(container);
        container._seriesKey = key;

        if (container._uplot) {
            container._uplot.setData(data);
            showCurrent(null);
            return;
        }

        body.innerHTML = '';
        container._uplot = new uPlot(
            buildOptions(options, body, labels, function (u) { showCurrent(u.cursor.idx); }),
            data,
            body
        );
        showCurrent(null);

        if (typeof ResizeObserver !== 'undefined') {
            container._resizeObserver = new ResizeObserver(function () {
                if (container._uplot) container._uplot.setSize(canvasSize(body, multi));
            });
            container._resizeObserver.observe(body);
        }
    }

    function buildUrl(options) {
        var params = new URLSearchParams({
            host: options.host,
            measurement: options.measurement,
            field: options.field,
            range: options.range,
            aggregate: options.aggregate || 'avg'
        });
        if (options.tags) params.set('tags', options.tags);
        if (options.kind) params.set('kind', options.kind);
        if (options.transform) params.set('transform', options.transform);
        if (options.tagMode) params.set('tag_mode', options.tagMode);
        if (options.chartOptions) params.set('options', options.chartOptions);
        if (options.invert) params.set('invert', '1');
        return brokeAppUrl('/api/metrics/query') + '?' + params.toString();
    }

    async function renderChart(options) {
        var container = options.container;
        try {
            var response = await fetch(buildUrl(options), {
                credentials: 'same-origin',
                headers: { 'Accept': 'application/json' }
            });
            if (!response.ok) {
                renderEmpty(container, 'Could not load this series.');
                return;
            }
            draw(container, await response.json(), options);
        } catch (_) {
            renderEmpty(container, 'Could not load this series.');
        }
    }

    function initDashboard(root) {
        if (!root) return;
        var host = root.getAttribute('data-host');
        var range = root.getAttribute('data-range');

        var charts = Array.prototype.map.call(root.querySelectorAll('.met-chart'), function (node) {
            return {
                container: node,
                host: host,
                range: range,
                measurement: node.getAttribute('data-measurement'),
                field: node.getAttribute('data-field'),
                unit: node.getAttribute('data-unit'),
                tags: node.getAttribute('data-tags'),
                kind: node.getAttribute('data-kind'),
                transform: node.getAttribute('data-transform'),
                tagMode: node.getAttribute('data-tag-mode'),
                chartOptions: node.getAttribute('data-options'),
                aggregate: node.getAttribute('data-aggregate') || 'avg',
                invert: node.getAttribute('data-invert') === '1'
            };
        });

        charts.forEach(renderChart);
        setInterval(function () { charts.forEach(renderChart); }, REFRESH_MS);
    }

    /* ============ Board editor ============ */

    /* The server has already turned the raw catalogue into families and named them, so
       the editor only ever shows a label and the note describing what a family draws. */
    function seriesLabel(entry) {
        return entry.label || entry.key || '';
    }

    function appendLabel(parent, entry) {
        var label = document.createElement('span');
        label.className = 'met-editor-label';
        label.textContent = seriesLabel(entry);
        parent.appendChild(label);

        if (entry.note) {
            var note = document.createElement('span');
            note.className = 'met-editor-note';
            note.textContent = entry.note;
            parent.appendChild(note);
        }
    }

    function initEditor(config) {
        var panel = document.getElementById('met-editor');
        var toggle = document.getElementById('met-edit-toggle');
        if (!panel || !toggle) return;

        var selectedList = document.getElementById('met-editor-selected');
        var availableList = document.getElementById('met-editor-available');
        var filterInput = document.getElementById('met-editor-filter');
        var status = document.getElementById('met-editor-status');

        var available = config.available || [];
        var byKey = {};
        available.forEach(function (entry) { byKey[entry.key] = entry; });

        // Keys only; the editor reorders this array and the server stores that order.
        var chosen = (config.charts || []).map(function (c) { return c.key; })
            .filter(function (key) { return byKey[key]; });

        var dragKey = null;

        function setStatus(message, isError) {
            status.textContent = message || '';
            status.classList.toggle('is-error', !!isError);
        }

        function renderSelected() {
            selectedList.textContent = '';
            if (!chosen.length) {
                var empty = document.createElement('li');
                empty.className = 'met-editor-empty';
                empty.textContent = 'Nothing selected. The board would be blank.';
                selectedList.appendChild(empty);
                return;
            }

            chosen.forEach(function (key) {
                var entry = byKey[key];
                var item = document.createElement('li');
                item.className = 'met-editor-item';
                item.draggable = true;
                item.dataset.key = key;

                var handle = document.createElement('i');
                handle.className = 'ph ph-dots-six-vertical met-editor-handle';
                item.appendChild(handle);

                appendLabel(item, entry);

                var remove = document.createElement('button');
                remove.type = 'button';
                remove.className = 'met-editor-remove';
                remove.title = 'Remove from board';
                remove.innerHTML = '<i class="ph ph-x"></i>';
                remove.addEventListener('click', function () {
                    chosen = chosen.filter(function (k) { return k !== key; });
                    render();
                });
                item.appendChild(remove);

                item.addEventListener('dragstart', function () {
                    dragKey = key;
                    item.classList.add('is-dragging');
                });
                item.addEventListener('dragend', function () {
                    dragKey = null;
                    item.classList.remove('is-dragging');
                });
                item.addEventListener('dragover', function (event) {
                    event.preventDefault();
                    if (!dragKey || dragKey === key) return;
                    var from = chosen.indexOf(dragKey);
                    var to = chosen.indexOf(key);
                    if (from < 0 || to < 0) return;
                    chosen.splice(from, 1);
                    chosen.splice(to, 0, dragKey);
                    renderSelected();
                });

                selectedList.appendChild(item);
            });
        }

        function renderAvailable() {
            var filter = (filterInput.value || '').trim().toLowerCase();
            availableList.textContent = '';

            var groups = {};
            available.forEach(function (entry) {
                if (chosen.indexOf(entry.key) !== -1) return;
                var haystack = [
                    entry.label, entry.measurement, entry.kind, entry.note
                ].join(' ').toLowerCase();
                if (filter && haystack.indexOf(filter) === -1) return;
                (groups[entry.measurement] = groups[entry.measurement] || []).push(entry);
            });

            var names = Object.keys(groups).sort();
            if (!names.length) {
                var empty = document.createElement('p');
                empty.className = 'met-editor-empty';
                empty.textContent = filter
                    ? 'Nothing matches that filter.'
                    : 'Every series this host sends is already on the board.';
                availableList.appendChild(empty);
                return;
            }

            names.forEach(function (name) {
                var group = document.createElement('div');
                group.className = 'met-editor-group';

                var heading = document.createElement('h4');
                heading.textContent = name;
                group.appendChild(heading);

                groups[name].forEach(function (entry) {
                    var button = document.createElement('button');
                    button.type = 'button';
                    button.className = 'met-editor-add';
                    button.innerHTML = '<i class="ph ph-plus"></i>';
                    appendLabel(button, entry);
                    button.addEventListener('click', function () {
                        if (chosen.indexOf(entry.key) === -1) chosen.push(entry.key);
                        render();
                    });
                    group.appendChild(button);
                });

                availableList.appendChild(group);
            });
        }

        function render() {
            renderSelected();
            renderAvailable();
        }

        async function send(method, body) {
            setStatus('Saving…');
            try {
                var response = await fetch(
                    brokeAppUrl('/api/metrics/hosts/' + encodeURIComponent(config.host) + '/charts'),
                    {
                        method: method,
                        credentials: 'same-origin',
                        headers: {
                            'Content-Type': 'application/json',
                            'Accept': 'application/json',
                            'X-CSRF-Token': window.BROKE_CSRF_TOKEN || ''
                        },
                        body: body ? JSON.stringify(body) : undefined
                    }
                );
                if (!response.ok) {
                    var data = await response.json().catch(function () { return {}; });
                    setStatus(data.error || ('Request failed (' + response.status + ')'), true);
                    return;
                }
                window.location.reload();
            } catch (_) {
                setStatus('Network error while saving.', true);
            }
        }

        toggle.addEventListener('click', function () {
            panel.hidden = !panel.hidden;
            toggle.classList.toggle('is-active', !panel.hidden);
            if (!panel.hidden) render();
        });

        filterInput.addEventListener('input', renderAvailable);

        document.getElementById('met-editor-cancel').addEventListener('click', function () {
            chosen = (config.charts || []).map(function (c) { return c.key; })
                .filter(function (key) { return byKey[key]; });
            panel.hidden = true;
            toggle.classList.remove('is-active');
            setStatus('');
        });

        document.getElementById('met-editor-save').addEventListener('click', function () {
            if (!chosen.length) {
                setStatus('Pick at least one series, or use Reset to suggested.', true);
                return;
            }
            // Only the family key travels: the server rebuilds the rest of the selector
            // from its own classification, so a board can never store a chart definition
            // the browser made up.
            send('PUT', { charts: chosen.map(function (key) { return { key: key }; }) });
        });

        document.getElementById('met-editor-reset').addEventListener('click', function () {
            if (!confirm('Discard this board and go back to charts picked from the data?')) return;
            send('DELETE', null);
        });
    }

    /* config.js, which defines brokeAppUrl, is loaded after the content block, so page
       scripts must wait for the document rather than running at parse time. */
    function ready(callback) {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', callback);
        } else {
            callback();
        }
    }

    return {
        ready: ready,
        initDashboard: initDashboard,
        initEditor: initEditor,
        renderChart: renderChart,
        formatValue: formatValue
    };
})();
