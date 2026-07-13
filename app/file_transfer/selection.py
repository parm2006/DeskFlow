from pathlib import Path

from .models import FileItem, ItemType, Manifest
from .source import SourceFile
from .validation import validate_manifest


def snapshot_selection(paths):
    items = []
    sources = {}
    for selected in paths:
        selected = Path(selected)
        if selected.is_dir():
            _snapshot_directory(selected, selected.name, items, sources)
        else:
            _snapshot_file(selected, selected.name, items, sources)
    manifest = Manifest.create(items)
    validate_manifest(manifest)
    return manifest, sources


def _snapshot_directory(path, relative_path, items, sources):
    stat = path.stat()
    items.append(FileItem(relative_path, ItemType.DIRECTORY, 0, stat.st_mtime_ns))
    for child in sorted(path.iterdir(), key=lambda value: value.name.casefold()):
        child_relative = f"{relative_path}/{child.name}"
        if child.is_dir():
            _snapshot_directory(child, child_relative, items, sources)
        else:
            _snapshot_file(child, child_relative, items, sources)


def _snapshot_file(path, relative_path, items, sources):
    source = SourceFile.snapshot(path)
    items.append(
        FileItem(
            relative_path,
            ItemType.FILE,
            source.size,
            source.modified_ns,
            source.sha256,
            str(path),
        )
    )
    sources[relative_path] = source
