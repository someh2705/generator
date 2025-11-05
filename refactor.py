import argparse
from generator import ScenarioGenerator
from builder import ScenarioBuilder


def main():
    args = parse()
    generator = ScenarioGenerator(args.meta)
    builder = ScenarioBuilder(generator)
    builder.build()


def parse():
    parser = argparse.ArgumentParser()
    parser.add_argument("meta", help="")
    parser.add_argument("-o", "--out", help="")
    parser.add_argument("--multihop", default=False, action=argparse.BooleanOptionalAction)

    return parser.parse_args()


if __name__ == "__main__":
    main()
