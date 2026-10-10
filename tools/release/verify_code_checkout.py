"""Validate the exact staged source tree, with no local materials copied."""
import argparse
import json
from stage_code import ROOT, audit, git
from check_source import immutable_migrations, validate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-build', action='store_true', help='Python/sync checks only')
    args = parser.parse_args()
    audit(':')
    tree = git('write-tree').decode().strip()
    immutable_migrations('HEAD', tree)
    report = validate(tree, build=not args.no_build)
    pointer = ROOT/'.research/code-release-check/verified-tree.json'
    pointer.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(passed=report['passed'], source_tree=tree,
                         checks=len(report['checks']), receipt=str(pointer)), ensure_ascii=False))


if __name__ == '__main__':
    main()
