def greet(name: str) -> str:
    return f"Hello, {name}!"


def main():
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("name", nargs="?", default="World")
    args = p.parse_args()
    print(greet(args.name))


if __name__ == "__main__":
    main()
