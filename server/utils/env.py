
# Load environment variables

import os
import dotenv

dotenv.load_dotenv()

class Args:
    def __init__(self):
        self.data_path = os.getenv('DATA_PATH')

args = Args()