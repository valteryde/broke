
import pathlib
from .env import args

BASE_DIR = pathlib.Path(__file__).parent.parent.resolve()

if hasattr(args, 'data_path') and args.data_path:
    DATA_BASE_DIR = pathlib.Path(args.data_path).resolve()
else:
    DATA_BASE_DIR = BASE_DIR.joinpath('data')

def path(*subpaths: str) -> pathlib.Path:
    """
    Construct an absolute path by joining BASE_DIR with subpaths.
    """
    return BASE_DIR.joinpath(*subpaths)

def data_path(*subpaths: str) -> pathlib.Path:
    """
    Construct an absolute path within the 'data' directory.
    """
    return DATA_BASE_DIR.joinpath(*subpaths)