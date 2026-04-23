#!/bin/bash
# Run BitBang E2E tests against test.bitba.ng
#
# Usage:
#   ./run_tests.sh                  # run all tests
#   ./run_tests.sh test_page_load   # run a specific test file
#   ./run_tests.sh -k "test_post"   # run tests matching a pattern

set -e

cd "$(dirname "$0")"

export BITBANG_TEST_SERVER="${BITBANG_TEST_SERVER:-test.bitba.ng}"

# Create screenshots dir
mkdir -p tests/screenshots

if [ $# -eq 0 ]; then
    python3 -m pytest tests/ -v --screenshot=only-on-failure --output=tests/screenshots "$@"
elif [[ "$1" == -* ]]; then
    python3 -m pytest tests/ -v --screenshot=only-on-failure --output=tests/screenshots "$@"
else
    python3 -m pytest "tests/test_${1}.py" -v --screenshot=only-on-failure --output=tests/screenshots "${@:2}"
fi
