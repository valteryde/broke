"""Strip a configured URL prefix from incoming WSGI PATH_INFO so Flask routes stay root-relative."""


def normalize_application_prefix(raw: str | None) -> str:
    """Return '', or a path like ``/broke`` (leading slash, no trailing slash)."""
    p = (raw or "").strip()
    if not p or p == "/":
        return ""
    if not p.startswith("/"):
        p = "/" + p
    return p.rstrip("/")


class ApplicationPrefixMiddleware:
    """
    When the client requests ``/PREFIX/...``, set SCRIPT_NAME and pass ``/...``
    as PATH_INFO so url_for(), static, etc. emit ``/PREFIX/...`` in HTML.

    If PATH_INFO does not start with PREFIX (reverse proxy already normalized),
    environ is unchanged.
    """

    def __init__(self, app, prefix: str):
        self.app = app
        self.prefix = normalize_application_prefix(prefix)

    def __call__(self, environ, start_response):
        if not self.prefix:
            return self.app(environ, start_response)

        path_info = environ.get("PATH_INFO") or ""
        if path_info != self.prefix and not path_info.startswith(self.prefix + "/"):
            return self.app(environ, start_response)

        script = environ.get("SCRIPT_NAME") or ""
        environ["SCRIPT_NAME"] = script + self.prefix
        rest = path_info[len(self.prefix) :] or "/"
        if not rest.startswith("/"):
            rest = "/" + rest
        environ["PATH_INFO"] = rest
        return self.app(environ, start_response)
