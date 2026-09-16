#!/usr/bin/env python3
from __future__ import annotations
import os, re, json, hashlib, shutil, zipfile, unicodedata, random, math
from pathlib import Path
from typing import Optional, Iterable
import pandas as pd
import numpy as np
import requests

SEED = 20260915
random.seed(SEED)
np.random.seed(SEED)

PII_COL_PATTERNS = [
    r"(^|_)(user_?name|username|reviewer|reviewer_?name|email|phone|telephone|account_?id|user_?id)($|_)",
    r"(^|_)(alamat|address)($|_)",
]

APP_DOMAIN_MAP = {
    "kai": ("transportation_mobility","rail_service"),
    "mobilejkn": ("health_healthcare","public_health_service"),
    "mobile jkn": ("health_healthcare","public_health_service"),
    "satusehat": ("health_healthcare","public_health_service"),
    "jmo": ("government_public_services","social_security_employment"),
    "bmkg": ("government_public_services","public_information_weather"),
    "mypertamina": ("government_public_services","energy_public_service"),
}

def norm_text(x):
    if pd.isna(x): return ""
    x = unicodedata.normalize("NFC", str(x))
    x = re.sub(r"<[^>]+>", " ", x)
    x = re.sub(r"\s+", " ", x).strip()
    return x

def text_hash(x):
    return hashlib.sha256(norm_text(x).encode("utf-8")).hexdigest()

def infer_column(columns, candidates):
    norm = {str(c).strip().lower(): c for c in columns}
    for cand in candidates:
        if cand.lower() in norm:
            return norm[cand.lower()]
    # fuzzy containment fallback
    for cand in candidates:
        for low, orig in norm.items():
            if cand.lower() in low:
                return orig
    return None

def pii_columns(df):
    drops = []
    for c in df.columns:
        low = str(c).lower()
        if any(re.search(p, low) for p in PII_COL_PATTERNS):
            drops.append(c)
    return drops

def mendeley_list(dataset_id, version, folder_id="root"):
    url = f"https://data.mendeley.com/public-api/datasets/{dataset_id}/files"
    r = requests.get(url, params={"folder_id":folder_id, "version":version}, timeout=60)
    r.raise_for_status()
    return r.json()

def mendeley_download_recursive(dataset_id, version, dest: Path):
    dest.mkdir(parents=True, exist_ok=True)
    downloaded = []
    queue = [("root", Path("."))]
    seen = set()
    while queue:
        folder_id, rel = queue.pop(0)
        if folder_id in seen: 
            continue
        seen.add(folder_id)
        items = mendeley_list(dataset_id, version, folder_id)
        for item in items:
            name = item.get("name") or item.get("filename") or item.get("id","item")
            ctype = str(item.get("type","")).lower()
            is_folder = ctype == "folder" or item.get("content_details") is None
            if is_folder and item.get("id"):
                queue.append((item["id"], rel/name))
                continue
            cd = item.get("content_details") or {}
            durl = cd.get("download_url")
            if not durl:
                continue
            out = dest/rel/name
            out.parent.mkdir(parents=True, exist_ok=True)
            if not out.exists() or out.stat().st_size == 0:
                with requests.get(durl, stream=True, timeout=120) as rr:
                    rr.raise_for_status()
                    with out.open("wb") as f:
                        for chunk in rr.iter_content(1024*1024):
                            if chunk: f.write(chunk)
            downloaded.append(out)
    return downloaded

def unpack_archives(folder: Path):
    for p in list(folder.rglob("*")):
        if p.is_file() and p.suffix.lower() == ".zip":
            d = p.with_suffix("")
            if not d.exists():
                d.mkdir(parents=True, exist_ok=True)
                try:
                    with zipfile.ZipFile(p) as z:
                        z.extractall(d)
                except zipfile.BadZipFile:
                    pass

def read_tables(folder: Path):
    tables = []
    for p in folder.rglob("*"):
        if not p.is_file():
            continue
        s = p.suffix.lower()
        try:
            if s == ".csv":
                # robust CSV
                for enc in ("utf-8","utf-8-sig","latin-1"):
                    try:
                        df = pd.read_csv(p, encoding=enc, low_memory=False)
                        break
                    except Exception:
                        df = None
                if df is not None: tables.append((p,df))
            elif s in (".xlsx",".xls"):
                xl = pd.ExcelFile(p)
                for sh in xl.sheet_names:
                    tables.append((Path(str(p)+f"::{sh}"), pd.read_excel(p, sheet_name=sh)))
            elif s == ".parquet":
                tables.append((p,pd.read_parquet(p)))
            elif s in (".json",".jsonl"):
                try:
                    if s == ".jsonl":
                        tables.append((p,pd.read_json(p, lines=True)))
                    else:
                        obj=json.loads(p.read_text(encoding="utf-8"))
                        if isinstance(obj,list): tables.append((p,pd.DataFrame(obj)))
                except Exception:
                    pass
        except Exception as e:
            print("READ_FAIL",p,e)
    return tables

