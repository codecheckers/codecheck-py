# Tasks for this repository; the CODECHECK template itself lives in .codecheck/ (run from the repository root).
# Zenodo targets need the API token in .env (ZENODO_API_TOKEN_SANDBOX / ZENODO_API_TOKEN), see README.md.
# Extra options via ARGS, e.g. make zenodo-sandbox ARGS="--include-outputs --outputs-license mit"

TEMPLATE := .codecheck
ZENODO := cd $(TEMPLATE) && python zenodo_deposit.py

.PHONY: help test pdf zenodo-metadata zenodo-reserve-sandbox zenodo-sandbox zenodo-status-sandbox \
	zenodo-reserve zenodo zenodo-status

help:
	@echo "make test                    run the test suite"
	@echo "make pdf                     build the certificate ($(TEMPLATE)/codecheck.pdf)"
	@echo "make zenodo-metadata         print the Zenodo metadata built from codecheck.yml (no upload)"
	@echo "make zenodo-reserve-sandbox  create a draft on the Zenodo sandbox, reserve its DOI -> codecheck.yml"
	@echo "make zenodo-sandbox          rebuild the PDF, upload it, set the metadata (sandbox)"
	@echo "make zenodo-status-sandbox   show the record (sandbox)"
	@echo "make zenodo-reserve / zenodo / zenodo-status   the same on zenodo.org"
	@echo "The record is never published: check it on Zenodo and publish it yourself."

test:
	pytest tests/

pdf:
	cd $(TEMPLATE) && sh notebook_to_pdf.sh

zenodo-metadata:
	$(ZENODO) metadata --dry-run $(ARGS)

zenodo-reserve-sandbox:
	$(ZENODO) reserve --sandbox $(ARGS)

zenodo-sandbox: pdf
	$(ZENODO) all --sandbox $(ARGS)

zenodo-status-sandbox:
	$(ZENODO) status --sandbox $(ARGS)

zenodo-reserve:
	$(ZENODO) reserve $(ARGS)

zenodo: pdf
	$(ZENODO) all $(ARGS)

zenodo-status:
	$(ZENODO) status $(ARGS)
