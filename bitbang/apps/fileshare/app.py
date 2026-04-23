"""BitBang File Sharing App - Share files or folders.

Share a file or folder from your computer to anyone with a browser.
No account, no upload wait, no file size limits.

Usage:
    python app.py /path/to/file      # Share single file
    python app.py /path/to/folder    # Share folder (browse mode)
    python app.py .                  # Share current directory
"""

import os
import sys
import mimetypes

from flask import Flask, send_file, request, jsonify, abort, render_template
from bitbang import BitBangWSGI
try:
    from .core import format_size, get_file_icon, safe_path, should_show
except ImportError:
    from core import format_size, get_file_icon, safe_path, should_show

app = Flask(__name__, template_folder="templates")

# Configuration (set from CLI)
BASE_PATH = None  # File or directory path
FILE_MODE = False  # True if sharing single file
FILE_NAME = None   # Display name for single file mode
UPLOAD_ENABLED = False


@app.route('/favicon.ico')
def favicon():
    return send_file('static/favicon.png', mimetype='image/png')


@app.route('/')
def index():
    """Serve the appropriate UI based on mode."""
    if FILE_MODE:
        # Single file mode - show download page
        filename = FILE_NAME or os.path.basename(BASE_PATH)
        size = format_size(os.path.getsize(BASE_PATH))
        icon = get_file_icon(filename)
        return render_template('send.html', filename=filename, size=size, icon=icon)
    else:
        # Directory mode - show file browser
        return render_template('browse.html')


@app.route('/api/list')
def list_files():
    """List directory contents (browse mode only).

    Query params:
        path: Relative path within shared directory (default: root)

    Returns:
        JSON with path, parent, and entries array
    """
    if FILE_MODE:
        abort(404)
    rel_path = request.args.get('path', '')
    abs_path = safe_path(BASE_PATH, rel_path)

    if abs_path is None:
        abort(403)

    if not os.path.isdir(abs_path):
        abort(400)

    entries = []
    try:
        for name in os.listdir(abs_path):
            if not should_show(name):
                continue

            full_path = os.path.join(abs_path, name)
            try:
                stat = os.stat(full_path)
            except (OSError, PermissionError):
                continue

            entry = {
                'name': name,
                'modified': stat.st_mtime,
            }

            if os.path.isdir(full_path):
                entry['type'] = 'directory'
            else:
                entry['type'] = 'file'
                entry['size'] = stat.st_size
                entry['mime'] = mimetypes.guess_type(name)[0]

            entries.append(entry)
    except PermissionError:
        abort(403)

    # Sort: directories first, then by name (case-insensitive)
    entries.sort(key=lambda e: (e['type'] != 'directory', e['name'].lower()))

    return jsonify({
        'path': rel_path or '/',
        'parent': os.path.dirname(rel_path) if rel_path else None,
        'entries': entries
    })


@app.route('/download')
def download_single():
    """Download the shared file (single file mode)."""
    if not FILE_MODE:
        abort(404)
    filename = FILE_NAME or os.path.basename(BASE_PATH)
    return send_file(
        BASE_PATH,
        as_attachment=True,
        download_name=filename
    )


@app.route('/api/download')
def download():
    """Download a file (browse mode).

    Query params:
        path: Relative path to file

    Returns:
        File stream with Content-Disposition: attachment
    """
    if FILE_MODE:
        abort(404)
    rel_path = request.args.get('path', '')
    abs_path = safe_path(BASE_PATH, rel_path)

    if abs_path is None or not os.path.isfile(abs_path):
        abort(404)

    return send_file(
        abs_path,
        as_attachment=True,
        download_name=os.path.basename(abs_path)
    )


@app.route('/api/preview')
def preview():
    """Preview a file inline (browse mode only).

    Query params:
        path: Relative path to file

    Returns:
        File stream with appropriate MIME type (inline display)
    """
    if FILE_MODE:
        abort(404)
    rel_path = request.args.get('path', '')
    abs_path = safe_path(BASE_PATH, rel_path)

    if abs_path is None or not os.path.isfile(abs_path):
        abort(404)

    mime = mimetypes.guess_type(abs_path)[0] or 'application/octet-stream'

    return send_file(abs_path, mimetype=mime)


@app.route('/api/upload', methods=['POST'])
def upload():
    """Upload a file (browse mode only).

    Form data:
        file: The file to upload
        path: Target directory (relative path)

    Returns:
        JSON with success status and filename
    """
    if FILE_MODE:
        abort(404)

    if 'file' not in request.files:
        abort(400, 'No file provided')

    file = request.files['file']
    if file.filename == '':
        abort(400, 'No file selected')

    # Validate target directory
    rel_path = request.form.get('path', '')
    if rel_path:
        target_dir = safe_path(BASE_PATH, rel_path)
    else:
        target_dir = BASE_PATH

    if target_dir is None or not os.path.isdir(target_dir):
        abort(403, 'Invalid target directory')

    # Sanitize filename - keep only the basename to prevent path traversal
    filename = os.path.basename(file.filename)
    if not filename or filename.startswith('.'):
        abort(400, 'Invalid filename')

    # Save the file
    dest_path = os.path.join(target_dir, filename)
    try:
        file.save(dest_path)
    except (OSError, PermissionError) as e:
        abort(500, f'Failed to save file: {e}')

    return jsonify({
        'success': True,
        'filename': filename,
        'size': os.path.getsize(dest_path)
    })


@app.route('/api/info')
def info():
    """Get server info and capabilities.

    Returns:
        JSON with mode, file/folder name, size info
    """
    if FILE_MODE:
        return jsonify({
            'mode': 'send',
            'filename': FILE_NAME or os.path.basename(BASE_PATH),
            'size': os.path.getsize(BASE_PATH)
        })

    # Browse mode - count files
    total_files = 0
    total_size = 0

    try:
        for dirpath, dirnames, filenames in os.walk(BASE_PATH):
            # Filter hidden directories
            dirnames[:] = [d for d in dirnames if should_show(d)]
            for f in filenames:
                if should_show(f):
                    total_files += 1
                    try:
                        total_size += os.path.getsize(os.path.join(dirpath, f))
                    except (OSError, PermissionError):
                        pass
    except (OSError, PermissionError):
        pass

    return jsonify({
        'mode': 'browse',
        'root': os.path.basename(BASE_PATH) or 'Files',
        'upload_enabled': UPLOAD_ENABLED,
        'total_files': total_files,
        'total_size': total_size
    })


def main():
    global BASE_PATH, FILE_MODE, FILE_NAME
    import argparse
    from bitbang.adapter import add_bitbang_args, bitbang_kwargs

    parser = argparse.ArgumentParser(description='Share files via BitBang')
    parser.add_argument('path', help='File or directory to share')
    add_bitbang_args(parser)
    args = parser.parse_args()

    BASE_PATH = os.path.abspath(os.path.expanduser(args.path))

    if not os.path.exists(BASE_PATH):
        print(f"Error: {BASE_PATH} does not exist")
        sys.exit(1)

    if os.path.isfile(BASE_PATH):
        FILE_MODE = True
        FILE_NAME = os.path.basename(BASE_PATH)
        print(f"Sharing file: {FILE_NAME} ({format_size(os.path.getsize(BASE_PATH))})")
    else:
        FILE_MODE = False
        print(f"Sharing directory: {BASE_PATH}")

    adapter = BitBangWSGI(app, **bitbang_kwargs(args, program_name='fileshare'))
    adapter.run()


if __name__ == '__main__':
    main()
