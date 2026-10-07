#!/bin/bash
set -e  # exit on error

# Notebook name (without extension)
NOTEBOOK="codecheck"
MARKDOWN_FILE="${NOTEBOOK}.md"

# Delete old Markdown to ensure we wait for the new one
if [ -f "$MARKDOWN_FILE" ]; then
    echo "[CODECHECK - Py] Deleting old $MARKDOWN_FILE..."
    rm "$MARKDOWN_FILE"
fi

# Convert notebook to Markdown
echo "[CODECHECK - Py] Converting $NOTEBOOK.ipynb to Markdown..."
# Execute first, then convert: nbconvert removes tagged outputs before it executes, so this needs two steps.
# Outputs of cells tagged `remove-output` (e.g. the copy report for the codechecker) are not in the certificate.
EXECUTED="${NOTEBOOK}.executed.ipynb"
trap 'rm -f "$EXECUTED"' EXIT  # also after an error
jupyter nbconvert --to notebook --execute --output "$EXECUTED" "$NOTEBOOK.ipynb"
# Plain URLs become links in the PDF, as they are in Jupyter (Typst's Markdown renderer does not link them)
"${PYTHON:-python3}" markdown_links.py "$EXECUTED"
jupyter nbconvert --to markdown --no-input --no-prompt --output "$NOTEBOOK" \
    --TagRemovePreprocessor.enabled=True --TagRemovePreprocessor.remove_all_outputs_tags='["remove-output"]' "$EXECUTED"

# Wait until Markdown is created
echo "[CODECHECK - Py] Waiting for $MARKDOWN_FILE to be created..."
while [ ! -f "$MARKDOWN_FILE" ]; do
    sleep 0.5
done

echo "[CODECHECK - Py] $MARKDOWN_FILE found."

# Guard against huge Markdown (e.g. large tables or log output), Typst may run out of memory
MAX_MD_BYTES=${MAX_MD_BYTES:-5000000}
MD_SIZE=$(wc -c < "$MARKDOWN_FILE")
if [ "$MD_SIZE" -gt "$MAX_MD_BYTES" ]; then
    echo "[CODECHECK - Py] ERROR: $MARKDOWN_FILE is $MD_SIZE bytes (limit: $MAX_MD_BYTES)." >&2
    echo "[CODECHECK - Py] Typst will likely run out of memory. Check for large CSV summaries (use max_rows/max_cols in csv_files()) or large cell output." >&2
    echo "[CODECHECK - Py] Set MAX_MD_BYTES to override the limit." >&2
    exit 1
fi

# Start Typst compile
echo "[CODECHECK - Py] Compiling $NOTEBOOK.typ to PDF..."
typst compile "${NOTEBOOK}.typ"
echo "[CODECHECK - Py] Done compiling!"