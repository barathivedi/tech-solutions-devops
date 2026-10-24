# Project 1: Containerized Application Deployment for Tech Solutions

## 1. Project Overview

This project demonstrates the deployment of a web application using modern DevOps tools and practices.

The application consists of an Nginx frontend and a Python Flask backend. Docker is used for containerization, Jenkins automates the CI/CD pipeline, Kubernetes manages application workloads, and Helm manages Kubernetes releases.

## 2. Project Objectives

- Containerize the frontend and backend using Docker.
- Store project source code in GitHub.
- Automate application build and deployment using Jenkins.
- Deploy and manage application workloads using Kubernetes.
- Use Helm to manage application configuration and releases.
- Verify application availability using health checks.
- Document deployment and troubleshooting procedures.

## 3. Technology Stack

| Category | Technology |
|---|---|
| Operating System | Amazon Linux 2023 |
| Cloud Platform | AWS EC2 |
| Version Control | Git and GitHub |
| Frontend | Nginx |
| Backend | Python Flask |
| Containerization | Docker |
| CI/CD | Jenkins |
| Container Orchestration | Kubernetes using K3s |
| Deployment Management | Helm |
| Container Registry | Docker Hub |
| Monitoring | Prometheus and Grafana - planned |

## 4. Application Architecture

User
  |
  v
Kubernetes NodePort: 30080
  |
  v
Frontend Service
  |
  +--> Frontend Pod 1 - Nginx
  |
  +--> Frontend Pod 2 - Nginx
                 |
                 v
          Backend Service
             Port 5000
                 |
                 v
          Backend Pod
          Python Flask

Jenkins automates the build and deployment workflow. Docker images are stored in Docker Hub, and Helm manages the Kubernetes release.

## 5. DevOps Workflow

1. Maintain source code in GitHub.
2. Retrieve source code through Jenkins.
3. Build and test the application.
4. Build Docker images for the frontend and backend.
5. Publish versioned images to Docker Hub.
6. Deploy the application using Kubernetes and Helm.
7. Verify application endpoints and deployment health.

## 6. Docker Images

Frontend:
- barathivedi/tech-solutions-frontend:v4

Backend:
- barathivedi/tech-solutions-backend:v2

## 7. Kubernetes Deployment

Kubernetes namespace:
- tech-solutions-k8s

Helm release:
- tech-solutions

Resources:
- Frontend Deployment with two replicas.
- Backend Deployment with one replica.
- Frontend Service using NodePort 30080.
- Backend Service using ClusterIP port 5000.

The backend service is intended for internal cluster communication.

## 8. Application Endpoints

Frontend:
- http://localhost:30080/

Application information:
- http://localhost:30080/api/info

Health check:
- http://localhost:30080/health

These localhost URLs are intended for testing from the EC2 instance.

## 9. Useful Verification Commands

Check Kubernetes resources:

sudo kubectl --kubeconfig /etc/rancher/k3s/k3s.yaml get all -n tech-solutions-k8s

Check Helm release status:

sudo helm --kubeconfig /etc/rancher/k3s/k3s.yaml status tech-solutions -n tech-solutions-k8s

Check Helm release history:

sudo helm --kubeconfig /etc/rancher/k3s/k3s.yaml history tech-solutions -n tech-solutions-k8s

Test the application:

curl http://localhost:30080/api/info

Test the health endpoint:

curl http://localhost:30080/health

## 10. Current Project Status

- AWS EC2 environment configured.
- Docker application containerized.
- Jenkins pipeline successfully executed.
- Versioned Docker images available in Docker Hub.
- K3s Kubernetes cluster running.
- Frontend deployed with two replicas.
- Backend deployed with one replica.
- Frontend and backend Kubernetes Services configured.
- Helm chart created and validated.
- Helm release installed and upgraded.
- Kubernetes resources verified as running.

## 11. Future Enhancements

- Add Prometheus and Grafana monitoring after reviewing server capacity.
- Improve automated integration and deployment tests.
- Add deployment rollback testing.
- Improve application logging and alerting.
- Add security and resource-usage checks to the pipeline.

## 12. Learning Outcomes

This project demonstrates practical experience with:

- Linux server administration.
- Git and GitHub version control.
- Docker image creation and container management.
- Jenkins CI/CD pipeline automation.
- Kubernetes deployments, services, and replicas.
- Helm charts, releases, upgrades, and history.
- Application health checks and troubleshooting.
- Cloud-hosted application deployment.

## 13. Author

DevOps Learning Project - Tech Solutions
