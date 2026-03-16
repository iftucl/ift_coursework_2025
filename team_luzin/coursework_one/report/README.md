# LaTeX Report Compilation Guide

## Overview

This directory contains the LaTeX source for the technical report documenting the Portfolio Analysis Pipeline architecture and implementation.

**File**: `main.tex` (Complete LaTeX report skeleton)  
**Bibliography**: `references.bib` (BibTeX references)

## Report Structure

The report includes all required coursework sections:

1. **Introduction** - System overview and scope
2. **Investment Goals and Data Requirements** - Strategic objectives and data needs
3. **Proposed Solution and Vision** - Architecture rationale and design
4. **Architecture and Infrastructure Design** - Detailed technical design (6000+ words)
   - High-level architecture with TikZ diagrams
   - Three-pipeline design and data flow
   - Module hierarchy and dependencies
   - Database schema (PostgreSQL, MongoDB, MinIO)
   - Pipeline execution and orchestration
   - Scalability and performance analysis
   - Testing and quality assurance
5. **Conclusions** - Summary and future enhancements

## How to Compile

### Requirements

```bash
# Install LaTeX (MacOS with Homebrew)
brew install --cask mactex

# Or use a minimal installation
brew install basictex
```

### Compilation

```bash
# Generate PDF from LaTeX source
pdflatex main.tex

# Or using a LaTeX build script (if available)
latexmk -pdf main.tex

# With bibliography processing
pdflatex main.tex
biber main.bcf
pdflatex main.tex
pdflatex main.tex
```

### Clean Temporary Files

```bash
# Remove auxiliary files generated during compilation
latexmk -c

# Or manually
rm -f *.aux *.log *.out *.toc *.bbl *.bcf *.blg *.run.xml
```

## What's Included

✅ **Professional title page** with course and team information  
✅ **Complete section structure** for all required coursework sections  
✅ **TikZ diagram placeholders** for:
   - High-level system architecture
   - Pipeline data flow diagram
   - Module hierarchy and dependencies

✅ **Code listings setup** with Python syntax highlighting  
✅ **Table templates** for database schemas and test metrics  
✅ **Bibliography support** using biblatex + Biber  
✅ **Appendices** with:
   - Key algorithms and formulas
   - Database schema examples (SQL, MongoDB)
   - Configuration examples (YAML)
   - Testing metrics and coverage

## Customization

### Adding Content

1. Replace placeholder text in each section with your content
2. Update section lengths to match coursework requirements
3. Modify TikZ diagrams as needed (see LaTeX TikZ documentation)
4. Add references to `references.bib` using standard BibTeX format

### Modifying Diagrams

TikZ diagrams are embedded in the LaTeX source. To modify:

```latex
\begin{tikzpicture}[
    box/.style={rectangle, draw, thick, ...},
    arrow/.style={->, thick, draw, black}
]
    \node[box] (name) at (x, y) {Text};
    \draw[arrow] (from) -- (to);
\end{tikzpicture}
```

See the TikZ documentation for advanced features.

### Adding References

Add entries to `references.bib`:

```bibtex
@article{Author2024,
    author = {Author, A. and Co-author, B.},
    title = {Article Title},
    journal = {Journal Name},
    year = {2024},
    volume = {10},
    pages = {1--20}
}
```

Then cite in text using `\cite{Author2024}`.

## Word Count

The skeleton provides structure for approximately 8,000-10,000 words of content. The report is expandable to the 20,000-word maximum for Turnitin submission.

### Recommended Distribution

- Introduction: 500 words
- Investment Goals: 1,000 words
- Proposed Solution: 1,500 words
- Architecture & Infrastructure: 7,000 words (detailed)
- Implementation Details: 4,000 words
- Conclusions: 800 words
- References & Appendices: Variable

## Output

The compilation process generates:

- `main.pdf` - Final formatted report (ready for Turnitin submission)
- `main.aux`, `main.log` - LaTeX auxiliary files
- `main.bbl`, `main.bcf` - Bibliography processing files

## Common Issues

### Missing packages

If you get "package not found" errors:
```bash
# Update LaTeX packages
tlmgr update --all

# Or install full distribution
brew install --cask mactex
```

### Bibliography not appearing

Ensure you run the full compilation sequence:
```bash
pdflatex main.tex     # First pass
biber main.bcf        # Bibliography processing
pdflatex main.tex     # Second pass (resolves citations)
pdflatex main.tex     # Third pass (resolves references)
```

### TikZ diagrams not rendering

Verify TikZ library imports are present:
```latex
\usetikzlibrary{shapes, arrows, positioning, fit, calc}
```

## Tips

1. **Work incrementally** - Compile after each major section
2. **Use `\tableofcontents`** - Automatically updates with section changes
3. **Label figures and tables** - Use `\label{}` and `\ref{}` for cross-references
4. **Spell check** - Use `aspell` or similar before final submission
5. **PDF optimization** - Use `gs` or online tools to reduce file size for Turnitin

## Resources

- **LaTeX Guide**: https://www.overleaf.com/learn
- **TikZ Documentation**: https://pgf-tikz.github.io/pgf/pgfmanual.pdf
- **BibTeX Format**: https://www.ctan.org/pkg/biblatex
- **Overleaf Editor**: https://www.overleaf.com (online LaTeX editor alternative)

## Next Steps

1. Compile the skeleton to verify LaTeX installation
2. Expand each section with your project-specific content
3. Replace placeholder diagrams with your architecture
4. Update bibliography with relevant references
5. Review and optimize word count
6. Export final PDF for Turnitin submission

---

**Note**: The skeleton is ready for expansion. All structural elements are in place and fully functional. Simply replace placeholder text with your actual content, update diagrams, and customize as needed.
