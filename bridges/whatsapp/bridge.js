const express = require("express");
const { Client, LocalAuth } = require("whatsapp-web.js");
const qrcode = require("qrcode-terminal");

const bridgeUrl = (process.env.WHATSAPP_BRIDGE_URL || "http://whatsapp-bridge:8080").replace(/\/$/, "");
const enabledChannels = (process.env.ENABLED_CHANNELS || "ui,telegram")
  .split(",")
  .map((x) => x.trim().toLowerCase())
  .filter(Boolean);

const client = new Client({
  authStrategy: new LocalAuth(),
  puppeteer: { args: ["--no-sandbox", "--disable-setuid-sandbox"] },
});

client.on("qr", (qr) => qrcode.generate(qr, { small: true }));
client.on("ready", () => console.log("WhatsApp bridge ready"));

client.on("message", async (message) => {
  if (!message.body || message.fromMe) return;
  if (!enabledChannels.includes("whatsapp")) return;
  const senderId = message.author || message.from;
  try {
    await fetch(`${bridgeUrl}/whatsapp/incoming`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        sender_id: String(senderId),
        chat_id: String(message.from),
        text: message.body,
        metadata: { from: message.from, author: message.author, id: message.id?._serialized },
      }),
    });
  } catch (error) {
    console.error(error);
    try {
      await message.reply(`Bridge error: ${error.message}`);
    } catch (_) {}
  }
});

client.initialize();

const app = express();
app.use(express.json());

app.get("/health", (_req, res) => res.json({ status: "ok" }));

app.post("/send", async (req, res) => {
  const chatId = String(req.body?.chat_id || "");
  const text = String(req.body?.text || "");
  if (!chatId || !text) return res.status(400).json({ error: "chat_id and text are required" });
  try {
    const chat = await client.getChatById(chatId);
    await chat.sendMessage(text);
    return res.json({ ok: true });
  } catch (error) {
    return res.status(500).json({ ok: false, error: String(error?.message || error) });
  }
});

const port = Number(process.env.PORT || "8085");
app.listen(port, () => console.log(`WhatsApp sidecar listening on ${port}`));
