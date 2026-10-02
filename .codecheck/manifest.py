"""
Manifest processing module for CODECHECK certificates
https://codecheck.org.uk
"""
from pathlib import Path
import os
import shutil
from typing import List, Dict, Tuple, Optional

from validation_config import TEMPLATE_DIRS


def find_outputs_dir(base_dir) -> Path:
    """
    Directory with the reproduced output files, `.codecheck/outputs` or `codecheck/outputs` below `base_dir`.

    The first of the two directories that already has an `outputs/` directory is used, then the first of the two that
    exists (`outputs/` is created later), otherwise the default `.codecheck/outputs`. `.codecheck` has priority if both
    qualify.
    """
    base_dir = Path(base_dir)
    for name in TEMPLATE_DIRS:
        if (base_dir / name / 'outputs').is_dir():
            return base_dir / name / 'outputs'
    for name in TEMPLATE_DIRS:
        if (base_dir / name).is_dir():
            return base_dir / name / 'outputs'
    return base_dir / TEMPLATE_DIRS[0] / 'outputs'


def output_path(outputs_dir, file_path) -> Optional[Path]:
    """
    Path of a manifest file in `outputs_dir`, or None if the manifest path leads outside of it (absolute path, `..`).

    The check is lexical: symlinks in `outputs_dir` (e.g. to large original files) are not resolved.
    """
    outputs_dir = Path(os.path.normpath(outputs_dir))
    path = Path(os.path.normpath(outputs_dir / str(file_path)))
    return path if path.is_relative_to(outputs_dir) else None


def existing_file(base, file_path) -> Optional[Path]:
    """Path of a manifest file in `base` if it is inside `base` (see `output_path()`) and is a file, otherwise None."""
    path = output_path(base, file_path)
    return path if path is not None and path.is_file() else None


def manifest_file_paths(manifest) -> List:
    """File paths of the well-formed manifest entries; entries that are no mappings or have no file are skipped."""
    return [e['file'] for e in manifest if isinstance(e, dict) and e.get('file')] if isinstance(manifest, list) else []


