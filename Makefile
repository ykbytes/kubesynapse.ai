.PHONY: all build test test-goose-runtime-e2e lint docker-build docker-push helm-lint helm-package deploy clean ui-install ui-dev ui-build ui-preview docker-build-ui docker-push-ui docker-build-goose-runtime docker-push-goose-runtime

CONTAINER_CLI ?= podman
CONTAINER_BUILD_FLAGS ?= --format docker
REGISTRY ?= ghcr.io/your-org
VERSION ?= latest

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

docker-build: docker-build-operator docker-build-runtime docker-build-goose-runtime docker-build-gateway docker-build-ui

docker-build-operator:
	$(CONTAINER_CLI) build $(CONTAINER_BUILD_FLAGS) -t $(REGISTRY)/ai-operator:$(VERSION) ./operator

docker-build-runtime:
	$(CONTAINER_CLI) build $(CONTAINER_BUILD_FLAGS) -t $(REGISTRY)/ai-agent-runtime:$(VERSION) ./agent-runtime

docker-build-goose-runtime:
	$(CONTAINER_CLI) build $(CONTAINER_BUILD_FLAGS) -t $(REGISTRY)/ai-goose-runtime:$(VERSION) ./goose-runtime

docker-build-gateway:
	$(CONTAINER_CLI) build $(CONTAINER_BUILD_FLAGS) -t $(REGISTRY)/ai-api-gateway:$(VERSION) ./api-gateway

docker-build-ui:
	$(CONTAINER_CLI) build $(CONTAINER_BUILD_FLAGS) -t $(REGISTRY)/ai-agent-sandbox-web-ui:$(VERSION) ./web-ui

docker-push: docker-push-operator docker-push-runtime docker-push-goose-runtime docker-push-gateway docker-push-ui

docker-push-operator:
	$(CONTAINER_CLI) push $(REGISTRY)/ai-operator:$(VERSION)

docker-push-runtime:
	$(CONTAINER_CLI) push $(REGISTRY)/ai-agent-runtime:$(VERSION)

docker-push-goose-runtime:
	$(CONTAINER_CLI) push $(REGISTRY)/ai-goose-runtime:$(VERSION)

docker-push-gateway:
	$(CONTAINER_CLI) push $(REGISTRY)/ai-api-gateway:$(VERSION)

docker-push-ui:
	$(CONTAINER_CLI) push $(REGISTRY)/ai-agent-sandbox-web-ui:$(VERSION)

# ===========================
# Test & Lint
# ===========================

test:
	@if [ -d operator/tests ]; then cd operator && python -m pytest tests/ -v; else echo "No operator tests found"; fi
	@if [ -d agent-runtime/tests ]; then cd agent-runtime && python -m pytest tests/ -v; else echo "No agent-runtime tests found"; fi
	@if [ -d goose-runtime/tests ]; then cd goose-runtime && python -m pytest tests/ -v; else echo "No goose-runtime tests found"; fi
	@if [ -d api-gateway/tests ]; then cd api-gateway && python -m pytest tests/ -v; else echo "No api-gateway tests found"; fi

test-goose-runtime-e2e:
	cd goose-runtime && CONTAINER_CLI=$(CONTAINER_CLI) python -m pytest tests/test_container_e2e.py -v

lint:
	cd operator && python -m flake8 . --max-line-length=120
	cd agent-runtime && python -m flake8 . --max-line-length=120
	cd goose-runtime && python -m flake8 . --max-line-length=120
	cd api-gateway && python -m flake8 . --max-line-length=120

# ===========================
# Helm
# ===========================

helm-lint:
	helm lint ./charts/ai-agent-sandbox

helm-package:
	helm package ./charts/ai-agent-sandbox -d ./dist

helm-template:
	helm template ai-sandbox ./charts/ai-agent-sandbox

# ===========================
# Deploy (local cluster)
# ===========================

deploy:
	helm upgrade --install ai-agent-sandbox ./charts/ai-agent-sandbox

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
	$(CONTAINER_CLI) rmi $(REGISTRY)/ai-api-gateway:$(VERSION) || true
	$(CONTAINER_CLI) rmi $(REGISTRY)/ai-agent-sandbox-web-ui:$(VERSION) || true
