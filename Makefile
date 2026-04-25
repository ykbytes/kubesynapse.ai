.PHONY: all build test test-services test-integration lint \
	docker-build docker-push helm-lint helm-package deploy deploy-sample undeploy clean \
	deploy-ai-sandbox-kind deploy-ai-sandbox-kind-dry-run \
	ui-install ui-dev ui-build ui-preview \
	docker-build-operator docker-build-opencode-runtime docker-build-gateway \
	docker-build-ui docker-build-mcp-sidecars \
	docker-push-operator docker-push-opencode-runtime docker-push-gateway \
	docker-push-ui docker-push-mcp-sidecars \
	docker-build-mcp-code-exec docker-build-mcp-web-search docker-build-mcp-documents \
	docker-build-mcp-browser docker-build-mcp-database docker-build-mcp-git \
	docker-build-mcp-github-adapter docker-build-mcp-kubernetes docker-build-mcp-messaging \
	docker-build-mcp-rag \
	docker-push-mcp-code-exec docker-push-mcp-web-search docker-push-mcp-documents \
	docker-push-mcp-browser docker-push-mcp-database docker-push-mcp-git \
	docker-push-mcp-github-adapter docker-push-mcp-kubernetes docker-push-mcp-messaging \
	docker-push-mcp-rag \
	compose-up compose-down compose-build compose-logs compose-status \
	k8s-install k8s-upgrade k8s-uninstall k8s-status

CONTAINER_CLI ?= docker
CONTAINER_BUILD_FLAGS ?= --format docker
REGISTRY ?= docker.io/yakdhane
VERSION ?= latest
SKILLS_CATALOG_FILE ?= ./catalog/skills-catalog.json
HELM_SKILLS_CATALOG_ARG := $(if $(wildcard $(SKILLS_CATALOG_FILE)),--set-file skillsCatalog.catalogJson=$(SKILLS_CATALOG_FILE),)
AI_SANDBOX_RELEASE ?= ai-sandbox
AI_SANDBOX_NAMESPACE ?= ai-agent-sandbox
AI_SANDBOX_KIND_VALUES_FILE ?= ./deploy/values.ai-sandbox.kind-local.yaml
AI_SANDBOX_KIND_EXTRA_VALUES_FILES ?=
AI_SANDBOX_KIND_EXTRA_VALUES_ARGS := $(foreach file,$(AI_SANDBOX_KIND_EXTRA_VALUES_FILES),-f $(file))

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

docker-build: docker-build-operator docker-build-opencode-runtime docker-build-gateway docker-build-ui docker-build-mcp-sidecars

docker-build-operator:
	$(CONTAINER_CLI) build $(CONTAINER_BUILD_FLAGS) -t $(REGISTRY)/kubesynth-operator:$(VERSION) ./operator

docker-build-opencode-runtime:
	$(CONTAINER_CLI) build $(CONTAINER_BUILD_FLAGS) -t $(REGISTRY)/kubesynth-opencode-runtime:$(VERSION) ./opencode-runtime

docker-build-gateway:
	$(CONTAINER_CLI) build $(CONTAINER_BUILD_FLAGS) -t $(REGISTRY)/kubesynth-api-gateway:$(VERSION) ./api-gateway

docker-build-ui:
	$(CONTAINER_CLI) build $(CONTAINER_BUILD_FLAGS) -t $(REGISTRY)/kubesynth-web-ui:$(VERSION) ./web-ui

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

docker-push: docker-push-operator docker-push-opencode-runtime docker-push-gateway docker-push-ui docker-push-mcp-sidecars

docker-push-operator:
	$(CONTAINER_CLI) push $(REGISTRY)/kubesynth-operator:$(VERSION)

docker-push-opencode-runtime:
	$(CONTAINER_CLI) push $(REGISTRY)/kubesynth-opencode-runtime:$(VERSION)

docker-push-gateway:
	$(CONTAINER_CLI) push $(REGISTRY)/kubesynth-api-gateway:$(VERSION)

docker-push-ui:
	$(CONTAINER_CLI) push $(REGISTRY)/kubesynth-web-ui:$(VERSION)

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

test: test-services test-integration

test-gateway:
	cd api-gateway && python -m pytest tests/ -v --cov=. --cov-report=term-missing --cov-fail-under=30

test-operator:
	cd operator && python -m pytest tests/ -v --cov=. --cov-report=term-missing --cov-fail-under=30

test-services:
	@if [ -d operator/tests ]; then cd operator && python -m pytest tests/ -v; else echo "No operator tests found"; fi
	@if [ -d opencode-runtime/tests ]; then cd opencode-runtime && python -m pytest tests/ -v; else echo "No opencode-runtime tests found"; fi
	@if [ -d api-gateway/tests ]; then cd api-gateway && python -m pytest tests/ -v; else echo "No api-gateway tests found"; fi
	@if [ -d mcp-sidecars/github-adapter/tests ]; then cd mcp-sidecars/github-adapter && python -m pytest tests/ -v; else echo "No github adapter tests found"; fi

