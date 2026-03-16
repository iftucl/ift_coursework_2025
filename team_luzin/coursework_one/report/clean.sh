#!/bin/bash
# Clean LaTeX auxiliary files

REPORT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPORT_DIR"

echo "Cleaning LaTeX auxiliary files..."

rm -f *.aux
rm -f *.log
rm -f *.out
rm -f *.toc
rm -f *.bbl
rm -f *.bcf
rm -f *.blg
rm -f *.run.xml
rm -f *.fls
rm -f *.fdb_latexmk
rm -f *~

echo "✓ Cleanup complete"
echo ""
echo "Remaining files:"
ls -1h
