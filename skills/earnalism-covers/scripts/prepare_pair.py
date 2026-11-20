"""Package final cover files without changing pixels or production state."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile


def prepare(slug, book_file, front, back, output):
    from PIL import Image
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', slug):
        raise ValueError('Use the canonical lower-case book slug')
    book = json.loads(Path(book_file).read_text())
    if book.get('slug') != slug or not book.get('title') or not book.get('author'):
        raise ValueError('Book slug, title or author does not match current metadata')
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise ValueError('Use a new output directory; existing work is never overwritten')
    records, payloads = {}, {}
    for side, source in [('front', front), ('back', back)]:
        source = Path(source)
        data = source.read_bytes()
        if not data or len(data) > 20_000_000:
            raise ValueError(f'{side}: empty or larger than 20 MB')
        # Decode the exact bytes that will be copied, not a second source read.
        import io
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            fmt = image.format
            image.verify()
        if fmt not in ('PNG', 'JPEG', 'WEBP') or width < 800 or height < 1200:
            raise ValueError(f'{side}: use PNG, JPEG or WebP at least 800×1200')
        if width * 3 != height * 2:
            raise ValueError(f'{side}: expected the current 2:3 portrait series ratio')
        sha = hashlib.sha256(data).hexdigest()
        ext = {'PNG': 'png', 'JPEG': 'jpg', 'WEBP': 'webp'}[fmt]
        filename = f'{slug}-{side}-{sha[:16]}.{ext}'
        records[side] = {'file': filename, 'sha256': sha, 'bytes': len(data),
                         'width': width, 'height': height, 'format': fmt,
                         'source_file': str(source.resolve()),
                         'within_180kb_feature_target': len(data) <= 180_000}
        payloads[filename] = data
    if records['front']['sha256'] == records['back']['sha256']:
        raise ValueError('Front and back must be distinct files')
    if (records['front']['width'], records['front']['height']) != (records['back']['width'], records['back']['height']):
        raise ValueError('Front and back dimensions must match')
    report = {'schema': 'earnalism.cover-pair-handoff.v1', 'slug': slug,
              'title': book['title'], 'author': book['author'], 'covers': records,
              'status': 'PREPARED_NOT_UPLOADED', 'production_verified': False,
              'approval_evidence': 'Use the actual owner instruction and existing title record; this helper grants no approval.',
              'next_action': 'Canonical promotion through Integration Lane, then verify both production image URLs.'}
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.cover-pair-', dir=output.parent))
    try:
        for name, data in payloads.items():
            (staging / name).write_bytes(data)
        (staging / 'cover-pair.json').write_text(json.dumps(report, indent=2)+'\n')
        # mkdir is exclusive; a concurrent output must never be overwritten.
        output.mkdir()
        try:
            for item in staging.iterdir():
                shutil.copyfile(item, output / item.name)
        except Exception:
            # Retain a partial output for inspection; rerun must choose a new path.
            raise
    finally:
        shutil.rmtree(staging)
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for key in ('slug', 'book', 'front', 'back', 'output'):
        p.add_argument('--'+key, required=True)
    a = p.parse_args()
    try:
        print(json.dumps(prepare(a.slug, a.book, a.front, a.back, a.output), indent=2))
    except (ValueError, OSError, ImportError) as exc:
        p.exit(1, f'Cover pair not prepared: {exc}\n')


if __name__ == '__main__':
    # Prefer the existing bundled image runtime over installing dependencies.
    try:
        import PIL
    except ImportError:
        import os
        import sys
        bundled = Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3'
        if bundled.is_file() and bundled.resolve() != Path(sys.executable).resolve():
            os.execv(str(bundled), [str(bundled), str(Path(__file__).resolve()), *sys.argv[1:]])
    main()
