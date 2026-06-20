# =============================================================================
# ElasticOps - Root Makefile
# =============================================================================

.DEFAULT_GOAL := help

.PHONY: help

help:  ## Show available targets
	@echo "ElasticOps Makefile — delegates to sub-makefiles"
	@echo ""
	@echo "Local dev:   make -f Makefile.local <target>"
	@echo "Deploy:      make -f Makefile.deploy <target>"
	@echo ""
	@make -f Makefile.local help
