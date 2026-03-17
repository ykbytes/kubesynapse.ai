.PHONY: all build test test-goose-runtime-e2e lint docker-build docker-push helm-lint helm-package deploy clean ui-install ui-dev ui-build ui-preview docker-build-ui docker-push-ui docker-build-goose-runtime docker-push-goose-runtime docker-build-codex-runtime docker-push-codex-runtime docker-build-opencode-runtime docker-push-opencode-runtime docker-build-mcp-sidecars docker-push-mcp-sidecars docker-build-mcp-code-exec docker-push-mcp-code-exec docker-build-mcp-web-search docker-push-mcp-web-search docker-build-mcp-documents docker-push-mcp-documents docker-build-mcp-browser docker-push-mcp-browser docker-build-mcp-database docker-push-mcp-database docker-build-mcp-git docker-push-mcp-git docker-build-mcp-github-adapter docker-push-mcp-github-adapter docker-build-mcp-kubernetes docker-push-mcp-kubernetes docker-build-mcp-messaging docker-push-mcp-messaging docker-build-mcp-rag docker-push-mcp-rag

CONTAINER_CLI ?= podman
CONTAINER_BUILD_FLAGS ?= --format docker
REGISTRY ?= docker.io/yakdhane
VERSION ?= latest
SKILLS_CATALOG_FILE ?= ./catalog/skills-catalog.json
HELM_SKILLS_CATALOG_ARG := $(if $(wildcard $(SKILLS_CATALOG_FILE)),--set-file skillsCatalog.catalogJson=$(SKILLS_CATALOG_FILE),)

# ===========================
# Build
# ===========================

all: lint test docker-build helm-package

build-cli:
	python -m pip install -e ./cli

ui-install:
	cd web-ui && npm install

ui-dev:
	cd web-ui && npm run dev

ui-build:
	cd web-ui && npm run build

ui-preview:
	cd web-ui && npm run preview

# ===========================
# Container images
# ===========================

docker-build: docker-build-operator docker-build-runtime docker-build-goose-runtime docker-build-codex-runtime docker-build-opencode-runtime docker-build-gateway docker-build-ui docker-build-mcp-sidecars

docker-build-operator:
	$(CONTAINER_CLI) build $(CONTAINER_BUILD_FLAGS) -t $(REGISTRY)/ai-operator:$(VERSION) ./operator

docker-build-runtime:
	$(CONTAINER_CLI) build $(CONTAINER_BUILD_FLAGS) -t $(REGISTRY)/ai-agent-runtime:$(VERSION) ./agent-runtime

docker-build-goose-runtime:
	$(CONTAINER_CLI) build $(CONTAINER_BUILD_FLAGS) -t $(REGISTRY)/ai-goose-runtime:$(VERSION) ./goose-runtime

docker-build-codex-runtime:
	$(CONTAINER_CLI) build $(CONTAINER_BUILD_FLAGS) -t $(REGISTRY)/ai-codex-runtime:$(VERSION) ./codex-runtime

docker-build-opencode-runtime:
	$(CONTAINER_CLI) build $(CONTAINER_BUILD_FLAGS) -t $(REGISTRY)/ai-opencode-runtime:$(VERSION) ./opencode-runtime

docker-build-gateway:
	$(CONTAINER_CLI) build $(CONTAINER_BUILD_FLAGS) -t $(REGISTRY)/ai-api-gateway:$(VERSION) ./api-gateway

docker-build-ui:
	$(CONTAINER_CLI) build $(CONTAINER_BUILD_FLAGS) -t $(REGISTRY)/ai-agent-sandbox-web-ui:$(VERSION) ./web-ui

docker-build-mcp-sidecars: docker-build-mcp-code-exec docker-build-mcp-web-search docker-build-mcp-documents docker-build-mcp-browser docker-build-mcp-database docker-build-mcp-git docker-build-mcp-github-adapter docker-build-mcp-kubernetes docker-build-mcp-messaging docker-build-mcp-rag

docker-build-mcp-code-exec:
	$(CONTAINER_CLI) build $(CONTAINER_BUILD_FLAGS) -f ./mcp-sidecars/code-exec/Dockerfile -t $(REGISTRY)/mcp-code-exec:$(VERSION) ./mcp-sidecars

docker-build-mcp-web-search:
	$(CONTAINER_CLI) build $(CONTAINER_BUILD_FLAGS) -f ./mcp-sidecars/web-search/Dockerfile -t $(REGISTRY)/mcp-web-search:$(VERSION) ./mcp-sidecars

docker-build-mcp-documents:
	$(CONTAINER_CLI) build $(CONTAINER_BUILD_FLAGS) -f ./mcp-sidecars/documents/Dockerfile -t $(REGISTRY)/mcp-documents:$(VERSION) ./mcp-sidecars

