
import pathlib

BASE_DIR = pathlib.Path(__file__).parent.parent.resolve()

def path(*subpaths: str) -> pathlib.Path:
    """
    Construct an absolute path by joining BASE_DIR with subpaths.
    """
    return BASE_DIR.joinpath(*subpaths)
