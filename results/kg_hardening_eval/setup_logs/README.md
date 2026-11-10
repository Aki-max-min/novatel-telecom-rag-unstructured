# Setup logs

First attempt (files 01-03) ran with the shell's bare `python`, which resolved to the system `C:\Program Files\Python312\python.exe`
that has none of the project's packages (no torch, faiss, ollama, networkx). Step 2 (`graph_builder`) failed there with
`ModuleNotFoundError: No module named 'networkx'`. Nothing was installed.

The project's measurement environment is `.venv_colpali` (Python 3.12.10, torch 2.14.0+cu130, transformers 5.16.1,
sentence-transformers 5.6.0, faiss-cpu 1.15.0, numpy 2.5.2, ollama 0.6.3, networkx 3.6.1), the exact package set recorded in
`results/perf_report/run_manifest.json` for the v3 report. Files 11-13 are the same three commands run with
`.venv_colpali\Scripts\python.exe`; every later command of this evaluation uses that interpreter.
