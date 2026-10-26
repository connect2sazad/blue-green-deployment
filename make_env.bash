#!/usr/bin/env bash

set -euo pipefail

if [ ! -f .env ]; then
    if [ ! -f .env.example ]; then
        echo "Error: .env.example not found!"
        exit 1
    fi

    MONGO_USER="appadmin"
    MONGO_PASS="$(openssl rand -hex 24)"
    DB_NAME="multi-container-service-deployment"
    
    cp .env.example .env
    
    sed -i "s|^MONGO_INITDB_ROOT_USERNAME=.*|MONGO_INITDB_ROOT_USERNAME=${MONGO_USER}|" .env
    sed -i "s|^MONGO_INITDB_ROOT_PASSWORD=.*|MONGO_INITDB_ROOT_PASSWORD=${MONGO_PASS}|" .env
    sed -i "s|^MONGODB_URI=.*|MONGODB_URI=mongodb://${MONGO_USER}:${MONGO_PASS}@mongodb:27017/${DB_NAME}?authSource=admin|" .env

    chmod 600 .env    
    
    echo ".env generated from .env.example"

else 
    echo ".env already exists; keeping existing configuration."
fi

