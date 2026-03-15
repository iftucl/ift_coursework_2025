FROM python:3.11-bullseye

# Set environment variables for Poetry installation and configuration
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_VERSION=1.8.2 \
    POETRY_HOME="/opt/poetry" \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_NO_INTERACTION=1

# Install system dependencies required for Poetry, Ollama, and Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl build-essential libffi-dev libssl-dev \
    libpq-dev gcc python3-dev pkg-config libxml2-dev libxslt-dev && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN pip install "poetry==$POETRY_VERSION"
RUN poetry config keyring.enabled false

# Create a working directory for the application
WORKDIR /app

# Copy Poetry configuration files first to leverage Docker's caching mechanism
COPY pyproject.toml poetry.lock README.md* ./

# Install Ollama CLI (assumes Linux-based installation)
RUN curl -L https://ollama.com/download/ollama-linux-amd64 -o /usr/local/bin/ollama && \
    chmod +x /usr/local/bin/ollama

# Install Dolt CLI
RUN curl -L https://github.com/dolthub/dolt/releases/latest/download/install.sh | bash

# Install Python dependencies using Poetry
RUN poetry lock && poetry install --only main --no-root
RUN python3 -m spacy download en_core_web_sm
RUN python3 -m nltk.downloader stopwords


# Copy the rest of the application code into the container
COPY . .

# Expose the port used by Ollama (default: 11434)
EXPOSE 11434

# Set the default command to start a Bash shell (customize as needed)
CMD ["bash"]
