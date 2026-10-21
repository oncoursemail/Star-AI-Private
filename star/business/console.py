"""Serve STAR Commerce OS at http://127.0.0.1:8787 .

Run with: python -m star.business.console [--port 8787] [--db ~/.star-commerce/state.db]
No external networking, marketplace writes, or payments.
"""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from urllib.parse import urlparse, unquote

from .workforce import (artifact_path, init_db, queue_pipeline, record_expense,
                        review_offer, run_all, snapshot)

UI = Path(__file__).resolve().parent.parent / "data" / "business" / "console_ui.html"  # star/data is bundled by both Windows builds
MAX_BODY = 24_000


def create_handler(db, lock: threading.RLock):
    class Handler(BaseHTTPRequestHandler):
        server_version = "STAR-Commerce/0.1"

        def log_message(self, fmt, *args):
            # Avoid persisting browser requests / potential query data.
            pass

        def _reply(self, status: int, content: bytes, content_type="application/json; charset=utf-8",
                   extra=None):
            self.send_response(status)
            self.send_header("Content-Type",content_type)
            self.send_header("Content-Length",str(len(content)))
            self.send_header("Cache-Control","no-store")
            self.send_header("X-Content-Type-Options","nosniff")
            self.send_header("X-Frame-Options","DENY")
            self.send_header("Referrer-Policy","no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; connect-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'")
            for k,v in (extra or {}).items(): self.send_header(k,v)
            self.end_headers()
            self.wfile.write(content)

        def _json(self,status: int, obj):
            self._reply(status,json.dumps(obj,ensure_ascii=False).encode("utf-8"))

        def do_GET(self):
            route=urlparse(self.path).path
            if route in ("/","/index.html"):
                self._reply(200,UI.read_bytes(),"text/html; charset=utf-8")
            elif route=="/api/state":
                with lock: state=snapshot(db)
                self._json(200,state)
            elif route.startswith("/download/"):
                offer_id=unquote(route[len("/download/"):])
                try:
                    with lock: path=artifact_path(db,offer_id)
                    contents=path.read_bytes()
                    self._reply(200,contents,"application/zip",{
                        "Content-Disposition":f'attachment; filename="{path.name}"'})
                except (ValueError,OSError,FileNotFoundError): self._json(404,{"error":"Not found"})
            else:
                self._json(404,{"error":"Not found"})

        def do_POST(self):
            route=urlparse(self.path).path
            origin=self.headers.get("Origin","")
            host=self.headers.get("Host","")
            if (self.headers.get("X-Star-Action")!="1" or
                not origin or urlparse(origin).hostname not in ("127.0.0.1","localhost") or
                urlparse(origin).netloc != host or
                self.headers.get("Content-Type","").split(";",1)[0]!="application/json"):
                return self._json(403,{"error":"Origin / local action check failed"})
            length=int(self.headers.get("Content-Length","0") or 0)
            if not 0 < length <= MAX_BODY:
                return self._json(413,{"error":"Invalid request size"})
            try:
                payload=json.loads(self.rfile.read(length))
                if not isinstance(payload,dict): raise ValueError("Expected an object")
                with lock:
                    if route=="/api/queue":
                        result={"jobs":queue_pipeline(db,payload.get("offer_id",""))}
                    elif route=="/api/run":
                        result={"steps":run_all(db,limit=12)}
                    elif route=="/api/review":
                        review_offer(db,payload.get("offer_id",""),payload.get("rights_evidence",""))
                        result={"saved":True,"marketplace_published":False}
                    elif route=="/api/expense":
                        record_expense(db,payload.get("business_id",""),
                                       payload.get("category",""),payload.get("amount_cents",-1),
                                       payload.get("memo",""))
                        result={"saved":True,"source":"owner_entered"}
                    else: return self._json(404,{"error":"Unknown API endpoint"})
                self._json(200,result)
            except (KeyError,ValueError,TypeError) as e:
                self._json(400,{"error":str(e)[:200]})
            except Exception:
                self._json(500,{"error":"Internal failure; no marketplace action was taken"})

    return Handler


def main(argv=None):
    parser=argparse.ArgumentParser(description="Local STAR commerce draft console")
    parser.add_argument("--port",type=int,default=8787)
    parser.add_argument("--db",default=str(Path.home()/".star-commerce"/"state.db"))
    parser.add_argument("--worker",action="store_true",help="Run queued jobs repeatedly, no web dashboard")
    parser.add_argument("--once",action="store_true",help="Process queued jobs once and exit")
    parser.add_argument("--interval",type=int,default=60)
    args=parser.parse_args(argv)
    if not 1024 <= args.port <= 65535: parser.error("port must be 1024-65535")
    if not 5 <= args.interval <= 3600: parser.error("interval must be 5-3600 seconds")
    db=init_db(args.db)
    if args.once:
        print(json.dumps(run_all(db)))
        return 0
    if args.worker:
        import time
        print("Internal draft worker active; Ctrl+C stops. No marketplace calls.")
        try:
            while True:
                completed=run_all(db)
                if completed: print(json.dumps(completed),flush=True)
                time.sleep(args.interval)
        except KeyboardInterrupt: pass
        return 0
    if not UI.is_file(): parser.error("UI file missing")
    server=ThreadingHTTPServer(("127.0.0.1",args.port),create_handler(db,threading.RLock()))
    print(f"STAR Commerce OS: http://127.0.0.1:{args.port}",flush=True)
    print("LOCAL DRAFT MODE. No marketplaces, ads, production or payments are connected.",flush=True)
    try: server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt: pass
    finally: server.server_close();db.close()
    return 0


if __name__=="__main__": raise SystemExit(main())
