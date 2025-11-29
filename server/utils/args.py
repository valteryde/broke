
import argparse

parser = argparse.ArgumentParser(description="Server Path Configuration")
parser.add_argument('--data-path', type=str, required=False, help='Path to the data directory')
args = parser.parse_args()