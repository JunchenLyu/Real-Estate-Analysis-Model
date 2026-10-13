"""Module 2: 金融知识库 RAG —— 文档切片 + Embedding + 向量检索（Chroma），带本地关键词降级方案"""
import hashlib
import json
import re
from pathlib import Path

from ..config import KB_DOCS_DIR, KB_STORE_DIR, KB_CHUNKS_FILE

CATEGORY_RULES = [
    ("模型资料", ["投入产出", "模型", "量化", "传导机制", "指标体系"]),
    ("政策文件", ["政策", "红线", "贷款", "首付", "监管", "保交楼"]),
    ("风险案例", ["案例", "日本", "美国", "恒大", "海南", "次贷", "泡沫", "危机"]),
    ("研究论文", ["产业链", "结构", "研究", "带动效应"]),
]

_chroma_col = None
_fallback_chunks: list[dict] = []
_EMBED_NAME = "offline-bigram"


class OfflineBiGramEmbedding:
    """离线嵌入函数：中文 bigram + 英文词 → 哈希词袋向量（512维，L2归一化）。
    优势：零模型下载、零网络依赖、毫秒级计算，且完全规避 Chroma 默认
    embedding 需从 AWS S3 下载 ONNX 模型（约80MB）的网络问题。"""
    DIM = 512

    @staticmethod
    def _embed_one(text: str) -> list[float]:
        import hashlib
        vec = [0.0] * OfflineBiGramEmbedding.DIM
        for kw in _keywords(text):
            h = int(hashlib.md5(kw.encode("utf-8")).hexdigest(), 16) % OfflineBiGramEmbedding.DIM
            vec[h] += 1.0
        norm = sum(v * v for v in vec) ** 0.5 or 1.0
        return [v / norm for v in vec]

    def __call__(self, input):  # chromadb EmbeddingFunction 协议
        return [self._embed_one(t) for t in input]

    def name(self) -> str:
        return "offline-bigram-512"


def _get_embedding_function():
    """优先 MiniLM 深度语义嵌入（模型已本地缓存时），否则回退离线 bigram。
    MiniLM: 384维 sentence-transformer 语义向量，检索质量显著优于词袋。"""
    global _EMBED_NAME
    try:
        from pathlib import Path as _P
        cache = _P.home() / ".cache" / "chroma" / "onnx_models" / "all-MiniLM-L6-v2" / "onnx.tar.gz"
        if not cache.exists() or cache.stat().st_size < 70 * 1024 * 1024:
            raise FileNotFoundError("MiniLM 模型未缓存")
        from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2
        _EMBED_NAME = "minilm-semantic-384"
        return ONNXMiniLM_L6_V2()
    except Exception:
        _EMBED_NAME = "offline-bigram-512"
        return OfflineBiGramEmbedding()


def _category_of(text: str, source: str) -> str:
    for cat, kws in CATEGORY_RULES:
        if any(k in text or k in source for k in kws):
            return cat
    return "知识文档"


def _split_chunks(text: str, size: int = 320, overlap: int = 60) -> list[str]:
    """按段落聚合切片"""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks, buf = [], ""
    for p in paras:
        if len(buf) + len(p) <= size:
            buf += ("\n" if buf else "") + p
        else:
            if buf:
                chunks.append(buf)
            while len(p) > size:  # 超长段落硬切
                chunks.append(p[:size])
                p = p[size - overlap:]
            buf = p
    if buf:
        chunks.append(buf)
    return chunks


def build_knowledge_base() -> dict:
    """扫描 documents/ 目录，切片并向量化入库（同时缓存切片供降级检索）"""
    global _chroma_col, _fallback_chunks
    chunks = []
    for f in sorted(KB_DOCS_DIR.glob("*.md")):
        text = f.read_text(encoding="utf-8")
        for i, ch in enumerate(_split_chunks(text)):
            chunks.append({
                "id": f"{f.stem}_{i}",
                "text": ch,
                "source": f.name,
                "category": _category_of(ch, f.name),
                "content_hash": hashlib.sha256(ch.encode("utf-8")).hexdigest()[:16],
            })

    KB_CHUNKS_FILE.write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")
    _fallback_chunks = chunks

    status = {"chunks": len(chunks), "vector_db": "keyword-fallback"}
    try:
        import chromadb
        ef = _get_embedding_function()
        client = chromadb.PersistentClient(path=str(KB_STORE_DIR / "chroma"))
        col = client.get_or_create_collection(
            "real_estate_kb", metadata={"hnsw:space": "cosine"}, embedding_function=ef)
        # 嵌入模型变更或内容变化 → 重建向量库
        rebuild = col.count() != len(chunks)
        if not rebuild:
            stored = col.get()
            metadata = dict(zip(stored.get("ids") or [], stored.get("metadatas") or []))
            rebuild = any(
                (metadata.get(c["id"]) or {}).get("embed") != _EMBED_NAME
                or (metadata.get(c["id"]) or {}).get("content_hash") != c["content_hash"]
                for c in chunks
            )
        if rebuild:
            if col.count():
                client.delete_collection("real_estate_kb")
                col = client.get_or_create_collection(
                    "real_estate_kb", metadata={"hnsw:space": "cosine"}, embedding_function=ef)
            # 分批插入（大批量一次性 add 会触发 Chroma InternalError）
            B = 500
            for i in range(0, len(chunks), B):
                batch = chunks[i:i + B]
                col.add(
                    ids=[c["id"] for c in batch],
                    documents=[c["text"] for c in batch],
                    metadatas=[{"source": c["source"], "category": c["category"],
                                "embed": _EMBED_NAME, "content_hash": c["content_hash"]} for c in batch],
                )
        _chroma_col = col
        status["vector_db"] = f"chroma ({col.count()} vectors, hybrid: {_EMBED_NAME} + bigram)"
    except Exception as e:  # 无 chroma → 降级
        status["vector_db"] = f"keyword-fallback ({type(e).__name__})"
    return status


