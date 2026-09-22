#!/usr/bin/env python3
"""Refresh the complete source-file tree in README; --check only validates it."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
START = '<!-- BEGIN REPO TREE -->'
END = '<!-- END REPO TREE -->'


def source_files():
    output = subprocess.check_output(
        ['git', 'ls-files', '-co', '--exclude-standard', '-z'], cwd=ROOT)
    return sorted({name.decode() for name in output.split(b'\0')
                   if name and (ROOT / name.decode()).is_file()})


def render_tree():
    tree = {}
    for name in source_files():
        node = tree
        for part in Path(name).parts:
            node = node.setdefault(part, {})
    lines = ['CUA/']

    def visit(node, prefix=''):
        items = sorted(node.items(), key=lambda item: (not bool(item[1]), item[0]))
        for i, (name, children) in enumerate(items):
            last = i == len(items) - 1
            lines.append(prefix + ('└── ' if last else '├── ') + name
                         + ('/' if children else ''))
            if children:
                visit(children, prefix + ('    ' if last else '│   '))

    visit(tree)
    return '```text\n' + '\n'.join(lines) + '\n```\n'


def main():
    path = ROOT / 'README.md'
    text = path.read_text()
    before, remainder = text.split(START, 1)
    _, after = remainder.split(END, 1)
    updated = before + START + '\n' + render_tree() + END + after
    if '--check' in sys.argv:
        if updated != text:
            print('README tree is stale: run python3 scripts/update_readme_tree.py')
            return 1
        print('README tree matches all current source files.')
        return 0
    path.write_text(updated)
    print(f'Updated README tree: {len(source_files())} source files.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
