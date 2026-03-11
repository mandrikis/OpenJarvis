"""Tests for Agent Manager API routes."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from openjarvis.agents.manager import AgentManager


@pytest.fixture
def manager():
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = AgentManager(db_path=str(Path(tmpdir) / "agents.db"))
        yield mgr
        mgr.close()


try:
    from fastapi.testclient import TestClient

    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False


@pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")
class TestAgentManagerRoutes:
    @pytest.fixture
    def client(self, manager):
        from fastapi import FastAPI

        from openjarvis.server.agent_manager_routes import create_agent_manager_router

        app = FastAPI()
        router = create_agent_manager_router(manager)
        app.include_router(router)
        return TestClient(app)

    def test_list_agents_empty(self, client):
        resp = client.get("/v1/managed-agents")
        assert resp.status_code == 200
        assert resp.json()["agents"] == []

    def test_create_agent(self, client):
        resp = client.post("/v1/managed-agents", json={
            "name": "researcher",
            "agent_type": "monitor_operative",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "researcher"
        assert data["status"] == "idle"

    def test_get_agent(self, client):
        create_resp = client.post("/v1/managed-agents", json={"name": "test"})
        agent_id = create_resp.json()["id"]
        resp = client.get(f"/v1/managed-agents/{agent_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == agent_id

    def test_get_agent_not_found(self, client):
        resp = client.get("/v1/managed-agents/nonexistent")
        assert resp.status_code == 404

    def test_update_agent(self, client):
        create_resp = client.post("/v1/managed-agents", json={"name": "old"})
        agent_id = create_resp.json()["id"]
        resp = client.patch(f"/v1/managed-agents/{agent_id}", json={"name": "new"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "new"

    def test_delete_agent(self, client):
        create_resp = client.post("/v1/managed-agents", json={"name": "doomed"})
        agent_id = create_resp.json()["id"]
        resp = client.delete(f"/v1/managed-agents/{agent_id}")
        assert resp.status_code == 200

    def test_pause_resume(self, client):
        create_resp = client.post("/v1/managed-agents", json={"name": "pausable"})
        agent_id = create_resp.json()["id"]
        client.post(f"/v1/managed-agents/{agent_id}/pause")
        resp = client.get(f"/v1/managed-agents/{agent_id}")
        assert resp.json()["status"] == "paused"
        client.post(f"/v1/managed-agents/{agent_id}/resume")
        resp = client.get(f"/v1/managed-agents/{agent_id}")
        assert resp.json()["status"] == "idle"

    def test_create_task(self, client):
        create_resp = client.post("/v1/managed-agents", json={"name": "worker"})
        agent_id = create_resp.json()["id"]
        resp = client.post(f"/v1/managed-agents/{agent_id}/tasks", json={
            "description": "Find papers on reasoning",
        })
        assert resp.status_code == 200
        assert resp.json()["description"] == "Find papers on reasoning"

    def test_list_tasks(self, client):
        create_resp = client.post("/v1/managed-agents", json={"name": "worker"})
        agent_id = create_resp.json()["id"]
        client.post(f"/v1/managed-agents/{agent_id}/tasks", json={"description": "t1"})
        client.post(f"/v1/managed-agents/{agent_id}/tasks", json={"description": "t2"})
        resp = client.get(f"/v1/managed-agents/{agent_id}/tasks")
        assert len(resp.json()["tasks"]) == 2

    def test_channel_binding_crud(self, client):
        create_resp = client.post("/v1/managed-agents", json={"name": "slacker"})
        agent_id = create_resp.json()["id"]
        # Bind
        bind_resp = client.post(f"/v1/managed-agents/{agent_id}/channels", json={
            "channel_type": "slack",
            "config": {"channel": "#research"},
        })
        assert bind_resp.status_code == 200
        binding_id = bind_resp.json()["id"]
        # List
        list_resp = client.get(f"/v1/managed-agents/{agent_id}/channels")
        assert len(list_resp.json()["bindings"]) == 1
        # Unbind
        url = f"/v1/managed-agents/{agent_id}/channels/{binding_id}"
        unbind_resp = client.delete(url)
        assert unbind_resp.status_code == 200

    def test_templates(self, client):
        resp = client.get("/v1/templates")
        assert resp.status_code == 200
        templates = resp.json()["templates"]
        assert any(t["id"] == "research_monitor" for t in templates)
