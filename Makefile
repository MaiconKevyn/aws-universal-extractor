PROJECT_ROOT := $(abspath $(ARTIFACTS_DIR)/../../..)
RUNTIME_DEPS_DIR := $(PROJECT_ROOT)/.aws-sam/runtime-deps

.PHONY: \
	build-SubmitExtractionFunction \
	build-FetchDocumentFunction \
	build-ExtractPdfTextFunction \
	build-LoadExtractionProfileFunction \
	build-RunLlmExtractionFunction \
	build-ValidateSchemaFunction \
	build-PersistResultFunction \
	build-PersistFailureFunction

define build_lambda
	mkdir -p "$(ARTIFACTS_DIR)"
	test -d "$(RUNTIME_DEPS_DIR)"
	cp -R functions "$(ARTIFACTS_DIR)/"
	cp -R profiles "$(ARTIFACTS_DIR)/"
	cp -R "$(RUNTIME_DEPS_DIR)"/* "$(ARTIFACTS_DIR)/"
endef

build-SubmitExtractionFunction:
	$(build_lambda)

build-FetchDocumentFunction:
	$(build_lambda)

build-ExtractPdfTextFunction:
	$(build_lambda)

build-LoadExtractionProfileFunction:
	$(build_lambda)

build-RunLlmExtractionFunction:
	$(build_lambda)

build-ValidateSchemaFunction:
	$(build_lambda)

build-PersistResultFunction:
	$(build_lambda)

build-PersistFailureFunction:
	$(build_lambda)