class ManifestProcessor:
    """
    Processor for handling manifest files in CODECHECK certificates.

    Handles file validation, copying, and size tracking for manifest entries.
    """

    def __init__(self, manifest: List[Dict], base_dir: Path, outputs_dir: Optional[Path] = None):
        """
        Initialize manifest processor.

        Parameters
        ----------
        manifest : list of dict
            Manifest entries from codecheck.yml
        base_dir : Path
            Base directory (typically repository root)
        outputs_dir : Path, optional
            Directory of the reproduced files. Defaults to `find_outputs_dir(base_dir)`.
        """
        self.manifest = manifest
        self.base_dir = Path(base_dir)
        self.outputs_dir = Path(outputs_dir) if outputs_dir else find_outputs_dir(self.base_dir)

    def _entries(self):
        """Well-formed manifest entries; entries that are no mappings or have no file are skipped."""
        return (e for e in self.manifest if isinstance(e, dict) and e.get('file'))

    def _file_paths(self):
        """File paths of the well-formed manifest entries."""
        return manifest_file_paths(self.manifest)

    def validate_files_exist(self, source_dir: Optional[Path] = None) -> Tuple[bool, List[str]]:
        """
        Check if all manifest files exist in the source directory.

        Parameters
        ----------
        source_dir : Path, optional
            Directory to check for files. Defaults to base_dir.

        Returns
        -------
        tuple
            (all_exist: bool, missing_files: List[str])
        """
        if source_dir is None:
            source_dir = self.base_dir

        missing = [f for f in self._file_paths() if existing_file(source_dir, f) is None]
        return len(missing) == 0, missing

    def validate_output_files_exist(self) -> Tuple[bool, List[str]]:
        """
        Check if all manifest files exist in the outputs directory.

        Returns
        -------
        tuple
            (all_exist: bool, missing_files: List[str])
        """
        if not self.outputs_dir.exists():
            return False, list(self._file_paths())

        # paths outside of outputs/ count as missing
        missing = [f for f in self._file_paths() if existing_file(self.outputs_dir, f) is None]
        return len(missing) == 0, missing

    def get_file_sizes(self, use_outputs: bool = True) -> Dict[str, int]:
        """
        Get actual file sizes for all manifest files.

        Parameters
        ----------
        use_outputs : bool, optional
            If True, check files in outputs/ directory.
            If False, check in base directory. Defaults to True.

        Returns
        -------
        dict
            Mapping of file paths to sizes in bytes
        """
        sizes = {}
        base = self.outputs_dir if use_outputs else self.base_dir

        for file_path in self._file_paths():
            full_path = existing_file(base, file_path)
            if full_path is not None:
                sizes[file_path] = full_path.stat().st_size

        return sizes

    def compare_sizes(self) -> List[Dict]:
        """
        Compare declared sizes in manifest with actual file sizes.

        Returns
        -------
        list of dict
            Entries with size mismatches: [{file, declared, actual, difference}, ...]
        """
        mismatches = []
        actual_sizes = self.get_file_sizes(use_outputs=True)

        for entry in self._entries():
            file_path = entry['file']
            declared_size = entry.get('size')

            if declared_size is None:
                continue

            actual_size = actual_sizes.get(file_path)
            if actual_size is not None and actual_size != declared_size:
                mismatches.append({
                    'file': file_path,
                    'declared': declared_size,
                    'actual': actual_size,
                    'difference': actual_size - declared_size
                })

        return mismatches

    def copy_manifest_files(self,
                           source_dir: Optional[Path] = None,
                           keep_full_path: bool = True,
                           overwrite: bool = True,
                           dry_run: bool = False,
                           update: bool = False) -> List[Dict]:
        """
        Copy manifest files to outputs directory.

        Parameters
        ----------
        source_dir : Path, optional
            Source directory containing files. Defaults to base_dir.
        keep_full_path : bool, optional
            If True, maintain directory structure in outputs.
            If False, flatten all files to outputs root. Defaults to True.
        overwrite : bool, optional
            If True, overwrite existing files. Defaults to True.
        dry_run : bool, optional
            If True, don't actually copy files. Defaults to False.
        update : bool, optional
            If True, replace an existing file only if the source is newer (like `rsync --update`), so a file that
            was reproduced directly into outputs/ is not replaced by an older original. Defaults to False.

        Returns
        -------
        list of dict
            Information about copied files: [{file, source, destination, size}, ...]
        """
        if source_dir is None:
            source_dir = self.base_dir

        source_dir = Path(source_dir)
        copied = []

        # Create outputs directory if it doesn't exist
        if not dry_run and not self.outputs_dir.exists():
            self.outputs_dir.mkdir(parents=True, exist_ok=True)

        for entry in self._entries():
            file_path = entry['file']

            src = output_path(source_dir, file_path)
            dst = output_path(self.outputs_dir, file_path if keep_full_path else Path(file_path).name)

            if src is None or dst is None or not src.is_file():
                # Skip missing files and paths outside of the source or outputs directory (caught by validation)
                continue

            if keep_full_path and not dry_run:
                dst.parent.mkdir(parents=True, exist_ok=True)

            # Check if we should overwrite; never write through a symlink to the source or out of outputs/
            if dst.exists() and (not overwrite or dst.samefile(src)):
                continue
            if update and dst.exists() and src.stat().st_mtime <= dst.stat().st_mtime:
                continue  # the copy in outputs/ is up to date or newer
            if not dst.resolve().is_relative_to(self.outputs_dir.resolve()):
                continue

            # Copy the file
            if not dry_run:
                shutil.copy2(src, dst)

            copied.append({
                'file': file_path,
                'source': str(src),
                'destination': str(dst),
                'size': src.stat().st_size,
                'comment': entry.get('comment', '')
            })

        return copied

    def get_manifest_summary(self) -> Dict:
        """
        Get summary statistics about the manifest.

        Returns
        -------
        dict
            Summary with file counts, total size, etc.
        """
        file_paths = self._file_paths()
        sizes = self.get_file_sizes(use_outputs=True)
        total_size = sum(sizes.values())

        # Count file types
        extensions = {}
        for file_path in file_paths:
            ext = Path(str(file_path)).suffix.lower()
            extensions[ext] = extensions.get(ext, 0) + 1

        return {
            'total_files': len(file_paths),
            'total_size': total_size,
            'total_size_mb': round(total_size / (1024 * 1024), 2),
            'file_types': extensions,
            'has_comments': sum(1 for e in self._entries() if e.get('comment'))
        }

    def validate_paths(self) -> Tuple[bool, List[str]]:
        """
        Validate that all file paths are safe (no path traversal).

        Returns
        -------
        tuple
            (all_safe: bool, unsafe_paths: List[str])
        """
        unsafe = []
        for file_path in self._file_paths():
            # Check for path traversal attempts (absolute paths, `..`) and symlinks that lead outside
            if (output_path(self.outputs_dir, file_path) is None
                    or not (self.outputs_dir / file_path).resolve().is_relative_to(self.outputs_dir.resolve())):
                unsafe.append(file_path)

        return len(unsafe) == 0, unsafe
