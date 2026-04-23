import sys


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m bitbang <command> [args]")
        print("Commands: fileshare, webcam")
        sys.exit(1)

    cmd = sys.argv[1]
    sys.argv = [f"bitbang-{cmd}"] + sys.argv[2:]

    if cmd == "fileshare":
        from bitbang.apps.fileshare.app import main as app_main
        app_main()
    elif cmd == "webcam":
        from bitbang.apps.webcam.app import main as app_main
        app_main()
    else:
        print(f"Unknown command: {cmd}")
        print("Commands: fileshare, webcam")
        sys.exit(1)


if __name__ == "__main__":
    main()
