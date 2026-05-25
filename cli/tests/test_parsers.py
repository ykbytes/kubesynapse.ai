"""Tests for agentctl.commands._parsers — payload normalization and resource resolution."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from agentctl.commands._parsers import (
    coerce_agent_payload,
    coerce_policy_payload,
    coerce_workflow_payload,
    resolve_resource_name,
    resolve_namespace,
    normalize_workflow_steps,
    normalize_list_of_strings,
    normalize_sidecars,
    normalize_a2a_config_value,
    normalize_agent_skills_value,
    normalize_opencode_config_files_value,
)


class TestCoerceAgentPayload:
    def test_crd_style_minimal(self) -> None:
        doc = {
            "kind": "AIAgent",
            "metadata": {"name": "my-agent", "namespace": "test-ns"},
            "spec": {
                "model": "gpt-4",
                "runtime": {"kind": "opencode"},
            },
        }
        payload, inferred_name = coerce_agent_payload(doc, for_update=False)
        assert payload["name"] == "my-agent"
        assert payload["model"] == "gpt-4"
        assert payload["runtime_kind"] == "opencode"
        assert payload["storage_size"] == "1Gi"
        assert inferred_name == "my-agent"

    def test_crd_style_for_update_excludes_name(self) -> None:
        doc = {
            "kind": "AIAgent",
            "metadata": {"name": "my-agent"},
            "spec": {
                "model": "gpt-4",
                "runtime": {"kind": "opencode"},
            },
        }
        payload, inferred_name = coerce_agent_payload(doc, for_update=True)
        assert "name" not in payload
        assert payload["model"] == "gpt-4"

    def test_crd_style_full(self) -> None:
        doc = {
            "kind": "AIAgent",
            "metadata": {"name": "full-agent"},
            "spec": {
                "model": "claude-3",
                "systemPrompt": "You are a helpful agent.",
                "policyRef": "my-policy",
                "storage": {"size": "5Gi"},
                "runtime": {"kind": "opencode", "opencode": {"configFiles": {"config.md": "content"}}},
                "enableGVisor": True,
                "mcpServers": ["filesystem"],
                "mcpSidecars": [{"image": "mcp-server"}],
                "a2a": {"allowedCallers": [{"name": "other-agent", "namespace": "other-ns"}]},
                "skills": {"files": {"helper.md": "help text"}},
            },
        }
        payload, inferred_name = coerce_agent_payload(doc, for_update=False)
        assert payload["model"] == "claude-3"
        assert payload["system_prompt"] == "You are a helpful agent."
        assert payload["policy_ref"] == "my-policy"
        assert payload["storage_size"] == "5Gi"
        assert payload["enable_gvisor"] is True
        assert payload["mcp_servers"] == ["filesystem"]
        assert len(payload["mcp_sidecars"]) == 1
        assert payload["a2a_config"]["allowed_callers"][0]["name"] == "other-agent"
        assert payload["skills"]["files"]["helper.md"] == "help text"
        assert payload["opencode_config_files"]["config.md"] == "content"

    def test_flat_format(self) -> None:
        doc = {
            "name": "flat-agent",
            "model": "gpt-4",
            "system_prompt": "Be good.",
            "runtime_kind": "pi",
        }
        payload, inferred_name = coerce_agent_payload(doc, for_update=False)
        assert payload["name"] == "flat-agent"
        assert payload["model"] == "gpt-4"
        assert payload["runtime_kind"] == "pi"
        assert inferred_name == "flat-agent"

    def test_flat_format_camel_case(self) -> None:
        doc = {
            "name": "camel-agent",
            "model": "gpt-4",
            "systemPrompt": "Be good.",
            "runtimeKind": "opencode",
        }
        payload, inferred_name = coerce_agent_payload(doc, for_update=False)
        assert payload["name"] == "camel-agent"
        assert payload["system_prompt"] == "Be good."

    def test_unsupported_runtime_kind_raises(self) -> None:
        doc = {
            "kind": "AIAgent",
            "metadata": {"name": "bad"},
            "spec": {"model": "x", "runtime": {"kind": "invalid-runtime"}},
        }
        with pytest.raises(SystemExit):
            coerce_agent_payload(doc, for_update=False)


class TestCoerceWorkflowPayload:
    def test_crd_style_minimal(self) -> None:
        doc = {
            "kind": "AgentWorkflow",
            "metadata": {"name": "my-workflow"},
            "spec": {
                "description": "Test workflow",
                "input": "Do the thing",
                "messageBus": "nats",
                "steps": [
                    {"name": "step1", "agentRef": "agent-a", "prompt": "Do A"},
                ],
            },
        }
        payload, inferred_name = coerce_workflow_payload(doc, for_update=False)
        assert payload["name"] == "my-workflow"
        assert payload["description"] == "Test workflow"
        assert payload["input"] == "Do the thing"
        assert payload["message_bus"] == "nats"
        assert len(payload["steps"]) == 1
        assert payload["steps"][0]["agent_ref"] == "agent-a"
        assert inferred_name == "my-workflow"

    def test_crd_style_for_update_excludes_name(self) -> None:
        doc = {
            "kind": "AgentWorkflow",
            "metadata": {"name": "wf"},
            "spec": {"steps": [{"name": "s1", "agentRef": "a", "prompt": "p"}]},
        }
        payload, inferred_name = coerce_workflow_payload(doc, for_update=True)
        assert "name" not in payload

    def test_flat_format(self) -> None:
        doc = {
            "name": "flat-wf",
            "description": "Flat workflow",
            "steps": [{"name": "s1", "agent_ref": "a", "prompt": "p"}],
        }
        payload, inferred_name = coerce_workflow_payload(doc, for_update=False)
        assert payload["name"] == "flat-wf"
        assert len(payload["steps"]) == 1


class TestCoercePolicyPayload:
    def test_crd_style_policy(self) -> None:
        doc = {
            "kind": "AgentPolicy",
            "metadata": {"name": "strict"},
            "spec": {
                "inputGuardrails": {"blockPromptInjection": True},
                "outputGuardrails": {"maskPII": True},
                "allowedModels": ["github-copilot/gpt-5-mini"],
                "allowedMcpServers": ["context7"],
                "mcpRequireHitl": False,
            },
        }
        payload, inferred_name = coerce_policy_payload(doc, for_update=False)
        assert payload["name"] == "strict"
        assert payload["input_guardrails"]["blockPromptInjection"] is True
        assert payload["output_guardrails"]["maskPII"] is True
        assert payload["allowed_models"] == ["github-copilot/gpt-5-mini"]
        assert payload["allowed_mcp_servers"] == ["context7"]
        assert payload["mcp_require_hitl"] is False
        assert inferred_name == "strict"

    def test_flat_policy_for_update_excludes_name(self) -> None:
        doc = {
            "name": "strict",
            "allowed_models": ["github-copilot/gpt-5-mini"],
            "mcp_require_hitl": True,
        }
        payload, inferred_name = coerce_policy_payload(doc, for_update=True)
        assert "name" not in payload
        assert payload["allowed_models"] == ["github-copilot/gpt-5-mini"]
        assert payload["mcp_require_hitl"] is True
        assert inferred_name == "strict"


class TestResolveResourceName:
    def test_explicit_name_wins(self) -> None:
        assert resolve_resource_name("explicit", None, "inferred", "agent") == "explicit"

    def test_inferred_name_used_when_no_explicit(self) -> None:
        assert resolve_resource_name(None, None, "inferred", "agent") == "inferred"

    def test_raises_when_no_name_available(self) -> None:
        with pytest.raises(SystemExit):
            resolve_resource_name(None, None, None, "agent")

    def test_raises_with_file_hint(self) -> None:
        with pytest.raises(SystemExit):
            resolve_resource_name(None, Path("/tmp/test.yaml"), None, "agent")


class TestResolveNamespace:
    def test_from_metadata(self) -> None:
        doc = {"metadata": {"namespace": "doc-ns"}}
        assert resolve_namespace("default", doc) == "doc-ns"

    def test_fallback_to_default(self) -> None:
        doc = {"model": "gpt-4"}
        assert resolve_namespace("default", doc) == "default"


class TestNormalizeWorkflowSteps:
    def test_basic_steps(self) -> None:
        steps = [
            {"name": "s1", "agentRef": "a", "prompt": "do A", "dependsOn": [], "requireApproval": False},
        ]
        result = normalize_workflow_steps(steps)
        assert result[0]["name"] == "s1"
        assert result[0]["agent_ref"] == "a"
        assert result[0]["prompt"] == "do A"

    def test_depends_on_is_normalized(self) -> None:
        steps = [
            {"name": "s2", "agentRef": "b", "prompt": "do B", "dependsOn": ["s1"], "requireApproval": True},
        ]
        result = normalize_workflow_steps(steps)
        assert result[0]["depends_on"] == ["s1"]
        assert result[0]["require_approval"] is True

    def test_empty_steps(self) -> None:
        assert normalize_workflow_steps(None) == []
        assert normalize_workflow_steps([]) == []

    def test_execution_block_preserved(self) -> None:
        steps = [
            {"name": "s1", "agentRef": "a", "prompt": "p", "execution": {"timeout": 300}},
        ]
        result = normalize_workflow_steps(steps)
        assert result[0]["execution"] == {"timeout": 300}

    def test_execution_none_when_missing(self) -> None:
        steps = [{"name": "s1", "agentRef": "a", "prompt": "p"}]
        result = normalize_workflow_steps(steps)
        assert result[0]["execution"] is None


class TestNormalizeHelpers:
    def test_normalize_list_of_strings(self) -> None:
        assert normalize_list_of_strings(["a", "b"], "test") == ["a", "b"]

    def test_normalize_list_of_strings_skips_empty(self) -> None:
        assert normalize_list_of_strings(["a", "", "b"], "test") == ["a", "b"]

    def test_normalize_list_of_strings_default(self) -> None:
        assert normalize_list_of_strings(None, "test") == []

    def test_normalize_sidecars(self) -> None:
        sidecars = [{"image": "mcp-server:latest"}]
        result = normalize_sidecars(sidecars)
        assert result == [{"image": "mcp-server:latest"}]

    def test_normalize_sidecars_default(self) -> None:
        assert normalize_sidecars(None) == []

    def test_normalize_a2a_config(self) -> None:
        value = {"allowedCallers": [{"name": "agent-b", "namespace": "ns-b"}]}
        result = normalize_a2a_config_value(value, "a2a_config")
        assert result["allowed_callers"][0]["name"] == "agent-b"

    def test_normalize_a2a_config_snake_case(self) -> None:
        value = {"allowed_callers": [{"name": "agent-b", "namespace": "ns-b"}]}
        result = normalize_a2a_config_value(value, "a2a_config")
        assert result["allowed_callers"][0]["name"] == "agent-b"

    def test_normalize_a2a_config_dedup(self) -> None:
        value = {
            "allowedCallers": [
                {"name": "agent-b", "namespace": "ns-b"},
                {"name": "agent-b", "namespace": "ns-b"},
            ]
        }
        result = normalize_a2a_config_value(value, "a2a_config")
        assert len(result["allowed_callers"]) == 1

    def test_normalize_opencode_config_files(self) -> None:
        value = {"config.md": "content"}
        result = normalize_opencode_config_files_value(value, "opencode_config_files")
        assert result == {"config.md": "content"}

    def test_normalize_opencode_config_files_default(self) -> None:
        assert normalize_opencode_config_files_value(None, "test") == {}

    def test_normalize_skills(self) -> None:
        value = {"files": {"helper.md": "help text"}}
        result = normalize_agent_skills_value(value, "skills")
        assert result["files"]["helper.md"] == "help text"

    def test_normalize_skills_default(self) -> None:
        assert normalize_agent_skills_value(None, "skills") == {}
