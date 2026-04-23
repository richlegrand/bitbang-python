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


def safe_path(base_dir, requested_path):
    """Prevent path traversal attacks.

    Resolves the requested path and verifies it's within base_dir.

    Args:
        base_dir: The root directory being shared
        requested_path: User-provided relative path

    Returns:
        Absolute path if safe, None if path traversal attempted or doesn't exist
    """
    base = os.path.abspath(base_dir)
    requested = os.path.abspath(os.path.join(base, requested_path))

    # Check that resolved path starts with base (or equals base)
    if not requested.startswith(base + os.sep) and requested != base:
        return None

    # Check path exists
    if not os.path.exists(requested):
        return None

    return requested


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
