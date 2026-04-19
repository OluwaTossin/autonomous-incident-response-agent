"""CLI: build FAISS index and run retrieval queries."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.rag.chunking import chunk_documents
from app.rag.config import corpus_data_root, embedding_model as embedding_model_name
from app.rag.config import rag_index_dir
from app.rag.embeddings import embed_texts
from app.rag.index_store import build_index, save_index
from app.rag.loader import load_corpus
from app.rag.retrieve import retrieve


def cmd_build_index(args: argparse.Namespace) -> int:
    root = Path(args.root) if args.root else corpus_data_root()
    docs = load_corpus(root)
    if not docs:
        print("No documents found. Check corpus layout under data/ or workspaces/.../data/.", file=sys.stderr)
        return 1
    chunks = chunk_documents(
        docs,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
    )
    print(f"Loaded {len(docs)} files, {len(chunks)} chunks.", flush=True)
    model = embedding_model_name()
    texts = [c.text for c in chunks]
    print(f"Embedding with model={model!r} …", flush=True)
    vectors = embed_texts(texts, batch_size=args.batch_size, model=model)
    index = build_index(vectors)
    out_dir = Path(args.out) if args.out else rag_index_dir()
    save_index(index, chunks, embedding_model=model, base=out_dir)
    print(f"Wrote index to {out_dir} (dim={index.d}, chunks={len(chunks)}).")
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    hits = retrieve(
        args.query,
        top_k=args.top_k,
        index_dir=Path(args.index_dir) if args.index_dir else rag_index_dir(),
    )
    for i, h in enumerate(hits, 1):
        print(f"--- Hit {i} score={h.score:.4f} type={h.doc_type} source={h.source} ---")
        print(h.text[:2000])
        if len(h.text) > 2000:
            print("… [truncated]")
        print()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Local RAG: build index and query.")
    sub = p.add_subparsers(dest="command", required=True)

    b = sub.add_parser("build-index", help="Load corpus, chunk, embed, save FAISS index")
    b.add_argument("--root", type=str, default="", help="Project root (default: auto-detect)")
    b.add_argument("--out", type=str, default="", help="Index directory (default: RAG_INDEX_DIR)")
    b.add_argument("--chunk-size", type=int, default=900)
    b.add_argument("--chunk-overlap", type=int, default=150)
    b.add_argument("--batch-size", type=int, default=64)
    b.set_defaults(func=cmd_build_index)

    q = sub.add_parser("query", help="Retrieve top-k chunks for a natural language query")
    q.add_argument("query", type=str, help='e.g. "High CPU on payment-api in production"')
    q.add_argument("--top-k", type=int, default=5)
    q.add_argument("--index-dir", type=str, default="", help="Override RAG_INDEX_DIR")
    q.set_defaults(func=cmd_query)

    return p


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


def main_build() -> None:
    raise SystemExit(main(["build-index", *sys.argv[1:]]))


def main_query() -> None:
    raise SystemExit(main(["query", *sys.argv[1:]]))


if __name__ == "__main__":
    raise SystemExit(main())
