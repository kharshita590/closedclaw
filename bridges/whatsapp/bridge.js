const { Client, LocalAuth } = require("whatsapp-web.js");
const qrcode = require("qrcode-terminal");

const agentUrl = (process.env.AGENT_URL || "http://agent:8000").replace(/\/$/, "");

const client = new Client({
  authStrategy: new LocalAuth(),
  puppeteer: { args: ["--no-sandbox", "--disable-setuid-sandbox"] },
});

client.on("qr", (qr) => qrcode.generate(qr, { small: true }));
client.on("ready", () => console.log("WhatsApp bridge ready"));

client.on("message", async (message) => {
  if (!message.body || message.fromMe) return;
  try {
    const response = await fetch(`${agentUrl}/chat`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        message: message.body,
        channel: "whatsapp",
        user_id: message.author || message.from,
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
