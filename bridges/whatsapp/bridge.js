const { Client, LocalAuth } = require("whatsapp-web.js");
const qrcode = require("qrcode-terminal");
const { Pool } = require("pg");

const agentUrl = (process.env.AGENT_URL || "http://agent:8000").replace(/\/$/, "");
const agentApiKey = (process.env.AGENT_API_KEY || (process.env.AGENT_API_KEYS || "").split(",")[0] || "").trim();
const pairingTtlSeconds = Number(process.env.PAIRING_CODE_TTL_SECONDS || "600");
const databaseUrl = process.env.DATABASE_URL || "postgresql://closedclaw:closedclaw@postgres:5432/closedclaw";
const pool = new Pool({ connectionString: databaseUrl });

initDatabase().catch((error) => {
  console.error("Failed to initialize WhatsApp bridge database", error);
  process.exit(1);
});

const client = new Client({
  authStrategy: new LocalAuth(),
  puppeteer: { args: ["--no-sandbox", "--disable-setuid-sandbox"] },
});

client.on("qr", (qr) => qrcode.generate(qr, { small: true }));
client.on("ready", () => console.log("WhatsApp bridge ready"));

client.on("message", async (message) => {
  if (!message.body || message.fromMe) return;
  const senderId = message.author || message.from;
  try {
    if (!(await isAllowed("whatsapp", senderId))) {
      const text = message.body.trim();
      if (/^\d{6}$/.test(text)) {
        const result = await verifyCode("whatsapp", senderId, text);
        if (result.ok) {
          await addSender("whatsapp", senderId);
          await message.reply("Pairing complete. You can now message the agent.");
          return;
        }
        await message.reply(`Pairing failed: ${result.reason}`);
        return;
      }
      const code = await createCode("whatsapp", senderId);
      await message.reply(`Pairing required. Reply with this code within 10 minutes: ${code}`);
      return;
    }
    const response = await fetch(`${agentUrl}/chat`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        ...(agentApiKey ? { authorization: `Bearer ${agentApiKey}` } : {}),
      },
      body: JSON.stringify({
        message: message.body,
        channel: "whatsapp",
        user_id: senderId,
        thread_id: message.from,
        group_id: message.from.endsWith("@g.us") ? message.from : null,
        metadata: { from: message.from, author: message.author, id: message.id?._serialized },
      }),
    });
    const result = await response.json();
    await message.reply(result.response || "Done.");
  } catch (error) {
    console.error(error);
    await message.reply(`Agent error: ${error.message}`);
  }
});

client.initialize();

async function initDatabase() {
  await pool.query(`CREATE TABLE IF NOT EXISTS channel_policy (
    channel TEXT NOT NULL,
    sender_id TEXT NOT NULL,
    added_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(channel, sender_id)
  )`);
  await pool.query(`CREATE TABLE IF NOT EXISTS pairing_requests (
    channel TEXT NOT NULL,
    sender_id TEXT NOT NULL,
    code TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(channel, sender_id)
  )`);
}

async function isAllowed(channel, senderId) {
  const result = await pool.query("SELECT 1 FROM channel_policy WHERE channel = $1 AND sender_id = $2", [channel, String(senderId)]);
  return result.rowCount > 0;
}

async function addSender(channel, senderId) {
  await pool.query(
    `INSERT INTO channel_policy(channel, sender_id, added_at)
     VALUES ($1, $2, now())
     ON CONFLICT(channel, sender_id) DO NOTHING`,
    [channel, String(senderId)],
  );
}

async function createCode(channel, senderId) {
  const code = String(Math.floor(Math.random() * 1000000)).padStart(6, "0");
  const expiresAt = new Date(Date.now() + pairingTtlSeconds * 1000).toISOString();
  await pool.query(
    `INSERT INTO pairing_requests(channel, sender_id, code, expires_at, attempts)
     VALUES ($1, $2, $3, $4, 0)
     ON CONFLICT(channel, sender_id) DO UPDATE
     SET code = excluded.code, expires_at = excluded.expires_at, attempts = 0`,
    [channel, String(senderId), code, expiresAt],
  );
  return code;
}

async function verifyCode(channel, senderId, code) {
  const result = await pool.query("SELECT * FROM pairing_requests WHERE channel = $1 AND sender_id = $2", [channel, String(senderId)]);
  const row = result.rows[0];
  if (!row) return { ok: false, reason: "No pairing request found" };
  if (row.attempts >= 5) {
    await pool.query("DELETE FROM pairing_requests WHERE channel = $1 AND sender_id = $2", [channel, String(senderId)]);
    return { ok: false, reason: "Too many incorrect attempts. Request a new pairing code." };
  }
  if (new Date(row.expires_at) < new Date()) {
    await pool.query("DELETE FROM pairing_requests WHERE channel = $1 AND sender_id = $2", [channel, String(senderId)]);
    return { ok: false, reason: "Pairing code expired" };
  }
  await pool.query("UPDATE pairing_requests SET attempts = attempts + 1 WHERE channel = $1 AND sender_id = $2", [channel, String(senderId)]);
  if (String(row.code) !== String(code).trim()) return { ok: false, reason: "Incorrect pairing code" };
  await pool.query("DELETE FROM pairing_requests WHERE channel = $1 AND sender_id = $2", [channel, String(senderId)]);
  return { ok: true, reason: "paired" };
}