def _keywords(text: str) -> set:
    """中文 bigram + 英文单词，保证短查询与长文本可重叠匹配"""
    kws = set()
    for run in re.findall(r"[\u4e00-\u9fa5]+", text):
        if len(run) == 1:
            kws.add(run)
        else:
            kws.update(run[i:i + 2] for i in range(len(run) - 1))
    kws.update(re.findall(r"[A-Za-z]{3,}", text))
    return kws


def _keyword_search(query: str, top_k: int) -> list[dict]:
    """降级方案：关键词重叠打分（bigram 匹配 + 停用词过滤）"""
    STOP = {"分析", "影响", "如何", "什么", "进行", "以及", "对于", "当前", "系统",
            "问题", "相关", "回答", "一下", "帮我", "哪些", "造成", "冲击大", "请给"}
    qkws = _keywords(query) - STOP
    if not qkws:
        qkws = _keywords(query)
    if not _fallback_chunks:
        if KB_CHUNKS_FILE.exists():
            globals()["_fallback_chunks"] = json.loads(KB_CHUNKS_FILE.read_text(encoding="utf-8"))
        else:
            build_knowledge_base()
    scored = []
    for c in _fallback_chunks:
        ckws = _keywords(c["text"])
        score = len(qkws & ckws) / (len(qkws) + 1e-9)
        if score > 0:
            scored.append((score, c))
    scored.sort(key=lambda x: -x[0])
    return [dict(c, score=round(s, 3)) for s, c in scored[:top_k]]


SYNONYMS = {  # 口语词 → 知识库术语（查询扩展）
    "楼市": "房地产 房价", "房市": "房地产 房价", "地产": "房地产",
    "房子": "房地产 住宅", "买房": "商品房 销售", "房价": "价格 销售",
    "出问题": "风险 危机", "爆雷": "违约 危机", "暴雷": "违约 危机",
}


def _expand_query(query: str) -> str:
    extra = [v for k, v in SYNONYMS.items() if k in query]
    return query + " " + " ".join(extra) if extra else query


def search(query: str, top_k: int = 4) -> list[dict]:
    """混合检索（Hybrid Search）：MiniLM 语义向量 + bigram 关键词两路召回，
    RRF（Reciprocal Rank Fusion）融合排名。
    - 语义路：捕获同义改写（"楼市要出问题"≈"风险"），但中文能力弱
    - 关键词路：中文精确匹配强（"三道红线"直接命中政策文件）
    """
    semantic = []
    if _chroma_col is not None:
        try:
            res = _chroma_col.query(query_texts=[query], n_results=top_k * 2)
            for i in range(len(res["ids"][0])):
                semantic.append({
                    "text": res["documents"][0][i],
                    "source": res["metadatas"][0][i].get("source", ""),
                    "category": res["metadatas"][0][i].get("category", ""),
                    "score": round(1 - res["distances"][0][i], 3),
                })
        except Exception:
            semantic = []
    keyword = _keyword_search(_expand_query(query), top_k * 2)

    if not semantic:
        return keyword[:top_k]
    if not keyword:
        return semantic[:top_k]

    # RRF 融合：score = Σ w/(k + rank)，关键词路加权1.5x（中文精确匹配优先）
    K = 60
    scores, items = {}, {}
    for lst, w in ((semantic, 1.0), (keyword, 1.5)):
        for rank, item in enumerate(lst):
            key = item["text"][:80]
            scores[key] = scores.get(key, 0) + w / (K + rank + 1)
            items[key] = item
    fused = sorted(scores.items(), key=lambda x: -x[1])[:top_k]
    out = []
    for key, s in fused:
        it = dict(items[key])
        it["score"] = round(s, 4)
        out.append(it)
    return out
