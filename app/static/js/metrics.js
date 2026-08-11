/* Charts for the Servers pages, built on the vendored uPlot (app/static/js/vendor).

   uPlot draws to canvas, so it cannot inherit :root variables the way markup does.
   Colours are read out of the stylesheet once at startup instead, which keeps the
   theme in metrics.css rather than duplicated here. */

window.BrokeMetrics = (function () {
    var REFRESH_MS = 30000;
    var theme = null;

    function readTheme() {
        if (theme) return theme;
        var root = getComputedStyle(document.documentElement);
        function value(name, fallback) {
            return (root.getPropertyValue(name) || '').trim() || fallback;
        }
        theme = {
            line: value('--met-line', '#106ecc'),
            fill: value('--met-line-fill', 'rgba(16, 110, 204, 0.12)'),
            grid: value('--met-grid', '#e5e7eb'),
            axis: value('--met-axis', '#999999'),
            font: '11px ' + value('--met-chart-font', 'system-ui, sans-serif')
        };
        return theme;
    }

    function formatValue(value, unit) {
        if (value == null || isNaN(value)) return '—';
        if (unit === 'bytes') return formatBytes(value);
        if (unit === '%') return value.toFixed(1) + '%';
        if (Number.isInteger(value)) return value.toLocaleString();
        if (Math.abs(value) >= 1000) return Math.round(value).toLocaleString();
        if (Math.abs(value) >= 10) return value.toFixed(1);
        return value.toFixed(2);
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

    function canvasSize(body) {
        return {
            width: Math.max(120, body.clientWidth),
            height: Math.max(120, body.clientHeight)
        };
    }

    function buildOptions(options, body, onCursor) {
        var t = readTheme();
        var size = canvasSize(body);

        return {
            width: size.width,
            height: size.height,
            // Right padding leaves room for the final x-axis label, which otherwise gets
            // clipped by the plot edge.
            padding: [10, 26, 0, 0],
            legend: { show: false },
            cursor: {
                y: false,
                drag: { x: true, y: false },
                points: { size: 7, width: 1.5, stroke: '#ffffff', fill: t.line }
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
            series: [
                {},
                {
                    stroke: t.line,
                    width: 2,
                    fill: t.fill,
                    points: { show: false },
                    value: function (u, v) { return formatValue(v, options.unit); }
                }
            ],
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

    function draw(container, payload, options) {
        var body = container.querySelector('[data-role="canvas"]');
        var currentLabel = container.querySelector('[data-role="current"]');
        var points = payload.points || [];

        if (!points.length) {
            renderEmpty(container, 'No data in this range.');
            return;
        }

        // uPlot's time scale works in seconds; the API reports milliseconds.
        var xs = points.map(function (p) { return p.ts / 1000; });
        var ys = points.map(function (p) { return p.value; });
        var last = ys[ys.length - 1];

        // The explorer reuses one panel for whichever field you click, so a chart whose
        // series changed needs rebuilding rather than just new data: the unit, and with
        // it the axis formatting and scale, is baked into the options.
        var key = [options.measurement, options.field, options.tags || '', options.unit].join('|');
        if (container._uplot && container._seriesKey !== key) destroyChart(container);
        container._seriesKey = key;

        if (container._uplot) {
            container._uplot.setData([xs, ys]);
            if (currentLabel) currentLabel.textContent = formatValue(last, options.unit);
            return;
        }

        function onCursor(u) {
            if (!currentLabel) return;
            var idx = u.cursor.idx;
            var value = idx == null ? u.data[1][u.data[1].length - 1] : u.data[1][idx];
            currentLabel.textContent = formatValue(value, options.unit);
        }

        body.innerHTML = '';
        container._uplot = new uPlot(buildOptions(options, body, onCursor), [xs, ys], body);
        if (currentLabel) currentLabel.textContent = formatValue(last, options.unit);

        if (typeof ResizeObserver !== 'undefined') {
            container._resizeObserver = new ResizeObserver(function () {
                if (container._uplot) container._uplot.setSize(canvasSize(body));
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
                aggregate: node.getAttribute('data-aggregate') || 'avg',
                invert: node.getAttribute('data-invert') === '1'
            };
        });

        charts.forEach(renderChart);
        setInterval(function () { charts.forEach(renderChart); }, REFRESH_MS);
    }

    /* ============ Board editor ============ */

    function seriesLabel(entry) {
        var label = entry.measurement + '.' + entry.field;
        var tags = entry.tags && Object.keys(entry.tags);
        if (tags && tags.length) {
            label += ' · ' + tags.sort().map(function (k) {
                return k + '=' + entry.tags[k];
            }).join(' ');
        }
        return label;
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

                var label = document.createElement('span');
                label.className = 'met-editor-label';
                label.textContent = seriesLabel(entry);
                item.appendChild(label);

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
                if (filter && seriesLabel(entry).toLowerCase().indexOf(filter) === -1) return;
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
                    button.appendChild(document.createTextNode(seriesLabel(entry)));
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
            send('PUT', {
                charts: chosen.map(function (key) {
                    var entry = byKey[key];
                    return {
                        measurement: entry.measurement,
                        field: entry.field,
                        tags: entry.tags || {}
                    };
                })
            });
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
