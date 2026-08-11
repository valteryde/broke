/* Charts for the Servers pages, built on the vendored uPlot (app/static/js/vendor).

   uPlot draws to canvas, so it cannot inherit :root variables the way markup does.
   Colours are read out of the stylesheet instead — the shared theme once at startup, and
   each chart's accent off the element it draws into — which keeps the palette in
   metrics.css rather than duplicated here. */

window.BrokeMetrics = (function () {
    var REFRESH_MS = 30000;
    // Room for uPlot's legend, which renders under the plot inside the same box.
    var LEGEND_PX = 24;
    var theme = null;

    function readTheme() {
        if (theme) return theme;
        var root = getComputedStyle(document.documentElement);
        function value(name, fallback) {
            return (root.getPropertyValue(name) || '').trim() || fallback;
        }

        var palette = [];
        for (var i = 1; i <= 8; i++) palette.push(value('--met-line-' + i, '#106ecc'));

        theme = {
            line: value('--met-line', '#106ecc'),
            palette: palette,
            grid: value('--met-grid', '#e5e7eb'),
            axis: value('--met-axis', '#999999'),
            font: '11px ' + value('--met-chart-font', 'system-ui, sans-serif')
        };
        return theme;
    }

    /* Which colour a chart draws in is a stylesheet decision, keyed by measurement: the
       template sets data-accent, metrics.css turns that into --met-accent, and this reads
       back whatever it resolved to. */
    function accentOf(container) {
        var value = (getComputedStyle(container).getPropertyValue('--met-accent') || '').trim();
        return value || readTheme().line;
    }

    /* A single line wears the chart's accent. Several lines cannot — a disk per mount or
       a histogram's quantiles have to be told apart — so those step through the palette. */
    function lineColours(container, count) {
        if (count < 2) return [accentOf(container)];
        var palette = readTheme().palette;
        var colours = [];
        for (var i = 0; i < count; i++) colours.push(palette[i % palette.length]);
        return colours;
    }

    /* A canvas gradient needs a colour it can vary the alpha of, and the palette is
       written as hex in the stylesheet. */
    function withAlpha(colour, alpha) {
        var hex = (colour || '').trim();
        if (hex.charAt(0) !== '#') return hex;
        if (hex.length === 4) {
            hex = '#' + hex[1] + hex[1] + hex[2] + hex[2] + hex[3] + hex[3];
        }
        var parsed = parseInt(hex.slice(1), 16);
        if (isNaN(parsed)) return colour;
        var r = (parsed >> 16) & 255;
        var g = (parsed >> 8) & 255;
        var b = parsed & 255;
        return 'rgba(' + r + ',' + g + ',' + b + ',' + alpha + ')';
    }

    function areaFill(u, colour) {
        var gradient = u.ctx.createLinearGradient(0, u.bbox.top, 0, u.bbox.top + u.bbox.height);
        gradient.addColorStop(0, withAlpha(colour, 0.26));
        gradient.addColorStop(1, withAlpha(colour, 0.02));
        return gradient;
    }

    function formatValue(value, unit) {
        if (value == null || isNaN(value)) return '—';
        if (unit === 'bytes') return formatBytes(value);
        if (unit === 'bytes/s') return formatBytes(value) + '/s';
        if (unit === 'seconds') return formatDuration(value);
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

    /* Latencies arrive in seconds but are rarely read that way; a p99 of 0.0043 says
       much less than 4.3 ms. */
    function formatDuration(value) {
        var size = Math.abs(value);
        if (size === 0) return '0 s';
        if (size < 0.001) return (value * 1e6).toFixed(0) + ' µs';
        if (size < 1) return (value * 1000).toFixed(size < 0.01 ? 1 : 0) + ' ms';
        if (size < 60) return value.toFixed(size < 10 ? 2 : 1) + ' s';
        return (value / 60).toFixed(1) + ' min';
    }

    function formatTime(seconds) {
        return new Date(seconds * 1000).toLocaleString([], {
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        });
    }

    function canvasSize(body, reserved) {
        return {
            width: Math.max(120, body.clientWidth),
            height: Math.max(90, body.clientHeight - (reserved || 0))
        };
    }

    /* One chart can hold lines that do not share timestamps: a mount that appeared
       halfway through the window, or a counter whose first sample had nothing before it
       to differentiate against. uPlot wants a single x array, so the union of the stamps
       is filled with nulls, which draw as gaps rather than as invented readings. */
    function alignSeries(lines) {
        var seen = Object.create(null);
        lines.forEach(function (line) {
            (line.points || []).forEach(function (point) { seen[point.ts] = true; });
        });

        var stamps = Object.keys(seen).map(Number).sort(function (a, b) { return a - b; });
        var at = Object.create(null);
        stamps.forEach(function (ts, index) { at[ts] = index; });

        var columns = lines.map(function (line) {
            var column = new Array(stamps.length).fill(null);
            (line.points || []).forEach(function (point) {
                column[at[point.ts]] = point.value;
            });
            return column;
        });

        // uPlot's time scale works in seconds; the API reports milliseconds.
        return {
            xs: stamps.map(function (ts) { return ts / 1000; }),
            columns: columns
        };
    }

    function buildOptions(options, body, lines, colours, onCursor) {
        var t = readTheme();
        var single = lines.length < 2;
        var size = canvasSize(body, single ? 0 : LEGEND_PX);

        return {
            width: size.width,
            height: size.height,
            // Right padding leaves room for the final x-axis label, which otherwise gets
            // clipped by the plot edge.
            padding: [10, 26, 0, 0],
            legend: { show: !single },
            cursor: {
                y: false,
                drag: { x: true, y: false },
                points: {
                    size: 7,
                    width: 1.5,
                    stroke: '#ffffff',
                    fill: function (u, index) { return colours[index - 1] || t.line; }
                }
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
                    grid: { stroke: t.grid, width: 1, dash: [3, 4] },
                    ticks: { show: false },
                    values: function (u, splits) {
                        return splits.map(function (v) { return formatTick(v, options.unit); });
                    }
                }
            ],
            series: [{}].concat(lines.map(function (line, index) {
                var colour = colours[index];
                var series = {
                    label: line.label || ('series ' + (index + 1)),
                    stroke: colour,
                    width: 2,
                    points: { show: false },
                    value: function (u, v, seriesIdx) {
                        // With the cursor away uPlot has nothing to report; a legend of
                        // dashes says less than where each line currently sits.
                        if (v == null) v = lastValue(u.data[seriesIdx] || []);
                        return formatValue(v, options.unit);
                    }
                };
                // Stacked translucent areas turn to mud, so only a lone line is filled.
                if (single) {
                    series.fill = function (u) { return areaFill(u, colour); };
                }
                return series;
            })),
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

    function lastValue(column) {
        for (var i = column.length - 1; i >= 0; i--) {
            if (column[i] != null && !isNaN(column[i])) return column[i];
        }
        return null;
    }

    function appendStat(row, key, value) {
        var item = document.createElement('span');
        item.className = 'met-stat';

        var name = document.createElement('span');
        name.className = 'met-stat-key';
        name.textContent = key;
        item.appendChild(name);

        var reading = document.createElement('span');
        reading.className = 'met-stat-value';
        reading.textContent = value;
        item.appendChild(reading);

        row.appendChild(item);
    }

    /* What the window held, rather than only where it ended: a tile reading "34%" hides
       whether the last hour sat flat there or swung between 4 and 90. */
    function summarise(container, aligned, options) {
        var min = null;
        var max = null;
        var total = 0;
        var count = 0;

        aligned.columns.forEach(function (column) {
            column.forEach(function (value) {
                if (value == null || isNaN(value)) return;
                if (min == null || value < min) min = value;
                if (max == null || value > max) max = value;
                total += value;
                count += 1;
            });
        });

        var stats = container.querySelector('[data-role="stats"]');
        if (stats) {
            stats.textContent = '';
            if (count) {
                appendStat(stats, 'min', formatValue(min, options.unit));
                appendStat(stats, 'avg', formatValue(total / count, options.unit));
                appendStat(stats, 'max', formatValue(max, options.unit));
            }
        }

        var current = container.querySelector('[data-role="current"]');
        if (!current) return;
        var many = aligned.columns.length > 1;
        // Several lines have no one "current" reading; the legend names each of them.
        current.textContent = many
            ? aligned.columns.length + ' lines'
            : formatValue(lastValue(aligned.columns[0] || []), options.unit);
        current.classList.toggle('is-count', many);
    }

    function reportCursor(container, u, options) {
        var index = u.cursor.idx;

        var time = container.querySelector('[data-role="time"]');
        if (time) time.textContent = index == null ? '' : formatTime(u.data[0][index]);

        // With one line the header doubles as its readout; with several the legend does.
        var current = container.querySelector('[data-role="current"]');
        if (current && u.data.length === 2) {
            var column = u.data[1];
            current.textContent = formatValue(
                index == null ? lastValue(column) : column[index],
                options.unit
            );
        }
    }

    function renderEmpty(container, message) {
        destroyChart(container);
        var body = container.querySelector('[data-role="canvas"]');
        if (body) body.innerHTML = '<div class="met-chart-empty">' + message + '</div>';

        var current = container.querySelector('[data-role="current"]');
        if (current) {
            current.textContent = '—';
            current.classList.remove('is-count');
        }
        var stats = container.querySelector('[data-role="stats"]');
        if (stats) stats.textContent = '';
        var time = container.querySelector('[data-role="time"]');
        if (time) time.textContent = '';
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
        var lines = (payload.series || []).filter(function (line) {
            return (line.points || []).length;
        });

        if (!lines.length) {
            renderEmpty(container, 'No data in this range.');
            return;
        }

        var aligned = alignSeries(lines);
        var colours = lineColours(container, lines.length);
        var data = [aligned.xs].concat(aligned.columns);

        // The explorer reuses one panel for whichever field you click, and a family can
        // gain or lose a line between refreshes. Either changes the axes or the series
        // list, which are baked into the options, so the chart is rebuilt rather than
        // just refilled.
        var key = [
            options.measurement,
            options.field,
            options.tags || '',
            options.unit,
            lines.map(function (line) { return line.label; }).join(',')
        ].join('|');
        if (container._uplot && container._seriesKey !== key) destroyChart(container);
        container._seriesKey = key;

        if (container._uplot) {
            container._uplot.setData(data);
            summarise(container, aligned, options);
            return;
        }

        var reserved = lines.length < 2 ? 0 : LEGEND_PX;
        body.innerHTML = '';
        container._uplot = new uPlot(
            buildOptions(options, body, lines, colours, function (u) {
                reportCursor(container, u, options);
            }),
            data,
            body
        );
        summarise(container, aligned, options);

        if (typeof ResizeObserver !== 'undefined') {
            container._resizeObserver = new ResizeObserver(function () {
                if (container._uplot) container._uplot.setSize(canvasSize(body, reserved));
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
        // How to read the series, not which one: whether it is a histogram to take
        // quantiles of, a counter to differentiate, and which tags to group by.
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

    function accentDot(accent) {
        var dot = document.createElement('span');
        dot.className = 'met-swatch';
        dot.dataset.accent = accent || 'blue';
        return dot;
    }

    function matchesFilter(entry, filter) {
        if (!filter) return true;
        var haystack = [entry.label, entry.measurement, entry.note].join(' ').toLowerCase();
        return haystack.indexOf(filter) !== -1;
    }

    function initEditor(config) {
        var panel = document.getElementById('met-editor');
        var toggle = document.getElementById('met-edit-toggle');
        if (!panel || !toggle) return;

        var selectedList = document.getElementById('met-editor-selected');
        var availableList = document.getElementById('met-editor-available');
        var filterInput = document.getElementById('met-editor-filter');
        var status = document.getElementById('met-editor-status');
        var addSectionButton = document.getElementById('met-editor-add-section');

        var accents = config.accents || ['blue'];
        var maxName = config.max_section_name || 60;

        var available = config.available || [];
        var byKey = {};
        available.forEach(function (entry) { byKey[entry.key] = entry; });

        /* The board as the editor holds it: an ordered list of sections, each an ordered
           list of chart keys. groups[0] is the run above the first heading — it has no
           name and cannot be given one. Saving flattens this back into the single ordered
           list the server stores, which is why a section with no charts cannot survive a
           save: there is no row left to carry its name. */
        var groups = [];
        var dragKey = null;

        function loadGroups() {
            groups = [{ name: '', accent: '', keys: [] }];
            (config.charts || []).forEach(function (chart) {
                if (!byKey[chart.key]) return;
                var name = chart.section || '';
                var last = groups[groups.length - 1];
                if (last.name !== name) {
                    groups.push({
                        name: name,
                        accent: chart.section_accent || accents[0],
                        keys: []
                    });
                    last = groups[groups.length - 1];
                }
                last.keys.push(chart.key);
            });
        }

        function setStatus(message, isError) {
            status.textContent = message || '';
            status.classList.toggle('is-error', !!isError);
        }

        function locate(key) {
            for (var i = 0; i < groups.length; i++) {
                var at = groups[i].keys.indexOf(key);
                if (at !== -1) return { group: i, index: at };
            }
            return null;
        }

        function anyChosen() {
            return groups.some(function (group) { return group.keys.length > 0; });
        }

        /* A new section takes a colour nothing else is using, so two headings only ever
           match once someone has run out of palette. */
        function nextAccent() {
            var used = {};
            groups.forEach(function (group) { used[group.accent] = true; });
            for (var i = 0; i < accents.length; i++) {
                if (!used[accents[i]]) return accents[i];
            }
            return accents[groups.length % accents.length];
        }

        function moveKey(key, toGroup, toIndex) {
            var from = locate(key);
            if (!from) return false;

            var target = toIndex;
            if (from.group === toGroup && from.index < target) target--;
            if (from.group === toGroup && from.index === target) return false;

            groups[from.group].keys.splice(from.index, 1);
            groups[toGroup].keys.splice(target, 0, key);
            return true;
        }

        function renderItem(key, groupIndex, position) {
            var entry = byKey[key];
            var item = document.createElement('li');
            item.className = 'met-editor-item';
            item.draggable = true;
            item.dataset.key = key;
            if (key === dragKey) item.classList.add('is-dragging');

            var handle = document.createElement('i');
            handle.className = 'ph ph-dots-six-vertical met-editor-handle';
            item.appendChild(handle);

            item.appendChild(accentDot(entry.accent));

            var label = document.createElement('span');
            label.className = 'met-editor-label';
            label.textContent = entry.label;
            item.appendChild(label);

            if (entry.note) {
                var note = document.createElement('span');
                note.className = 'met-editor-note';
                note.textContent = entry.note;
                item.appendChild(note);
            }

            var remove = document.createElement('button');
            remove.type = 'button';
            remove.className = 'met-editor-remove';
            remove.title = 'Remove from board';
            remove.innerHTML = '<i class="ph ph-x"></i>';
            remove.addEventListener('click', function () {
                var at = locate(key);
                if (at) groups[at.group].keys.splice(at.index, 1);
                render();
            });
            item.appendChild(remove);

            item.addEventListener('dragstart', function (event) {
                dragKey = key;
                // Firefox refuses to start a drag that carries no payload.
                if (event.dataTransfer) event.dataTransfer.setData('text/plain', key);
                item.classList.add('is-dragging');
            });
            item.addEventListener('dragend', function () {
                dragKey = null;
                renderSelected();
            });
            item.addEventListener('dragover', function (event) {
                event.preventDefault();
                event.stopPropagation();
                if (!dragKey || dragKey === key) return;
                if (moveKey(dragKey, groupIndex, position)) renderSelected();
            });

            return item;
        }

        function renderGroupHead(group, index, wrap) {
            var bar = document.createElement('div');
            bar.className = 'met-editor-section-bar';

            var head = document.createElement('header');
            head.className = 'met-editor-section-head';

            var palette = document.createElement('div');
            palette.className = 'met-editor-palette';
            palette.hidden = true;

            var colour = document.createElement('button');
            colour.type = 'button';
            colour.className = 'met-editor-colour';
            colour.title = 'Section colour';
            colour.appendChild(accentDot(group.accent));
            colour.addEventListener('click', function () {
                palette.hidden = !palette.hidden;
            });

            accents.forEach(function (accent) {
                var choice = document.createElement('button');
                choice.type = 'button';
                choice.className = 'met-editor-colour';
                choice.title = accent;
                choice.dataset.choice = accent;
                choice.appendChild(accentDot(accent));
                choice.addEventListener('click', function () {
                    group.accent = accent;
                    wrap.dataset.accent = accent;
                    colour.textContent = '';
                    colour.appendChild(accentDot(accent));
                    palette.hidden = true;
                });
                palette.appendChild(choice);
            });

            var name = document.createElement('input');
            name.type = 'text';
            name.className = 'met-editor-name';
            name.value = group.name;
            name.maxLength = maxName;
            name.placeholder = 'Section name';
            name.addEventListener('input', function () { group.name = name.value; });

            var remove = document.createElement('button');
            remove.type = 'button';
            remove.className = 'met-editor-remove';
            remove.title = 'Remove section and keep its charts';
            remove.innerHTML = '<i class="ph ph-x"></i>';
            remove.addEventListener('click', function () {
                // The charts outlive the heading rather than leaving the board with it:
                // dropping someone's arrangement is not what "remove section" promises.
                groups[0].keys = groups[0].keys.concat(group.keys);
                groups.splice(index, 1);
                render();
            });

            head.appendChild(colour);
            head.appendChild(name);
            head.appendChild(remove);
            bar.appendChild(head);
            bar.appendChild(palette);
            return bar;
        }

        function renderGroupList(group, index) {
            var list = document.createElement('ul');
            list.className = 'met-editor-list';
            list.dataset.group = String(index);

            if (!group.keys.length) {
                var empty = document.createElement('li');
                empty.className = 'met-editor-empty';
                empty.textContent = 'Drag charts here.';
                list.appendChild(empty);
            }

            group.keys.forEach(function (key, position) {
                list.appendChild(renderItem(key, index, position));
            });

            // Dropping below the last item, or anywhere in an empty section, appends.
            list.addEventListener('dragover', function (event) {
                event.preventDefault();
                if (dragKey && moveKey(dragKey, index, group.keys.length)) renderSelected();
            });
            list.addEventListener('drop', function (event) { event.preventDefault(); });

            return list;
        }

        function renderGroup(group, index) {
            var wrap = document.createElement('div');
            wrap.className = 'met-editor-section';
            wrap.dataset.accent = group.accent || 'slate';

            if (index === 0) {
                wrap.classList.add('is-loose');
                var label = document.createElement('p');
                label.className = 'met-editor-section-loose';
                label.textContent = 'Above the first section';
                wrap.appendChild(label);
            } else {
                wrap.appendChild(renderGroupHead(group, index, wrap));
            }

            wrap.appendChild(renderGroupList(group, index));
            return wrap;
        }

        function renderSelected() {
            selectedList.textContent = '';

            if (!anyChosen() && groups.length < 2) {
                var empty = document.createElement('p');
                empty.className = 'met-editor-empty';
                empty.textContent = 'Nothing selected. The board would be blank.';
                selectedList.appendChild(empty);
                return;
            }

            groups.forEach(function (group, index) {
                // The unnamed run earns space only once something is in it.
                if (index === 0 && !group.keys.length) return;
                selectedList.appendChild(renderGroup(group, index));
            });
        }

        function renderAvailable() {
            var filter = (filterInput.value || '').trim().toLowerCase();
            availableList.textContent = '';

            var byMeasurement = {};
            available.forEach(function (entry) {
                if (locate(entry.key)) return;
                if (!matchesFilter(entry, filter)) return;
                (byMeasurement[entry.measurement] = byMeasurement[entry.measurement] || [])
                    .push(entry);
            });

            var names = Object.keys(byMeasurement).sort();
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

                byMeasurement[name].forEach(function (entry) {
                    var button = document.createElement('button');
                    button.type = 'button';
                    button.className = 'met-editor-add';
                    button.appendChild(accentDot(entry.accent));

                    var label = document.createElement('span');
                    label.className = 'met-editor-label';
                    label.textContent = entry.label;
                    button.appendChild(label);

                    if (entry.note) {
                        var note = document.createElement('span');
                        note.className = 'met-editor-note';
                        note.textContent = entry.note;
                        button.appendChild(note);
                    }

                    button.addEventListener('click', function () {
                        // Into the section being worked on, which is the last one open.
                        if (!locate(entry.key)) groups[groups.length - 1].keys.push(entry.key);
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

        addSectionButton.addEventListener('click', function () {
            groups.push({ name: '', accent: nextAccent(), keys: [] });
            render();
            var names = selectedList.querySelectorAll('.met-editor-name');
            if (names.length) names[names.length - 1].focus();
        });

        document.getElementById('met-editor-cancel').addEventListener('click', function () {
            loadGroups();
            panel.hidden = true;
            toggle.classList.remove('is-active');
            setStatus('');
        });

        document.getElementById('met-editor-save').addEventListener('click', function () {
            // A board is saved by family key, each carrying the heading it sits under: the
            // server resolves the key back to the selector it built, so a request can only
            // ever name something this host sends.
            var charts = [];
            groups.forEach(function (group) {
                var name = (group.name || '').trim();
                group.keys.forEach(function (key) {
                    charts.push({
                        key: key,
                        section: name,
                        section_accent: name ? group.accent : ''
                    });
                });
            });

            if (!charts.length) {
                setStatus('Pick at least one chart, or use Reset to suggested.', true);
                return;
            }
            send('PUT', { charts: charts });
        });

        document.getElementById('met-editor-reset').addEventListener('click', function () {
            if (!confirm('Discard this board and go back to charts picked from the data?')) return;
            send('DELETE', null);
        });

        /* ---- Arranging the board with a model ---- */

        /* A proposal replaces what is in the panel, never what is on the page. The board is
           shared with everyone looking at this host, so an arrangement nobody has read yet
           is a suggestion sitting in the editor until someone presses Save board. */
        function applyProposal(data) {
            var proposed = [{ name: '', accent: '', keys: [] }];
            var count = 0;

            (data.sections || []).forEach(function (section) {
                // The keys come from this host's own catalogue, but a board is not the
                // place to find out that something no longer resolves.
                var keys = (section.charts || []).filter(function (key) { return byKey[key]; });
                if (!keys.length) return;
                proposed.push({
                    name: section.name || '',
                    accent: section.accent || accents[0],
                    keys: keys
                });
                count += keys.length;
            });

            if (!count) {
                setStatus('That suggestion named nothing this host actually sends.', true);
                return;
            }

            groups = proposed;
            render();
            setStatus((data.note || 'Board arranged.') + ' Press Save board to keep it.');
        }

        var aiButton = document.getElementById('met-editor-ai');
        var aiPrompt = document.getElementById('met-editor-ai-prompt');

        async function arrangeWithAi() {
            var row = aiButton.parentNode;
            row.classList.add('is-busy');
            setStatus('Reading what this server reports…');

            try {
                var response = await fetch(
                    brokeAppUrl(
                        '/api/metrics/hosts/' + encodeURIComponent(config.host) + '/charts/arrange'
                    ),
                    {
                        method: 'POST',
                        credentials: 'same-origin',
                        headers: {
                            'Content-Type': 'application/json',
                            'Accept': 'application/json',
                            'X-CSRF-Token': window.BROKE_CSRF_TOKEN || ''
                        },
                        body: JSON.stringify({ prompt: aiPrompt ? aiPrompt.value : '' })
                    }
                );
                var data = await response.json().catch(function () { return {}; });
                if (!response.ok) {
                    setStatus(data.error || ('Request failed (' + response.status + ')'), true);
                    return;
                }
                applyProposal(data);
            } catch (_) {
                setStatus('Network error while arranging the board.', true);
            } finally {
                row.classList.remove('is-busy');
            }
        }

        if (aiButton) {
            aiButton.addEventListener('click', arrangeWithAi);
            aiPrompt.addEventListener('keydown', function (event) {
                if (event.key !== 'Enter') return;
                event.preventDefault();
                arrangeWithAi();
            });
        }

        loadGroups();
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
