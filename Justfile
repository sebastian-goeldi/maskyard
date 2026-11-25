# Build the English and Simplified Chinese docs into docs/site/.
docs:
    uv run --locked --group docs python docs/scripts/build.py

# Build and serve both languages at http://127.0.0.1:8000/.
docs-serve: docs
    uv run --locked python -m http.server 8000 --bind 127.0.0.1 --directory docs/site
