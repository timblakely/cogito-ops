import unittest

from coordinator.policy import Risk, classify, within_budget


class PolicyTests(unittest.TestCase):
    def test_docs_are_low_risk(self):
        self.assertEqual(classify(["README.md"]).risk, Risk.LOW)

    def test_workload_requires_approval(self):
        decision = classify(["kubernetes/apps/tools/app.yaml"])
        self.assertEqual(decision.risk, Risk.WORKLOAD)
        self.assertTrue(decision.merge_requires_approval)

    def test_secrets_are_high_risk(self):
        self.assertEqual(classify(["config/client-secret.yaml"]).risk, Risk.HIGH)

    def test_every_budget_dimension_is_enforced(self):
        limits = {"attempts": 2, "wall_seconds": 30, "token_budget": 100}
        self.assertTrue(within_budget(2, 30, 100, limits))
        self.assertFalse(within_budget(3, 1, 1, limits))


if __name__ == "__main__":
    unittest.main()
