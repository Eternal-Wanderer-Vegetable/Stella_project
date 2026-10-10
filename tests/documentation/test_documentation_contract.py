"""Standalone stdlib tests for documentation gates; no Bot or production data."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.check_docs import anchors, check, links


class DocumentationContractTests(unittest.TestCase):
    def test_code_examples_are_not_links_or_headings(self):
        text = '# Real\n```md\n# Fake\n[example](missing.md)\n```\n`[inline](missing.md)`\n'
        self.assertEqual(anchors(text), {'real'})
        self.assertEqual(links(text), [])

    def test_balanced_urls_titles_and_reference_definitions(self):
        text = '[a](<chapter (1).md> "label")\n[b](chapter(2).md)\n[x]: page.md "title"\n'
        self.assertEqual([target for _, target in links(text)],
                         ['chapter (1).md', 'chapter(2).md', 'page.md'])

    def test_repeated_headings_and_explicit_legacy_anchor(self):
        text = '# Title\n## 配置 `API`\n## 配置 `API`\n<a id="old-anchor"></a>\n'
        self.assertEqual(anchors(text), {'title', '配置-api', '配置-api-1', 'old-anchor'})

    def make_repo(self, root: Path):
        (root / 'docs/architecture').mkdir(parents=True)
        (root / 'AGENTS.md').write_text('# Agent\n[page](docs/architecture/page.md#topic)\n', encoding='utf-8')
        (root / 'docs/architecture/page.md').write_text('# Topic\n', encoding='utf-8')
        (root / 'docs/architecture/page.en.md').write_text('# Topic\n', encoding='utf-8')
        (root / 'docs/old.md').write_text('# Old\n<a id="old"></a>\n[page](architecture/page.md#topic)\n', encoding='utf-8')
        mapping = {'redirects': {'docs/old.md': 'docs/architecture/page.md'},
                   'anchors': {'docs/old.md': {'old': {'path': 'docs/architecture/page.md', 'fragment': 'topic'}}}}
        (root / 'docs/documentation-map.json').write_text(json.dumps(mapping), encoding='utf-8')
        state = {'active_feature': None, 'features': [{'id': 'D1', 'status': 'done',
                  'done_criteria': ['links work'], 'evidence': ['verified'], 'dependencies': []}]}
        (root / 'feature_list.json').write_text(json.dumps(state), encoding='utf-8')
        for name in ['progress.md', 'session-handoff.md']:
            (root / name).write_text('# State\n', encoding='utf-8')

    def test_valid_repository_and_history_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.make_repo(root)
            (root / 'docs/reports').mkdir()
            (root / 'docs/reports/old.md').write_text('[historical](missing.md)', encoding='utf-8')
            problems, counts = check(root)
            self.assertEqual(problems, [])
            self.assertEqual(counts['migration_anchors'], 1)

    def test_missing_target_anchor_pair_and_legacy_anchor_fail(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.make_repo(root)
            (root / 'docs/architecture/page.en.md').unlink()
            (root / 'docs/architecture/page.md').write_text('# Renamed\n[bad](missing.md)\n', encoding='utf-8')
            problems, _ = check(root)
            for marker in ['missing target', 'missing anchor', 'missing language pair', 'migration anchor missing']:
                self.assertTrue(any(marker in error for error in problems), marker)

    def test_done_without_evidence_and_root_escape_fail(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.make_repo(root)
            state_path = root / 'feature_list.json'
            state = json.loads(state_path.read_text(encoding='utf-8'))
            state['features'][0]['evidence'] = []
            state['features'][0]['dependencies'] = ['missing']
            state_path.write_text(json.dumps(state), encoding='utf-8')
            (root / 'AGENTS.md').write_text('[escape](../outside.md)\n', encoding='utf-8')
            problems, _ = check(root)
            for marker in ['done without evidence', 'invalid dependency', 'escapes repository']:
                self.assertTrue(any(marker in error for error in problems), marker)


if __name__ == '__main__':
    unittest.main()
