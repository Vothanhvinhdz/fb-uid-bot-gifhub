import os, asyncio, json, time
import aiohttp
from aiohttp import ClientSession
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

TELEGRAM_TOKEN = os.getenv("7618142601:AAH4_zzpHyy7wjioC9QbBCtXcuNO-roKl8s"")
FB_TOKEN = os.getenv("EAAGNO4a7r2wBPyLgahrnYRBnA4qQKZAlY5aofyumyBqHRhPZCwOzCSevSOiaaGpWCxZABbm9OMeYMghSZA4q3KPfnmcw396tQPGI9cTZAqF9feQn33HJtjj4QqGa3ZCiD7EXZCGZCgxbwPpWFvLCywzZCY74Gd9Aa8xOoWkphBvZAUFrUsap7GrcnOoOjfsWmYSHCJtwZDZD")
CONCURRENCY = int(os.getenv("CONCURRENCY", "6"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "10"))
CACHE_TTL = int(os.getenv("CACHE_TTL", "300"))
MAX_LIST_REPLY = int(os.getenv("MAX_LIST_REPLY", "50"))

_cache = {}
def cache_get(k):
    rec = _cache.get(k)
    if not rec: return None
    if time.time() > rec[1]: del _cache[k]; return None
    return rec[0]
def cache_set(k,v,ttl=CACHE_TTL): _cache[k]=(v,time.time()+ttl)

async def fetch_uid(session: ClientSession, uid: str):
    cached = cache_get(uid)
    if cached: return {**cached, "cached": True}
    url = f"https://graph.facebook.com/{uid}"
    params = {"access_token": FB_TOKEN}
    try:
        async with session.get(url, params=params, timeout=REQUEST_TIMEOUT) as r:
            text = await r.text()
            try: j = json.loads(text)
            except: j = {"raw": text}
            if r.status == 200 and "id" in j:
                res = {"uid": uid, "status":"alive", "data": j}
                cache_set(uid,res); return res
            else:
                err = j.get("error", {})
                code = err.get("code")
                if code == 803:
                    res = {"uid": uid, "status":"dead", "error": err}
                    cache_set(uid,res); return res
                return {"uid": uid, "status":"dead", "error": err or {"http": r.status}}
    except asyncio.TimeoutError:
        return {"uid": uid, "status":"error", "error":"timeout"}
    except Exception as e:
        return {"uid": uid, "status":"error", "error": str(e)}

async def bulk_check(uids):
    sem = asyncio.Semaphore(CONCURRENCY)
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT+5)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async def work(u):
            async with sem:
                return await fetch_uid(session, u)
        tasks = [asyncio.create_task(work(u.strip())) for u in uids if u.strip()]
        return await asyncio.gather(*tasks)

def parse_uids(text): return [p.strip() for p in text.replace(',', '\n').splitlines() if p.strip()]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Gửi danh sách UID (mỗi dòng 1 UID hoặc ngăn cách bằng dấu phẩy) để kiểm tra.")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or '').strip()
    if not text:
        await update.message.reply_text("❌ Không nhận được UID.")
        return
    uids = parse_uids(text)
    await update.message.reply_text(f"🔍 Nhận {len(uids)} UID, đang kiểm tra...")
    results = await bulk_check(uids)
    alive = [r for r in results if r.get('status')=='alive']
    dead = [r for r in results if r.get('status')=='dead']
    err = [r for r in results if r.get('status')=='error']
    summary = f"✅ Hoàn tất. Alive: {len(alive)} | Dead: {len(dead)} | Lỗi: {len(err)}"
    lines = [summary, '']
    def render(items,label):
        if not items: return ''
        out=[f'--- {label} ({min(len(items),MAX_LIST_REPLY)} hiển thị) ---']
        for it in items[:MAX_LIST_REPLY]:
            if it.get('status')=='alive':
                name=it.get('data',{}).get('name')
                fid=it.get('data',{}).get('id')
                out.append(f"{it['uid']} ✅ Alive (id={fid}, name={name})")
            else:
                out.append(f"{it['uid']} ❌ Dead ({it.get('error')})")
        return '\n'.join(out)
    lines.append(render(alive,'ALIVE'))
    lines.append(render(dead,'DEAD'))
    lines.append(render(err,'ERROR'))
    out='\n\n'.join([l for l in lines if l])
    if len(out)>3500:
        await update.message.reply_document(document=out.encode(), filename='fb_check_result.txt')
    else:
        await update.message.reply_text(out)

async def handle_doc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc:
        await update.message.reply_text("Không thấy file.")
        return
    f = await doc.get_file()
    b = await f.download_as_bytearray()
    try: txt=b.decode()
    except: txt=b.decode(errors='ignore')
    uids = parse_uids(txt)
    await update.message.reply_text(f"📄 File có {len(uids)} UID, bắt đầu kiểm tra...")
    results = await bulk_check(uids)
    alive = [r for r in results if r.get('status')=='alive']
    dead = [r for r in results if r.get('status')=='dead']
    await update.message.reply_text(f"Hoàn tất ✅ Alive: {len(alive)}, Dead: {len(dead)}")

def main():
    if not TELEGRAM_TOKEN or not FB_TOKEN:
        print("⚠️ Thiếu TELEGRAM_TOKEN hoặc FB_TOKEN trong GitHub Secrets.")
        return
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_doc))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.run_polling()

if __name__=='__main__':
    main()
