#!/bin/bash
# LaTeX Report Compilation Script
# Compiles the main.tex file to PDF with proper bibliography handling

set -e  # Exit on any error

REPORT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPORT_DIR"

echo "=================================="
echo "LaTeX Report Compilation Script"
echo "=================================="
echo ""
echo "Report Directory: $REPORT_DIR"
echo ""

# Check if pdflatex is installed
if ! command -v pdflatex &> /dev/null; then
    echo "❌ Error: pdflatex not found"
    echo "Install LaTeX with: brew install --cask mactex"
    exit 1
fi

echo "✓ pdflatex found"

# Check if biber is installed for bibliography
if ! command -v biber &> /dev/null; then
    echo "⚠️  Warning: biber not found (bibliography may not work)"
    echo "Install with: tlmgr install biber"
fi

echo ""
echo "Starting compilation..."
echo ""

# First pass: Generate .aux file
echo "[1/4] First LaTeX pass (generating .aux file)..."
pdflatex -interaction=nonstopmode main.tex > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "✓ First pass completed"
else
    echo "❌ First pass failed"
    exit 1
fi

# Bibliography processing
if command -v biber &> /dev/null; then
    echo "[2/4] Processing bibliography with Biber..."
    biber main > /dev/null 2>&1
    if [ $? -eq 0 ]; then
        echo "✓ Bibliography processed"
    else
        echo "⚠️  Bibliography processing had warnings (may be non-critical)"
    fi
else
    echo "[2/4] Biber not available, skipping bibliography processing"
fi

# Second pass: Resolve citations
echo "[3/4] Second LaTeX pass (resolving citations)..."
pdflatex -interaction=nonstopmode main.tex > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "✓ Second pass completed"
else
    echo "❌ Second pass failed"
    exit 1
fi

# Third pass: Resolve references
echo "[4/4] Third LaTeX pass (resolving references)..."
pdflatex -interaction=nonstopmode main.tex > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "✓ Third pass completed"
else
    echo "❌ Third pass failed"
    exit 1
fi

echo ""
echo "=================================="
echo "✅ Compilation Successful!"
echo "=================================="
echo ""
echo "Output: main.pdf"
echo ""

# Report file size
if [ -f main.pdf ]; then
    SIZE=$(du -h main.pdf | cut -f1)
    echo "File size: $SIZE"
    echo ""
    echo "You can now:"
    echo "  • Open main.pdf to view the report"
    echo "  • Submit to Turnitin"
    echo "  • Make edits and recompile"
fi

echo ""
echo "To clean auxiliary files, run: ./clean.sh"
echo ""
