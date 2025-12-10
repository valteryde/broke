
function openUrlWithArgs(url) {

    // Get the current URL's search parameters
    const currentParams = new URLSearchParams(window.location.search);

    // Create a new URL object
    const newUrl = new URL(url, window.location.origin);

    // Append current search parameters to the new URL
    currentParams.forEach((value, key) => {
        newUrl.searchParams.append(key, value);
    });

    // Navigate to the new URL
    window.location.href = newUrl.toString();
}
