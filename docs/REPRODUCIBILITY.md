# Reproducibility Notes

## 1. Environment

The V1 pipeline was executed in Google Colab with Google Drive mounted under:

```text
/content/drive/MyDrive/IndoMultiDomain
```

Install dependencies with:

```bash
pip install -r requirements.txt
```

## 2. Source acquisition

Third-party source files are deliberately excluded from this repository.

Download them from the source repositories listed in `docs/DATA_SOURCES.md`, then place them under:

```text
IndoMultiDomain/
└── 02_raw_sources/
    ├── SRC001/
    ├── SRC002/
    ├── ...
    └── SRC009/
```

Repository providers may change filenames or browser-download behavior. If a provider blocks anonymous programmatic downloads, manual download from the official source page is acceptable and should be logged in provenance metadata.

## 3. Build

The main builder is:

```bash
python src/indomultidomain_build_v1.py
```

The Colab-oriented workflow is available in `notebooks/01_core_v1_builder.ipynb`.

## 4. Source-specific correction

The final V1 build explicitly uses `reviewContent` for SRC006. The earlier fuzzy field-selection path could select `reviewTitle`; the final correction notebook documents and repairs this.

Run:

```text
notebooks/02_src006_final_fix.ipynb
```

## 5. Final audit

Run:

```text
notebooks/03_final_audit.ipynb
```

The V1 audit checks:

- schema completeness;
- unique `imd_id`;
- exact-text hash uniqueness;
- empty text;
- domain/source/genre distributions;
- length outliers;
- lightweight script/language review candidates;
- direct identifier signals;
- provenance and license completeness;
- soft-normalized duplicate candidates;
- split integrity.

## 6. Privacy clean and freeze

Run:

```text
notebooks/04_final_clean_and_freeze.ipynb
```

The final V1 privacy pass redacted:

- 1 email-containing record;
- 5 phone-number candidate records.

No exact duplicates were created by the redaction.

## 7. Expected frozen V1 statistics

```json
{
  "records": 69075,
  "words": 1418001,
  "domains": 8,
  "subdomains": 12,
  "genres": 3,
  "sources": 9,
  "exact_duplicates": 0,
  "empty_text": 0
}
```

Minor differences indicate that source versions, filenames, or upstream records may have changed. For exact V1 comparison, use the version identifiers recorded in the source registry and dataset release.
