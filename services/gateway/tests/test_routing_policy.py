"""The event-routing policy, stated as a table.

Three separate guards decide whether a plan sees an event, and each was added
after a different production failure:

  * unattributed repository traffic reached a plan still being drafted, handed
    Luna a plan with no approved version, and deadlocked it;
  * the fix for that excluded `review`, which silently disabled the review
    loop, so a comment on the plan issue was recorded and then ignored;
  * opening the implementation thread too early announced work that had not
    been approved.

Each was correct about the failure it targeted and wrong about its blast
radius. A point test per bug does not catch that: the risk is a future
narrowing that blocks legitimate traffic somewhere else. So the policy lives
here as data. Narrowing a state set without updating this table fails, and the
failure names the state and the traffic it would have dropped.
"""
import tempfile
import unittest

from coordinator.state import StateStore

REPOSITORY = "https://github.com/t/c.git"

# state -> (reached by unattributed repo traffic, Luna may take a turn,
#           implementation thread may open)
POLICY = {
    # Being drafted. Astra owns these; Luna has nothing to coordinate and no
    # frozen version to read. Unattributed traffic must not land here.
    "intake":          (False, False, False),
    "researching":     (False, False, False),
    "synthesizing":    (False, False, False),
    "research_failed": (False, False, False),
    # Drafted, awaiting approval. The owner comments on the issue here, and
    # routing those comments to Astra is Luna's job — but nothing is approved,
    # so no implementation thread.
    "review":          (False, True,  False),
    # Approved and under execution.
    "accepted":        (True,  True,  True),
    "decomposed":      (True,  True,  True),
    "running":         (True,  True,  True),
    "repairing":       (True,  True,  True),
    "needs_input":     (True,  True,  True),
    "paused":          (True,  True,  True),
    # Finished. No unattributed traffic reaches these and no failing turn may
    # revive them. `failed` is the one exception to being fully inert: the
    # owner's explicit retry has to reach Luna, or Failed -> Running is
    # unreachable and a failed plan is a dead end.
    "completed":       (False, False, False),
    "cancelled":       (False, False, False),
    "failed":          (False, True,  False),
}


class RoutingPolicyTests(unittest.TestCase):
    def _store(self, state: str) -> StateStore:
        store = StateStore(self.tmp.name)
        store.begin_intake("plan-x", "!room:x", "$root", REPOSITORY)
        with store.transaction() as db:
            db.execute("UPDATE plans SET state=? WHERE plan_id='plan-x'", (state,))
        return store

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile()

    def tearDown(self):
        self.tmp.close()

    def test_every_state_has_a_stated_policy(self):
        """No state may be silently unclassified."""
        declared = set(POLICY)
        self.assertTrue(StateStore.IMPLEMENTATION_STATES <= declared)
        self.assertTrue(StateStore.COORDINATED_STATES <= declared)
        self.assertTrue(StateStore.TERMINAL_STATES <= declared)

    def test_unattributed_repository_traffic_reaches_only_the_stated_states(self):
        for state, (reachable, _, _) in POLICY.items():
            with self.subTest(state=state):
                store = self._store(state)
                try:
                    hit = [row["plan_id"] for row
                           in store.active_plans_for_repository("https://github.com/t/c")]
                    self.assertEqual(
                        hit == ["plan-x"], reachable,
                        f"a push with no plan id {'reached' if hit else 'missed'} a plan "
                        f"in {state!r}; POLICY says reachable={reachable}")
                finally:
                    store.close()

    def test_luna_acts_only_on_the_stated_states(self):
        for state, (_, coordinated, _) in POLICY.items():
            with self.subTest(state=state):
                self.assertEqual(
                    state in StateStore.COORDINATED_STATES, coordinated,
                    f"Luna would {'act on' if coordinated else 'skip'} {state!r} "
                    f"per POLICY; COORDINATED_STATES disagrees")

    def test_implementation_thread_opens_only_on_the_stated_states(self):
        for state, (_, _, opens) in POLICY.items():
            with self.subTest(state=state):
                self.assertEqual(
                    state in StateStore.IMPLEMENTATION_STATES, opens,
                    f"the implementation thread would {'open' if opens else 'stay shut'} "
                    f"in {state!r} per POLICY; IMPLEMENTATION_STATES disagrees")

    def test_no_terminal_plan_is_reachable_by_unattributed_traffic(self):
        """A stray push must never revive a finished plan, however it ended."""
        for state in StateStore.TERMINAL_STATES:
            with self.subTest(state=state):
                reachable, _, opens = POLICY[state]
                self.assertFalse(reachable or opens)

    def test_only_failed_among_terminal_states_accepts_an_explicit_retry(self):
        """A failed plan must not become a dead end.

        The owner's retry reaction enqueues owner.retry for Luna. If `failed`
        is not coordinated, Luna skips it and the documented Failed -> Running
        transition cannot happen. Completed and cancelled stay fully inert.
        """
        self.assertIn("failed", StateStore.COORDINATED_STATES)
        for state in ("completed", "cancelled"):
            with self.subTest(state=state):
                self.assertNotIn(state, StateStore.COORDINATED_STATES)

    def test_a_failed_plan_keeps_its_pin(self):
        """Pinning is the mitigation for a flat room; failure must not undo it.

        The conversation has no threads, so the pin is how an open plan stays
        findable. A failed plan still wants an explicit retry, so releasing its
        pin loses it in the stream at the one moment it needs attention.
        Completed and cancelled are genuinely done and do release it.
        """
        for state, should_unpin in (("failed", False),
                                    ("completed", True), ("cancelled", True)):
            with self.subTest(state=state):
                store = self._store("running")
                try:
                    store.complete_matrix("plan:plan-x:card", "$card")
                    store.complete_matrix("plan:plan-x:pin", "$card")
                    store.set_plan_state("plan-x", state)
                    unpins = [row for row in store.pending_matrix(50)
                              if row["kind"] == "unpin"]
                    self.assertEqual(bool(unpins), should_unpin)
                finally:
                    store.close()

    def test_the_terminal_vocabulary_matches_what_completion_writes(self):
        """finish_merge writes 'completed'; the constant must agree.

        While TERMINAL_STATES said 'complete', a finished plan was not
        terminal: its card was never unpinned, completion never pinged, and a
        failing turn could drag it back into needs_input.
        """
        store = self._store("review")
        try:
            with store.transaction() as db:
                db.execute("UPDATE plans SET state='completed' WHERE plan_id='plan-x'")
            self.assertIn(store.plan("plan-x")["state"], StateStore.TERMINAL_STATES)
            self.assertEqual(store.active_plan_for_room("!room:x"), None)
        finally:
            store.close()
