// Node webhook receiver: check the signature on the raw body before trusting anything in it.
//   METALLIC_WEBHOOK_SECRET=whsec_... node webhook-receiver.mjs
import { createServer } from "node:http";
import { verifyWebhook } from "../metallic-api.mjs";

const secret = process.env.METALLIC_WEBHOOK_SECRET;
const seen = new Set(); // deliveries are retried: de-duplicate on the event id

createServer((req, res) => {
  const chunks = [];
  req.on("data", (c) => chunks.push(c));
  req.on("end", async () => {
    const raw = new Uint8Array(Buffer.concat(chunks));
    if (!(await verifyWebhook(secret, req.headers["metallic-signature"] ?? "", raw))) {
      res.writeHead(401).end();
      return;
    }
    const event = JSON.parse(Buffer.from(raw).toString("utf8"));
    res.writeHead(204).end(); // answer fast, work after
    if (seen.has(event.id)) return;
    seen.add(event.id);
    console.log(event.type, event.data);
  });
}).listen(8787, "127.0.0.1");
