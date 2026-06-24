from __future__ import annotations

from routers import workflows


def _workflow_manifest(name: str, agent_refs: list[str]) -> dict:
    return {
        "apiVersion": "kubesynapse.ai/v1alpha1",
        "kind": "AgentWorkflow",
        "metadata": {"name": name, "namespace": "default"},
        "spec": {
            "steps": [
                {"name": f"step-{index}", "type": "agent", "agentRef": agent_ref, "prompt": "Do work."}
                for index, agent_ref in enumerate(agent_refs, start=1)
            ],
        },
    }


def test_delete_workflow_can_clean_exclusive_agents_and_related_triggers(monkeypatch) -> None:
    target = _workflow_manifest("daily-standup-opt-abc", ["standup-git-opt-abc", "shared-agent"])
    other = _workflow_manifest("other-workflow", ["shared-agent"])
    deleted_resources: list[tuple[str, str, str]] = []
    deleted_triggers: list[str] = []

    def fake_read_custom_resource(plural: str, name: str, namespace: str, _label: str) -> dict:
        assert plural == "agentworkflows"
        assert name == "daily-standup-opt-abc"
        assert namespace == "default"
        return target

    def fake_list_custom_resources(plural: str, namespace: str) -> list[dict]:
        assert namespace == "default"
        if plural == "agentworkflows":
            return [target, other]
        return []

    def fake_delete_custom_resource(plural: str, name: str, namespace: str, _label: str) -> None:
        deleted_resources.append((plural, name, namespace))

    monkeypatch.setattr(workflows, "ensure_namespace_access", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(workflows, "read_custom_resource", fake_read_custom_resource)
    monkeypatch.setattr(workflows, "list_custom_resources", fake_list_custom_resources)
    monkeypatch.setattr(workflows, "delete_custom_resource", fake_delete_custom_resource)
    monkeypatch.setattr(
        workflows,
        "list_workflow_triggers",
        lambda _namespace: [
            {
                "name": "candidate-trigger",
                "target_kind": "workflow",
                "workflow_ref": {"name": "daily-standup-opt-abc", "namespace": "default"},
            },
            {
                "name": "other-trigger",
                "target_kind": "workflow",
                "workflow_ref": {"name": "other-workflow", "namespace": "default"},
            },
        ],
    )
    monkeypatch.setattr(workflows, "delete_workflow_trigger", lambda _namespace, name: deleted_triggers.append(name) or True)

    response = workflows.delete_workflow(
        "daily-standup-opt-abc",
        namespace="default",
        delete_related_resources=True,
        user={"username": "admin"},
    )

    assert ("agentworkflows", "daily-standup-opt-abc", "default") in deleted_resources
    assert ("aiagents", "standup-git-opt-abc", "default") in deleted_resources
    assert ("aiagents", "shared-agent", "default") not in deleted_resources
    assert deleted_triggers == ["candidate-trigger"]
    assert response.related == {
        "delete_related_resources": True,
        "deleted_agents": ["standup-git-opt-abc"],
        "skipped_agents": [{"name": "shared-agent", "reason": "referenced by another workflow"}],
        "deleted_triggers": ["candidate-trigger"],
    }

