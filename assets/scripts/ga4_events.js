/**
 * River Monitor — Google Analytics 4 event tracking.
 * Uses MutationObserver + debounced listeners on Dash component IDs.
 * Only fires when gtag is loaded (GA_MEASUREMENT_ID is set).
 */
(function() {
    'use strict';

    // Debounce helper
    function debounce(fn, delay) {
        var timer;
        return function() {
            var args = arguments;
            clearTimeout(timer);
            timer = setTimeout(function() { fn.apply(null, args); }, delay);
        };
    }

    function sendEvent(name, params) {
        if (typeof gtag === 'function') {
            gtag('event', name, params);
        }
    }

    // Track element value changes via MutationObserver
    var trackedIds = {
        'river-map-station-select': { event: 'station_select', attr: 'value', source: 'map' },
        'river-station-select': { event: 'station_select', attr: 'value', source: 'details' },
        'river-view-mode': { event: 'view_switch', attr: 'value' },
        'river-search': { event: 'search_station', attr: 'value' },
    };

    // Click tracking
    var clickIds = {
        'river-upload-layer-btn': 'layer_upload',
        'river-clear-layer-btn': 'layer_clear',
        'river-map-html-btn': 'download_click',
        'river-html-btn': 'download_click',
    };

    // Toggle tracking
    var toggleIds = {
        'river-flood-zones-toggle': 'map_layer_toggle',
    };

    function setupClickTracking() {
        Object.keys(clickIds).forEach(function(id) {
            var el = document.getElementById(id);
            if (el && !el._ga4_click) {
                el._ga4_click = true;
                el.addEventListener('click', function() {
                    sendEvent(clickIds[id], { element_id: id });
                });
            }
        });
    }

    function setupToggleTracking() {
        Object.keys(toggleIds).forEach(function(id) {
            var el = document.getElementById(id);
            if (el && !el._ga4_toggle) {
                el._ga4_toggle = true;
                var input = el.querySelector('input[type="checkbox"]');
                if (input) {
                    input.addEventListener('change', function() {
                        sendEvent(toggleIds[id], {
                            element_id: id,
                            checked: input.checked,
                        });
                    });
                }
            }
        });
    }

    // Watch for Dash component value changes via data attributes
    var debouncedSearch = debounce(function(value) {
        if (value && value.length >= 2) {
            sendEvent('search_station', { search_term: value });
        }
    }, 1000);

    function setupMutationObserver() {
        var observer = new MutationObserver(function(mutations) {
            mutations.forEach(function(m) {
                if (m.type === 'attributes') {
                    var id = m.target.id;
                    var config = trackedIds[id];
                    if (config) {
                        var value = m.target.getAttribute(config.attr) ||
                                    m.target.value;
                        if (value) {
                            if (config.event === 'search_station') {
                                debouncedSearch(value);
                            } else {
                                sendEvent(config.event, {
                                    element_id: id,
                                    value: value,
                                    source: config.source || '',
                                });
                            }
                        }
                    }
                }
            });
        });

        observer.observe(document.body, {
            attributes: true,
            subtree: true,
            attributeFilter: ['value', 'data-value'],
        });
    }

    // Track PDF scenario views/downloads
    function setupScenarioTracking() {
        document.addEventListener('click', function(e) {
            var link = e.target.closest('a[href*="/api/flood-scenarios/"]');
            if (link) {
                var filename = link.href.split('/').pop();
                var isDownload = link.hasAttribute('download');
                sendEvent(isDownload ? 'scenario_download' : 'scenario_view', {
                    filename: filename,
                });
            }
        });
    }

    function setup() {
        setupClickTracking();
        setupToggleTracking();
        setupMutationObserver();
        setupScenarioTracking();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', setup);
    } else {
        setup();
    }

    // Re-setup after Dash re-renders
    new MutationObserver(function() {
        setTimeout(function() {
            setupClickTracking();
            setupToggleTracking();
        }, 300);
    }).observe(document.body, { childList: true, subtree: true });
})();
