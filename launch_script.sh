#!/bin/bash

# Log file path
LOG_FILE="/home/ubuntu/launch_log.txt"
REPO_NAME="offline_flask_apis"
AWS_REGION="us-west-2"
AWS_ACCOUNT_ID="798784231454"

# Log function
log() {
    echo "[$(date)] $1" >> "$LOG_FILE"
}

# Check if log file exists, create it if not
if [ ! -e "$LOG_FILE" ]; then
    sudo touch "$LOG_FILE"
fi

# update and install software
log "Updating packages..."
sudo apt update

log "Installing awscli..."
# sudo apt install -y awscli
sudo snap install aws-cli --classic

log "Installing Docker..."
sudo apt install -y docker.io

log "install jq"
sudo apt-get install -y jq

log "install mysql"
sudo apt install mysql-client-core-8.0

log "Logging in to ECR..."a
aws ecr get-login-password --region $AWS_REGION | sudo docker login --username AWS --password-stdin $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com

log "Describe images"
describe_images_output=$(aws ecr describe-images --repository-name $REPO_NAME --registry-id $AWS_ACCOUNT_ID --region $AWS_REGION)

# Check if there are any images in the repository
if [ "$(echo "$describe_images_output" | jq -r '.imageDetails | length')" -eq 0 ]; then
    echo "No images found in the repository."
    exit 1
fi

log "Sort images by timestamp in descending order"
latest_image=$(echo "$describe_images_output" | jq -r '.imageDetails | sort_by(.imagePushedAt) | last')

log "Extract image tag from the latest image"
latest_image_tag=$(echo "$latest_image" | jq -r '.imageTags[0]')

log "Latest image tag: $latest_image_tag"

log "Pulling Docker image..."
sudo docker pull $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$REPO_NAME:$latest_image_tag

log "Running Docker container..."
sudo docker run -d -p 80:80 $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$REPO_NAME:$latest_image_tag
