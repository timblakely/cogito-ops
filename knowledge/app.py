"""Shared RAG retrieval API and Streamable HTTP MCP endpoint."""
import asyncio, hashlib, json, os, re, sys
from contextlib import asynccontextmanager

import asyncpg, httpx, jwt, yaml
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

DB = os.getenv("DATABASE_URL", "")
EMBEDDINGS = os.getenv("EMBEDDING_URL", "http://knowledge-embeddings:8000/v1")
MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
OIDC_ISSUER = os.getenv("OIDC_ISSUER", "")
OIDC_AUDIENCE = os.getenv("OIDC_AUDIENCE", "knowledge")
RESOURCE_URL = os.getenv("RESOURCE_URL", "")
ADMIN_GROUP = os.getenv("ADMIN_GROUP", "knowledge-admins")
READER_GROUP = os.getenv("READER_GROUP", "knowledge-readers")

SCHEMA = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS sources (id text PRIMARY KEY, uri text NOT NULL, title text,
  fingerprint text NOT NULL, model text NOT NULL, indexed_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS chunks (source_id text NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  ordinal integer NOT NULL, content text NOT NULL, embedding vector(1024) NOT NULL,
  PRIMARY KEY (source_id, ordinal));
CREATE INDEX IF NOT EXISTS chunks_embedding_idx ON chunks USING hnsw (embedding vector_cosine_ops);
"""

class Ingest(BaseModel):
    uri: str
    title: str = ""
    content: str = Field(min_length=1)

class Search(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=5, ge=1, le=20)

def chunks(text: str, size: int = 4000, overlap: int = 600):
    text = re.sub(r"\s+", " ", text).strip()
    return [text[i:i + size] for i in range(0, len(text), size - overlap)]

async def embed(inputs):
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(f"{EMBEDDINGS}/embeddings", json={"model": MODEL, "input": inputs})
        r.raise_for_status()
    vectors = [x["embedding"] for x in r.json()["data"]]
    if any(len(v) != 1024 for v in vectors): raise RuntimeError("embedding model did not return 1024 dimensions")
    return vectors

async def claims(authorization: str | None):
    if not OIDC_ISSUER: return {"groups": [ADMIN_GROUP, READER_GROUP]}
    if not authorization or not authorization.startswith("Bearer "):
        metadata = f'{RESOURCE_URL}/.well-known/oauth-protected-resource' if RESOURCE_URL else ""
        raise HTTPException(401, "Bearer token required", headers={"WWW-Authenticate": f'Bearer resource_metadata="{metadata}"'})
    async with httpx.AsyncClient(timeout=10) as client:
        config = (await client.get(f"{OIDC_ISSUER}/.well-known/openid-configuration")).json()
        jwks = (await client.get(config["jwks_uri"])).json()
    key = jwt.PyJWKClient(config["jwks_uri"]).get_signing_key_from_jwt(authorization[7:]).key
    return jwt.decode(authorization[7:], key, algorithms=["RS256", "ES256"], audience=OIDC_AUDIENCE, issuer=OIDC_ISSUER)

async def require(authorization, admin=False):
    c = await claims(authorization); groups = set(c.get("groups", []))
    if (ADMIN_GROUP if admin else READER_GROUP) not in groups: raise HTTPException(403, "insufficient role")
    return c

async def ingest(pool, item: Ingest):
    body = item.content.encode(); digest = hashlib.sha256(body).hexdigest(); sid = hashlib.sha256(item.uri.encode()).hexdigest()
    parts = chunks(item.content); vectors = await embed(parts)
    async with pool.acquire() as conn:
        async with conn.transaction():
            old = await conn.fetchval("SELECT fingerprint FROM sources WHERE id=$1", sid)
            if old == digest: return {"source_id": sid, "chunks": 0, "unchanged": True}
            await conn.execute("INSERT INTO sources(id,uri,title,fingerprint,model) VALUES($1,$2,$3,$4,$5) ON CONFLICT(id) DO UPDATE SET uri=$2,title=$3,fingerprint=$4,model=$5,indexed_at=now()", sid,item.uri,item.title,digest,MODEL)
            await conn.execute("DELETE FROM chunks WHERE source_id=$1", sid)
            await conn.executemany("INSERT INTO chunks(source_id,ordinal,content,embedding) VALUES($1,$2,$3,$4::vector)", [(sid,i,p,json.dumps(v)) for i,(p,v) in enumerate(zip(parts,vectors))])
    return {"source_id": sid, "chunks": len(parts), "unchanged": False}

async def search(pool, request: Search):
    vector = json.dumps((await embed([request.query]))[0])
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT s.uri,s.title,c.content,1-(c.embedding <=> $1::vector) AS score,s.indexed_at FROM chunks c JOIN sources s ON s.id=c.source_id ORDER BY c.embedding <=> $1::vector LIMIT $2", vector, request.limit)
    return [{"source": r["uri"], "title": r["title"], "excerpt": r["content"][:800], "score": round(float(r["score"]),4), "indexed_at": r["indexed_at"].isoformat()} for r in rows]

@asynccontextmanager
async def lifespan(app):
    app.state.pool = await asyncpg.create_pool(DB, min_size=1, max_size=8)
    async with app.state.pool.acquire() as c: await c.execute(SCHEMA)
    yield
    await app.state.pool.close()

app = FastAPI(lifespan=lifespan)
@app.get("/healthz")
async def healthz(): return {"ok": True, "model": MODEL}
@app.get("/.well-known/oauth-protected-resource")
async def protected_resource_metadata():
    return {"resource": RESOURCE_URL, "authorization_servers": [OIDC_ISSUER], "scopes_supported": ["knowledge.read", "knowledge.admin"]}
@app.post("/v1/search")
async def api_search(request: Search, authorization: str | None = Header(default=None)):
    await require(authorization); return {"data": await search(app.state.pool, request)}
@app.post("/v1/ingest")
async def api_ingest(item: Ingest, authorization: str | None = Header(default=None)):
    await require(authorization, True); return await ingest(app.state.pool, item)
@app.post("/mcp")
async def mcp(body: dict, authorization: str | None = Header(default=None)):
    await require(authorization); method, ident = body.get("method"), body.get("id")
    if method == "initialize": result = {"protocolVersion":"2025-03-26","capabilities":{"tools":{}},"serverInfo":{"name":"knowledge","version":"1.0"}}
    elif method == "tools/list": result = {"tools":[{"name":"knowledge_search","description":"Search the shared knowledge corpus and return cited excerpts.","inputSchema":{"type":"object","properties":{"query":{"type":"string"},"limit":{"type":"integer","default":5}},"required":["query"]}}]}
    elif method == "tools/call" and body.get("params",{}).get("name") == "knowledge_search":
        data = await search(app.state.pool, Search(**body["params"].get("arguments",{}))); result = {"content":[{"type":"text","text":json.dumps(data)}]}
    else: return {"jsonrpc":"2.0","id":ident,"error":{"code":-32601,"message":"method not found"}}
    return {"jsonrpc":"2.0","id":ident,"result":result}

async def catalog():
    pool = await asyncpg.create_pool(DB); data = yaml.safe_load(open(os.getenv("SOURCES_FILE", "/config/sources.yaml"))) or {}
    for source in data.get("web", []):
        async with httpx.AsyncClient(timeout=180) as client:
            r = await client.post(f"{os.environ['FIRECRAWL_URL']}/v2/scrape", json={"url":source["url"],"formats":["markdown"]}); r.raise_for_status()
        payload=r.json()["data"]; await ingest(pool, Ingest(uri=source["url"], title=payload.get("metadata",{}).get("title",source["url"]), content=payload["markdown"]))
    # OpenCloud exposes the RAG Inbox through WebDAV.  A depth-infinity listing
    # is intentionally restricted to this dedicated folder; fingerprints make
    # polling idempotent and avoid downloading unchanged files into the corpus.
    if os.getenv("WEBDAV_URL"):
        from urllib.parse import unquote, urljoin
        auth=(os.environ["WEBDAV_USERNAME"], os.environ["WEBDAV_PASSWORD"])
        headers={"Depth":"infinity"}
        async with httpx.AsyncClient(timeout=180, auth=auth) as client:
            listing=await client.request("PROPFIND", os.environ["WEBDAV_URL"], headers=headers)
            listing.raise_for_status()
            hrefs=re.findall(r"<[^>]*href[^>]*>(.*?)</[^>]*href>", listing.text, flags=re.I)
            for href in hrefs:
                if href.endswith("/") or not re.search(r"\.(pdf|docx?|pptx?|xlsx?|epub|txt|md)$", href, re.I): continue
                uri=urljoin(os.environ["WEBDAV_URL"], href)
                file=await client.get(uri); file.raise_for_status()
                parsed=await client.put(os.getenv("TIKA_URL", "http://knowledge-tika:9998/tika"), content=file.content, headers={"Accept":"text/plain"})
                parsed.raise_for_status()
                await ingest(pool, Ingest(uri=unquote(uri), title=unquote(href.rsplit("/",1)[-1]), content=parsed.text))
    await pool.close()

if __name__ == "__main__":
    if len(sys.argv)>1 and sys.argv[1]=="ingest-catalog": asyncio.run(catalog())
    else:
        import uvicorn; uvicorn.run(app, host="0.0.0.0", port=8080)
