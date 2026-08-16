"""Fileshare core utilities - shared between Flask and FastAPI."""

import os

# Security: files/folders to always hide
SYSTEM_FILES = {'.DS_Store', 'Thumbs.db', 'desktop.ini', '.git', '__pycache__', '.env'}


def format_size(size):
    """Format file size for display."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024:
            return f"{size:.1f} {unit}" if unit != 'B' else f"{size} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


def get_file_icon(filename):
    """Get emoji icon for file type."""
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    icons = {
        'pdf': '\U0001F4D5',
        'doc': '\U0001F4D8', 'docx': '\U0001F4D8',
        'xls': '\U0001F4D7', 'xlsx': '\U0001F4D7',
        'ppt': '\U0001F4D9', 'pptx': '\U0001F4D9',
        'zip': '\U0001F4E6', 'tar': '\U0001F4E6', 'gz': '\U0001F4E6', 'rar': '\U0001F4E6', '7z': '\U0001F4E6',
        'jpg': '\U0001F5BC\uFE0F', 'jpeg': '\U0001F5BC\uFE0F', 'png': '\U0001F5BC\uFE0F', 'gif': '\U0001F5BC\uFE0F', 'webp': '\U0001F5BC\uFE0F',
        'mp4': '\U0001F3AC', 'mov': '\U0001F3AC', 'avi': '\U0001F3AC', 'mkv': '\U0001F3AC', 'webm': '\U0001F3AC',
        'mp3': '\U0001F3B5', 'wav': '\U0001F3B5', 'flac': '\U0001F3B5', 'ogg': '\U0001F3B5',
        'py': '\U0001F40D', 'js': '\U0001F4DC', 'ts': '\U0001F4DC', 'html': '\U0001F310', 'css': '\U0001F3A8',
        'txt': '\U0001F4C4', 'md': '\U0001F4DD',
    }
    return icons.get(ext, '\U0001F4C4')


def _within(path, base):
    """True if path is base itself or strictly inside it."""
    return path == base or path.startswith(base + os.sep)


def safe_path(base_dir, requested_path):
    """Prevent path traversal and symlink escapes.

    Resolves symlinks on both the base and the requested path, then verifies
    the result is still inside the base.

    A lexical check is not enough on its own. os.path.abspath normalizes ".."
    but does not follow symlinks, so a link inside the share pointing outside
    it still has a path under the base: the prefix test passes and the kernel
    then follows the link on open. os.path.realpath is what actually resolves
    it.

    Both sides must be resolved. A share root that is itself a symlink is
    ordinary -- macOS puts temp dirs under /var, a link to /private/var, and
    plenty of home and NAS layouts do the same -- so comparing a resolved path
    against an unresolved base would reject every such share.

    Args:
        base_dir: The root directory being shared
        requested_path: User-provided relative path

    Returns:
        Resolved absolute path if safe, None if it escapes the base or does
        not exist. The path is fully resolved, so it has no symlink components
        left for a later open to follow somewhere else.
    """
    base = os.path.abspath(base_dir)
    requested = os.path.abspath(os.path.join(base, requested_path))

    # Cheap lexical rejection first: catches ".." without touching the disk.
    if not _within(requested, base):
        return None

    if not os.path.exists(requested):
        return None

    real_base = os.path.realpath(base)
    real_path = os.path.realpath(requested)

    if not _within(real_path, real_base):
        return None

    return real_path


def visible_under(base_dir, abs_path):
    """True if every path component between the share root and abs_path passes
    should_show.

    Hiding an entry from the listing is not a read control on its own: without
    this, ".env" is absent from a directory listing but still served to anyone
    who asks for it by name, and so is anything inside a hidden directory.
    Checking the whole relative path rather than just the basename is what
    stops ".git/config" from being reachable while ".git" is hidden.
    """
    real_base = os.path.realpath(os.path.abspath(base_dir))
    try:
        rel = os.path.relpath(abs_path, real_base)
    except ValueError:
        return False
    if rel == os.curdir:
        return True
    for part in rel.split(os.sep):
        if part in ('', os.curdir):
            continue
        if not should_show(part):
            return False
    return True


def safe_visible_path(base_dir, requested_path):
    """safe_path plus the hidden-file policy. Use this for every read."""
    abs_path = safe_path(base_dir, requested_path)
    if abs_path is None or not visible_under(base_dir, abs_path):
        return None
    return abs_path


def should_show(name, show_hidden=False):
    """Determine if file/folder should be shown in listing.

    Args:
        name: File or folder name
        show_hidden: Whether to show dotfiles

    Returns:
        True if should be shown, False otherwise
    """
    if name in SYSTEM_FILES:
        return False
    if name.startswith('.') and not show_hidden:
        return False
    return True
