"""Tests for Sentry `_meta` truncation helpers."""

from ward import test

from app.utils.sentry_meta import (
    annotate_frame_var_truncations,
    lookup_frame_var_meta,
    truncation_info_for_var,
)


def _meta_for_var(frame_index: int, var_name: str, *, original_len: int = 15):
    return {
        "exception": {
            "values": {
                "0": {
                    "stacktrace": {
                        "frames": {
                            str(frame_index): {
                                "vars": {
                                    var_name: {
                                        "": {
                                            "len": original_len,
                                            "rem": [["!limit", "x"]],
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }


@test("lookup_frame_var_meta finds truncated list leaf")
def _():
    meta = _meta_for_var(1, "items", original_len=42)
    leaf = lookup_frame_var_meta(meta, frame_index=1, var_name="items")
    assert leaf is not None
    assert leaf["len"] == 42


@test("truncation_info_for_var returns collection label with original length")
def _():
    meta = _meta_for_var(0, "big_list", original_len=20)
    info = truncation_info_for_var(
        meta,
        frame_index=0,
        var_name="big_list",
        value=[0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    )
    assert info is not None
    assert info["kind"] == "collection"
    assert info["original_len"] == 20
    assert "20 items" in info["label"]


@test("truncation_info_for_var returns None when meta missing")
def _():
    info = truncation_info_for_var(
        {},
        frame_index=0,
        var_name="x",
        value=[1, 2, 3],
    )
    assert info is None


@test("annotate_frame_var_truncations maps reversed display frames to original indices")
def _():
    # Original order: frame0 (bottom), frame1 (top / crash site)
    # Display (reversed): frame1 first, then frame0
    frames = [
        {
            "function": "crash",
            "vars": {"items": list(range(10))},
        },
        {
            "function": "caller",
            "vars": {"ok": [1, 2, 3]},
        },
    ]
    # Meta indexes refer to original order: crash is index 1
    meta = _meta_for_var(1, "items", original_len=50)

    annotate_frame_var_truncations(frames, meta, reversed_for_display=True)

    assert "items" in frames[0]["_var_truncations"]
    assert frames[0]["_var_truncations"]["items"]["original_len"] == 50
    assert frames[1]["_var_truncations"] == {}


@test("annotate_frame_var_truncations without reverse uses display index as original")
def _():
    frames = [
        {"function": "a", "vars": {"items": list(range(10))}},
        {"function": "b", "vars": {}},
    ]
    meta = _meta_for_var(0, "items", original_len=12)
    annotate_frame_var_truncations(frames, meta, reversed_for_display=False)
    assert "items" in frames[0]["_var_truncations"]
    assert frames[1]["_var_truncations"] == {}
