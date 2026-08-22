"""Update notices, driven by what the signaling server reports.

The server states the newest release of every BitBang client project in
its reply to a registration we were already making. We look up our own
row and compare locally.

Nothing is sent to obtain this. Not a version, not a product name, not
an extra request -- the table is identical for every device, so what we
receive implies nothing about what we are. That is the whole reason the
lookup happens here rather than the server tailoring an answer, and the
reason no client polls GitHub for itself: doing so would tell a third
party that this machine runs BitBang, on a schedule, forever.
"""

_PRERELEASE_MARKS = "-+"


def _parse(version):
    """Return (major, minor, patch) or None if it isn't a version we know.

    Tolerates a leading "v" and ignores any -suffix or +build. Missing
    components read as zero, so "0.2" parses as (0, 2, 0).
    """
    if not version:
        return None
    s = str(version).strip().lstrip("v")
    for mark in _PRERELEASE_MARKS:
        i = s.find(mark)
        if i >= 0:
            s = s[:i]
    if not s:
        return None
    parts = s.split(".")
    if len(parts) > 3:
        return None
    out = [0, 0, 0]
    for i, p in enumerate(parts):
        if not p.isdigit():
            return None
        out[i] = int(p)
    return tuple(out)


def _is_prerelease(version):
    s = str(version).strip().lstrip("v")
    return any(mark in s for mark in _PRERELEASE_MARKS)


def is_newer(latest, current):
    """Whether `latest` is a strictly greater release than `current`.

    A pre-release suffix is ignored for the numeric comparison and then
    broken in the local build's favor: a 0.2.0.dev build of 0.2.0 is
    ahead of released 0.2.0, not behind it, so a development checkout is
    never told to upgrade into what it already contains. Anything
    unparseable on either side returns False -- staying quiet beats a
    wrong notice.
    """
    l, c = _parse(latest), _parse(current)
    if l is None or c is None:
        return False
    if l != c:
        return l > c
    # Equal numbers: a local pre-release is behind the same released
    # version, while a plain equal version has nothing to offer.
    return _is_prerelease(current) and not _is_prerelease(latest)


def update_notice(versions, current, product, install_hint=None):
    """The line to print when a newer release exists, else None.

    `product` is the row to read: "python" for the library itself, and
    something else for an application embedding it, since a user of the
    OctoPrint plugin upgrades the plugin rather than this package.
    """
    if not versions or not isinstance(versions, dict):
        return None
    latest = versions.get(product)
    if not isinstance(latest, str) or not is_newer(latest, current):
        return None
    line = f"A newer {product} release is available: {latest} (this is {current})"
    return f"{line}  {install_hint}" if install_hint else line