def choose_best_table(tables, text_candidates, source_id):
    cand = []
    for p,df in tables:
        tc = infer_column(df.columns, text_candidates)
        if tc is not None:
            nonempty = df[tc].astype(str).str.strip().ne("").sum()
            score = nonempty
            lname = str(p).lower()
            if source_id=="SRC006" and "raw" in lname: score *= 2
            if source_id=="SRC008" and "units" in lname: score *= 3
            if source_id=="SRC003" and "rating" in lname: score *= 2
            cand.append((score,p,df,tc))
    if not cand:
        return None
    cand.sort(key=lambda x:x[0], reverse=True)
    return cand[0]

def sample_stratified(df, target_n, strata_cols):
    if target_n is None or len(df) <= target_n:
        return df.copy()
    strata_cols = [c for c in strata_cols if c in df.columns]
    if not strata_cols:
        return df.sample(target_n, random_state=SEED)
    # proportional with at least one per stratum, deterministic
    groups = list(df.groupby(strata_cols, dropna=False))
    total=len(df)
    pieces=[]
    remaining=target_n
    allocations=[]
    for key,g in groups:
        n=max(1, round(target_n*len(g)/total))
        n=min(n,len(g))
        allocations.append([key,g,n])
    # adjust total
    cur=sum(x[2] for x in allocations)
    while cur>target_n:
        candidates=[x for x in allocations if x[2]>1]
        if not candidates: break
        x=max(candidates,key=lambda z:z[2])
        x[2]-=1; cur-=1
    while cur<target_n:
        candidates=[x for x in allocations if x[2]<len(x[1])]
        if not candidates: break
        x=max(candidates,key=lambda z:len(z[1])-z[2])
        x[2]+=1; cur+=1
    for _,g,n in allocations:
        pieces.append(g.sample(n, random_state=SEED))
    return pd.concat(pieces, ignore_index=True).sample(frac=1,random_state=SEED).reset_index(drop=True)

def quality_flag(t):
    t=norm_text(t)
    if not t: return "empty"
    if len(t)<10: return "short_text"
    if "\ufffd" in t: return "encoding_issue"
    if len(set(t.lower().split())) <= 2 and len(t.split())>6: return "suspected_spam"
    return "pass"

def deterministic_split(h):
    x=int(h[:8],16)%100
    return "train" if x<80 else ("validation" if x<90 else "test")

def harmonize(df, src, text_col, original_id_col=None, source_file=""):
    df=df.copy()
    df=df.drop(columns=pii_columns(df), errors="ignore")
    out=pd.DataFrame(index=df.index)
    out["text"]=df[text_col].map(norm_text)
    out=out[out["text"].str.len()>0].copy()
    # app-aware domain mapping for IGAR
    base_domain=src["domain"]; base_sub=src["subdomain"]
    out["domain"]=base_domain
    out["subdomain"]=base_sub
    if src["source_id"]=="SRC003":
        appcol=infer_column(df.columns,["app","app_name","application"])
        if appcol:
            apps=df.loc[out.index,appcol].astype(str).str.lower()
            domains=[]; subs=[]
            for a in apps:
                pair=next((v for k,v in APP_DOMAIN_MAP.items() if k in a), (base_domain,base_sub))
                domains.append(pair[0]); subs.append(pair[1])
            out["domain"]=domains; out["subdomain"]=subs
    out["genre"]=src["genre"]
    out["source_id"]=src["source_id"]
    out["source_repository"]=src["provider"]
    out["source_dataset"]=src["name"]
    out["source_version"]=src["version"]
    out["source_platform"]=""
    if original_id_col and original_id_col in df.columns:
        out["original_id"]=df.loc[out.index,original_id_col].astype(str)
    else:
        out["original_id"]=""
    out["language"]="id"
    # date/year if discoverable
    datecol=infer_column(df.columns,["date","timestamp","created_at","at","purchase_date","tanggal"])
    if datecol:
        dates=pd.to_datetime(df.loc[out.index,datecol], errors="coerce")
        out["year"]=dates.dt.year.astype("Int64")
    else:
        out["year"]=pd.Series([pd.NA]*len(out), index=out.index, dtype="Int64")
    # preserve original label/task only
    labcol=infer_column(df.columns,["sentiment","label","vader_label","labelScoreBase","class"])
    if labcol:
        out["original_task"]="source_label"
        out["original_label"]=df.loc[out.index,labcol].astype(str)
        out["original_label_type"]=str(labcol)
    else:
        out["original_task"]=""
        out["original_label"]=""
        out["original_label_type"]=""
    out["license"]=src["license"]
    out["provenance_note"]=f'{src["source_id"]}; source_file={source_file}'
    out["char_count"]=out["text"].str.len()
    out["word_count"]=out["text"].str.split().str.len()
    out["quality_flag"]=out["text"].map(quality_flag)
    out["duplicate_group"]=out["text"].map(text_hash)
    out["split"]=out["duplicate_group"].map(deterministic_split)
    codes = {
      "education":"EDU","health_healthcare":"HLT","finance_banking":"FIN",
      "government_public_services":"GOV","ecommerce_retail":"ECO",
      "transportation_mobility":"TRN","tourism_hospitality":"TOU",
      "law_governance":"LAW"
    }
    seq=np.arange(1,len(out)+1)
    out["imd_id"]=[f'IMD-{codes.get(d,"OTH")}-{src["source_id"]}-{i:08d}' for d,i in zip(out["domain"],seq)]
    cols=["imd_id","text","domain","subdomain","genre","source_id","source_repository",
          "source_dataset","source_version","source_platform","original_id","language","year",
          "original_task","original_label","original_label_type","license","provenance_note",
          "char_count","word_count","quality_flag","duplicate_group","split"]
    return out[cols].reset_index(drop=True)

