"""Move document/output directories into ignored local_data without deleting files."""
import argparse
from pathlib import Path
import shutil

SOURCE_DIRECTORIES = {'ui','services','utils','scripts','tests','examples','assets','packaging',
                      'artifacts','build','dist','release','local_data'}
DOCUMENT_SUFFIXES = {'.pdf','.docx','.png','.jpg','.jpeg','.webp','.bmp','.tif','.tiff','.tmp'}


def organize(root, apply=False):
    moves = []
    for path in sorted(root.iterdir()):
        if path.name.startswith('.') or path.name.endswith('.egg-info'):
            continue
        if path.is_dir() and path.name not in SOURCE_DIRECTORIES:
            moves.append((path, root/'local_data'/path.name))
        elif path.is_file() and path.suffix.lower() in DOCUMENT_SUFFIXES:
            moves.append((path, root/'local_data'/'loose_files'/path.name))
    if apply:
        for source, destination in moves:
            if destination.exists():
                raise FileExistsError(f'Will not overwrite existing destination: {destination}')
        for source, destination in moves:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
    return len(moves)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true',help='Move files; default only counts candidates')
    args=parser.parse_args()
    count=organize(Path(__file__).resolve().parents[1],args.apply)
    print(f'{count} document/output locations {"moved into local_data" if args.apply else "would be moved; pass --apply"}.')
