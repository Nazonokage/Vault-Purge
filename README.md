# Pic Purge

> Local image duplicate and blur reviewer with reversible moves.

[![GitHub Repo](https://img.shields.io/badge/GitHub-Repository-blue?logo=github)](https://github.com/Nazonokage/pic-purge)

Pic Purge is a fast, web-based tool that runs locally on your machine to help you organize your photo library. It identifies duplicate images, detects blurry shots, and lets you review them in a clean UI before making any safe, reversible moves.

## Repository Description (For your GitHub "About" section)
*You can copy and paste this into the "Description" field on the right side of your GitHub repo:*
**"A fast, local web tool to find and review duplicate or blurry images using perceptual hashing, featuring safe and reversible file moves."**

## Features

- **Fast Duplication Detection:** Uses `ImageHash` and `Pillow` to quickly identify duplicate or highly similar images via perceptual hashing.
- **Blur Detection:** Automatically detects blurry images, helping you keep only the highest quality photos.
- **Web UI:** Built with FastAPI, featuring a clean, responsive HTML/JS/CSS interface to visually review your image groups side-by-side.
- **Reversible Moves:** Safe file operations that allow you to reverse actions if you make a mistake—nothing is permanently deleted without your final say.
- **Local & Private:** Everything runs locally on your machine using an SQLite database (`sqlmodel`) to cache results.

## How It Works

1. **Scan**: The application traverses your selected directories (`core/scanner.py`) to locate all supported image formats.
2. **Analyze & Hash**: Each image is processed to generate a perceptual hash (`core/hasher.py`) and is evaluated for blurriness/quality (`core/classifier.py`). Important metadata like EXIF data is also parsed (`utils/exif_handler.py`).
3. **Group**: Images with identical or highly similar perceptual hashes are clustered together into duplicate groups (`core/grouper.py`). 
4. **Review**: The FastAPI backend serves a responsive web dashboard (`ui/static/`) where you can visually compare these groups or review the detected blurry photos. 
5. **Resolve**: When you decide to remove an image, the resolver (`core/resolver.py`) executes a *reversible* file move (`utils/file_ops.py`), ensuring you never accidentally lose a precious photo permanently.

## Directory Structure

```text
pic-purge/
├── image_dedup/
│   ├── core/               # Core processing logic
│   │   ├── classifier.py   # Blurriness & quality classification
│   │   ├── grouper.py      # Groups similar images by hash
│   │   ├── hasher.py       # Perceptual hashing (ImageHash)
│   │   ├── resolver.py     # Reversible file operations & logic
│   │   └── scanner.py      # Directory traversal
│   ├── storage/            # Database management
│   │   ├── database.py     # SQLite connection and sessions
│   │   └── models.py       # SQLModel database schemas
│   ├── ui/                 # Web interface assets
│   │   └── static/         # HTML, JS, and CSS for the dashboard
│   ├── utils/              # Helper functions
│   │   ├── exif_handler.py # EXIF data extraction
│   │   ├── file_ops.py     # Safe file move/delete utilities
│   │   └── thumb_cache.py  # Thumbnail caching for fast UI rendering
│   └── cli/                # Typer CLI entry points
├── tests/                  # Test suite
├── pyproject.toml          # Project dependencies and metadata
├── Todo.md                 # Planned features and tasks
├── CHANGELOG.md            # Version history
└── README.md               # This documentation
```

## Installation

This project requires Python 3.11+.

1. Clone the repository:
   ```bash
   git clone https://github.com/Nazonokage/pic-purge.git
   cd pic-purge
   ```

2. Install dependencies (we recommend using a virtual environment):
   ```bash
   pip install -e .
   ```

## Usage

To start the local web interface and API:

```bash
uvicorn image_dedup.main:app --reload
```
*(Or use the CLI command `image-dedup` if configured)*

Navigate to `http://localhost:8000` in your web browser to access the application.

## License
MIT License