def load_hf_bse(src, raw_dir):
    from datasets import load_dataset
    ds=load_dataset(src["identifier"])
    df=ds["train"].to_pandas()
    raw_file=raw_dir/f'{src["source_id"]}_bse_raw.parquet'
    df.to_parquet(raw_file,index=False)
    return df, raw_file

def process_source(src, root):
    raw=root/"02_raw_sources"/src["source_id"]
    harm=root/"03_harmonized"/"source_level"
    raw.mkdir(parents=True,exist_ok=True); harm.mkdir(parents=True,exist_ok=True)
    if src["provider"]=="huggingface":
        df, source_file = load_hf_bse(src, raw)
        tc=infer_column(df.columns,src["text_candidates"].split("|"))
        ic=infer_column(df.columns,src["id_candidates"].split("|")) if src["id_candidates"] else None
    else:
        version=str(src["version"])
        try:
            mendeley_download_recursive(src["identifier"],version,raw)
        except Exception as e:
            if src["source_id"]=="SRC002" and version!="1":
                print("Retry telemedicine with v1:",e)
                version="1"
                src=dict(src);src["version"]="1"
                mendeley_download_recursive(src["identifier"],version,raw)
            else:
                raise
        unpack_archives(raw)
        tables=read_tables(raw)
        best=choose_best_table(tables,src["text_candidates"].split("|"),src["source_id"])
        if best is None:
            print("No suitable text table for",src["source_id"])
            for p,df0 in tables[:10]:
                print(" ",p, list(df0.columns), len(df0))
            return None
        _,source_file,df,tc=best
        ic=infer_column(df.columns,src["id_candidates"].split("|")) if src["id_candidates"] else None

        # Travel: aggressively avoid ground-truth/reference summary tables
        if src["source_id"]=="SRC007":
            lname=str(source_file).lower()
            if any(k in lname for k in ("ground","summary","reference")):
                alternatives=[]
                for p,d in tables:
                    tc2=infer_column(d.columns,src["text_candidates"].split("|"))
                    if tc2 and not any(k in str(p).lower() for k in ("ground","summary","reference")):
                        alternatives.append((len(d),p,d,tc2))
                if alternatives:
                    alternatives.sort(reverse=True,key=lambda x:x[0])
                    _,source_file,df,tc=alternatives[0]

    # dedup exact before sampling
    work=df.copy()
    work["_tmp_text"]=work[tc].map(norm_text)
    work=work[work["_tmp_text"].str.len()>0].copy()
    work["_tmp_hash"]=work["_tmp_text"].map(text_hash)
    work=work.drop_duplicates("_tmp_hash",keep="first").drop(columns=["_tmp_text","_tmp_hash"])
    # infer strata
    strata=[]
    for cand in ["app","app_name","rating","score","product_id","category","mata_pelajaran","kelas","year","type","jenis"]:
        c=infer_column(work.columns,[cand])
        if c and c not in strata: strata.append(c)
    work=sample_stratified(work,src["target_n"],strata[:3])
    out=harmonize(work,src,tc,ic,str(source_file))
    out=out[out["quality_flag"]!="empty"].copy()
    outpath=harm/f'{src["source_id"]}_harmonized.parquet'
    out.to_parquet(outpath,index=False)
    out.to_csv(harm/f'{src["source_id"]}_harmonized.csv',index=False)
    print(src["source_id"],"raw",len(df),"selected",len(work),"core",len(out),"file",source_file)
    return out

