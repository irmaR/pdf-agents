#!/usr/bin/env bash
set -e

echo "=== Chargeback Bot — Team Setup ==="

# Check pyenv is managing the version
if command -v pyenv &>/dev/null; then
  pyenv install --skip-existing $(cat .python-version)
  pyenv local $(cat .python-version)
fi

# Create venv if it doesn't exist
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
  echo "Created .venv"
fi

source .venv/bin/activate

pip install --upgrade pip --quiet

# Install from lock file if it exists, else from requirements
if [ -f "requirements.lock" ]; then
  echo "Installing from requirements.lock (exact versions)..."
  pip install -r requirements.lock --quiet
else
  echo "Installing from requirements.txt..."
  pip install -r requirements.txt --quiet
  pip freeze > requirements.lock
  echo "Generated requirements.lock — commit this file"
fi

# Set up .env
if [ ! -f ".env" ]; then
  cp .env.example .env
  echo ""
  echo ">>> .env created. Open it and paste your ANTHROPIC_API_KEY <<<"
  echo ">>> Get yours at: https://console.anthropic.com               <<<"
  echo ""
fi

python3 db.py
python3 generate_pdf.py

echo ""
echo "Setup complete. Next: add your API key to .env, then:"
echo "  python main.py sample_clean.pdf"
echo "  pytest tests/evals/ -v"