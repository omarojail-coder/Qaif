from pathlib import Path
from .predictor import SaddlePredictor

def create_predictor():
    return SaddlePredictor(Path(__file__).resolve().parent)
