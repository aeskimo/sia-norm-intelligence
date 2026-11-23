# SIA Norm Intelligence – Makefile (REQ-000, docs/05_MILESTONES.md M0)
# Implementierung der Targets: scripts/make.py (plattformübergreifend).
# Windows ohne natives `make`: make.cmd <target>

ifeq ($(OS),Windows_NT)
  SYSTEM_PY := python
else
  SYSTEM_PY := python3
endif

.DEFAULT_GOAL := check

.PHONY: setup check eval run ingest extract

extract:
	$(SYSTEM_PY) scripts/make.py extract $(NORM)

ingest:
	$(SYSTEM_PY) scripts/make.py ingest $(NORM)

setup:
	$(SYSTEM_PY) scripts/make.py setup

check:
	$(SYSTEM_PY) scripts/make.py check

eval:
	$(SYSTEM_PY) scripts/make.py eval

run:
	$(SYSTEM_PY) scripts/make.py run
