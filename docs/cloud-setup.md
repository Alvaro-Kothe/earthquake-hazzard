# CoreOS

## Startup scripts

The VM on the cloud running on the cloud uses [CoreOS](https://docs.fedoraproject.org/en-US/fedora-coreos/).

The startup scripts are defined using `ignition` and imported in Google Cloud with `metadata.user-data` using `terraform`.

The configuration is first written in [`butane`](https://coreos.github.io/butane/) and then converted to `ignition`.
To convert a butane file run:

```
podman run --interactive --rm quay.io/coreos/butane:release \
       --pretty --strict < path/to/my/butane/file.bu > path/to/my/ignition/file.ign
```

## Cloning files

I use `git clone` to import the repository files into the virutal machine (VM).
I login into the VM forwarding my ssh-agent with:

```
gcloud compute ssh core@my-vm -- -A
```

Then I clone this repository with `git clone` using `ssh`.

After cloning, make sure to create the `.env` file with the correct values.
The path to the GCP private key is not needed.

## Executing the container

The [`ignition` script](/cloud-startup/docker-compose.ign) ensures the installation of `docker-compose`.
Then, inside the container, start the services with

```
sudo /opt/bin/docker-compose up -d
```
