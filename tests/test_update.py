"""Update-notice logic. Mirrors cmd/bitbang/update_test.go in the CLI --
the two clients read the same table and must agree on what it means."""

import pytest

from bitbang.update import is_newer, update_notice


@pytest.mark.parametrize("latest,current,want,why", [
    ("0.1.56", "0.1.55", True,  "patch bump"),
    ("0.2.0",  "0.1.55", True,  "minor bump"),
    ("1.0.0",  "0.9.9",  True,  "major bump"),
    ("0.1.55", "0.1.55", False, "same version"),
    ("0.1.54", "0.1.55", False, "server behind us"),
    ("0.1.10", "0.1.9",  True,  "numeric, not lexical -- 10 > 9"),
    ("0.10.0", "0.9.0",  True,  "numeric minor"),
    ("v0.1.56", "0.1.55", True, "leading v tolerated"),
    ("0.1.56", "v0.1.55", True, "leading v on ours too"),
    ("0.2",    "0.1.55", True,  "missing patch reads as zero"),

    # The case that decides whether a dev checkout nags forever.
    ("0.2.0", "0.2.0-dev", True,  "released beats our pre-release of it"),
    ("0.1.55", "0.2.0-dev", False, "our dev build is ahead of the last release"),
    ("0.2.0-rc1", "0.2.0-dev", False, "no notice between two pre-releases"),

    ("", "0.1.55", False, "nothing reported"),
    (None, "0.1.55", False, "missing entirely"),
    ("garbage", "0.1.55", False, "unparseable remote stays quiet"),
    ("0.1.56", "garbage", False, "unparseable local stays quiet"),
    ("0.1.56.1", "0.1.55", False, "four components is not a version we know"),
])
def test_is_newer(latest, current, want, why):
    assert is_newer(latest, current) is want, why


def test_notice_names_both_versions():
    got = update_notice({"python": "0.1.56"}, "0.1.55", "python")
    assert "0.1.56" in got and "0.1.55" in got


def test_notice_appends_the_install_hint():
    got = update_notice({"python": "0.1.56"}, "0.1.55", "python",
                        "pip install --upgrade bitbang")
    assert got.endswith("pip install --upgrade bitbang")


def test_silent_when_current():
    assert update_notice({"python": "0.1.55"}, "0.1.55", "python") is None


# An embedding application reads its own row. A plugin user upgrades the
# plugin, so telling them about the library's release sends them to the
# wrong place -- and the plugin must not go quiet just because the
# library happens to be current.
def test_product_selects_the_row():
    versions = {"python": "0.1.55", "octoprint": "0.3.0"}
    assert update_notice(versions, "0.1.55", "python") is None
    got = update_notice(versions, "0.2.11", "octoprint")
    assert got is not None and "0.3.0" in got and "octoprint" in got


@pytest.mark.parametrize("versions", [
    None, {}, {"cli": "9.9.9"}, "not-a-dict", {"python": 42}, {"python": None},
])
def test_nothing_to_say(versions):
    assert update_notice(versions, "0.1.55", "python") is None
