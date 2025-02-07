SHELL := /bin/bash
DOCKER = docker

.PHONY: ignition data clean

ignition: cloud-startup/docker-compose.ign

%.ign: %.bu
	$(DOCKER) run --interactive --rm quay.io/coreos/butane:release \
		--pretty --strict < $< > $@

data:
	curl -O https://naciscdn.org/naturalearth/110m/cultural/ne_110m_admin_0_countries.zip && \
	unzip -d src/dags/include ne_110m_admin_0_countries.zip && \
	rm ne_110m_admin_0_countries.zip

clean:
	rm src/dags/include/ne_110m_admin_0_countries.*
