const LOCAL_HTTP_HOSTS = new Set(["localhost", "127.0.0.1"]);

function parseUrl(value) {
  try {
    return new URL(String(value || ""));
  } catch (_err) {
    return null;
  }
}

function isLocalRendererUrl(value) {
  const url = parseUrl(value);
  return Boolean(url && url.protocol === "file:");
}

function sameOrigin(left, right) {
  const leftUrl = parseUrl(left);
  const rightUrl = parseUrl(right);
  return Boolean(leftUrl && rightUrl && leftUrl.origin === rightUrl.origin);
}

function isAllowedBackendUrl(value) {
  const url = parseUrl(value);
  if (!url) {
    return false;
  }

  if (url.protocol === "https:") {
    return true;
  }

  return url.protocol === "http:" && LOCAL_HTTP_HOSTS.has(url.hostname);
}

function isAllowedBootstrapUrl(value) {
  const url = parseUrl(value);
  if (!url) {
    return false;
  }

  return isAllowedBackendUrl(url.origin) && url.pathname === "/api/desktop/bootstrap";
}

function isAllowedExternalUrl(value) {
  const url = parseUrl(value);
  if (!url) {
    return false;
  }

  return url.protocol === "https:" || url.protocol === "http:";
}

function isAllowedNavigationUrl(targetUrl, currentBackendUrl) {
  if (isLocalRendererUrl(targetUrl)) {
    return true;
  }

  if (!currentBackendUrl) {
    return false;
  }

  return sameOrigin(targetUrl, currentBackendUrl);
}

module.exports = {
  isAllowedBackendUrl,
  isAllowedBootstrapUrl,
  isAllowedExternalUrl,
  isAllowedNavigationUrl,
  isLocalRendererUrl,
  sameOrigin,
};