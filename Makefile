.PHONY: clean clean-all

clean:
	@echo "🧹 Cleaning python cache..."
	@find . -type d -name "__pycache__" -prune -exec rm -rf {} +
	@find . -type f -name "*.py[cod]" -delete
	@rm -rf .pytest_cache .mypy_cache .ruff_cache

#clean-all: clean
#	@echo "🔥 Removing outputs and logs..."
#	@rm -rf outputs logs checkpoints
