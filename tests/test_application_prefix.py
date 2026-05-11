"""URL prefix (BROKE_APPLICATION_PREFIX) behavior."""

import os

from ward import test


def _reset_prefix_env(prev: str | None) -> None:
    if prev is None:
        os.environ.pop("BROKE_APPLICATION_PREFIX", None)
    else:
        os.environ["BROKE_APPLICATION_PREFIX"] = prev


@test("create_app normalizes BROKE_APPLICATION_PREFIX and sets session cookie path")
def _():
    from app.utils.app import create_app

    prev = os.environ.get("BROKE_APPLICATION_PREFIX")
    prev_env = os.environ.get("FLASK_ENV")
    os.environ["FLASK_ENV"] = "testing"
    os.environ["BROKE_APPLICATION_PREFIX"] = "broke"

    try:
        app = create_app()
        assert app.config["BROKE_APPLICATION_PREFIX"] == "/broke"
        assert app.config["SESSION_COOKIE_PATH"] == "/broke/"
    finally:
        _reset_prefix_env(prev)
        if prev_env is None:
            os.environ.pop("FLASK_ENV", None)
        else:
            os.environ["FLASK_ENV"] = prev_env


@test("prefixed request serves login page with prefixed static URLs")
def _():
    from app.utils.app import create_app

    prev = os.environ.get("BROKE_APPLICATION_PREFIX")
    prev_env = os.environ.get("FLASK_ENV")
    os.environ["FLASK_ENV"] = "testing"
    os.environ["BROKE_APPLICATION_PREFIX"] = "/broke"

    try:
        app = create_app()
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        with app.test_client() as client:
            response = client.get("/broke/login")
        assert response.status_code == 200
        assert b"/broke/static/" in response.data
    finally:
        _reset_prefix_env(prev)
        if prev_env is None:
            os.environ.pop("FLASK_ENV", None)
        else:
            os.environ["FLASK_ENV"] = prev_env


@test("sanitize_next_app_path strips leading application prefix from next param")
def _():
    from app.utils.security import sanitize_next_app_path
    from flask import Flask

    app = Flask(__name__)
    with app.test_request_context(environ_overrides={"SCRIPT_NAME": "/broke", "PATH_INFO": "/login"}):
        assert sanitize_next_app_path("/news") == "/news"
        assert sanitize_next_app_path("/broke/news") == "/news"
