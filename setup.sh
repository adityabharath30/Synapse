#!/bin/bash

# Setup script for Personal Knowledge Graph + RAG System

echo "Setting up Personal Knowledge Graph + RAG System..."
echo ""

# Check Python version
python_version=$(python3 --version 2>&1 | awk '{print $2}')
echo "Python version: $python_version"

# Install dependencies
echo ""
echo "Installing dependencies..."
pip install -r requirements.txt

# Download SpaCy model
echo ""
echo "Downloading SpaCy model..."
python3 -m spacy download en_core_web_sm

# Create data directory
echo ""
echo "Creating data directory..."
mkdir -p data/documents

# Create .env file if it doesn't exist
if [ ! -f .env ]; then
    echo ""
    echo "Creating .env file..."
    cat > .env << EOF
# OpenAI Configuration (Optional)
# If using OpenAI embeddings and GPT, set your API key here
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_MODEL=gpt-3.5-turbo
EOF
    echo ".env file created. Please edit it to add your OpenAI API key if needed."
else
    echo ".env file already exists."
fi

echo ""
echo "Setup complete!"
echo ""
echo "Next steps:"
echo "1. Add your documents to the data/documents folder"
echo "2. (Optional) Edit .env to add your OpenAI API key"
echo "3. Run: python main.py"
echo "   Or with OpenAI: python main.py --openai"
echo ""

