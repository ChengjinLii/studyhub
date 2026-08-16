# StudyHub AI Platform

`ai_platform` contains offline AI research and evaluation code. It is deliberately
separate from the production `backend` and must not connect to StudyHub databases.

Current work:

- [`rag_experiments`](rag_experiments/README.md): read-only RAG corpus, retrieval,
  reranking, evaluation, and visualization experiments.

Production integration is out of scope until an experiment has a reviewed data
contract, permission model, and deployment plan.
