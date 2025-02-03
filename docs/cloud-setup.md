# CoreOS Cloud Setup

This document describes how to configure the cloud virtual machine (VM) running Fedora CoreOS.

## Startup Scripts

The VM uses [Fedora CoreOS](https://docs.fedoraproject.org/en-US/fedora-coreos/) as its operating system.
Startup scripts are defined using the `Ignition` configuration format
and imported into Google Cloud via the `metadata.user-data` field using Terraform.

The configuration is authored in [Butane](https://coreos.github.io/butane/),
then converted to an Ignition file.
To perform the conversion, run:

```bash
podman run --interactive --rm quay.io/coreos/butane:release \
       --pretty --strict < path/to/your/file.bu > path/to/your/file.ign
```

## Cloning the Repository

To import the repository files into the VM, use `git clone` over SSH. Follow these steps:

1. **SSH into the VM**

   Forward your SSH agent by running:

   ```bash
   gcloud compute ssh core@my-vm -- -A
   ```

2. **Clone the Repository**

   Clone the repository using SSH:

   ```bash
   git clone git@github.com:<my-username>/<my-repository> earthquake
   ```

   This will create an `earthquake` directory containing your project files.

3. **Configure Environment Variables**

   After cloning, create the `.env` file with the correct configuration values.
   Note that the path to the GCP private key is not required on the VM.

4. **Restart the Service (if needed)**

   If this is the first time you are setting up the `earthquake` directory,
   restart the machine or the systemd service.
   To restart the service, run:

   ```bash
   sudo systemctl restart earthquake
   ```

## Executing the Container

The systemd service, defined in the [cloud-startup](/cloud-startup/docker-compose.bu) file,
automatically starts the containers and runs the workflows when the VM boots up.