test-integration:
	@if [ -d tests ]; then python -m pytest tests/ -v; else echo "No integration tests found"; fi

lint:
	ruff check operator/ api-gateway/ opencode-runtime/
	cd api-gateway && bandit -r . -c ../.bandit.yaml || true

format:
	ruff format operator/ api-gateway/ opencode-runtime/
	ruff check --fix operator/ api-gateway/ opencode-runtime/

# ===========================
# Helm
# ===========================

helm-lint:
	helm lint ./charts/kubesynth

helm-package:
	helm package ./charts/kubesynth -d ./dist

helm-template:
	helm template ai-sandbox ./charts/kubesynth $(HELM_SKILLS_CATALOG_ARG)

# ===========================
# Deploy (local cluster)
# ===========================

deploy:
	helm upgrade --install kubesynth ./charts/kubesynth $(HELM_SKILLS_CATALOG_ARG)

deploy-ai-sandbox-kind-dry-run:
	helm upgrade $(AI_SANDBOX_RELEASE) ./charts/kubesynth -n $(AI_SANDBOX_NAMESPACE) --reuse-values --server-side=true --force-conflicts -f $(AI_SANDBOX_KIND_VALUES_FILE) $(AI_SANDBOX_KIND_EXTRA_VALUES_ARGS) $(HELM_SKILLS_CATALOG_ARG) --dry-run

deploy-ai-sandbox-kind:
	helm upgrade $(AI_SANDBOX_RELEASE) ./charts/kubesynth -n $(AI_SANDBOX_NAMESPACE) --reuse-values --server-side=true --force-conflicts -f $(AI_SANDBOX_KIND_VALUES_FILE) $(AI_SANDBOX_KIND_EXTRA_VALUES_ARGS) $(HELM_SKILLS_CATALOG_ARG)

deploy-sample:
	kubectl apply -f examples/sample-agent.yaml
	kubectl apply -f examples/sample-tenant.yaml
	kubectl apply -f examples/sample-policy.yaml

undeploy:
	helm uninstall kubesynth || true
	kubectl delete crd aiagents.kubesynth.ai || true
	kubectl delete crd agentpolicies.kubesynth.ai || true
	kubectl delete crd agentapprovals.kubesynth.ai || true
	kubectl delete crd agenttenants.kubesynth.ai || true
	kubectl delete crd agentworkflows.kubesynth.ai || true
	kubectl delete crd agentevals.kubesynth.ai || true

# ===========================
# Docker Compose (local dev)
# ===========================

COMPOSE_FILE ?= docker-compose.yml

compose-up:
	docker compose -f $(COMPOSE_FILE) up -d
	@echo ""
	@echo "KubeSynth is running:"
	@echo "  API Gateway:  http://localhost:8080"
	@echo "  Web UI:       http://localhost:3000"
	@echo "  LiteLLM:      http://localhost:4000"

compose-down:
	docker compose -f $(COMPOSE_FILE) down

compose-down-volumes:
	docker compose -f $(COMPOSE_FILE) down -v

compose-build:
	docker compose -f $(COMPOSE_FILE) build --no-cache

compose-logs:
	docker compose -f $(COMPOSE_FILE) logs -f

compose-status:
	docker compose -f $(COMPOSE_FILE) ps

# ===========================
# Kubernetes deployment
# ===========================

K8S_NAMESPACE ?= kubesynth
K8S_RELEASE ?= kubesynth
K8S_VALUES ?= ./deploy/values.production.yaml

k8s-install:
	./scripts/deploy-k8s.sh install

k8s-upgrade:
	./scripts/deploy-k8s.sh upgrade

k8s-uninstall:
	./scripts/deploy-k8s.sh uninstall

k8s-status:
	./scripts/deploy-k8s.sh status

k8s-logs:
	./scripts/deploy-k8s.sh logs $(SERVICE)

k8s-port-forward:
	./scripts/deploy-k8s.sh port-forward

# ===========================
# Clean
# ===========================

clean:
	rm -rf bin/ dist/
	$(CONTAINER_CLI) rmi $(REGISTRY)/kubesynth-operator:$(VERSION) || true
	$(CONTAINER_CLI) rmi $(REGISTRY)/kubesynth-opencode-runtime:$(VERSION) || true
	$(CONTAINER_CLI) rmi $(REGISTRY)/kubesynth-api-gateway:$(VERSION) || true
	$(CONTAINER_CLI) rmi $(REGISTRY)/kubesynth-web-ui:$(VERSION) || true
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
