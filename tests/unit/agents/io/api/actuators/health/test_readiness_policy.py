"""Which degraded agents take the pod out of service rotation (C3).

The table in ``ReadinessPolicy`` is the whole of this: three policies, and one rule -- the root
gates under all of them -- that keeps a single-agent application behaving exactly as it did
before the key existed.
"""

import pytest

from blueprint.agents.io.api.actuators.health.readiness_policy import CONFIG_KEY, ReadinessPolicy


class TestParse:
    @pytest.mark.parametrize("value", ["all", "critical", "any", "ALL", " Critical "])
    def test_a_named_policy_is_returned(self, value: str) -> None:
        assert ReadinessPolicy.parse(value) == value.strip().lower()

    @pytest.mark.parametrize("value", ["critcal", "none", "", None, 3])
    def test_anything_else_raises_rather_than_defaulting(self, value: object) -> None:
        """A misspelt policy silently read as 'all' would remove a whole group from rotation."""
        with pytest.raises(ValueError, match=CONFIG_KEY):
            ReadinessPolicy.parse(value)

    def test_the_message_names_the_three_that_exist(self) -> None:
        with pytest.raises(ValueError) as exc:
            ReadinessPolicy.parse("critcal")
        for policy in ("all", "critical", "any"):
            assert policy in str(exc.value)


class TestASingleAgentApplication:
    """The root is the whole application, so every policy has to agree about it."""

    @pytest.mark.parametrize("policy", list(ReadinessPolicy))
    def test_a_healthy_root_is_ready_under_every_policy(self, policy: ReadinessPolicy) -> None:
        assert policy.is_ready({"": True}, set()) is True

    @pytest.mark.parametrize("policy", list(ReadinessPolicy))
    def test_a_degraded_root_is_never_ready(self, policy: ReadinessPolicy) -> None:
        """The root holds the shared infrastructure; its failure is not a partial one."""
        assert policy.is_ready({"": False}, {"orders"}) is False


class TestAGroup:
    def test_all_refuses_readiness_for_any_degraded_agent(self) -> None:
        assert ReadinessPolicy.ALL.is_ready({"": True, "orders": True, "billing": False}, set()) is False

    def test_all_is_ready_when_every_agent_is_up(self) -> None:
        assert ReadinessPolicy.ALL.is_ready({"": True, "orders": True, "billing": True}, set()) is True

    def test_critical_ignores_an_agent_the_deployment_can_run_without(self) -> None:
        assert ReadinessPolicy.CRITICAL.is_ready({"": True, "orders": True, "billing": False}, {"orders"}) is True

    def test_critical_refuses_readiness_for_a_flagged_agent(self) -> None:
        assert ReadinessPolicy.CRITICAL.is_ready({"": True, "orders": False, "billing": True}, {"orders"}) is False

    def test_critical_with_nothing_flagged_is_ready_whatever_fails(self) -> None:
        """A deployment that flagged nothing said no agent is worth removing the pod for."""
        assert ReadinessPolicy.CRITICAL.is_ready({"": True, "orders": False}, set()) is True

    def test_any_is_ready_while_one_agent_is_up(self) -> None:
        assert ReadinessPolicy.ANY.is_ready({"": True, "orders": False, "billing": True}, set()) is True

    def test_any_refuses_readiness_when_every_agent_is_down(self) -> None:
        assert ReadinessPolicy.ANY.is_ready({"": True, "orders": False, "billing": False}, set()) is False