docker-build-mcp-browser:
	$(CONTAINER_CLI) build $(CONTAINER_BUILD_FLAGS) -f ./mcp-sidecars/browser/Dockerfile -t $(REGISTRY)/mcp-browser:$(VERSION) ./mcp-sidecars

docker-build-mcp-database:
	$(CONTAINER_CLI) build $(CONTAINER_BUILD_FLAGS) -f ./mcp-sidecars/database/Dockerfile -t $(REGISTRY)/mcp-database:$(VERSION) ./mcp-sidecars

docker-build-mcp-git:
	$(CONTAINER_CLI) build $(CONTAINER_BUILD_FLAGS) -f ./mcp-sidecars/git/Dockerfile -t $(REGISTRY)/mcp-git:$(VERSION) ./mcp-sidecars

docker-build-mcp-github-adapter:
	$(CONTAINER_CLI) build $(CONTAINER_BUILD_FLAGS) -f ./mcp-sidecars/github-adapter/Dockerfile -t $(REGISTRY)/mcp-github-adapter:$(VERSION) ./mcp-sidecars

docker-build-mcp-kubernetes:
	$(CONTAINER_CLI) build $(CONTAINER_BUILD_FLAGS) -f ./mcp-sidecars/kubernetes/Dockerfile -t $(REGISTRY)/mcp-kubernetes:$(VERSION) ./mcp-sidecars

docker-build-mcp-messaging:
	$(CONTAINER_CLI) build $(CONTAINER_BUILD_FLAGS) -f ./mcp-sidecars/messaging/Dockerfile -t $(REGISTRY)/mcp-messaging:$(VERSION) ./mcp-sidecars

docker-build-mcp-rag:
	$(CONTAINER_CLI) build $(CONTAINER_BUILD_FLAGS) -f ./mcp-sidecars/rag/Dockerfile -t $(REGISTRY)/mcp-rag:$(VERSION) ./mcp-sidecars

docker-push: docker-push-operator docker-push-runtime docker-push-goose-runtime docker-push-codex-runtime docker-push-opencode-runtime docker-push-gateway docker-push-ui docker-push-mcp-sidecars

docker-push-operator:
	$(CONTAINER_CLI) push $(REGISTRY)/ai-operator:$(VERSION)

docker-push-runtime:
	$(CONTAINER_CLI) push $(REGISTRY)/ai-agent-runtime:$(VERSION)

docker-push-goose-runtime:
	$(CONTAINER_CLI) push $(REGISTRY)/ai-goose-runtime:$(VERSION)

docker-push-codex-runtime:
	$(CONTAINER_CLI) push $(REGISTRY)/ai-codex-runtime:$(VERSION)

docker-push-opencode-runtime:
	$(CONTAINER_CLI) push $(REGISTRY)/ai-opencode-runtime:$(VERSION)

docker-push-gateway:
	$(CONTAINER_CLI) push $(REGISTRY)/ai-api-gateway:$(VERSION)

docker-push-ui:
	$(CONTAINER_CLI) push $(REGISTRY)/ai-agent-sandbox-web-ui:$(VERSION)

docker-push-mcp-sidecars: docker-push-mcp-code-exec docker-push-mcp-web-search docker-push-mcp-documents docker-push-mcp-browser docker-push-mcp-database docker-push-mcp-git docker-push-mcp-github-adapter docker-push-mcp-kubernetes docker-push-mcp-messaging docker-push-mcp-rag

docker-push-mcp-code-exec:
	$(CONTAINER_CLI) push $(REGISTRY)/mcp-code-exec:$(VERSION)

docker-push-mcp-web-search:
	$(CONTAINER_CLI) push $(REGISTRY)/mcp-web-search:$(VERSION)

docker-push-mcp-documents:
	$(CONTAINER_CLI) push $(REGISTRY)/mcp-documents:$(VERSION)

docker-push-mcp-browser:
	$(CONTAINER_CLI) push $(REGISTRY)/mcp-browser:$(VERSION)

docker-push-mcp-database:
	$(CONTAINER_CLI) push $(REGISTRY)/mcp-database:$(VERSION)

docker-push-mcp-git:
	$(CONTAINER_CLI) push $(REGISTRY)/mcp-git:$(VERSION)

docker-push-mcp-github-adapter:
	$(CONTAINER_CLI) push $(REGISTRY)/mcp-github-adapter:$(VERSION)

docker-push-mcp-kubernetes:
	$(CONTAINER_CLI) push $(REGISTRY)/mcp-kubernetes:$(VERSION)

docker-push-mcp-messaging:
	$(CONTAINER_CLI) push $(REGISTRY)/mcp-messaging:$(VERSION)

docker-push-mcp-rag:
	$(CONTAINER_CLI) push $(REGISTRY)/mcp-rag:$(VERSION)

# ===========================
# Test & Lint
# ===========================

