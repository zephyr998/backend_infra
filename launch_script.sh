#!/bin/bash

# Log file path
LOG_FILE="$HOME/launch_log.txt"

# Log function
log() {
    echo "[$(date)] $1" >> "$LOG_FILE"
}

# Check if log file exists, create it if not
if [ ! -e "$LOG_FILE" ]; then
    touch "$LOG_FILE"
fi

# update and install software
log "Updating packages..."
sudo apt update

log "Installing awscli..."
sudo apt install -y awscli

log "Installing Docker..."
sudo apt install -y docker.io

log "install jq"
sudo apt-get install -y jq

log "Logging in to ECR..."
aws ecr get-login-password --region us-west-2 | sudo docker login --username AWS --password-stdin 798784231454.dkr.ecr.us-west-2.amazonaws.com

log "Describe images"
describe_images_output=$(aws ecr describe-images --repository-name health_check --registry-id 798784231454 --region us-west-2)

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
sudo docker pull 798784231454.dkr.ecr.us-west-2.amazonaws.com/health_check:$latest_image_tag

log "Running Docker container..."
sudo docker run -d -p 80:80 798784231454.dkr.ecr.us-west-2.amazonaws.com/health_check:$latest_image_tag