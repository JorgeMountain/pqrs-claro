"""Etiqueta en el catálogo local la colección incorporada de Admisiones UdeA 2027-1."""

import argparse
from pathlib import Path

from pqrs_claro.extraction import PDFExtractor
from pqrs_claro.source_library import SourceLibrary

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args()
    if not (args.data_dir / "biblioteca.sqlite").is_file():
        parser.error("El directorio debe contener el catálogo biblioteca.sqlite.")
    count = SourceLibrary(args.data_dir, PDFExtractor()).seed_admissions_2027_1()
    print(f"Versiones etiquetadas: {count}")
