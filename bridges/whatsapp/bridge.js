const { Client, LocalAuth } = require("whatsapp-web.js");
const qrcode = require("qrcode-terminal");
const fs = require("fs");
const path = require("path");
const yaml = require("js-yaml");
const sqlite3 = require("sqlite3").verbose();

const agentUrl = (process.env.AGENT_URL || "http://agent:8000").replace(/\/$/, "");
const agentApiKey = (process.env.AGENT_API_KEY || (process.env.AGENT_API_KEYS || "").split(",")[0] || "").trim();
const policyPath = process.env.CHANNEL_POLICY_PATH || "channel_policy.yaml";
const pairingDbPath = process.env.PAIRING_DB_PATH || "memory/pairing_requests.db";
const pairingTtlSeconds = Number(process.env.PAIRING_CODE_TTL_SECONDS || "600");

fs.mkdirSync(path.dirname(pairingDbPath), { recursive: true });
const pairingDb = new sqlite3.Database(pairingDbPath);
pairingDb.serialize(() => {
  pairingDb.run(`CREATE TABLE IF NOT EXISTS pairing_requests (
    channel TEXT NOT NULL,
    sender_id TEXT NOT NULL,
    code TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(channel, sender_id)
  )`);
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
    if (!isAllowed("whatsapp", senderId)) {
      const text = message.body.trim();
      if (/^\d{6}$/.test(text)) {
        const result = await verifyCode("whatsapp", senderId, text);
        if (result.ok) {
          addSender("whatsapp", senderId);
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

function loadPolicy() {
  if (!fs.existsSync(policyPath)) {
    fs.writeFileSync(policyPath, yaml.dump({ channels: { slack: { allowed_senders: [] }, telegram: { allowed_senders: [] }, whatsapp: { allowed_senders: [] } } }));
  }
  return yaml.load(fs.readFileSync(policyPath, "utf8")) || {};
}

function savePolicy(policy) {
  fs.writeFileSync(policyPath, yaml.dump(policy, { sortKeys: true }));
}

function isAllowed(channel, senderId) {
  const policy = loadPolicy();
  const allowed = (((policy.channels || {})[channel] || {}).allowed_senders || []).map(String);
  return allowed.includes(String(senderId));
}

function addSender(channel, senderId) {
  const policy = loadPolicy();
  policy.channels = policy.channels || {};
  policy.channels[channel] = policy.channels[channel] || {};
  policy.channels[channel].allowed_senders = policy.channels[channel].allowed_senders || [];
  if (!policy.channels[channel].allowed_senders.map(String).includes(String(senderId))) {
    policy.channels[channel].allowed_senders.push(String(senderId));
  }
  savePolicy(policy);
}

function createCode(channel, senderId) {
  const code = String(Math.floor(Math.random() * 1000000)).padStart(6, "0");
  const expiresAt = new Date(Date.now() + pairingTtlSeconds * 1000).toISOString();
  return new Promise((resolve, reject) => {
    pairingDb.run(
      `INSERT INTO pairing_requests(channel, sender_id, code, expires_at, attempts)
       VALUES (?, ?, ?, ?, 0)
       ON CONFLICT(channel, sender_id) DO UPDATE
       SET code = excluded.code, expires_at = excluded.expires_at, attempts = 0`,
      [channel, senderId, code, expiresAt],
      (error) => (error ? reject(error) : resolve(code)),
    );
  });
}

function verifyCode(channel, senderId, code) {
  return new Promise((resolve, reject) => {
    pairingDb.get(
      "SELECT * FROM pairing_requests WHERE channel = ? AND sender_id = ?",
      [channel, senderId],
      (error, row) => {
        if (error) return reject(error);
        if (!row) return resolve({ ok: false, reason: "No pairing request found" });
        if (new Date(row.expires_at) < new Date()) {
          pairingDb.run("DELETE FROM pairing_requests WHERE channel = ? AND sender_id = ?", [channel, senderId]);
          return resolve({ ok: false, reason: "Pairing code expired" });
        }
        pairingDb.run("UPDATE pairing_requests SET attempts = attempts + 1 WHERE channel = ? AND sender_id = ?", [channel, senderId]);
        if (String(row.code) !== String(code).trim()) return resolve({ ok: false, reason: "Incorrect pairing code" });
        pairingDb.run("DELETE FROM pairing_requests WHERE channel = ? AND sender_id = ?", [channel, senderId]);
        return resolve({ ok: true, reason: "paired" });
      },
    );
  });
}
