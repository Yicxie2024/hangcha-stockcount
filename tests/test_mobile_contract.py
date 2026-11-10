"""Small dependency-free checks for the mobile/desktop deployment contract.

These do not replace an iPhone/Android test of touch and offline persistence.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class MobileContractTests(unittest.TestCase):
    def test_swipe_draft_ui_and_undo_duration(self):
        html = (ROOT / 'index.html').read_text(encoding='utf-8')
        js = (ROOT / 'app.js').read_text(encoding='utf-8')
        for marker in ('id="draftSwipe"', 'id="draftSwipeMore"', 'id="discardDraftBtn"', 'id="undoDeletion"'):
            self.assertIn(marker, html)
        self.assertIn('const UNDO_DURATION_MS=3000;', js)
        self.assertIn('function initDraftSwipe()', js)
        self.assertIn('function putDraftDurably(snapshot)', js)
        self.assertIn('function discardCurrentDraft()', js)
        self.assertIn('function showDeletionUndo(tombstone)', js)
        self.assertNotIn('6500', js)

    def test_swipe_area_does_not_include_global_page(self):
        js = (ROOT / 'app.js').read_text(encoding='utf-8')
        self.assertIn("const card=$('draftSwipe')", js)
        self.assertIn("e.target.closest('button, input, textarea, select, .location-trail')", js)

    def test_offline_release_version(self):
        self.assertIn('v0.4.4', (ROOT / 'index.html').read_text(encoding='utf-8'))
        self.assertIn('hangcha-stockcount-v0.4.4', (ROOT / 'sw.js').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
