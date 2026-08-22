"""Path grains for the usage beacon."""

from ward import test

from app.utils.usage_normalize import normalize_path, normalize_referrer


@test("normalize_path strips query and trailing slash")
def _():
    grains = normalize_path("/tickets/BAC-106?x=1#hash")
    assert grains["path"] == "/tickets/BAC-106"
    assert grains["route"] == "/tickets/:id"
    assert grains["sector"] == "tickets"


@test("normalize_path collapses uuid and numeric segments")
def _():
    grains = normalize_path("/users/550e8400-e29b-41d4-a716-446655440000/2")
    assert grains["route"] == "/users/:id/:id"
    assert grains["sector"] == "users"


@test("normalize_path treats site root as (root)")
def _():
    grains = normalize_path("/")
    assert grains == {"path": "/", "route": "/", "sector": "(root)"}


@test("normalize_referrer keeps an in-app path")
def _():
    assert normalize_referrer("/settings/team") == "/settings/team"


@test("normalize_referrer drops a different host")
def _():
    assert normalize_referrer("https://other.example/path", page_host="app.example") is None
