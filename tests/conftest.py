"""
Shared fixtures. All test images are converted from one tiny base image, `tests/data/base.png` (24x16 px).
"""
import base64
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# the modules under test live in `.codecheck/` (the template directory)
sys.path.insert(0, str(Path(__file__).parent.parent / '.codecheck'))

DATA_DIR = Path(__file__).parent / 'data'
BASE_IMAGE = DATA_DIR / 'base.png'

# formats Typst can include (see IMAGE_EXTENSIONS in codecheck.py) and formats it cannot
SUPPORTED_IMAGES = ['base.png', 'photo.jpg', 'photo.jpeg', 'anim.gif', 'vector.svg', 'doc.pdf']
UNSUPPORTED_IMAGES = ['scan.tiff', 'web.webp', 'old.bmp', 'figure.eps']
RASTER_WITH_DIMENSIONS = ['base.png', 'photo.jpg', 'photo.jpeg', 'anim.gif']  # SVG and PDF have no pixel size


@pytest.fixture(scope='session')
def image_dir(tmp_path_factory):
    """Directory with the base PNG converted to JPEG, GIF, TIFF, WebP, BMP, EPS, a 2-page PDF and an SVG."""
    Image = pytest.importorskip('PIL.Image')
    out = tmp_path_factory.mktemp('images')

    base = Image.open(BASE_IMAGE)
    rgb = base.convert('RGB')
    (out / 'base.png').write_bytes(BASE_IMAGE.read_bytes())
    rgb.save(out / 'photo.jpg')
    rgb.save(out / 'photo.jpeg', format='JPEG')
    rgb.save(out / 'anim.gif')
    rgb.save(out / 'scan.tiff')
    rgb.save(out / 'web.webp')
    rgb.save(out / 'old.bmp')
    rgb.save(out / 'figure.eps')
    rgb.save(out / 'doc.pdf', save_all=True, append_images=[rgb.rotate(90, expand=True)])  # 2 pages

    encoded = base64.b64encode(BASE_IMAGE.read_bytes()).decode()
    (out / 'vector.svg').write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'width="{base.width}" height="{base.height}">'
        f'<image width="{base.width}" height="{base.height}" xlink:href="data:image/png;base64,{encoded}"/></svg>'
    )
    return out


def section(markdown, fname):
    """The part of the `manifest_files()` output that belongs to one file."""
    return markdown.split(f"### `{fname}`")[1].split("### `")[0]


requires_git = pytest.mark.skipif(shutil.which('git') is None, reason='git is not installed')


def git_commit_all(repo, *paths):
    """`git init` in `repo` (no-op if it is a repository already) and commit `paths`; returns the commit SHA."""
    def run(*args):
        return subprocess.run(['git', '-C', str(repo), '-c', 'user.name=t', '-c', 'user.email=t@example.org', *args],
                              check=True, capture_output=True, text=True).stdout.strip()
    run('init', '-q')
    run('add', *paths)
    run('commit', '-q', '-m', 'init')
    return run('rev-parse', 'HEAD')