test:
	@if [ -d operator/tests ]; then cd operator && python -m pytest tests/ -v; else echo "No operator tests found"; fi
	@if [ -d agent-runtime/tests ]; then cd agent-runtime && python -m pytest tests/ -v; else echo "No agent-runtime tests found"; fi
	@if [ -d goose-runtime/tests ]; then cd goose-runtime && python -m pytest tests/ -v; else echo "No goose-runtime tests found"; fi
	@if [ -d codex-runtime/tests ]; then cd codex-runtime && python -m pytest tests/ -v; else echo "No codex-runtime tests found"; fi
	@if [ -d opencode-runtime/tests ]; then cd opencode-runtime && python -m pytest tests/ -v; else echo "No opencode-runtime tests found"; fi
	@if [ -d api-gateway/tests ]; then cd api-gateway && python -m pytest tests/ -v; else echo "No api-gateway tests found"; fi
	@if [ -d mcp-sidecars/github-adapter/tests ]; then cd mcp-sidecars/github-adapter && python -m pytest tests/ -v; else echo "No github adapter tests found"; fi

test-goose-runtime-e2e:
	cd goose-runtime && CONTAINER_CLI=$(CONTAINER_CLI) python -m pytest tests/test_container_e2e.py -v

lint:
	cd operator && python -m flake8 . --max-line-length=120
	cd agent-runtime && python -m flake8 . --max-line-length=120
	cd goose-runtime && python -m flake8 . --max-line-length=120
	cd codex-runtime && python -m flake8 . --max-line-length=120
	cd opencode-runtime && python -m flake8 . --max-line-length=120
	cd api-gateway && python -m flake8 . --max-line-length=120

# ===========================
# Helm
# ===========================

helm-lint:
	helm lint ./charts/ai-agent-sandbox

helm-package:
	helm package ./charts/ai-agent-sandbox -d ./dist

helm-template:
	helm template ai-sandbox ./charts/ai-agent-sandbox $(HELM_SKILLS_CATALOG_ARG)

# ===========================
# Deploy (local cluster)
# ===========================

deploy:
	helm upgrade --install ai-agent-sandbox ./charts/ai-agent-sandbox $(HELM_SKILLS_CATALOG_ARG)

deploy-sample:
	kubectl apply -f examples/sample-agent.yaml
	kubectl apply -f examples/sample-tenant.yaml
	kubectl apply -f examples/sample-policy.yaml

undeploy:
	helm uninstall ai-agent-sandbox || true
	kubectl delete crd aiagents.sandbox.enterprise.ai || true
	kubectl delete crd agentpolicies.sandbox.enterprise.ai || true
	kubectl delete crd agentapprovals.sandbox.enterprise.ai || true
	kubectl delete crd agenttenants.sandbox.enterprise.ai || true
	kubectl delete crd agentworkflows.sandbox.enterprise.ai || true
	kubectl delete crd agentevals.sandbox.enterprise.ai || true

# ===========================
# Clean
# ===========================

clean:
	rm -rf bin/ dist/
	$(CONTAINER_CLI) rmi $(REGISTRY)/ai-operator:$(VERSION) || true
	$(CONTAINER_CLI) rmi $(REGISTRY)/ai-agent-runtime:$(VERSION) || true
	$(CONTAINER_CLI) rmi $(REGISTRY)/ai-goose-runtime:$(VERSION) || true
	$(CONTAINER_CLI) rmi $(REGISTRY)/ai-codex-runtime:$(VERSION) || true
	$(CONTAINER_CLI) rmi $(REGISTRY)/ai-api-gateway:$(VERSION) || true
	$(CONTAINER_CLI) rmi $(REGISTRY)/ai-agent-sandbox-web-ui:$(VERSION) || true
	$(CONTAINER_CLI) rmi $(REGISTRY)/mcp-code-exec:$(VERSION) || true
	$(CONTAINER_CLI) rmi $(REGISTRY)/mcp-web-search:$(VERSION) || true
	$(CONTAINER_CLI) rmi $(REGISTRY)/mcp-documents:$(VERSION) || true
	$(CONTAINER_CLI) rmi $(REGISTRY)/mcp-browser:$(VERSION) || true
	$(CONTAINER_CLI) rmi $(REGISTRY)/mcp-database:$(VERSION) || true
	$(CONTAINER_CLI) rmi $(REGISTRY)/mcp-git:$(VERSION) || true
	$(CONTAINER_CLI) rmi $(REGISTRY)/mcp-github-adapter:$(VERSION) || true
	$(CONTAINER_CLI) rmi $(REGISTRY)/mcp-kubernetes:$(VERSION) || true
	$(CONTAINER_CLI) rmi $(REGISTRY)/mcp-messaging:$(VERSION) || true
	$(CONTAINER_CLI) rmi $(REGISTRY)/mcp-rag:$(VERSION) || true
