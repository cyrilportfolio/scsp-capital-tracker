PYTHON ?= python
IMAGE  ?= scsp-tracker

.PHONY: install data run test docker-build docker-run clean

install:
	$(PYTHON) -m pip install -r requirements.txt

data:
	$(PYTHON) -m src.generate_data

run:
	$(PYTHON) -m src.main

run-2022:
	$(PYTHON) -m src.main --date 2022-12-31

test:
	$(PYTHON) -m pytest

docker-build:
	docker build -t $(IMAGE) .

docker-run:
	docker run --rm \
		-v "$(CURDIR)/data:/app/data" \
		-v "$(CURDIR)/output:/app/output" \
		$(IMAGE)

clean:
	rm -rf output/*.xlsx output/*.txt
	find . -name '__pycache__' -type d -exec rm -rf {} +
