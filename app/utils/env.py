
# Load environment variables

import os
import dotenv
import logging

dotenv.load_dotenv()


class Args:
    def __init__(self):
        self.data_path = os.getenv('DATA_PATH')


args = Args()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.info(f"Data path is set to: {args.data_path}")
