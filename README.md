# IndoMultiDomain Builder & Audit

Reproducibility code for **IndoMultiDomain-Core V1**, a provenance-aware and harmonized multi-domain corpus for Indonesian NLP.

Dataset release:  
https://huggingface.co/datasets/surodipoikromo/IndoMultiDomain

## What this repository contains

This repository contains the **builder, source harmonization workflow, audit, privacy-cleaning, and freeze logic** used to construct IndoMultiDomain-Core V1.

It intentionally does **not** include:

- third-party raw datasets;
- redistributed source archives;
- the released IndoMultiDomain corpus files;
- authentication tokens or credentials;
- personal identifiers removed during corpus construction.

The released corpus is hosted separately on Hugging Face.

## Repository structure

```text
indomultidomain-builder/
├── src/
│   └── indomultidomain_build_v1.py
├── notebooks/
│   ├── 01_core_v1_builder.ipynb
│   ├── 02_src006_final_fix.ipynb
│   ├── 03_final_audit.ipynb
│   └── 04_final_clean_and_freeze.ipynb
├── config/
│   └── source_registry_v1_1.csv
├── docs/
│   ├── DATA_SOURCES.md
│   └── REPRODUCIBILITY.md
├── requirements.txt
├── .gitignore
├── LICENSE
└── README.md
```

## Reproducing the pipeline

The original construction workflow used Google Colab with Google Drive mounted at:

```text
/content/drive/MyDrive/IndoMultiDomain
```

A typical sequence is:

1. Obtain each original dataset from its official repository.
2. Place source files under the expected `02_raw_sources/SRCxxx/` folders.
3. Review `config/source_registry_v1_1.csv`.
4. Run `notebooks/01_core_v1_builder.ipynb`.
5. Run the documented SRC006 correction notebook.
6. Run `notebooks/03_final_audit.ipynb`.
7. Run `notebooks/04_final_clean_and_freeze.ipynb`.
8. Compare the resulting frozen statistics with the V1 release.

Frozen V1 summary:

- 69,075 records
- 1,418,001 words
- 8 domains
- 12 subdomains
- 3 genres
- 9 source datasets
- zero exact duplicates
- zero empty texts

## Important reproducibility note

Some source datasets cannot be fetched automatically from anonymous environments because their repositories may require browser-based download or may change access behavior over time. This repository therefore preserves the **processing and audit workflow**, while acquisition of third-party source data remains subject to the original repositories and licenses.

## License

Code in this repository is released under the MIT License.

The code license **does not apply to third-party datasets or their underlying texts**. Users must comply with the original source licenses and attribution requirements.
