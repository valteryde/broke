/**
 * Work cycles UI: jdenticon for avatars on the living board.
 */
(function () {
    function paint() {
        try {
            if (typeof jdenticon !== "undefined") {
                jdenticon();
            }
        } catch (e) {
            /* ignore */
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", paint);
    } else {
        paint();
    }
})();
