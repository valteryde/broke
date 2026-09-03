"""City name lookup and Miller projection for the Usage map."""

from ward import test

from app.utils.city_coords import fold_name, lookup, point_for, project


@test("fold_name strips accents so København matches Copenhagen's ascii form")
def _():
    assert fold_name("København") == "kobenhavn"
    assert fold_name("Århus") == "arhus"
    assert fold_name("München") == "munchen"


@test("lookup finds Natural Earth populated places by English and local names")
def _():
    assert lookup("Copenhagen", "DK") == (12.56, 55.68)
    assert lookup("København", "DK") == (12.56, 55.68)
    assert lookup("Aarhus", "DK") == (10.21, 56.16)
    assert lookup("New York City", "US") is not None
    assert lookup("Nowhereville", "DK") is None
    assert lookup("Copenhagen", "US") is None


@test("Copenhagen projects inside the Denmark outline on the usage map")
def _():
    point = point_for("Copenhagen", "DK")
    assert point is not None
    # Denmark path bbox in world-110m.json: x 685.0–702.3, y 195.0–212.3
    assert 685.0 <= point["x"] <= 703.0
    assert 195.0 <= point["y"] <= 213.0
    aarhus = point_for("Aarhus", "DK")
    assert aarhus is not None
    assert 685.0 <= aarhus["x"] <= 703.0
    assert abs(aarhus["x"] - point["x"]) > 2


@test("project is the Miller crop used by world-110m.json")
def _():
    x, y = project(12.56, 55.68)
    assert round(x, 1) == point_for("Copenhagen", "DK")["x"]
    assert round(y, 1) == point_for("Copenhagen", "DK")["y"]
