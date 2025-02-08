# CoreOS Cloud Setup

## Startup Scripts

The VM uses [Fedora CoreOS](https://docs.fedoraproject.org/en-US/fedora-coreos/) as its operating system.
Startup scripts are defined using the `Ignition` configuration format and imported into Google Cloud via the `metadata.user-data` field using Terraform.
The configuration is authored in [Butane](https://coreos.github.io/butane/), then converted to an Ignition file.

To convert your Butane file to Ignition, run:

```bash
podman run --interactive --rm quay.io/coreos/butane:release \
       --pretty --strict < path/to/your/file.bu > path/to/your/file.ign
```

Alternatively, you can use `make ignition` to perform the conversion for the necessary files.

## Cloning the Repository

To clone the repository, you'll need to create an SSH key and deploy it to GitHub.

1. **SSH into the VM**: `gcloud compute ssh core@my-vm`
2. **Create the SSH key**: `ssh-keygen -t ed25519 -C my-vm`
3. **Copy the public key from**: `cat ~/.ssh/id_ed25519.pub`
4. **Paste the public key in GitHub**: Go to repository settings > Deploy keys > Add deploy key
5. **Add GitHub to known hosts**: `ssh -T git@github.com` (answer "yes" to the prompt)
6. **Restart git-sync service**: `sudo systemctl restart git-sync.service`
7. **Set up environment variables**:
    - `cd ~/earthquake`
    - `cp .env.example .env`
    - Configure the `.env` file
8. **Restart earthquake service**: `sudo systemctl restart earthquake.service`

## Executing the Container

The `systemd` services,
defined in the [cloud-startup](/cloud-startup/docker-compose.bu),
sync the repository when the machine is booted and then start running the container.
