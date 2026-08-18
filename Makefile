.PHONY: help install seed run test quality lineage graph query clean docker

PY ?= python3
export PYTHONPATH := src

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS=":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

install: ## install dependencies
	$(PY) -m pip install -r requirements.txt

seed: ## generate the raw source files
	$(PY) -m pipeline.generate_source_data --rows 20000

run: ## extract, transform, test, export
	$(PY) -m pipeline.run run

quality: ## run the data quality suite against the existing warehouse
	$(PY) -m pipeline.run test

lineage: ## print the model DAG in execution order
	$(PY) -m pipeline.run lineage

graph: ## print the lineage as a Mermaid diagram
	$(PY) -m pipeline.run lineage --mermaid

query: ## ad hoc SQL, e.g. make query SQL="SELECT * FROM mart_daily_revenue LIMIT 5"
	$(PY) -m pipeline.run query "$(SQL)"

test: ## run the unit and integration tests
	$(PY) -m pytest tests -q

sqlite: ## prove the same SQL runs on SQLite
	ELT_ENGINE=sqlite ELT_WAREHOUSE=data/warehouse.sqlite $(PY) -m pipeline.run run

clean: ## remove generated data, warehouse and artifacts
	rm -rf data artifacts .pytest_cache
	find . -name __pycache__ -type d -exec rm -rf {} +

docker: ## build the image
	docker build -t retail-elt-pipeline .
