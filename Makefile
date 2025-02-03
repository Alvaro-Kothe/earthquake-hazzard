SHELL := /bin/bash
DOCKER = docker

.PHONY: ignition

ignition: cloud-startup/docker-compose.ign

%.ign: %.bu
	$(DOCKER) run --interactive --rm quay.io/coreos/butane:release \
		--pretty --strict < $< > $@

