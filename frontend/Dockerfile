# syntax=docker/dockerfile:1

# Production image for the frontend: build static files, serve them with
# nginx. No Node in the runtime image and no dev server.
#
# Build context is the repository root, matching backend/Dockerfile:
#   docker build -f frontend/Dockerfile .

# --- Stage 1: build ----------------------------------------------------------
FROM node:22-alpine AS builder

WORKDIR /app

# Manifests first so the install layer survives source changes.
COPY frontend/package.json frontend/package-lock.json ./

# npm ci, not npm install: installs exactly what the lockfile says and fails
# if the lockfile and manifest disagree, rather than quietly resolving
# something new inside a build nobody is watching.
RUN npm ci

COPY frontend/ ./

# Vite substitutes this at BUILD time, not at run time — it ends up inside
# the bundle as a literal. That means the image is specific to the API URL it
# was built against, which is why it is an ARG rather than a runtime
# environment variable that would silently do nothing.
ARG VITE_API_URL=http://localhost:8000
ENV VITE_API_URL=$VITE_API_URL

RUN npm run build

# --- Stage 2: runtime --------------------------------------------------------
FROM nginx:1.27-alpine AS runtime

COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80
