/**
 * River Monitor — user layer upload handler.
 * Wires the Upload Layer button to a hidden file input, uploads via fetch
 * to /api/river/upload-layer, and bridges the result into Dash via
 * dash_clientside.set_props(). Clear Layer button calls /api/river/clear-layers.
 */
(function() {
    function setup() {
        var btn = document.getElementById('river-upload-layer-btn');
        if (!btn || btn._rv_setup) return;
        btn._rv_setup = true;

        // Create hidden file input
        var fi = document.createElement('input');
        fi.type = 'file';
        fi.accept = '.geojson,.json,.zip';
        fi.multiple = false;
        fi.style.display = 'none';
        document.body.appendChild(fi);

        // Button click opens native file dialog
        btn.addEventListener('click', function() { fi.click(); });

        // File selected → upload via fetch
        fi.addEventListener('change', async function() {
            if (!fi.files || fi.files.length === 0) return;
            var fd = new FormData();
            for (var i = 0; i < fi.files.length; i++)
                fd.append('files', fi.files[i]);

            var badge = document.getElementById('river-upload-status');
            if (badge) {
                badge.style.display = '';
                badge.textContent = 'Uploading...';
            }

            try {
                var r = await fetch('/api/river/upload-layer',
                    {method: 'POST', body: fd});
                var j = await r.json();
                fi.value = '';
                if (j.loaded && j.loaded.length > 0) {
                    var info = j.loaded[0];
                    if (badge) badge.textContent =
                        info.name + ' (' + info.feature_count + ' features)';
                    dash_clientside.set_props(
                        'river-upload-result', {data: j});
                    // Show clear button
                    var clr = document.getElementById('river-clear-layer-btn');
                    if (clr) clr.style.display = '';
                } else {
                    if (badge) badge.textContent = j.error || 'Upload Failed';
                }
            } catch(e) {
                console.error('Layer upload failed:', e);
                fi.value = '';
                if (badge) badge.textContent = 'Upload Error';
            }
        });

        // Clear button handler
        var clrBtn = document.getElementById('river-clear-layer-btn');
        if (clrBtn && !clrBtn._rv_setup) {
            clrBtn._rv_setup = true;
            clrBtn.addEventListener('click', async function() {
                try {
                    await fetch('/api/river/clear-layers',
                        {method: 'POST'});
                    dash_clientside.set_props(
                        'river-clear-result',
                        {data: {cleared: true, ts: Date.now()}});
                    clrBtn.style.display = 'none';
                    var badge = document.getElementById('river-upload-status');
                    if (badge) badge.style.display = 'none';
                } catch(e) {
                    console.error('Clear layers failed:', e);
                }
            });
        }
    }

    // Run setup after page loads and after Dash re-renders (page navigation)
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', setup);
    } else {
        setup();
    }
    new MutationObserver(function() {
        setTimeout(setup, 300);
    }).observe(document.body, {childList: true, subtree: true});
})();
