"""Retained inactive generations must be exact approved bytes, not hidden drift."""
import argparse
import copy
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import k408_negative as target


class RetainedGenerationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)/'home'
        self.kit = Path(self.temp.name)/'kit'
        (self.kit/'release').mkdir(parents=True)
        (self.kit/'release/axiom-cli').write_bytes(b'approved cli')
        (self.kit/'release/axiom-graphd').write_bytes(b'approved daemon')
        self.state = {'engine_generations':['0.1.0'],
                      'cli_generations':['0.1.0-home-derived'], 'active':'same A'}
        self.args = argparse.Namespace(home=self.home,kit=self.kit)

    def invoke(self, mutate):
        def original(_):
            return copy.deepcopy(self.state)
        def negative(_):
            mutate()
            return {'snapshot':target.previous.snapshot(self.home)}
        with patch.object(target.previous,'snapshot',original), patch.object(target.previous,'run',negative):
            return target.run(self.args)

    def add_candidate(self, body):
        self.state['cli_generations'].append('0.1.1-different-home-digest')
        path=self.home/'.local/share/axiom-cli/generations/0.1.1-different-home-digest/axiom-cli'
        path.parent.mkdir(parents=True);path.write_bytes(body)

    def test_actual_home_derived_generation_is_supported(self):
        r=self.invoke(lambda:self.add_candidate(b'approved cli'))
        self.assertTrue(r['inactive_candidate_verified'])
        self.assertEqual(r['snapshot']['active'],'same A')

    def test_retained_changed_bytes_are_rejected(self):
        with self.assertRaises(AssertionError):
            self.invoke(lambda:self.add_candidate(b'unapproved'))

    def test_unknown_generation_is_rejected(self):
        with self.assertRaises(AssertionError):
            self.invoke(lambda:self.state['engine_generations'].append('99.0.0'))


if __name__ == '__main__':
    unittest.main()
