"""Offline regressions. Does not connect to a PBX."""
import unittest
from pathlib import Path
from qpanel.ami_live import parse_queue_events

ROOT=Path(__file__).resolve().parents[1]

class Beta2RegressionTests(unittest.TestCase):
    def test_hint_state_and_static_membership_kept(self):
        events=[
            {'Event':'QueueParams','Queue':'8001','Calls':'0'},
            {'Event':'QueueMember','Queue':'8001','Location':'Local/100@from-queue/n','StateInterface':'hint:100@ext-local','Membership':'static','Status':'1'},
        ]
        data=parse_queue_events(events)
        member=data['8001']['members']['Local/100@from-queue/n']
        self.assertEqual(member['StateInterface'],'hint:100@ext-local')
        self.assertEqual(member['Membership'],'static')

    # Historical snapshot assertion retained in tests/historical.
    pass

    # Historical snapshot assertion retained in tests/historical.
    pass

    # Historical snapshot assertion retained in tests/historical.
    pass

if __name__=='__main__':unittest.main()
