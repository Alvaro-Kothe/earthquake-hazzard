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

You can clone the repository creating an ssh key and deploying it to GitHub or
forwarding your ssh agent.

### Create ssh Key and Deploy (Recommended)

Adding the ssh key to the virtual machine is needed to sync the repository on startup
and to automatically start the services with `docker-compose`.

1. **SSH into the VM**

    ```console
    gcloud compute ssh core@my-vm
    ```

2. **Create the ssh key**

    ```console
    ssh-keygen -t ed25519 -C my-vm
    ```

    Copy the ssh public key, obtained by the command `cat ~/.ssh/id_ed25519.pub`

3. **Paste the public key in GitHub**

    In the repository go to settings &rarr; Deploy keys -> Add deploy key.
    The paste the public key from the VM.

4. **Add github.com to known hosts**

    ```console
    ssh -T git@github.com
    ```

    Just answer yes in the prompt.

5. **Restart git-sync service**

    ```console
    sudo systemctl restart git-sync.service
    ```

6. **Set up environment variables**

    ```console
    cd ~/earthquake
    cp .env.example .env
    ```

    Configure the `.env`.

7. **Restart earthquake service**

    ```console
    sudo systemctl restart earthquake.service
    ```

## Executing the Container

The systemd service, defined in the [cloud-startup](/cloud-startup/docker-compose.bu) file,
automatically starts the containers and runs the workflows when the VM boots up.
