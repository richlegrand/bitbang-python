"""Path-confinement tests for the fileshare app.

These cover the two ways a share can leak beyond its root: a symlink whose
lexical path looks contained, and a hidden entry that is filtered from the
listing but still served when named directly.

Each test fails against the previous implementation, which used
os.path.abspath (no symlink resolution) and applied should_show only to
directory listings.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from bitbang.apps.fileshare.core import (  # noqa: E402
    safe_path,
    safe_visible_path,
    should_show,
    visible_under,
)


@pytest.fixture
def share(tmp_path):
    """A share directory beside an 'outside' directory holding a secret."""
    share_dir = tmp_path / "share"
    outside_dir = tmp_path / "outside"
    share_dir.mkdir()
    outside_dir.mkdir()
    (outside_dir / "secret.txt").write_text("secret")
    # tmp_path itself may sit under a symlink (macOS /var -> /private/var), so
    # resolve here: the tests assert on paths safe_path returns, and those are
    # fully resolved.
    return str(share_dir), str(outside_dir)


def test_rejects_symlinked_file(share):
    share_dir, outside_dir = share
    os.symlink(os.path.join(outside_dir, "secret.txt"),
               os.path.join(share_dir, "link.txt"))
    assert safe_path(share_dir, "link.txt") is None


def test_rejects_symlinked_dir(share):
    share_dir, outside_dir = share
    os.symlink(outside_dir, os.path.join(share_dir, "link"))
    assert safe_path(share_dir, "link/secret.txt") is None
    assert safe_path(share_dir, "link") is None


def test_allows_symlinked_base(tmp_path):
    """A share root that is itself a symlink is legitimate and common.

    Resolving the requested path but not the base rejects every such share,
    which is the standard way this fix ships broken.
    """
    real = tmp_path / "real"
    real.mkdir()
    (real / "ok.txt").write_text("hi")
    link = tmp_path / "link"
    os.symlink(str(real), str(link))

    got = safe_path(str(link), "ok.txt")
    assert got is not None
    assert got.endswith("ok.txt")
    assert safe_path(str(link), "") is not None


def test_still_rejects_traversal(share):
    share_dir, _ = share
    for bad in ("../outside/secret.txt", "..", "a/../../outside/secret.txt"):
        assert safe_path(share_dir, bad) is None, bad


def test_allows_ordinary_file(share):
    share_dir, _ = share
    with open(os.path.join(share_dir, "a.txt"), "w") as f:
        f.write("x")
    assert safe_path(share_dir, "a.txt") is not None


def test_nonexistent_returns_none(share):
    share_dir, _ = share
    assert safe_path(share_dir, "nope.txt") is None


def test_hidden_entries_are_not_readable_by_path(share):
    """Filtering the listing is not a read control unless reads enforce it."""
    share_dir, _ = share
    with open(os.path.join(share_dir, ".env"), "w") as f:
        f.write("SECRET=1")
    git_dir = os.path.join(share_dir, ".git")
    os.mkdir(git_dir)
    with open(os.path.join(git_dir, "config"), "w") as f:
        f.write("[core]")

    for hidden in (".env", ".git/config", ".git"):
        assert safe_visible_path(share_dir, hidden) is None, hidden
        # safe_path alone still resolves them; the policy lives one layer up.
        assert safe_path(share_dir, hidden) is not None, hidden

    with open(os.path.join(share_dir, "visible.txt"), "w") as f:
        f.write("x")
    assert safe_visible_path(share_dir, "visible.txt") is not None


def test_visible_under_walks_every_component(share):
    share_dir, _ = share
    nested = os.path.join(share_dir, ".git", "objects")
    os.makedirs(nested)
    assert not visible_under(share_dir, os.path.join(nested, "abc"))
    assert visible_under(share_dir, os.path.join(share_dir, "plain.txt"))
    assert visible_under(share_dir, share_dir)


def test_should_show_unchanged(share):
    assert should_show("notes.txt")
    assert not should_show(".env")
    assert not should_show(".git")
    assert should_show(".hidden", show_hidden=True)
