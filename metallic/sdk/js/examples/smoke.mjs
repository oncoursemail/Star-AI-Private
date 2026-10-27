// SDK smoke test (run by metallic/tests/test_api_v1.py against a local server):
//   node smoke.mjs <baseUrl> <serverKey> <webhookSecret> <signatureHeader> <bodyBase64> <now>
import { MetallicApi, MetallicApiError, verifyWebhook } from "../metallic-api.mjs";

const [baseUrl, key, secret, header, bodyB64, now] = process.argv.slice(2);
const anon = new MetallicApi({ baseUrl });
const server = new MetallicApi({ baseUrl, token: key });

const { games } = await anon.listGames();
const beta = await anon.getRelease("beta");
const hb = await server.serverHeartbeat({ game: "RC", server_id: "node-1", players: 3 });
let wrongCredential = 0;
try {
  await server.listFriends();
} catch (err) {
  if (!(err instanceof MetallicApiError)) throw err;
  wrongCredential = err.status;
}
const body = Buffer.from(bodyB64, "base64");
const opts = { now: Number(now) };
console.log(JSON.stringify({
  games: games.length,
  release: beta.components[0].version,
  heartbeat: hb.ok === true,
  wrongCredential,
  webhookSignatureOk: await verifyWebhook(secret, header, new Uint8Array(body), opts),
  tamperedRejected: !(await verifyWebhook(secret, header, new Uint8Array([...body, 32]), opts)),
}));
