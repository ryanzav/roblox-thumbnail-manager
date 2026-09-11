from pathlib import Path
from src.config import load_config
from src.image_moderation import check_image_safety
print(check_image_safety(load_config(), Path('/Users/yogollc/Desktop/project-thumbnail-optimizer/docs/images/thumbnails/thumb-001.png').read_bytes()))
