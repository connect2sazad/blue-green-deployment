
# Blue-Green Deployment

Project: https://roadmap.sh/projects/blue-green-deployment

This project demonstrates how to implement a **blue-green deployment strategy** for a simple web application. It allows you to deploy new versions with minimal downtime, improve deployment reliability, and automatically roll back to the previous version if a deployment fails.

The project uses **AWS EC2, Docker, Docker Compose, and GitLab CI/CD** to automate the deployment process.

## Prerequisites

Before getting started, make sure you have:

- An AWS account.
- An EC2 instance with SSH access.
- Docker and Docker Compose installed on your EC2 instance.
- A GitLab account and access to the project repository.
- Basic knowledge of Git, Docker, and SSH.

If you need help creating an EC2 instance and connecting to it via SSH from your local terminal, check out my [YouTube playlist](https://www.youtube.com/playlist?list=PLP-z5YySqpBA).

## Initial Deployment

Follow these steps to deploy the application on your EC2 instance for the first time.

### 1. Connect to Your EC2 Instance

Connect to your EC2 instance using SSH and your private key:

```bash
ssh -i /path/to/your-private-key.pem \
  <EC2_USER>@<EC2_PUBLIC_IP>
```

Replace `/path/to/your-private-key.pem`, `<EC2_USER>`, and `<EC2_PUBLIC_IP>` with your actual values.

On your first connection, SSH may ask you to verify the server's host fingerprint. Confirm it only after verifying that it belongs to your EC2 instance.

### 2. Install Docker

Install Docker and the Docker Compose plugin on your EC2 instance if they are not already installed.

Verify the installation:

```bash
docker --version
docker compose version
```

### 3. Clone the Repository

Clone the project repository and navigate to the project directory:

```bash
git clone https://gitlab.com/connect2sazad/blue-green-deployment.git
cd blue-green-deployment
```

### 4. Configure the Environment

Make the environment setup script executable and run it:

```bash
chmod +x make_env.bash
./make_env.bash
```

Follow any prompts provided by the script to complete the configuration.

### 5. Start the Application

Start the application and its associated services in detached mode:

```bash
docker compose up -d
```

Verify that the containers are running:

```bash
docker compose ps
```

Your initial deployment is now complete.

## Configure GitLab CI/CD

GitLab CI/CD automates the deployment process whenever you push code to the repository. The pipeline uses SSH to connect to your EC2 instance and execute the deployment workflow.

### 1. Fork or Copy the Repository

Fork the project repository, or clone it and push the code to a new GitLab repository that you own.

### 2. Configure CI/CD Variables

In your GitLab project, navigate to:

**Settings → CI/CD → Variables**

Add the following variables:

| Variable | Type | Description |
|---|---|---|
| `EC2_HOST` | Variable | Public IP address or hostname of your EC2 instance. |
| `EC2_KNOWN_HOSTS` | File | SSH host key entries for your EC2 instance. |
| `EC2_SSH_PRIVATE_KEY` | File | Private SSH key used to connect to your EC2 instance. |
| `EC2_USER` | Variable | SSH username for your EC2 instance. |

#### Generate the SSH Host Keys

Run the following command on your local machine to retrieve the EC2 instance's SSH host key:

```bash
ssh-keyscan -H <EC2_PUBLIC_IP>
```

Add the output to the `EC2_KNOWN_HOSTS` CI/CD variable.

**Security note:** For production environments, verify the host key's fingerprint through a trusted source before adding it. Do not rely on an unverified `ssh-keyscan` result alone.

#### Configure the Private Key

Add the contents of your EC2 private key file to `EC2_SSH_PRIVATE_KEY`.

For example, the file may be named `your-key.pem`. Copy its complete contents, including the `BEGIN` and `END` lines.

Keep private keys secret. Never commit them to your repository or expose them in pipeline logs.

For sensitive variables, enable the appropriate masking and protection options supported by GitLab. If you use a file-type variable, ensure the pipeline reads the key from the file path provided by GitLab.

### 3. Configure the GitLab Runner

The project uses GitLab CI/CD to run the deployment pipeline.

If you use a self-hosted GitLab Runner, update the `tags` section in `.gitlab-ci.yml` to match the tags configured for your runner.

For example:

```yaml
tags:
  - your-runner-tag
```

Make sure the runner is online and configured to execute the project's pipeline jobs.

### 4. Trigger a Deployment

Once the CI/CD variables and runner are configured, push your changes to the repository:

```bash
git add .
git commit -m "Update application"
git push origin main
```

Replace `main` with your deployment branch if necessary.

You can monitor the pipeline in **Build → Pipelines** in your GitLab project.

## How Blue-Green Deployment Works

The deployment workflow uses two application environments:

- **Blue:** The currently active application version.
- **Green:** The environment used to deploy and validate the new version.

When a new version is pushed to the repository, the deployment pipeline builds or retrieves the updated application image and deploys it to the inactive environment.

The workflow then switches traffic to the new version after a successful deployment.

If the deployment or validation fails, the workflow attempts to restore the previous working version.

This approach helps minimize downtime and reduces the risk associated with deploying new application versions.

## Verify the Deployment

After a successful pipeline run, verify that the application is accessible through your EC2 instance's public IP address or configured domain.

You can also inspect the running containers on the instance:

```bash
docker compose ps
docker compose logs
```

If the application is not accessible, check the container logs, security group rules, application ports, and deployment pipeline logs.

## Troubleshooting

### SSH Connection Issues

- Verify that `EC2_HOST` and `EC2_USER` are correct.
- Ensure the EC2 security group allows SSH access on port `22` from the runner's IP address.
- Check that the private key is configured correctly.
- Verify the host keys stored in `EC2_KNOWN_HOSTS`.

### Docker Issues

- Confirm that Docker is installed and running.
- Check the container status with `docker compose ps`.
- Review application logs with `docker compose logs`.

### Pipeline Failures

- Review the failed job logs in GitLab.
- Verify that all required CI/CD variables are configured.
- Ensure your GitLab Runner is online and has the correct tags.
- Check that the deployment scripts handle errors and rollback as expected.

## Conclusion

This project demonstrates how to implement a blue-green deployment workflow using AWS EC2, Docker, and GitLab CI/CD.

By automating deployments, validating new application versions, and providing a rollback mechanism, the workflow helps make application releases more reliable and easier to manage.
