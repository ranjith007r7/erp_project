"""
Unified Intelligence Layer (UIL): plain-English questions over the ERP's
own data, answered by an LLM that can only ever READ a curated, tenant-
scoped set of views. See manifest.py (what the AI may see), safety.py
(what SQL it may run), executor.py (how it runs, tamper-proof org
isolation), and pipeline.py (the question -> answer flow).
"""