def build_all(root: Path, sources):
    for d in ["01_registry","02_raw_sources","03_harmonized/source_level","04_analysis","05_manuscript","06_builder","07_huggingface_release"]:
        (root/d).mkdir(parents=True,exist_ok=True)
    parts=[]
    failures=[]
    for src in sources:
        if not str(src["status"]).startswith("ACCEPT"):
            continue
        print("\n==",src["source_id"],src["name"],"==")
        try:
            out=process_source(dict(src),root)
            if out is not None: parts.append(out)
        except Exception as e:
            print("FAILED",src["source_id"],repr(e))
            failures.append({"source_id":src["source_id"],"error":repr(e)})
    if not parts:
        raise RuntimeError("No source completed.")
    core=pd.concat(parts,ignore_index=True)
    # Cross-source exact duplicate grouping; keep canonical first but preserve report
    core["duplicate_group"]=core["text"].map(text_hash)
    dup_report=core[core.duplicated("duplicate_group",keep=False)].sort_values("duplicate_group")
    dup_report.to_csv(root/"04_analysis"/"exact_duplicate_report.csv",index=False)
    before=len(core)
    core=core.drop_duplicates("duplicate_group",keep="first").reset_index(drop=True)
    # regenerate splits after global dedup
    core["split"]=core["duplicate_group"].map(deterministic_split)
    core.to_parquet(root/"03_harmonized"/"indomultidomain_core_v1.parquet",index=False)
    core.to_csv(root/"03_harmonized"/"indomultidomain_core_v1.csv",index=False)
    for sp in ["train","validation","test"]:
        core[core["split"]==sp].to_parquet(root/"03_harmonized"/f"indomultidomain_{sp}_v1.parquet",index=False)

    # statistics
    source_stats=core.groupby(["source_id","source_dataset"],dropna=False).agg(
        records=("imd_id","count"),words=("word_count","sum"),chars=("char_count","sum"),
        median_words=("word_count","median")
    ).reset_index()
    domain_stats=core.groupby(["domain"],dropna=False).agg(
        records=("imd_id","count"),words=("word_count","sum"),chars=("char_count","sum"),
        median_words=("word_count","median"),sources=("source_id","nunique"),genres=("genre","nunique")
    ).reset_index()
    genre_stats=core.groupby(["genre"],dropna=False).agg(
        records=("imd_id","count"),words=("word_count","sum"),chars=("char_count","sum"),
        median_words=("word_count","median")
    ).reset_index()
    quality_stats=core.groupby(["quality_flag"],dropna=False).size().reset_index(name="records")
    split_stats=core.groupby(["split"],dropna=False).size().reset_index(name="records")
    source_stats.to_csv(root/"04_analysis"/"source_statistics.csv",index=False)
    domain_stats.to_csv(root/"04_analysis"/"domain_statistics.csv",index=False)
    genre_stats.to_csv(root/"04_analysis"/"genre_statistics.csv",index=False)
    quality_stats.to_csv(root/"04_analysis"/"quality_statistics.csv",index=False)
    split_stats.to_csv(root/"04_analysis"/"split_statistics.csv",index=False)

    summary={
        "dataset":"IndoMultiDomain-Core V1",
        "records":int(len(core)),
        "records_before_global_exact_dedup":int(before),
        "domains":int(core.domain.nunique()),
        "genres":int(core.genre.nunique()),
        "sources":int(core.source_id.nunique()),
        "words":int(core.word_count.sum()),
        "characters":int(core.char_count.sum()),
        "failures":failures,
    }
    (root/"04_analysis"/"build_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")

    # release manifest + dataset card starter
    pd.DataFrame(sources).to_csv(root/"07_huggingface_release"/"source_manifest.csv",index=False)
    card=f"""---
language:
- id
license: other
pretty_name: IndoMultiDomain-Core V1
---

# IndoMultiDomain-Core V1

A provenance-aware, harmonized, multi-domain corpus of natural Indonesian digital text.

## Build summary

- Records: {summary['records']:,}
- Domains: {summary['domains']}
- Genres: {summary['genres']}
- Source datasets included: {summary['sources']}
- Words: {summary['words']:,}

The release is distributed under source-specific licenses. See `source_manifest.csv`.
No new semantic annotation is introduced by IndoMultiDomain V1; original labels are retained only as provenance metadata.

## Core principles
- natural/non-synthetic text
- explicit source provenance
- source-aware controlled sampling
- minimal reversible cleaning
- removal of direct identifier columns
- exact duplicate control
- grouped deterministic train/validation/test splits
"""
    (root/"07_huggingface_release"/"README.md").write_text(card,encoding="utf-8")
    print("\nFINAL SUMMARY")
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    return core,summary

